"""One discoverable command contract shared by the CLI and MCP transport."""

import jsonschema

from . import backend, catalog
from .project import Project
from .vmf import MapError

STRING = {"type": "string"}
INTEGER = {"type": "integer"}
VECTOR = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
PROPERTIES = {
    "type": "object",
    "additionalProperties": {"type": ["string", "number", "null"]},
}
REVISION = {
    "type": "string",
    "pattern": "^[a-f0-9]{64}$",
    "description": "Current revision returned by inspect; stale revisions are refused.",
}
MAP = {"type": "string", "description": "VMF path inside the server workspace."}
KIND = {
    "enum": ["world", "entity", "solid", "side", "group"],
    "description": "Qualify IDs reused across VMF object namespaces.",
}


def schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def operation(name: str, props: dict, required: list[str]) -> dict:
    return schema({"op": {"const": name}, **props}, ["op", *required])


OPERATIONS = {
    "oneOf": [
        operation(
            "add_box",
            {
                "min": VECTOR,
                "max": VECTOR,
                "material": STRING,
                "parent_id": INTEGER,
                "parent_kind": {"enum": ["world", "entity"]},
            },
            ["min", "max"],
        ),
        operation(
            "add_room",
            {
                "min": VECTOR,
                "max": VECTOR,
                "material": STRING,
                "thickness": {"type": "number", "exclusiveMinimum": 0},
            },
            ["min", "max"],
        ),
        operation(
            "add_entity",
            {"classname": STRING, "origin": VECTOR, "properties": PROPERTIES},
            ["classname", "origin"],
        ),
        operation(
            "set_properties",
            {"id": INTEGER, "properties": PROPERTIES, "kind": KIND},
            ["id", "properties"],
        ),
        operation(
            "add_output",
            {
                "id": INTEGER,
                "event": STRING,
                "target": STRING,
                "input": STRING,
                "parameter": STRING,
                "delay": {"type": "number", "minimum": 0},
                "times": {"type": "integer", "minimum": -1},
            },
            ["id", "event", "target", "input"],
        ),
        operation(
            "translate",
            {"id": INTEGER, "delta": VECTOR, "kind": {"enum": ["entity", "solid"]}},
            ["id", "delta"],
        ),
        operation(
            "delete", {"id": INTEGER, "kind": {"enum": ["entity", "solid"]}}, ["id"]
        ),
    ]
}


def spec(description: str, props: dict, required: list[str], readonly: bool = True):
    return {
        "description": description,
        "inputSchema": schema(props, required),
        "readonly": readonly,
    }


TOOLS = {
    "doctor": spec(
        "Report legacy CS:GO SDK and Hammer++ readiness without launching tools.",
        {},
        [],
    ),
    "create_map": spec(
        "Create a new native VMF, refusing overwrite. csgo-room is an enclosed test room with team spawns and light.",
        {"path": MAP, "template": {"enum": ["empty", "csgo-room"], "default": "empty"}},
        ["path"],
        False,
    ),
    "inspect_map": spec(
        "Read map revision, counts, classnames and a page of objects, including hidden objects.",
        {
            "path": MAP,
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        ["path"],
    ),
    "inspect_object": spec(
        "Read one object, outputs, side IDs and its original VMF source.",
        {"path": MAP, "id": INTEGER, "kind": KIND},
        ["path", "id"],
    ),
    "validate_map": spec(
        "Check structural VMF validity. This cannot establish sealing, convexity or playability.",
        {"path": MAP},
        ["path"],
    ),
    "edit_map": spec(
        "Apply an atomic batch to the inspected revision. Unknown blocks and comments remain intact. dry_run returns proposed IDs/hash without publishing. add_room min/max are interior bounds. parent_id adds a brush to an existing entity.",
        {
            "path": MAP,
            "expected_revision": REVISION,
            "operations": {
                "type": "array",
                "items": OPERATIONS,
                "minItems": 1,
                "maxItems": 1000,
            },
            "dry_run": {"type": "boolean"},
        },
        ["path", "expected_revision", "operations"],
        False,
    ),
    "map_history": spec(
        "Read transaction history and undo position.", {"path": MAP}, ["path"]
    ),
    "undo_map": spec(
        "Restore the prior transaction; refuses external map changes.",
        {"path": MAP, "expected_revision": REVISION},
        ["path", "expected_revision"],
        False,
    ),
    "redo_map": spec(
        "Reapply an undone transaction; refuses external map changes.",
        {"path": MAP, "expected_revision": REVISION},
        ["path", "expected_revision"],
        False,
    ),
    "compile_map": spec(
        "Invoke actual configured VBSP/VVIS/VRAD in a fresh staging directory. Missing tools, timeouts and leaks fail. Does not install outputs into the game.",
        {
            "path": MAP,
            "expected_revision": REVISION,
            "mode": {"enum": ["bsp", "fast", "full"]},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 3600},
        },
        ["path", "expected_revision"],
        False,
    ),
    "open_editor": spec(
        "Launch configured Hammer++ with this VMF. Does not save/reload existing work or prove the map rendered.",
        {"path": MAP},
        ["path"],
        False,
    ),
    "capture_editor": spec(
        "Capture a specific configured Hammer++ process window to a new workspace PNG on Windows. Inspect the returned image for visual evidence.",
        {"pid": {"type": "integer", "minimum": 1}, "output": STRING},
        ["pid", "output"],
        False,
    ),
    "entity_catalog": spec(
        "Search the installed CS:GO FGD or inspect a classname and inherited keyvalues, inputs and outputs. Requires source extra.",
        {
            "query": STRING,
            "classname": STRING,
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        [],
    ),
    "asset_catalog": spec(
        "Find materials or models in local loose files and VPK directories, without extracting assets. Requires source extra.",
        {
            "kind": {"enum": ["material", "model"]},
            "query": STRING,
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        [],
    ),
    "rea_probe": spec(
        "Run configured REA read-only PE-resource analysis on one configured tool; no target execution or injection.",
        {"target": {"enum": ["hammer", "vbsp", "vvis", "vrad"]}},
        ["target"],
    ),
}


def execute(project: Project, config: dict, action: str, args: dict) -> dict:
    if action not in TOOLS:
        raise MapError(f"Unknown tool: {action}")
    try:
        jsonschema.Draft202012Validator(TOOLS[action]["inputSchema"]).validate(args)
    except jsonschema.ValidationError as exc:
        raise MapError(
            f"Invalid {action} argument at {list(exc.absolute_path)}: {exc.message}"
        ) from exc
    values = dict(args)
    path = values.pop("path", None)
    if action == "doctor":
        return backend.doctor(project, config)
    if action == "create_map":
        return project.create(path, **values)
    if action == "inspect_map":
        return project.inspect(path, **values)
    if action == "inspect_object":
        return project.object(path, values["id"], values.get("kind"))
    if action == "validate_map":
        return project.validate(path)
    if action == "edit_map":
        return project.apply(path, **values)
    if action == "map_history":
        return project.history(path)
    if action in ("undo_map", "redo_map"):
        return project.restore(path, values["expected_revision"], action.split("_")[0])
    if action == "compile_map":
        return backend.compile_map(project, config, path, **values)
    if action == "open_editor":
        return backend.open_editor(project, config, path)
    if action == "capture_editor":
        from .windows import capture_editor

        return capture_editor(project, config, **values)
    if action == "entity_catalog":
        return catalog.entities(project, config, **values)
    if action == "asset_catalog":
        return catalog.assets(project, config, **values)
    return backend.rea_probe(project, config, **values)
