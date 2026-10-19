"""Exercise actual MCP BSP decompilation, native copy and real Source compilation."""

import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys
import uuid

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Real legacy CS:GO BSP to decompile")
    parser.add_argument("--workspace", default=".")
    parser.add_argument(
        "--solid",
        type=int,
        action="append",
        required=True,
        help="Source solid ID from an earlier search; repeat for the whole item",
    )
    parser.add_argument("--delta", type=float, nargs=3, default=[0, 0, 0])
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve(strict=True)
    folder = ".local/reference-verification/" + uuid.uuid4().hex
    receipt = {"source": str(Path(args.source).resolve()), "steps": []}

    async def scenario():
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "cli_anything.hammerplusplus",
                "--workspace",
                str(workspace),
                "mcp",
            ],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
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
                        raise RuntimeError(json.dumps(result))
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

    anyio.run(scenario)
    out = workspace / folder / "verification.json"
    out.write_text(json.dumps(receipt, indent=2))
    print(
        json.dumps(
            {
                "ok": True,
                "receipt": str(out),
                "destination": receipt["destination"],
                "counts": receipt["counts"],
                "bsp": receipt["compile"]["bsp"]["path"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
