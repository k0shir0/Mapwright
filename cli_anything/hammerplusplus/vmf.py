"""VMF source-span edits. Unknown data and untouched bytes stay intact."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math
import re
from typing import Any


class MapError(ValueError):
    pass


@dataclass
class Node:
    key: str
    start: int
    end: int
    value: str | None = None
    value_start: int = 0
    close: int = 0
    children: list[Node] = field(default_factory=list)

    def blocks(self, key: str) -> list[Node]:
        return [n for n in self.children if n.key == key and n.value is None]

    def props(self, key: str) -> list[Node]:
        return [n for n in self.children if n.key == key and n.value is not None]

    def get(self, key: str, default: str = "") -> str:
        entries = self.props(key)
        return entries[0].value if entries else default

    def walk(self):
        for node in self.children:
            yield node
            yield from node.walk()


TOKEN = re.compile(r'\s+|//[^\r\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+')


def unquote(token: str) -> str:
    if not token.startswith('"'):
        return token
    # VMF does not interpret C escapes such as \n in Windows paths.
    return re.sub(r'\\(["\\])', r"\1", token[1:-1])


def quote(value: Any) -> str:
    value = str(value)
    if any(ord(c) < 32 and c != "\x1b" for c in value) or '"' in value:
        raise MapError("VMF values cannot contain quotes or control characters")
    # Hammer uses literal backslashes; preserve them rather than JSON escaping.
    if value.endswith("\\"):
        raise MapError("VMF values cannot end in a backslash")
    return '"' + value + '"'


def parse(text: str) -> Node:
    tokens = []
    pos = 1 if text.startswith("\ufeff") else 0
    for match in TOKEN.finditer(text, pos):
        if match.start() != pos:
            raise MapError(f"Invalid VMF token at offset {pos}")
        pos = match.end()
        token = match.group()
        if token.isspace() or token.startswith("//"):
            continue
        tokens.append((token, match.start(), match.end()))
    if pos != len(text):
        raise MapError(f"Unterminated VMF string at offset {pos}")
    cursor = 0

    def read(depth: int, nested: bool) -> tuple[list[Node], int, int]:
        nonlocal cursor
        if depth > 128:
            raise MapError("VMF nesting exceeds 128 levels")
        nodes = []
        while cursor < len(tokens):
            key, start, _ = tokens[cursor]
            cursor += 1
            if key == "}":
                if not nested:
                    raise MapError("Unexpected closing brace")
                return nodes, start, tokens[cursor - 1][2]
            if key == "{" or cursor >= len(tokens):
                raise MapError("Expected VMF key/value or block")
            value, vstart, vend = tokens[cursor]
            cursor += 1
            if value == "{":
                children, close, end = read(depth + 1, True)
                nodes.append(
                    Node(unquote(key), start, end, close=close, children=children)
                )
            elif value == "}":
                raise MapError(f"Missing value for {key}")
            else:
                nodes.append(Node(unquote(key), start, vend, unquote(value), vstart))
        if nested:
            raise MapError("Unclosed VMF block")
        return nodes, len(text), len(text)

    children, close, end = read(0, False)
    return Node("__root__", 0, end, close=close, children=children)


def vector(value: Any, length: int = 3) -> list[float]:
    if isinstance(value, str):
        try:
            result = [
                float(x)
                for x in value.replace("(", " ")
                .replace(")", " ")
                .replace("[", " ")
                .replace("]", " ")
                .split()
            ]
        except ValueError as exc:
            raise MapError("Expected a numeric vector") from exc
    elif isinstance(value, (list, tuple)) and not any(
        isinstance(x, bool) for x in value
    ):
        try:
            result = [float(x) for x in value]
        except (TypeError, ValueError) as exc:
            raise MapError("Expected a numeric vector") from exc
    else:
        raise MapError("Expected a numeric vector")
    if len(result) != length or not all(math.isfinite(x) for x in result):
        raise MapError(f"Expected {length} finite coordinates")
    return result


def fmt(values) -> str:
    return " ".join(format(v, ".17g") for v in values)


def position(value: Any) -> list[float]:
    result = vector(value)
    if any(abs(v) > 32768 for v in result):
        raise MapError("Position exceeds Source coordinate bounds")
    return result


def block(name: str, properties: dict[str, Any], children: str = "") -> str:
    return (
        name
        + "\n{\n"
        + "".join(f"\t{quote(k)} {quote(v)}\n" for k, v in properties.items())
        + children
        + "}\n"
    )


def replace(text: str, changes: list[tuple[int, int, str]]) -> str:
    for start, end, value in sorted(changes, reverse=True):
        text = text[:start] + value + text[end:]
    return text


def insert(text: str, parent: Node, addition: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    addition = addition.replace("\r\n", "\n").replace("\n", newline)
    return text[: parent.close] + newline + addition + text[parent.close :]


def set_properties(text: str, node: Node, properties: dict[str, Any]) -> str:
    changes = []
    additions = ""
    for key, value in properties.items():
        if key == "id":
            raise MapError("Object IDs are immutable")
        existing = node.props(key)
        if value is None:
            changes.extend((n.start, n.end, "") for n in existing)
        elif existing:
            changes.append((existing[0].value_start, existing[0].end, quote(value)))
            changes.extend((n.start, n.end, "") for n in existing[1:])
        else:
            additions += f"\t{quote(key)} {quote(value)}\n"
    if additions:
        newline = "\r\n" if "\r\n" in text else "\n"
        changes.append(
            (node.close, node.close, newline + additions.replace("\n", newline))
        )
    return replace(text, changes)


def new_map() -> str:
    return (
        block(
            "versioninfo",
            {
                "editorversion": "400",
                "editorbuild": "8864",
                "mapversion": "1",
                "formatversion": "100",
                "prefab": "0",
            },
        )
        + block("visgroups", {})
        + block("viewsettings", {"bSnapToGrid": "1", "nGridSpacing": "16"})
        + block(
            "world",
            {
                "id": "1",
                "mapversion": "1",
                "classname": "worldspawn",
                "skyname": "sky_dust",
            },
        )
        + block("cameras", {"activecamera": "-1"})
        + block("cordons", {"active": "0"})
    )


def find_id(
    root: Node, object_id: int, kind: str | None = None, *, allowed=None
) -> Node:
    if isinstance(object_id, bool) or not isinstance(object_id, int):
        raise MapError("id must be an integer")
    kinds = set(allowed or ("world", "entity", "solid", "side", "group"))
    if kind is not None:
        if kind not in kinds:
            raise MapError(f"Expected kind from {sorted(kinds)}")
        kinds = {kind}
    matches = [
        n
        for n in root.walk()
        if n.value is None
        and n.key in kinds
        and n.get("id").isdecimal()
        and int(n.get("id")) == object_id
    ]
    if len(matches) > 1 and len({n.key for n in matches}) > 1:
        raise MapError(
            f"Ambiguous id {object_id}; specify kind from {sorted({n.key for n in matches})}"
        )
    if len(matches) != 1:
        raise MapError(f"Expected one object with id {object_id}, found {len(matches)}")
    return matches[0]


def next_id(root: Node) -> int:
    ids = [
        int(n.value)
        for n in root.walk()
        if n.key == "id" and n.value is not None and n.value.isdecimal()
    ]
    return max(ids, default=0) + 1


def make_box(low: Any, high: Any, material: str, start_id: int) -> tuple[str, int]:
    lo, hi = vector(low), vector(high)
    if not all(-32768 <= a < b <= 32768 for a, b in zip(lo, hi)):
        raise MapError(
            "Box minimum must be below maximum, within +/-32768 Source units"
        )
    x, y, z = lo
    X, Y, Z = hi
    # VMF plane points are clockwise when viewed from outside (normal points in).
    faces = [
        ([(x, y, Z), (X, y, Z), (X, Y, Z)], "[1 0 0 0] 0.25", "[0 -1 0 0] 0.25"),
        ([(x, Y, z), (X, Y, z), (X, y, z)], "[1 0 0 0] 0.25", "[0 -1 0 0] 0.25"),
        ([(x, y, z), (X, y, z), (X, y, Z)], "[1 0 0 0] 0.25", "[0 0 -1 0] 0.25"),
        ([(X, Y, z), (x, Y, z), (x, Y, Z)], "[1 0 0 0] 0.25", "[0 0 -1 0] 0.25"),
        ([(x, Y, z), (x, y, z), (x, y, Z)], "[0 1 0 0] 0.25", "[0 0 -1 0] 0.25"),
        ([(X, y, z), (X, Y, z), (X, Y, Z)], "[0 1 0 0] 0.25", "[0 0 -1 0] 0.25"),
    ]
    children = ""
    for offset, (points, u, v) in enumerate(faces, 1):
        children += block(
            "side",
            {
                "id": start_id + offset,
                "plane": " ".join("(" + fmt(p) + ")" for p in reversed(points)),
                "material": material,
                "uaxis": u,
                "vaxis": v,
                "rotation": "0",
                "lightmapscale": "16",
                "smoothing_groups": "0",
            },
        )
    children += block(
        "editor", {"color": "0 180 220", "visgroupshown": "1", "visgroupautoshown": "1"}
    )
    return block("solid", {"id": start_id}, children), start_id


def mutate(text: str, operation: dict) -> tuple[str, dict]:
    if not isinstance(operation, dict):
        raise MapError("Each operation must be an object")
    root = parse(text)
    op = operation.get("op")
    fields = {
        "add_box": ({"min", "max"}, {"material", "parent_id", "parent_kind"}),
        "add_room": ({"min", "max"}, {"material", "thickness"}),
        "add_entity": ({"classname", "origin"}, {"properties"}),
        "set_properties": ({"id", "properties"}, {"kind"}),
        "add_output": (
            {"id", "event", "target", "input"},
            {"parameter", "delay", "times"},
        ),
        "translate": ({"id", "delta"}, {"kind"}),
        "delete": ({"id"}, {"kind"}),
    }
    if op not in fields:
        raise MapError(f"Unknown operation: {op}")
    required, optional = fields[op]
    if required - operation.keys() or operation.keys() - required - optional - {"op"}:
        raise MapError(
            f"{op}: required fields {sorted(required)}, optional fields {sorted(optional)}"
        )
    oid = next_id(root)
    worlds = root.blocks("world")
    if len(worlds) != 1:
        raise MapError("VMF must have exactly one world")
    world = worlds[0]
    if op == "add_box":
        if "parent_kind" in operation and "parent_id" not in operation:
            raise MapError("parent_kind requires parent_id")
        parent = (
            find_id(
                root,
                operation["parent_id"],
                operation.get("parent_kind"),
                allowed=("world", "entity"),
            )
            if "parent_id" in operation
            else world
        )
        if parent.key not in ("world", "entity"):
            raise MapError("Box parent must be world or entity")
        addition, _ = make_box(
            operation["min"],
            operation["max"],
            operation.get("material", "tools/toolsnodraw"),
            oid,
        )
        return insert(text, parent, addition), {"op": op, "ids": [oid]}
    if op == "add_room":
        lo, hi = vector(operation["min"]), vector(operation["max"])
        if not all(a < b for a, b in zip(lo, hi)):
            raise MapError("Room interior minimum must be below maximum")
        thickness = operation.get("thickness", 16)
        if (
            isinstance(thickness, bool)
            or not isinstance(thickness, (float, int))
            or not math.isfinite(thickness)
            or thickness <= 0
        ):
            raise MapError("Room thickness must be positive and finite")
        x, y, z = lo
        X, Y, Z = hi
        t = thickness
        walls = [
            ([x - t, y - t, z - t], [X + t, Y + t, z]),
            ([x - t, y - t, Z], [X + t, Y + t, Z + t]),
            ([x - t, y - t, z], [x, Y + t, Z]),
            ([X, y - t, z], [X + t, Y + t, Z]),
            ([x, y - t, z], [X, y, Z]),
            ([x, Y, z], [X, Y + t, Z]),
        ]
        additions = []
        ids = []
        for low, high in walls:
            addition, _ = make_box(
                low, high, operation.get("material", "dev/dev_measuregeneric01b"), oid
            )
            additions.append(addition)
            ids.append(oid)
            oid += 7
        return insert(text, world, "".join(additions)), {"op": op, "ids": ids}
    if op == "add_entity":
        classname = operation["classname"]
        if (
            not isinstance(classname, str)
            or not re.fullmatch("[A-Za-z_][A-Za-z_0-9]*", classname)
            or classname == "worldspawn"
        ):
            raise MapError("Invalid entity classname")
        properties = operation.get("properties", {})
        if (
            not isinstance(properties, dict)
            or {"id", "classname", "origin"} & properties.keys()
            or any(
                v is None or not isinstance(v, (str, int, float))
                for v in properties.values()
            )
        ):
            raise MapError(
                "Entity properties must be scalar keyvalues; id, classname and origin are reserved"
            )
        addition = block(
            "entity",
            {
                "id": oid,
                "classname": classname,
                "origin": fmt(position(operation["origin"])),
                **properties,
            },
            block(
                "editor",
                {"color": "220 180 0", "visgroupshown": "1", "visgroupautoshown": "1"},
            ),
        )
        return insert(text, root, addition), {"op": op, "ids": [oid]}
    allowed = (
        ("entity",)
        if op == "add_output"
        else (
            ("solid", "entity")
            if op in ("translate", "delete")
            else ("world", "entity", "solid", "side")
        )
    )
    node = find_id(root, operation["id"], operation.get("kind"), allowed=allowed)
    if op == "set_properties":
        props = operation["properties"]
        if (
            not isinstance(props, dict)
            or not props
            or not all(
                isinstance(k, str) and (v is None or isinstance(v, (str, int, float)))
                for k, v in props.items()
            )
        ):
            raise MapError(
                "properties must be a nonempty object of scalar keyvalues or null for deletion"
            )
        if node.key not in ("world", "entity", "side", "solid"):
            raise MapError(
                "Properties can only be set on a world, entity, solid or side"
            )
        return set_properties(text, node, props), {"op": op, "ids": [operation["id"]]}
    if op == "add_output":
        if node.key != "entity":
            raise MapError("Outputs require an entity")
        event, target, inp, parameter = (
            operation.get(k, "") for k in ("event", "target", "input", "parameter")
        )
        if (
            not all(isinstance(v, str) for v in (event, target, inp, parameter))
            or not all((event, target, inp))
            or any("," in v or "\x1b" in v for v in (event, target, inp, parameter))
        ):
            raise MapError(
                "Output names must be strings without commas or escape separators"
            )
        delay = operation.get("delay", 0)
        times = operation.get("times", -1)
        if (
            isinstance(delay, bool)
            or not isinstance(delay, (int, float))
            or not math.isfinite(delay)
            or delay < 0
            or isinstance(times, bool)
            or not isinstance(times, int)
            or times < -1
        ):
            raise MapError("Output delay must be nonnegative, times an integer >= -1")
        prop = f'\t{quote(event)} {quote(f"{target},{inp},{parameter},{fmt([delay])},{times}")}\n'
        connections = node.blocks("connections")
        return insert(
            text,
            connections[0] if connections else node,
            prop if connections else block("connections", {}, prop),
        ), {"op": op, "ids": [operation["id"]]}
    if op == "delete":
        if node.key not in ("entity", "solid"):
            raise MapError("Only entire entities or solids can be deleted")
        return text[: node.start] + text[node.end :], {
            "op": op,
            "ids": [operation["id"]],
        }
    if node.key not in ("entity", "solid"):
        raise MapError("Translate requires a solid or entity")

    def contained_solids(parent: Node):
        yield from parent.blocks("solid")
        for hidden in parent.blocks("hidden"):
            yield from contained_solids(hidden)

    solids = [node] if node.key == "solid" else list(contained_solids(node))
    sides = [side for solid in solids for side in solid.blocks("side")]
    if any(side.blocks("dispinfo") for side in sides) or node.get(
        "classname"
    ).startswith(("info_overlay", "func_instance")):
        raise MapError(
            "Translation of displacements, overlays and instances requires the editor"
        )
    delta = vector(operation["delta"])
    changes = []
    properties = node.props("origin") if node.key == "entity" else []
    for side in sides:
        for key in ("plane", "uaxis", "vaxis"):
            properties.extend(side.props(key))
    for prop in properties:
        if prop.key in ("origin", "plane"):
            values = vector(prop.value, 9 if prop.key == "plane" else 3)
            moved = [x + delta[i % 3] for i, x in enumerate(values)]
            if any(abs(x) > 32768 for x in moved):
                raise MapError("Translation leaves Source coordinate bounds")
            val = (
                " ".join("(" + fmt(moved[i : i + 3]) + ")" for i in range(0, 9, 3))
                if prop.key == "plane"
                else fmt(moved)
            )
            changes.append((prop.value_start, prop.end, quote(val)))
        elif prop.key in ("uaxis", "vaxis"):
            axis = vector(prop.value, 5)
            if axis[4] == 0:
                raise MapError("Texture scale cannot be zero")
            axis[3] -= sum(a * b for a, b in zip(axis[:3], delta)) / axis[4]
            changes.append(
                (
                    prop.value_start,
                    prop.end,
                    quote("[" + fmt(axis[:4]) + "] " + fmt(axis[4:])),
                )
            )
    if not changes:
        raise MapError("Object has no translatable geometry or origin")
    return replace(text, changes), {"op": op, "ids": [operation["id"]]}


def inspect(text: str, offset: int = 0, limit: int = 100) -> dict:
    root = parse(text)
    if offset < 0 or not 1 <= limit <= 1000:
        raise MapError("offset must be nonnegative and limit between 1 and 1000")
    objects = [
        n
        for n in root.walk()
        if n.value is None and n.key in ("world", "entity", "solid")
    ]
    counts = Counter(n.key for n in objects)
    return {
        "counts": dict(counts),
        "classnames": dict(
            Counter(n.get("classname") for n in objects if n.key == "entity")
        ),
        "total": len(objects),
        "offset": offset,
        "objects": [describe(n) for n in objects[offset : offset + limit]],
        "next_offset": offset + limit if offset + limit < len(objects) else None,
    }


def describe(node: Node) -> dict:
    return {
        "kind": node.key,
        "id": int(node.get("id", "0")),
        "properties": {n.key: n.value for n in node.children if n.value is not None},
        "outputs": [
            {"event": p.key, "value": p.value}
            for b in node.blocks("connections")
            for p in b.children
            if p.value is not None
        ],
        "side_ids": [int(n.get("id", "0")) for n in node.blocks("side")],
    }


def validate(text: str) -> dict:
    root = parse(text)
    errors, warnings = [], []
    ids = []
    if (
        len(root.blocks("world")) != 1
        or root.blocks("world")[0].get("classname") != "worldspawn"
    ):
        errors.append("Expected exactly one worldspawn world block")
    for n in root.walk():
        if n.value is not None:
            continue
        if n.key in ("world", "entity", "solid", "side", "group"):
            value = n.get("id")
            if not value.isdecimal() or int(value) < 1:
                errors.append(f"{n.key} has invalid id {value!r}")
            else:
                ids.append(("entity" if n.key == "world" else n.key, int(value)))
        try:
            if n.key == "entity":
                if not n.get("classname"):
                    errors.append(f'Entity {n.get("id")} has no classname')
                if n.props("origin"):
                    position(n.get("origin"))
            if n.key == "solid" and len(n.blocks("side")) < 4:
                errors.append(f'Solid {n.get("id")} has fewer than four sides')
            if n.key == "side":
                plane = vector(n.get("plane"), 9)
                a, b, c = plane[:3], plane[3:6], plane[6:]
                u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
                normal = [
                    u[1] * v[2] - u[2] * v[1],
                    u[2] * v[0] - u[0] * v[2],
                    u[0] * v[1] - u[1] * v[0],
                ]
                if sum(x * x for x in normal) < 1e-12:
                    errors.append(f'Side {n.get("id")} has a degenerate plane')
                if not n.get("material"):
                    errors.append(f'Side {n.get("id")} has no material')
                for key in ("uaxis", "vaxis"):
                    if vector(n.get(key), 5)[4] == 0:
                        errors.append(f'Side {n.get("id")} has zero texture scale')
                if any(abs(x) > 32768 for x in plane):
                    errors.append(
                        f'Side {n.get("id")} exceeds Source coordinate bounds'
                    )
        except MapError as exc:
            errors.append(f'{n.key} {n.get("id")}: {exc}')
    for (kind, value), count in Counter(ids).items():
        if count > 1:
            errors.append(f"Duplicate {kind} id {value}")
    classes = {n.get("classname") for n in root.walk() if n.key == "entity"}
    for classname in ("info_player_terrorist", "info_player_counterterrorist"):
        if classname not in classes:
            warnings.append(f"No {classname} spawn")
    warnings.append(
        "Structural checks do not prove convexity, sealing, FGD compatibility or playability; compile and inspect in Hammer++"
    )
    return {"valid": not errors, "errors": errors, "warnings": warnings}
