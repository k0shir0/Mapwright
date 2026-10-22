"""Offline GOKZ Mapping API checks. Geometry results never certify gameplay."""

from __future__ import annotations

from collections import Counter, defaultdict
import difflib
import math
import re

from . import vmf
from .project import digest

MAPPING_API = "https://github.com/KZGlobalTeam/gokz/wiki/Mapping-API"
JUMPSTATS = "https://github.com/KZGlobalTeam/gokz/wiki/Jumpstats"
COURSE = re.compile(r"climb_(?:(bonus[1-9][0-9]*)_)?(start|end)(button|zone)?$")
TRIGGERS = {
    "climb_teleport",
    "climb_bhop_reset",
    "climb_anti_pause",
    "climb_anti_checkpoint",
    "climb_anti_jumpstat",
    "climb_anti_bhop",
}
NAMES = TRIGGERS | {
    "climb_startbutton",
    "climb_endbutton",
    "climb_startzone",
    "climb_endzone",
    "climb_start",
}
COLLISION = {
    "worldspawn",
    "func_detail",
    "func_brush",
    "func_wall",
    "func_button",
    "func_breakable",
}
LIMITATIONS = (
    "Static VMF analysis, not the BSP or server physics. Exact geometry checks cover "
    "axis-aligned six-face boxes only; slopes, displacements, props, instances and dynamic "
    "collision require editor/in-game inspection. Hidden objects are excluded. "
    "Compile and test on the intended 128-tick GOKZ server and movement mode."
)


def normal(side):
    p = vmf.vector(side.get("plane"), 9)
    a, b = [p[i + 3] - p[i] for i in range(3)], [p[i + 6] - p[i] for i in range(3)]
    n = [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
    length = math.sqrt(sum(v * v for v in n))
    if not math.isfinite(length) or length < 1e-9:
        raise vmf.MapError("Degenerate face plane")
    return [v / length for v in n], p[:3]


def box(solid):
    """Read plane equations, not arbitrary plane-point extrema (which need not be vertices)."""
    sides = solid.blocks("side")
    if len(sides) != 6 or any(s.blocks("dispinfo") for s in sides):
        return None
    planes = {}
    try:
        for side in sides:
            n, p = normal(side)
            axis = max(range(3), key=lambda i: abs(n[i]))
            if abs(abs(n[axis]) - 1) > 1e-7:
                return None
            key = (axis, 1 if n[axis] > 0 else -1)
            if key in planes:
                return None
            planes[key] = (p[axis], side)
        if len(planes) != 6:
            return None
        # VMF normals point inward.
        lo = [planes[i, 1][0] for i in range(3)]
        hi = [planes[i, -1][0] for i in range(3)]
        if any(a >= b for a, b in zip(lo, hi)):
            return None
        return {"min": lo, "max": hi, "top": planes[2, -1][1], "planes": planes}
    except vmf.MapError:
        return None


def overlap(a, b, axes=(0, 1, 2), inclusive=False):
    return all(
        (
            max(a["min"][i], b["min"][i]) <= min(a["max"][i], b["max"][i])
            if inclusive
            else max(a["min"][i], b["min"][i]) < min(a["max"][i], b["max"][i])
        )
        for i in axes
    )


def inside(point, b):
    return all(a - 1e-6 <= v <= z + 1e-6 for v, a, z in zip(point, b["min"], b["max"]))


class Analysis:
    def __init__(self, text):
        self.root = vmf.parse(text)
        self.entities = []
        self.solids = []
        self.hidden = 0
        self.findings = []
        self.unsupported = []

        def walk(parent, owner=None):
            for n in parent.children:
                if n.value is not None:
                    continue
                hidden = n.key == "hidden" or any(
                    e.get("visgroupshown", "1") == "0"
                    or e.get("visgroupautoshown", "1") == "0"
                    for e in n.blocks("editor")
                )
                if hidden:
                    self.hidden += sum(
                        x.key in ("entity", "solid") for x in n.walk()
                    ) + (n.key in ("entity", "solid"))
                    continue
                current = n if n.key in ("world", "entity") else owner
                if n.key == "entity":
                    self.entities.append(n)
                if n.key == "solid":
                    bounds = box(n)
                    row = {"node": n, "owner": owner, "box": bounds}
                    self.solids.append(row)
                    if bounds is None:
                        self.unsupported.append(
                            {
                                "id": n.get("id"),
                                "kind": "solid",
                                "reason": "Requires a six-face axis-aligned box without displacement",
                            }
                        )
                else:
                    walk(n, current)

        walk(self.root)
        self.ids = vmf.id_index(self.root)
        self.owner_volumes = defaultdict(list)
        self.solid_rows = {}
        self.side_rows = {}
        for row in self.solids:
            self.solid_rows[id(row["node"])] = row
            for side in row["node"].blocks("side"):
                self.side_rows[id(side)] = row
            if row["box"]:
                self.owner_volumes[id(row["owner"])].append(row["box"])
        self.named = defaultdict(list)
        for e in self.entities:
            if e.get("targetname"):
                self.named[e.get("targetname")].append(e)
        self.ground = [
            s
            for s in self.solids
            if s["box"]
            and s["owner"]
            and s["owner"].get("classname") in COLLISION
            and not any(water(f.get("material")) for f in s["node"].blocks("side"))
        ]

    def add(self, rule, message, node=None, severity="warning", **details):
        self.findings.append(
            {
                "rule": rule,
                "severity": severity,
                "id": node.get("id") if node else None,
                "kind": node.key if node else "map",
                "targetname": node.get("targetname") if node else "",
                "message": message,
                **details,
            }
        )

    def volumes(self, entity):
        return list(self.owner_volumes.get(id(entity), []))

    def point(self, e):
        try:
            return vmf.vector(e.get("origin"))
        except vmf.MapError:
            self.add(
                "entity.origin",
                "A finite three-coordinate origin is required",
                e,
                "error",
            )
            return None

    def number(self, e, key, default=0, integer=False):
        raw = e.get(key, str(default))
        try:
            value = float(raw)
            if not math.isfinite(value) or (
                integer and not re.fullmatch(r"[0-9]+", raw)
            ):
                raise ValueError
            return int(value) if integer else value
        except ValueError:
            self.add(
                "value." + key,
                f"{key} must be a finite {'bare nonnegative integer' if integer else 'number'}",
                e,
                "error",
                value=raw,
            )
            return None

    def angles(self, e):
        try:
            angles = vmf.vector(e.get("angles"))
            if abs(angles[0]) > 89 or abs(angles[2]) > 1e-6 or abs(angles[1]) > 360:
                self.add(
                    "angles.sanity",
                    "Review pitch, yaw and roll; typical player destination angles are 0 yaw 0",
                    e,
                    angles=angles,
                )
        except vmf.MapError:
            self.add(
                "angles.missing",
                "Set finite Pitch Yaw Roll destination angles",
                e,
                "error",
            )

    def floor(self, p):
        tops = [
            s["box"]["max"][2]
            for s in self.ground
            if all(s["box"]["min"][i] <= p[i] <= s["box"]["max"][i] for i in (0, 1))
            and s["box"]["max"][2] <= p[2] + 1e-6
        ]
        return max(tops) if tops else None

    def audit(self, timer_profile="either"):
        worlds = self.root.blocks("world")
        version = worlds[0].get("climb_mapping_api_version") if len(worlds) == 1 else ""
        if not re.fullmatch(r"[1-9][0-9]*", version):
            self.add(
                "mapping.version",
                "Set worldspawn climb_mapping_api_version to a bare positive integer (verified FGD version: 1)",
                worlds[0] if worlds else None,
                "error",
            )
        elif version != "1":
            self.add(
                "mapping.version",
                "Mapping API version differs from the verified Version 1 contract; check the intended plugin",
                worlds[0],
            )
        courses = defaultdict(lambda: {"start": [], "end": [], "dest": []})
        courses[""]
        startzones = []
        for e in self.entities:
            name = e.get("targetname")
            match = COURSE.fullmatch(name)
            if match:
                course, end, kind = match.groups()
                course = course or ""
                expected = (
                    "func_button"
                    if kind == "button"
                    else (
                        "trigger_multiple"
                        if kind == "zone"
                        else "info_teleport_destination"
                    )
                )
                if e.get("classname") != expected:
                    self.add("timer.class", f"{name} must use {expected}", e, "error")
                    continue
                if not kind:
                    if end == "start":
                        courses[course]["dest"].append(e)
                        self.angles(e)
                    else:
                        self.add(
                            "timer.name",
                            "An end destination is not a GOKZ course-start entity",
                            e,
                        )
                    continue
                courses[course][end].append(e)
                if not any(s["owner"] is e for s in self.solids):
                    self.add(
                        "timer.volume",
                        "Timer buttons/zones require brush geometry",
                        e,
                        "error",
                    )
                if kind == "button":
                    flags = self.number(e, "spawnflags", integer=True)
                    if flags is not None and flags & 33 != 33:
                        self.add(
                            "button.flags",
                            "Enable Don't move (1) and Toggle (32); combined mask 33",
                            e,
                            spawnflags=flags,
                        )
                    if (
                        timer_profile == "buttons"
                        and flags is not None
                        and not flags & 1024
                    ):
                        self.add(
                            "button.use",
                            "Physical timer buttons need Use Activates (1024)",
                            e,
                            "error",
                        )
                else:
                    flags = self.number(e, "spawnflags", integer=True)
                    if flags is not None and not flags & 1:
                        self.add(
                            "trigger.clients",
                            "Enable timer zone Clients flag (1)",
                            e,
                            "error",
                        )
                    if end == "start":
                        startzones.append(e)
            elif name in TRIGGERS:
                if e.get("classname") != "trigger_multiple":
                    self.add(
                        "trigger.class", f"{name} must use trigger_multiple", e, "error"
                    )
                if not any(s["owner"] is e for s in self.solids):
                    self.add(
                        "trigger.volume",
                        "KZ triggers require child brush volumes",
                        e,
                        "error",
                    )
                flags = self.number(e, "spawnflags", integer=True)
                if flags is not None and not flags & 1:
                    self.add(
                        "trigger.clients",
                        "Enable trigger spawnflag Clients (1)",
                        e,
                        "error",
                    )
            elif name.casefold().startswith("climb_"):
                suggestions = difflib.get_close_matches(name, sorted(NAMES), n=1)
                self.add(
                    "name.unknown",
                    "Unrecognized climb_* name; names are the GOKZ API",
                    e,
                    suggestions=suggestions,
                )
        for course, ends in courses.items():
            for end in ("start", "end"):
                if timer_profile == "buttons" and not any(
                    e.get("classname") == "func_button" for e in ends[end]
                ):
                    self.add(
                        "timer.buttons_required",
                        f"Physical-button profile requires {course or 'main'} {end} func_button",
                        severity="error",
                    )
                if not ends[end]:
                    self.add(
                        "timer.pair",
                        f"Missing {course or 'main'} {end} button or zone",
                        severity="error",
                    )
            if not ends["dest"]:
                self.add(
                    "course.start",
                    f"Missing climb_{course+'_' if course else ''}start course destination",
                    severity="error",
                )
            elif len(ends["dest"]) > 1:
                self.add(
                    "course.duplicate",
                    f"Ambiguous course start for {course or 'main'}",
                    severity="error",
                )
        for i, a in enumerate(startzones):
            for b in startzones[i + 1 :]:
                if any(
                    overlap(x, y, inclusive=True)
                    for x in self.volumes(a)
                    for y in self.volumes(b)
                ):
                    self.add(
                        "zone.overlap",
                        "Start zones overlap; verify they cannot activate simultaneously",
                        a,
                        other_id=b.get("id"),
                    )

    def antibhop(self):
        destinations = [
            e
            for e in self.entities
            if e.get("classname") == "info_teleport_destination"
        ]
        for e in self.named["climb_anti_bhop"]:
            delay = self.number(e, "climb_anti_bhop_time", 0.2)
            if delay is not None and delay < 0:
                self.add(
                    "antibhop.delay",
                    "Anti-bhop time must be nonnegative; zero is always active",
                    e,
                    "error",
                )
            for b in self.volumes(e):
                dims = [z - a for a, z in zip(b["min"], b["max"])]
                if min(dims) < 16 - 1e-6:
                    self.add(
                        "antibhop.thickness",
                        "Anti-bhop volumes need at least 16 units on every axis to resist bypasses",
                        e,
                        "error",
                        dimensions=dims,
                    )
                for dest in destinations:
                    p = self.point(dest)
                    if p is None or not inside(p, b):
                        continue
                    floor = self.floor(p)
                    if floor is None:
                        self.add(
                            "antibhop.floor_unknown",
                            "Ground height under this destination needs manual measurement",
                            dest,
                        )
                    elif p[2] - floor < 4 - 1e-6:
                        self.add(
                            "antibhop.triggerhop",
                            "Teleport destinations inside anti-bhop need at least 4 units above ground",
                            dest,
                            "error",
                            clearance=p[2] - floor,
                        )

    def teleports(self):
        routes = []
        for e in self.entities:
            gokz = e.get("targetname") == "climb_teleport"
            if not gokz and e.get("classname") != "trigger_teleport":
                continue
            key = "climb_teleport_destination" if gokz else "target"
            target = e.get(key)
            matches = self.named.get(target, [])
            if not target or target.startswith("!") or not matches:
                self.add(
                    "teleport.destination",
                    "Teleport needs an existing named destination; GOKZ does not resolve ! names",
                    e,
                    "error",
                    destination=target,
                )
            elif len(matches) > 1:
                self.add(
                    "teleport.ambiguous",
                    "Multiple entities share this destination name; review plugin selection",
                    e,
                    destination=target,
                )
            for dest in matches:
                self.point(dest)
                self.angles(dest)
            row = {
                "id": e.get("id"),
                "destination": target,
                "destination_ids": [d.get("id") for d in matches],
            }
            if gokz:
                for suffix, default in (
                    ("reset_speed", 1),
                    ("use_dest_angles", 1),
                    ("reorient_player", 0),
                    ("relative", 0),
                ):
                    value = self.number(
                        e, "climb_teleport_" + suffix, default, integer=True
                    )
                    row[suffix] = value
                    if value not in (None, 0, 1):
                        self.add(
                            "teleport.boolean",
                            f"climb_teleport_{suffix} must be 0 or 1",
                            e,
                            "error",
                        )
                if row["reorient_player"] and row["relative"]:
                    self.add(
                        "teleport.reorient_relative",
                        "Reorient overrides destination-angle selection; relative offsets rotate and destination-yaw edits can visibly lag",
                        e,
                    )
            routes.append(row)
        return routes

    def bhop(self, route=None, minimum_mbh=300):
        grouped = defaultdict(list)
        for e in self.named["climb_teleport"]:
            typ = self.number(e, "climb_teleport_type", 0, integer=True)
            if typ not in (None, 0, 1, 2, 3):
                self.add(
                    "bhop.type",
                    "Teleport type must be 0 Normal, 1 Multi, 2 Single or 3 Sequential",
                    e,
                    "error",
                )
            delay = self.number(e, "climb_teleport_delay", 0)
            if delay is not None and (
                delay < 0 or (typ in (1, 2, 3) and delay < 0.08 - 1e-9)
            ):
                self.add(
                    "bhop.delay",
                    "Bhop types need grounded delay >=0.08 seconds (0.1 is common); normal delay must be nonnegative",
                    e,
                    "error",
                    delay=delay,
                )
            if typ in (2, 3):
                grouped[e.get("climb_teleport_destination")].append(e.get("id"))
        for target, ids in grouped.items():
            if target and len(ids) > 1:
                self.add(
                    "bhop.shared_destination",
                    "Single/sequential triggers share a reset destination; review intended chain behavior",
                    destination=target,
                    ids=ids,
                )
        measurements = []
        if route:
            selected = [self.select(s) for s in route]
            for a, b in zip(selected, selected[1:]):
                measure = measure_boxes(a, b)
                measurements.append(measure)
                if not measure["jumpstat_block_geometry"]:
                    self.add(
                        "bhop.block_geometry",
                        "Selected route lacks parallel, aligned, same-height block geometry",
                        measure=measure,
                    )
                if measure["gap"] < minimum_mbh:
                    self.add(
                        "bhop.mbh_distance",
                        "Route gap is below the selected server's MBH minimum",
                        gap=measure["gap"],
                        minimum=minimum_mbh,
                    )
                corridor = measure["corridor"]
                for ground in self.ground:
                    bounds = ground["box"]
                    if ground["node"].get("id") in (a["id"], b["id"]):
                        continue
                    if (
                        not overlap(bounds, corridor, axes=(0, 1))
                        or bounds["max"][2] < min(a["max"][2], b["max"][2]) - 18
                    ):
                        continue
                    covered = any(
                        overlap(bounds, v, axes=(0, 1))
                        and v["min"][2] <= bounds["max"][2] <= v["max"][2]
                        for e in self.named["climb_teleport"]
                        if e.get("climb_teleport_type", "0") in {"1", "2", "3"}
                        for v in self.volumes(e)
                    )
                    if not covered:
                        self.add(
                            "bhop.chain_ground",
                            "Potential standable ground between route blocks lacks a bhop trigger; ground contact may reset the chain",
                            ground["node"],
                        )
        else:
            self.add(
                "bhop.route_unknown",
                "Supply an ordered route of landing solids to check gaps and potential chain-reset ground",
                severity="info",
            )
        return {
            "route_measurements": measurements,
            "minimum_mbh": minimum_mbh,
            "chain_semantics": "Ground/ladder contact away from single/sequential triggers resets state; Multi resets it too. Validate actual landing trajectories in-game.",
        }

    def select(self, selector):
        node = vmf.find_id(
            self.root, selector["id"], selector.get("kind", "solid"), index=self.ids
        )
        if node.key == "side":
            row = self.side_rows.get(id(node))
            rows = [row] if row is not None else []
            if not rows or rows[0]["box"] is None or rows[0]["box"]["top"] is not node:
                raise vmf.MapError("Select a top face of an axis-aligned box")
        else:
            row = self.solid_rows.get(id(node))
            rows = [row] if row is not None else []
        if len(rows) != 1 or rows[0]["box"] is None:
            raise vmf.MapError(
                "Selected solid must be an active axis-aligned six-face box without displacements"
            )
        return {
            "id": rows[0]["node"].get("id"),
            **{k: rows[0]["box"][k] for k in ("min", "max")},
        }

    def headhitter(self, start=None, end=None):
        if (start is None) != (end is None):
            raise vmf.MapError("Headhitter corridor requires both start and end")
        if start is None and len(self.ground) > 1000:
            raise vmf.MapError(
                "Map exceeds 1000 collision boxes; select start/end for a bounded headhitter corridor check"
            )
        if start:
            measured = measure_boxes(self.select(start), self.select(end))
            corridor = measured["corridor"]
            floors = [
                {
                    "min": corridor["min"],
                    "max": [*corridor["max"][:2], measured["takeoff_z"]],
                    "id": str(start["id"]),
                }
            ]
        else:
            floors = [{**s["box"], "id": s["node"].get("id")} for s in self.ground]
        pairs = 0
        for floor in floors:
            for ceiling in self.ground:
                b = ceiling["box"]
                if not overlap(floor, b, axes=(0, 1)) or b["min"][2] <= floor["max"][2]:
                    continue
                clearance = b["min"][2] - floor["max"][2]
                if clearance < 129:
                    pairs += 1
                    self.add(
                        "head.clearance",
                        "Low ceiling: intentional headhitters need in-game confirmation; head hits can invalidate following bhops",
                        ceiling["node"],
                        clearance=clearance,
                        floor_id=floor["id"],
                        standing_apex=129,
                        crouched_apex=111,
                        below_thresholds=[
                            n
                            for n, h in {
                                "walk": 73,
                                "crouch": 55,
                                "standing_jump_64tick": 127,
                                "jump_crouch_64tick": 118,
                                "crouch_jump": 121,
                            }.items()
                            if clearance < h
                        ],
                    )
        return {"low_clearance_pairs": pairs}

    def ladders(self, landing=None):
        target = self.select(landing) if landing else None
        rows = []
        for s in self.solids:
            faces = [
                f
                for f in s["node"].blocks("side")
                if f.get("material").casefold() == "tools/toolsinvisibleladder"
            ]
            if not faces:
                continue
            owner = s["owner"]
            if owner and owner.get("classname") in (
                "func_ladder",
                "func_useableladder",
            ):
                self.add(
                    "ladder.owner",
                    "CS:GO textured ladders belong to world/func_detail; func_ladder is not a working CS:GO ladder",
                    owner,
                    "error",
                )
            row = {
                "id": s["node"].get("id"),
                "faces": [
                    {"id": f.get("id"), "inward_normal": normal(f)[0]} for f in faces
                ],
            }
            if s["box"]:
                row["dimensions"] = [
                    b - a for a, b in zip(s["box"]["min"], s["box"]["max"])
                ]
                row["top_z"] = s["box"]["max"][2]
                if target and abs(row["top_z"] - target["max"][2]) > 1e-6:
                    self.add(
                        "ladder.laj_height",
                        "LAJ jumpstats require ladder top and landing top at the same height, with zero offset",
                        s["node"],
                        ladder_top=row["top_z"],
                        landing_top=target["max"][2],
                    )
            rows.append(row)
        return {
            "ladders": rows,
            "climb_context": {"vanilla_speed": 156, "skz_kzt_speed": 200},
            "verification": "Measure LAJ offset and actual ladder collision in-game",
        }

    def water(self):
        rows = []
        for s in self.solids:
            wet = [f for f in s["node"].blocks("side") if water(f.get("material"))]
            if not wet:
                continue
            b = s["box"]
            owner = s["owner"]
            rows.append(
                {"id": s["node"].get("id"), "water_faces": [f.get("id") for f in wet]}
            )
            if b is None or len(wet) != 1 or (b and wet[0] is not b["top"]):
                self.add(
                    "water.top",
                    "Use a rectangular level brush with water material on its top face only",
                    s["node"],
                    "error",
                )
            if any(
                f not in wet and f.get("material").casefold() != "tools/toolsnodraw"
                for f in s["node"].blocks("side")
            ):
                self.add(
                    "water.nodraw",
                    "All non-water faces should use tools/toolsnodraw",
                    s["node"],
                    "error",
                )
            if (
                owner
                and owner.key == "entity"
                and owner.get("classname") != "func_water_analog"
            ):
                self.add(
                    "water.owner",
                    "Use world water or func_water_analog for moving water",
                    owner,
                    "error",
                )
        if rows:
            if not any(
                e.get("classname") == "water_lod_control" for e in self.entities
            ):
                self.add(
                    "water.lod",
                    "Consider water_lod_control to control water rendering distances",
                )
            worlds = self.root.blocks("world")
            if not worlds or not worlds[0].get("skyname"):
                self.add(
                    "water.sky",
                    "Set skyname and build a skybox; check for leaks that disable water rendering",
                    severity="error",
                )
            self.add(
                "water.runtime",
                "Inspect skybox, leaks, water rendering and water-contact jumpstat invalidation in-game",
                severity="info",
            )
        return {"water_brushes": rows, "swim_speed_multiplier": 0.8}

    def spawns(self, minimum_t_spawns=1, minimum_ct_spawns=1):
        counts = Counter(e.get("classname") for e in self.entities)
        classes = ("info_player_terrorist", "info_player_counterterrorist")
        for cls in classes:
            if not counts[cls]:
                self.add("spawn.missing", f"No {cls} spawn", severity="error")
        for cls, minimum in zip(classes, (minimum_t_spawns, minimum_ct_spawns)):
            if counts[cls] < minimum:
                self.add(
                    "spawn.capacity",
                    f"{cls} has {counts[cls]} spawns; profile requires {minimum}",
                    severity="error",
                )
        if counts[classes[0]] != counts[classes[1]]:
            self.add(
                "spawn.parity",
                "Team spawn counts differ",
                counts={c: counts[c] for c in classes},
            )
        for e in self.entities:
            if e.get("classname") not in classes:
                continue
            p = self.point(e)
            self.angles(e)
            if p is None:
                continue
            floor = self.floor(p)
            if floor is None or p[2] - floor > 18:
                self.add(
                    "spawn.support",
                    "No box floor within 18 units beneath spawn origin; inspect unsupported geometry in-game",
                    e,
                    "warning" if self.unsupported else "error",
                    floor_z=floor,
                )
            hull = {
                "min": [p[0] - 16, p[1] - 16, p[2]],
                "max": [p[0] + 16, p[1] + 16, p[2] + 72],
            }
            for s in self.ground:
                if overlap(hull, s["box"]):
                    self.add(
                        "spawn.blocked",
                        "Standing player hull overlaps brush collision",
                        e,
                        "error",
                        solid_id=s["node"].get("id"),
                    )
            ceilings = [
                s["box"]["min"][2] - p[2]
                for s in self.ground
                if overlap(hull, s["box"], axes=(0, 1)) and s["box"]["min"][2] >= p[2]
            ]
            if ceilings and min(ceilings) < 129:
                self.add(
                    "spawn.ceiling",
                    "Spawn has limited jump headroom",
                    e,
                    clearance=min(ceilings),
                    standing_hull=72,
                    standing_jump_apex=129,
                )
            for name, zones in self.named.items():
                if name.endswith("startzone") and COURSE.fullmatch(name):
                    for zone in zones:
                        if any(overlap(hull, b) for b in self.volumes(zone)):
                            self.add(
                                "spawn.startzone",
                                "Spawn overlaps a start zone; entering stops the timer and updates start position",
                                e,
                                zone_id=zone.get("id"),
                            )
        return {
            "spawn_counts": {c: counts[c] for c in classes},
            "checks_performed": [
                "box_hull_clearance",
                "box_floor_support",
                "team_capacity",
            ],
            "route_verified": False,
            "replay_bots_verified": False,
        }


def water(material):
    m = material.casefold().removeprefix("materials/")
    return m.startswith("liquids/") or m.startswith("dev/dev_water")


def measure_boxes(a, b):
    axes = [
        i for i in (0, 1) if b["min"][i] >= a["max"][i] or a["min"][i] >= b["max"][i]
    ]
    gaps = [
        max(0, b["min"][i] - a["max"][i], a["min"][i] - b["max"][i]) for i in (0, 1)
    ]
    gap = math.hypot(*gaps)
    axis = axes[0] if len(axes) == 1 else None
    aligned = axis is not None and all(
        abs(a[k][1 - axis] - b[k][1 - axis]) < 1e-6 for k in ("min", "max")
    )
    dz = b["max"][2] - a["max"][2]
    corridor = {
        "min": [min(a["min"][i], b["min"][i]) for i in range(3)],
        "max": [max(a["max"][i], b["max"][i]) for i in range(3)],
    }
    if axis is not None:
        corridor["min"][axis] = min(a["max"][axis], b["max"][axis])
        corridor["max"][axis] = max(a["min"][axis], b["min"][axis])
    return {
        "from_id": a["id"],
        "to_id": b["id"],
        "gap": gap,
        "delta_z": dz,
        "axis": axis,
        "takeoff_z": a["max"][2],
        "jumpstat_block_geometry": aligned and abs(dz) < 1e-6,
        "corridor": corridor,
    }


def run(project, path, check="audit", **options):
    _, raw, text, _ = project.read(path)
    analysis = Analysis(text)
    data = {}
    if check == "audit":
        analysis.audit(options.get("timer_profile", "either"))
        analysis.antibhop()
        data["teleports"] = analysis.teleports()
        data.update(analysis.bhop())
        data.update(analysis.ladders())
        data.update(analysis.water())
        data.update(
            analysis.spawns(
                options.get("minimum_t_spawns", 1), options.get("minimum_ct_spawns", 1)
            )
        )
        # Avoid an O(brushes squared) whole-map ceiling scan in the default audit.
    elif check == "measure":
        data = measure_boxes(
            analysis.select(options["start"]), analysis.select(options["end"])
        )
        data.update(
            {
                "minimum_block_distance": 186,
                "bhop_reference": 240,
                "minimum_mbh": options.get("minimum_mbh", 300),
                "above_jumpstats_maximum": data["gap"] > 500,
                "practice_distances": list(range(210, 246, 5)),
                "tier_context": "GOKZ LJ tier starts: VNL 210, SKZ/KZT 215; perfect VNL 240, SKZ/KZT 270. These are jumpstat thresholds, not map tiers or reachability predictions.",
            }
        )
        if data["gap"] > 500:
            analysis.add(
                "jump.maximum",
                "Gap exceeds GOKZ JS_MAX_JUMP_DISTANCE 500",
                severity="warning",
            )
        if not data["jumpstat_block_geometry"] or data["gap"] < 186:
            analysis.add(
                "jump.block",
                "Jumpstat block geometry needs parallel, flat, aligned, same-height edges and a gap >=186",
                severity="warning",
            )
    else:
        method = {
            "antibhop": analysis.antibhop,
            "bhop": analysis.bhop,
            "teleports": analysis.teleports,
            "headhitter": analysis.headhitter,
            "ladders": analysis.ladders,
            "water": analysis.water,
            "spawns": analysis.spawns,
        }[check]
        result = method(**options)
        data = (
            result
            if isinstance(result, dict)
            else {"teleports": result} if result is not None else {}
        )
    return {
        "revision": digest(raw),
        "check": check,
        "valid": not any(f["severity"] == "error" for f in analysis.findings),
        "complete": not analysis.unsupported,
        "findings": analysis.findings,
        "unsupported_geometry": analysis.unsupported,
        "excluded_hidden_objects": analysis.hidden,
        **data,
        "sources": [MAPPING_API, JUMPSTATS],
        "limitations": LIMITATIONS,
    }


def test_plan(project, path):
    report = run(project, path)
    return {
        "revision": report["revision"],
        "steps": [
            "Validate VMF structure, review kz_audit findings, compile a fresh BSP and inspect Hammer++ captures.",
            "Package and install matching BSP/NAV outputs with verified embedded assets; NAV file presence alone does not prove a parsed mesh or replay behavior.",
            "Load the compiled map on a 128-tick legacy CS:GO SourceMod server with the intended GOKZ version, DHooks and MovementAPI.",
            "Select the intended VNL/SKZ/KZT mode; use its actual cvars. Compare all supported modes separately.",
            "For SKZ, verify gokz-mode-simplekz and actual movement with a completed route; play recorded runs at the expected concurrent replay load, with combat bot quota zero. Record plugin versions, mode and plugin/engine bot limits.",
            "Test main/bonus start and end timers, zone exit/entry behavior, !m and !b <number>, !checkpoint/!gocheck and !ssp/!csp.",
            "Use GOKZ +measure and !measureblock. KZTimer-specific !measure/!bhopcheck require that plugin.",
            "Walk, jumpbug and triggerhop through anti-bhop; test every bhop reset, teleport angle/speed option, ladder exit, water contact and headhitter chain.",
            "Check timer-tech skips, clips, moving blocks, spawn collision, lighting, sealing and the jumpstats room (at least four LJ blocks for Global map approval).",
        ],
        "sandbox_cvars": [
            "sv_cheats 1",
            "sv_airaccelerate 1000",
            "sv_enablebunnyhopping 1",
        ],
        "cvar_scope": "Exploratory local movement only. These values do not reproduce GOKZ modes; never use them to certify mode feasibility.",
        "must_confirm_in_game": report["findings"],
        "unsupported_geometry": report["unsupported_geometry"],
        "limitations": LIMITATIONS,
        "sources": [
            MAPPING_API,
            JUMPSTATS,
            "https://github.com/KZGlobalTeam/gokz/blob/master/COMMANDS.md",
        ],
    }
