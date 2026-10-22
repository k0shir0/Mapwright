"""Official MCP SDK stdio transport; map operations share the CLI contract."""

from functools import partial
import base64
import json
import os
from urllib.parse import unquote

from .api import TOOLS, execute
from . import __version__
from .backend import BackendError
from .project import Project


def serve(project: Project, config: dict):
    # A daemon's owned editor sessions must also close if its process crashes.
    # One-shot CLI calls deliberately leave their sessions available to later calls.
    project.native_owner_pid = os.getpid()
    try:
        import anyio
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import (
            CallToolResult,
            TextContent,
            ImageContent,
            Tool,
            ToolAnnotations,
            Resource,
            ResourceTemplate,
            Prompt,
            PromptArgument,
            PromptMessage,
            GetPromptResult,
        )
        from mcp.server.lowlevel.helper_types import ReadResourceContents
    except ImportError as exc:
        raise BackendError(
            'Install the MCP extra: python -m pip install -e ".[mcp]"'
        ) from exc
    server = Server(
        "mapwright",
        version=__version__,
        instructions=(
            "Mapwright is a KZ-first legacy CS:GO Source 1 bridge. Start with doctor and inspect_map; kz_audit and kz_test_plan explain KZ findings. "
            "IDs have separate namespaces: supply kind when ambiguous. Pass the exact current revision to writes; dry_run previews. "
            "Use flat map_* tools for single edits, edit_map for atomic batches; only replace_source replaces untouched source. "
            "KZ behavior depends on exact climb_* names and GOKZ plugin settings. kz-room supplies main timer zones/course start. "
            "This workflow delivers matching BSP/NAV files and embedded dependencies; empty NAVs prove presence only. package_map verifies the archive; runtime rendering, SKZ movement and replay behavior need separate evidence. "
            "Every tool request has a permanent action receipt; use timeline_status, action_history, inspect_action and checkout_action for saved-state recovery with retained future history. "
            "open_editor owns a private Windows desktop and staged map. Use inspected semantic controls, then save_editor with the source revision; close_editor releases its process tree. "
            "Native actions expose checkpointed/document_reversible; check them and inspect resulting state. capture_editor auto uses native viewport readback on verified renderer DLLs, with explicit UI-only fallback; viewport requires GPU capture and window captures UI chrome. Compile fresh and test the intended GOKZ mode in-game. "
            "Static checks cannot prove movement feasibility; unsupported geometry is reported. Read hammer://guide/kz for the workflow."
        ),
    )

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name=name,
                description=tool["description"],
                inputSchema=tool["inputSchema"],
                outputSchema=tool["outputSchema"],
                annotations=ToolAnnotations(
                    readOnlyHint=tool["readonly"],
                    destructiveHint=tool["destructive"],
                    idempotentHint=tool["readonly"],
                    openWorldHint=tool["openworld"],
                ),
            )
            for name, tool in TOOLS.items()
        ]

    @server.list_resources()
    async def list_resources():
        return [
            Resource(
                uri="hammer://guide/kz",
                name="KZ mapping workflow",
                mimeType="text/markdown",
            ),
            Resource(
                uri="hammer://workspace/artifacts",
                name="Recovery artifact index",
                mimeType="application/json",
            ),
            Resource(
                uri="hammer://workspace/operations",
                name="Recent workspace operation log",
                mimeType="application/json",
            ),
        ]

    @server.list_resource_templates()
    async def list_resource_templates():
        return [
            ResourceTemplate(
                uriTemplate="hammer://artifact/{path}",
                name="Read workspace bridge artifact (URL-encoded path)",
                mimeType="application/json",
            )
        ]

    @server.read_resource()
    async def read_resource(uri):
        value = str(uri)
        if value == "hammer://guide/kz":
            return [ReadResourceContents(KZ_GUIDE, "text/markdown")]
        if value == "hammer://workspace/artifacts":
            result = await anyio.to_thread.run_sync(
                partial(execute, project, config, "list_artifacts", {})
            )
        elif value == "hammer://workspace/operations":
            result = await anyio.to_thread.run_sync(
                partial(execute, project, config, "operation_log", {})
            )
        elif value.startswith("hammer://artifact/"):
            path = unquote(value[len("hammer://artifact/") :])
            result = await anyio.to_thread.run_sync(
                partial(execute, project, config, "read_artifact", {"path": path})
            )
        else:
            raise ValueError(
                "Unknown resource; list resources and use the advertised artifact template"
            )
        return [
            ReadResourceContents(
                json.dumps(result, ensure_ascii=True, separators=(",", ":")),
                "application/json",
            )
        ]

    @server.list_prompts()
    async def list_prompts():
        return [
            Prompt(
                name="kz_mapping_workflow",
                description="Create/edit, audit, compile and verify a KZ map",
                arguments=[
                    PromptArgument(
                        name="path", description="Workspace VMF path", required=True
                    ),
                    PromptArgument(
                        name="task",
                        description="Requested mapping change",
                        required=False,
                    ),
                ],
            )
        ]

    @server.get_prompt()
    async def get_prompt(name, arguments):
        if name != "kz_mapping_workflow" or not arguments or not arguments.get("path"):
            raise ValueError("Use kz_mapping_workflow with path and optional task")
        project.map_path(arguments["path"])
        text = f"Work on {arguments['path']}. Requested change: {arguments.get('task','inspect and improve KZ mapping')}.\n{KZ_GUIDE}"
        return GetPromptResult(
            description="KZ map verification workflow",
            messages=[
                PromptMessage(role="user", content=TextContent(type="text", text=text))
            ],
        )

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        try:
            context = server.request_context
            token = context.meta.progressToken if context.meta else None

            async def progress():
                tick = 0
                while True:
                    try:
                        await context.session.send_progress_notification(
                            token, tick, message=f"Running {name}"
                        )
                    except (
                        OSError,
                        RuntimeError,
                        anyio.BrokenResourceError,
                        anyio.ClosedResourceError,
                    ):
                        return
                    tick += 1
                    await anyio.sleep(2)

            async with anyio.create_task_group() as group:
                if token is not None and name in (
                    "compile_map",
                    "package_map",
                    "edit_map",
                    "copy_reference_objects",
                    "import_reference_map",
                    "create_checkpoint",
                    "restore_checkpoint",
                ):
                    group.start_soon(progress)
                try:
                    data = await anyio.to_thread.run_sync(
                        partial(execute, project, config, name, arguments)
                    )
                except (ValueError, OSError, TypeError, KeyError, TimeoutError) as exc:
                    # Catch inside the group: clients need a tool error, not ExceptionGroup.
                    data = None
                    failure = exc
                else:
                    failure = None
                finally:
                    group.cancel_scope.cancel()
            if failure is not None:
                raise failure
            result = {"ok": True, "data": data}
        except (ValueError, OSError, TypeError, KeyError, TimeoutError) as exc:
            result = {"ok": False, "error": str(exc)}
            if isinstance(exc, BackendError):
                result["details"] = exc.details
        content = [
            TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            )
        ]
        if name == "capture_editor" and result["ok"]:
            content.append(
                ImageContent(
                    type="image",
                    mimeType="image/png",
                    data=base64.b64encode(
                        project.confined(result["data"]["path"]).read_bytes()
                    ).decode("ascii"),
                )
            )
        return CallToolResult(
            content=content,
            structuredContent=result,
            isError=not result["ok"],
        )

    async def run():
        try:
            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())
        finally:
            from .native_session import close_sessions

            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(partial(close_sessions, project, config))

    anyio.run(run)


KZ_GUIDE = """Read doctor and inspect_map. New KZ maps can use create_map template=kz-room.
Source/artifact pages default to 8000 characters/bytes. Large results carry
response.truncated, totals and an immutable result artifact; read every evidence
page or request response_mode=full. Preserve valid/complete and unsupported counts.
Pin expected_revision across source pages and expected_history_revision across
map_history pages. Never replace a map using incomplete source.
Inspect exact object IDs/kinds and the current revision. Use map_* tools for a single
edit or edit_map for atomic batches, with expected_revision and optional dry_run.
set_properties null removes a key; add_entity properties cannot be null.
For ladders/water use add_box face_materials (top/bottom/north/south/east/west).
Run validate_map and kz_audit; a successful check returns ok=true even with findings.
Inspect data.valid, findings, complete and unsupported_geometry. Use kz_measure_jumps
on solids/top faces, ordered kz_check_bhop routes, and corridor headhitter checks.
Check every light origin/emitting surface clears walls, props and fixture housings.
Inspect every visible block from reachable views for missing/reversed faces, missing
materials or exposed nodraw; ordinary boxes need six faces. Verify lighting/surfaces
in a fresh compiled render; unsupported geometry needs manual inspection.
KZ names are a plugin API: preserve climb_* names; enable button flags 1+32, trigger
Clients=1, anti-bhop thickness >=16u, destination floor clearance >=4u, bhop delay >=0.08s.
Every tool request has an action ID. action_history and inspect_action expose retained
attempts/results and before/after saved-file states; checkout_action restores a chosen
action with expected_head from timeline_status, retaining future actions for redo.
open_editor launches a staged copy on an owned private Windows desktop. Inspect menus
and controls, use semantic editor_action messages, and check document_reversible.
save_editor commits staged bytes with the source map's expected_revision. close_editor
releases the owned session. Native UI undo/camera state is separate from saved VMF state.
capture_editor method=viewport requires actual render-thread pixels; method=window
captures UI chrome. auto reports fallback explicitly. Uniform frames carry warnings;
inspect the image and camera/map state before claiming visible geometry.
Named checkpoints are also available for explicit file/folder snapshots.
inspect_checkpoint lists every current revision needed for restore_checkpoint;
restoration keeps a reverse checkpoint and resumable recovery receipt. Never overwrite
external changes. operation_log, list_artifacts and read_artifact expose evidence.
Import references to new VMFs, inspect actual selections, then copy with both revisions.
Compile with asset packing enabled for a fresh BSP and matching NAV; empty NAVs
prove presence only. package_map verifies archive contents and build hashes.
Use kz_audit timer_profile=buttons for physical +use timers; profile spawn capacity.
Inspect stage logs and real editor captures, then use kz_test_plan
on the intended GOKZ mode/server. Process launch, structural validity and box geometry
do not prove rendering, movement feasibility or playability. Unusual geometry needs
manual/editor inspection. GOKZ zones are named Hammer entities, not an in-game zone editor.
"""
