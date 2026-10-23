"""Exercise actual MCP BSP decompilation, native copy and real Source compilation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._support import JsonArgumentParser, run, verify

from datetime import timedelta
import json
import uuid


def main():
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument("source", help="Real legacy CS:GO BSP to decompile")
    parser.add_argument(
        "--workspace",
        default=".",
        help="Configured workspace for import, copy and compile artifacts (default: current directory)",
    )
    parser.add_argument(
        "--solid",
        type=int,
        action="append",
        required=True,
        help="Source solid ID from an earlier search; repeat for the whole item",
    )
    parser.add_argument(
        "--delta",
        type=float,
        nargs=3,
        default=[0, 0, 0],
        help="Translation X Y Z applied to the copied solids (default: 0 0 0)",
    )
    args = parser.parse_args()
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from cli.hammerplusplus.errors import AgentError

    workspace = Path(args.workspace).resolve(strict=True)
    folder = ".local/reference-verification/" + uuid.uuid4().hex
    receipt = {"source": str(Path(args.source).resolve()), "steps": []}

    async def scenario():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "cli.hammerplusplus",
                "--workspace",
                str(workspace),
                "mcp",
            ],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=30)
            ) as client:
                await client.initialize()

                async def call(name, values):
                    response = await client.call_tool(
                        name,
                        values,
                        read_timeout_seconds=timedelta(seconds=240),
                    )
                    result = response.structuredContent or json.loads(
                        response.content[0].text
                    )
                    if response.isError or not result["ok"]:
                        raise AgentError(result["error"], result.get("details"))
                    receipt["steps"].append(name)
                    return result["data"]

                source = folder + "/reference.vmf"
                destination = folder + "/copied-room.vmf"
                imported = await call(
                    "import_reference_map",
                    {"source": str(Path(args.source).resolve()), "output": source},
                )
                found = await call(
                    "search_reference_map",
                    {"path": source, "kind": "solid", "limit": 5},
                )
                created = await call(
                    "create_map", {"path": destination, "template": "csgo-room"}
                )
                copied = await call(
                    "copy_reference_objects",
                    {
                        "source": source,
                        "destination": destination,
                        "source_revision": imported["revision"],
                        "expected_revision": created["revision"],
                        "selection": [{"id": i, "kind": "solid"} for i in args.solid],
                        "delta": args.delta,
                    },
                )
                checked = await call("inspect_map", {"path": destination})
                assert checked["counts"]["solid"] == 6 + len(args.solid), checked
                compiled = await call(
                    "compile_map",
                    {
                        "path": destination,
                        "expected_revision": copied["revision"],
                        "timeout": 180,
                    },
                )
                assert compiled["bsp"]["version"] == 21
                assert all(stage["returncode"] == 0 for stage in compiled["stages"])
                receipt.update(
                    destination=destination,
                    provenance=imported["provenance"],
                    reference_solids=found["total"],
                    copied=copied["copied"],
                    asset_mount=copied["asset_mount"],
                    counts=checked["counts"],
                    compile=compiled,
                )

    out = workspace / folder / "verification.json"
    verify(scenario, receipt, out)
    return {
        "receipt": str(out),
        "destination": receipt["destination"],
        "counts": receipt["counts"],
        "bsp": receipt["compile"]["bsp"]["path"],
    }


if __name__ == "__main__":
    raise SystemExit(run(main))
