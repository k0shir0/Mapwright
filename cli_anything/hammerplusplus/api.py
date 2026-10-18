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
        "Import an explicitly supplied external VMF or CS:GO BSP. BSPSource decompiles BSP to VMF; embedded assets are safely extracted locally. Returns provenance and reconstruction limits.",
        {
            "source": STRING,
            "output": MAP,
            "timeout": {"type": "integer", "minimum": 1, "maximum": 3600},
        },
        ["source", "output"],
        False,
    ),
    "search_reference_map": spec(
        "Find reference-map entities and world brushes by text in names/materials/properties and optional spatial bounds. Use this evidence to resolve the user plain-language item description before copying.",
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
        "Inspect the actual configured Hammer++ PID: menus, enabled commands, windows, dialogs and controls. Native UI fallback for all editor features, including those without dedicated VMF helpers.",
        {
            "pid": {"type": "integer", "minimum": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        ["pid"],
    ),
    "editor_action": spec(
        "Interact with the actual editor using discovered menu paths/control handles, keyboard, mouse, text, combo selection, drag or window actions. GUI changes/saves act inside Hammer++; inspect state and rendered capture afterward.",
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
