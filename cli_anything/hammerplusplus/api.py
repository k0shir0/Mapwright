"""One discoverable command contract shared by the CLI and MCP transport."""

import jsonschema
import time
import uuid

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
ENTITY_PROPERTIES = {
    "type": "object",
    "additionalProperties": {"type": ["string", "number"]},
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
                "face_materials": schema(
                    {
                        k: STRING
                        for k in ("top", "bottom", "south", "north", "west", "east")
                    },
                    [],
                ),
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
            {"classname": STRING, "origin": VECTOR, "properties": ENTITY_PROPERTIES},
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
        operation("replace_source", {"source": STRING}, ["source"]),
    ]
}


def spec(description: str, props: dict, required: list[str], readonly: bool = True):
    return {
        "description": description,
        "inputSchema": schema(props, required),
        "readonly": readonly,
    }


TOOLS = {
    "list_map_files": spec(
        "List mapping files in the selected workspace.",
        {"query": STRING, "limit": {"type": "integer", "minimum": 1, "maximum": 1000}},
        [],
    ),
    "read_map_source": spec(
        "Read any native VMF feature as paginated source text with its revision. Use replace_source in edit_map to author features without a specialized helper.",
        {
            "path": MAP,
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000000},
        },
        ["path"],
    ),
    "delete_map_file": spec(
        "Delete a VMF file after snapshotting it; returns a token for recovery. Requires current revision.",
        {"path": MAP, "expected_revision": REVISION},
        ["path", "expected_revision"],
        False,
    ),
    "restore_map_file": spec(
        "Restore a deleted map from its recovery token, refusing overwrite.",
        {"token": STRING},
        ["token"],
        False,
    ),
    "import_reference_map": spec(
        "Import an external VMF or CS:GO BSP to a new VMF. BSP inputs require configured bspsrc_java (BSPSource bundled Java). Assets extract locally; returns provenance and reconstruction limits.",
        {
            "source": STRING,
            "output": MAP,
            "timeout": {"type": "integer", "minimum": 1, "maximum": 3600},
        },
        ["source", "output"],
        False,
    ),
    "search_reference_map": spec(
        "Search raw source text (including names, properties, coordinates and comments) of entities/world brushes, with optional spatial bounds. Resolve the user's item description before copying.",
        {
            "path": MAP,
            "query": STRING,
            "minimum": VECTOR,
            "maximum": VECTOR,
            "kind": {"enum": ["solid", "entity", ""]},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        ["path"],
    ),
    "copy_reference_objects": spec(
        "Copy identified reference solids/entities into an existing destination VMF with both revisions checked, ID and targetname remapping, linked entities, texture-locked translation and provenance. Supports displacements and overlay face remapping; inspect external-reference warnings.",
        {
            "source": MAP,
            "destination": MAP,
            "source_revision": REVISION,
            "expected_revision": REVISION,
            "selection": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10000,
                "items": schema(
                    {"id": INTEGER, "kind": {"enum": ["solid", "entity"]}},
                    ["id", "kind"],
                ),
            },
            "delta": VECTOR,
            "prefix": STRING,
            "include_links": {"type": "boolean"},
            "dry_run": {"type": "boolean"},
        },
        ["source", "destination", "source_revision", "expected_revision", "selection"],
        False,
    ),
    "inspect_editor": spec(
        "Inspect actual Hammer++ menus, windows and controls by verified PID. Windows and desktop extra required. Native UI fallback; inspect enabled dialogs before acting.",
        {
            "pid": {"type": "integer", "minimum": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        ["pid"],
    ),
    "editor_action": spec(
        "Dispatch native Hammer++ actions using inspected labels/owned handles. Windows and desktop extra required. Checkpoint saved map files before GUI edits; unsaved GUI state requires Hammer undo. Verify state and capture afterward.",
        {
            "pid": {"type": "integer", "minimum": 1},
            "action": {
                "enum": [
                    "menu",
                    "keys",
                    "text",
                    "select",
                    "invoke",
                    "click",
                    "double_click",
                    "drag",
                    "scroll",
                    "focus",
                    "restore",
                    "maximize",
                    "close",
                ]
            },
            "hwnd": INTEGER,
            "menu": STRING,
            "text": STRING,
            "keys": STRING,
            "x": INTEGER,
            "y": INTEGER,
            "end_x": INTEGER,
            "end_y": INTEGER,
            "button": {"enum": ["left", "right", "middle"]},
            "steps": {"type": "integer", "minimum": -100, "maximum": 100},
        },
        ["pid", "action"],
        False,
    ),
    "doctor": spec(
        "Report legacy CS:GO SDK and Hammer++ readiness without launching tools.",
        {},
        [],
    ),
    "create_map": spec(
        "Create a new native VMF, refusing overwrite. csgo-room is an enclosed test room with team spawns and light.",
        {
            "path": MAP,
            "template": {"enum": ["empty", "csgo-room", "kz-room"], "default": "empty"},
        },
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
        "Apply an atomic revision-checked batch. Targeted operations preserve untouched source; replace_source replaces the whole document. dry_run previews IDs/hash. Prefer flat map_* tools for single operations. Room bounds are interior; parent_id attaches a brush.",
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
        "Capture configured Hammer++ to a new PNG on Windows. window uses PrintWindow (GPU viewports may be blank); screen requires desktop extra and an unobscured window. Inspect the image for actual rendering.",
        {
            "pid": {"type": "integer", "minimum": 1},
            "output": STRING,
            "method": {"enum": ["window", "screen"]},
        },
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

PAGE = {
    "offset": {"type": "integer", "minimum": 0},
    "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
}
SELECTOR = schema({"id": INTEGER, "kind": {"enum": ["solid", "side"]}}, ["id"])
KZ_TOOLS = {
    "kz_audit": (
        "audit",
        "Audit GOKZ main/bonus timers, exact names, flags, starts, teleports, anti-bhop, ladders, water and spawns.",
    ),
    "kz_check_antibhop": (
        "antibhop",
        "Check >=16u anti-bhop volume thickness, delay and >=4u destination floor clearance.",
    ),
    "kz_check_bhop": (
        "bhop",
        "Check GOKZ teleport types/delays and optionally ordered landing-block route gaps/reset-ground candidates.",
    ),
    "kz_measure_jumps": (
        "measure",
        "Measure edge gap/delta-z between box solids or top sides; report jumpstat geometry and server thresholds, not reachability.",
    ),
    "kz_check_headhitter": (
        "headhitter",
        "Find box floor/ceiling clearances, optionally along a selected jump corridor; report headhit jumpstat context.",
    ),
    "kz_check_ladders": (
        "ladders",
        "Inspect invisible-ladder material, ownership and optional LAJ landing height; in-game zero-offset verification still required.",
    ),
    "kz_check_water": (
        "water",
        "Check rectangular level water, top-only material, nodraw sides, ownership, skyname and LOD context.",
    ),
    "kz_check_teleports": (
        "teleports",
        "Resolve GOKZ/native teleport destinations and summarize angle, speed, relative/reorient behavior.",
    ),
    "kz_spawn_check": (
        "spawns",
        "Check team spawn presence/parity, brush hull overlap, angles, ceilings and start zones.",
    ),
    "kz_test_plan": (
        "test_plan",
        "Return an in-game GOKZ verification recipe tied to current VMF findings and revision.",
    ),
}
for name, (check, description) in KZ_TOOLS.items():
    props = {"path": MAP}
    required = ["path"]
    if check in ("measure", "headhitter"):
        props.update(start=SELECTOR, end=SELECTOR)
        if check == "measure":
            required.extend(["start", "end"])
    if check == "ladders":
        props["landing"] = SELECTOR
    if check in ("bhop", "measure"):
        props["minimum_mbh"] = {"type": "number", "minimum": 0, "maximum": 500}
    if check == "bhop":
        props["route"] = {
            "type": "array",
            "items": SELECTOR,
            "minItems": 2,
            "maxItems": 100,
        }
    TOOLS[name] = spec(
        description
        + " Read-only VMF analysis; unsupported geometry is reported; compile/test in-game.",
        props,
        required,
    )

# Keep edit_map for atomic batches; individual tools avoid a large union schema.
for op in OPERATIONS["oneOf"]:
    name = op["properties"]["op"]["const"]
    TOOLS["map_" + name] = spec(
        "Apply one "
        + name
        + " operation with revision check, snapshots and dry-run. "
        + (
            "Replaces the entire source; inspect a checkpoint first."
            if name == "replace_source"
            else "See field schema; untouched bytes remain intact."
        ),
        {
            "path": MAP,
            "expected_revision": REVISION,
            "dry_run": {"type": "boolean"},
            **{k: v for k, v in op["properties"].items() if k != "op"},
        },
        ["path", "expected_revision", *[k for k in op["required"] if k != "op"]],
        False,
    )

TOOLS.update(
    {
        "operation_log": spec(
            "Read paginated workspace JSONL operation outcomes, timestamps, session/call IDs and errors. Logs rotate at 4 MiB; source bodies are hashed.",
            PAGE,
            [],
        ),
        "list_artifacts": spec(
            "List history, snapshots, trash tokens, receipts/builds, imports and checkpoints without hiding bridge state.",
            {**PAGE, "category": STRING},
            [],
        ),
        "read_artifact": spec(
            "Read a confined bridge artifact as bounded bytes/text or base64. Offsets are bytes; snapshots expose exact prior VMF source.",
            {
                "path": STRING,
                "offset": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000000},
            },
            ["path"],
        ),
        "create_checkpoint": spec(
            "Snapshot explicit workspace files/folders, including saved maps, assets and local config. No overwrite. Limits 10000 files, 128 MiB/file, 512 MiB total. Unsaved GUI state is excluded.",
            {
                "paths": {
                    "type": "array",
                    "items": STRING,
                    "minItems": 1,
                    "maxItems": 100,
                },
                "label": STRING,
            },
            ["paths"],
            False,
        ),
        "inspect_checkpoint": spec(
            "Read a checkpoint and current revisions (including null for absent files); review changes before restoring.",
            {"token": STRING},
            ["token"],
        ),
        "restore_checkpoint": spec(
            "Restore checkpoint files/folders after matching every inspected current revision. Keeps a reverse checkpoint and resumable receipt; multi-file restoration is recoverable, not atomic. dry_run previews.",
            {
                "token": STRING,
                "expected_revisions": {
                    "type": "object",
                    "additionalProperties": {"anyOf": [REVISION, {"type": "null"}]},
                },
                "dry_run": {"type": "boolean"},
            },
            ["token", "expected_revisions"],
            False,
        ),
        "resume_recovery": spec(
            "Resume an interrupted checkpoint restore only if every file matches the receipt's before/after hashes. Refuses external changes.",
            {"token": STRING},
            ["token"],
            False,
        ),
        "lock_status": spec(
            "Inspect workspace write-lock owner, timestamp and process liveness without removing it.",
            {},
            [],
        ),
        "recover_lock": spec(
            "Remove the unchanged inspected write lock only when its owner is confirmed dead. Ambiguous liveness fails closed.",
            {"expected_revision": REVISION},
            ["expected_revision"],
            False,
        ),
    }
)

OUTPUT_SCHEMA = schema(
    {
        "ok": {"type": "boolean"},
        "data": {"type": "object"},
        "error": STRING,
        "details": {"type": "object"},
        "warnings": {"type": "array", "items": STRING},
    },
    ["ok"],
)
for name, tool in TOOLS.items():
    tool["outputSchema"] = OUTPUT_SCHEMA
    tool["destructive"] = (
        name
        in {
            "delete_map_file",
            "edit_map",
            "undo_map",
            "redo_map",
            "copy_reference_objects",
            "editor_action",
            "restore_checkpoint",
            "resume_recovery",
            "recover_lock",
        }
        or name.startswith("map_")
        and name != "map_history"
    )
    tool["openworld"] = name in {
        "import_reference_map",
        "compile_map",
        "open_editor",
        "inspect_editor",
        "editor_action",
        "capture_editor",
        "rea_probe",
        "entity_catalog",
        "asset_catalog",
        "doctor",
    }


def _execute(project: Project, config: dict, action: str, args: dict) -> dict:
    import json

    try:
        json.dumps(args, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MapError("Tool arguments must contain finite JSON values") from exc
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
    if action in KZ_TOOLS:
        from . import kz

        check = KZ_TOOLS[action][0]
        return (
            kz.test_plan(project, path)
            if check == "test_plan"
            else kz.run(project, path, check, **values)
        )
    if action.startswith("map_") and action != "map_history":
        expected = values.pop("expected_revision")
        dry = values.pop("dry_run", False)
        return project.apply(path, expected, [{"op": action[4:], **values}], dry)
    if action in {
        "operation_log",
        "list_artifacts",
        "read_artifact",
        "create_checkpoint",
        "inspect_checkpoint",
        "restore_checkpoint",
        "resume_recovery",
        "lock_status",
        "recover_lock",
    }:
        from . import workspace

        method = {
            "operation_log": workspace.operations,
            "list_artifacts": workspace.artifacts,
            "read_artifact": workspace.read_artifact,
            "create_checkpoint": workspace.checkpoint,
            "inspect_checkpoint": workspace.checkpoint_status,
            "restore_checkpoint": workspace.restore_checkpoint,
            "resume_recovery": workspace.resume_recovery,
            "lock_status": workspace.lock_status,
            "recover_lock": workspace.recover_lock,
        }[action]
        if action == "read_artifact":
            values["path"] = path
        return method(project, **values)
    if action == "list_map_files":
        return project.files(**values)
    if action == "read_map_source":
        return project.source(path, **values)
    if action == "delete_map_file":
        return project.delete_file(path, **values)
    if action == "restore_map_file":
        return project.restore_file(**values)
    if action in (
        "import_reference_map",
        "search_reference_map",
        "copy_reference_objects",
    ):
        from . import reference

        if action == "import_reference_map":
            import zipfile

            try:
                return reference.import_map(project, config, **values)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
                raise backend.BackendError(f"Reference import failed: {exc}") from exc
        if action == "search_reference_map":
            return reference.search(project, path, **values)
        return reference.copy_objects(project, config=config, **values)
    if action in ("inspect_editor", "editor_action", "capture_editor"):
        if action == "capture_editor":
            from . import windows as native
        else:
            from . import desktop as native

        try:
            return getattr(native, action)(project, config, **values)
        except backend.BackendError:
            raise
        except Exception as exc:
            # Win32 and pywinauto exceptions are not necessarily OSError subclasses.
            raise backend.BackendError(
                f"Native editor operation failed: {exc}"
            ) from exc
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
    if action == "entity_catalog":
        return catalog.entities(project, config, **values)
    if action == "asset_catalog":
        return catalog.assets(project, config, **values)
    return backend.rea_probe(project, config, **values)


def execute(project: Project, config: dict, action: str, args: dict) -> dict:
    from . import workspace

    call_id = uuid.uuid4().hex
    start = time.monotonic()
    # Reading audit/recovery metadata remains a pure read and never logs itself.
    record = action not in {
        "operation_log",
        "list_artifacts",
        "read_artifact",
        "inspect_checkpoint",
        "lock_status",
        "map_history",
    }
    event = {"call_id": call_id, "tool": action, **workspace.summary(args)}
    warning = None

    def write(status, **extra):
        nonlocal warning
        if record:
            try:
                workspace.log(project, {**event, "status": status, **extra})
            except (OSError, ValueError) as exc:
                warning = f"Operation audit unavailable: {exc}"

    write("started")
    try:
        result = _execute(project, config, action, args)
    except Exception as exc:
        write(
            "failed",
            error=str(exc)[:4000],
            elapsed_seconds=round(time.monotonic() - start, 3),
        )
        raise
    write(
        "completed",
        revision=result.get("revision"),
        **{
            key: result[key]
            for key in (
                "token",
                "reverse_checkpoint",
                "recovery_token",
                "valid",
                "dry_run",
            )
            if key in result
        },
        elapsed_seconds=round(time.monotonic() - start, 3),
    )
    if warning:
        result = {**result, "audit_warning": warning}
    return result
