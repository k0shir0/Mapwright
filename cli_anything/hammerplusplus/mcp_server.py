"""Official MCP SDK stdio transport; map operations share the CLI contract."""

from functools import partial
import base64
import json

from .api import TOOLS, execute
from . import __version__
from .backend import BackendError
from .project import Project


def serve(project: Project, config: dict):
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
        )
    except ImportError as exc:
        raise BackendError(
            'Install the MCP extra: python -m pip install -e ".[mcp]"'
        ) from exc
    server = Server(
        "hammerplusplus-agent",
        version=__version__,
        instructions="Legacy CS:GO Source 1 mapping. Start with doctor and inspect_map. Pass the returned revision to edit_map. Use native compilers and editor captures before claiming playable or rendered results.",
    )

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name=name,
                description=tool["description"],
                inputSchema=tool["inputSchema"],
                annotations=ToolAnnotations(
                    readOnlyHint=tool["readonly"],
                    destructiveHint=not tool["readonly"],
                    openWorldHint=name in ("import_reference_map", "editor_action"),
                ),
            )
            for name, tool in TOOLS.items()
        ]

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        try:
            if name not in TOOLS:
                raise ValueError(f"Unknown tool: {name}")
            data = await anyio.to_thread.run_sync(
                partial(execute, project, config, name, arguments)
            )
            result = {"ok": True, "data": data}
            if name == "validate_map" and not data["valid"]:
                result["ok"] = False
        except (ValueError, OSError, TypeError, KeyError, TimeoutError) as exc:
            result = {"ok": False, "error": str(exc)}
            if isinstance(exc, BackendError):
                result["details"] = exc.details
        content = [
            TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
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
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)
