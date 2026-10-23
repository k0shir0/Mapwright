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
from .errors import failure as error_result


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
            "Mapwright is a KZ-first legacy CS:GO Source 1 bridge. Read hammer://guide/kz for task routing. "
            "Inspect current revisions before writes; dry_run previews. Check data.valid/complete as well as ok. "
            "Large results retain immutable evidence; read selected fields with read_artifact."
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
            result = error_result(exc)
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


KZ_GUIDE = """Mapwright edits VMF source and compiles BSP maps with matching NAV files for legacy
CS:GO. Offline VMF operations are portable; native Hammer++ needs Windows.
Inspection: inspect_map returns revision and typed IDs; use focused object pages.
Editing: use map_* for one edit or edit_map for an atomic batch; preview dry_run,
then write with expected_revision. Preserve unrelated source. Replacement needs
all source pages pinned to the same revision.
KZ rules: kz_audit returns exact required names, flags and geometry findings;
use timer_profile=buttons for physical +use timers. Read the installed mapping
skill's KZ contract for authoring details. kz_test_plan selects runtime checks.
Native work: doctor first; compile fresh, package dependencies, inspect captures.
open_editor stages a private document; inspect state, save_editor to commit,
close_editor to release it. Saved-file recovery excludes unsaved editor memory.
Recovery: inspect_action/action_history retain attempts; inspect evidence before
undo, checkpoint restore or checkout_action with expected_head.
Results: ok means execution succeeded; inspect valid, complete and unsupported
geometry before claims. Read relevant omitted fields via read_artifact field=NAME;
follow next_offset. Full bytes remain available for exact reconstruction.
Report source, packaging, rendering and gameplay evidence separately. Use the
requested acceptance scope; an editor capture cannot prove in-game behavior.
"""
