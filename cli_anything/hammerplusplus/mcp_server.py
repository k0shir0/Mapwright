"""Official MCP SDK stdio transport; map operations share the CLI contract."""

from functools import partial
import json

from .api import TOOLS, execute
from .backend import BackendError
from .project import Project


def serve(project: Project, config: dict):
    try:
        import anyio
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
    except ImportError as exc:
        raise BackendError(
            'Install the MCP extra: python -m pip install -e ".[mcp]"'
        ) from exc
    server = Server(
        "hammerplusplus-agent",
        version="0.1.0",
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
                    openWorldHint=False,
                ),
            )
            for name, tool in TOOLS.items()
        ]

    @server.call_tool()
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
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
            ],
            structuredContent=result,
            isError=not result["ok"],
        )

    async def run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)
