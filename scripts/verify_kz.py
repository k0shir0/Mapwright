"""Verify KZ authoring/measurement through real MCP and actual Source compilers."""

import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys
import struct
import uuid

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        default=".",
        help="Existing workspace with configured legacy CS:GO compilers",
    )
    args = parser.parse_args()
    root = Path(args.workspace).resolve(strict=True)
    folder = ".local/kz-verification/" + uuid.uuid4().hex
    path = folder + "/kz_verification.vmf"
    report = {"path": path, "steps": []}

    async def scenario():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "cli_anything.hammerplusplus", "--workspace", str(root), "mcp"],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()

                async def call(name, values):
                    response = await client.call_tool(
                        name, values, read_timeout_seconds=timedelta(seconds=240)
                    )
                    if response.isError:
                        raise RuntimeError(json.dumps(response.structuredContent))
                    report["steps"].append(name)
                    return response.structuredContent["data"]

                result = await call("create_map", {"path": path, "template": "kz-room"})
                revision = result["revision"]

                async def edit(operation, **values):
                    nonlocal revision
                    result = await call(
                        "map_" + operation,
                        {"path": path, "expected_revision": revision, **values},
                    )
                    revision = result["revision"]
                    return result["results"][0]["ids"][0]

                first = await edit(
                    "add_box",
                    min=[-192, -64, 0],
                    max=[-160, 64, 32],
                    material="dev/dev_measuregeneric01b",
                )
                second = await edit(
                    "add_box",
                    min=[80, -64, 0],
                    max=[112, 64, 32],
                    material="dev/dev_measuregeneric01b",
                )
                anti = await edit(
                    "add_entity",
                    classname="trigger_multiple",
                    origin=[0, 0, 0],
                    properties={
                        "targetname": "climb_anti_bhop",
                        "spawnflags": "1",
                        "climb_anti_bhop_time": "0.2",
                    },
                )
                await edit(
                    "add_box",
                    min=[-216, -88, 0],
                    max=[-136, 88, 48],
                    material="tools/toolstrigger",
                    parent_id=anti,
                    parent_kind="entity",
                )
                await edit(
                    "add_entity",
                    classname="info_teleport_destination",
                    origin=[-176, 0, 36],
                    properties={"targetname": "practice_reset", "angles": "0 0 0"},
                )
                bhop = await edit(
                    "add_entity",
                    classname="trigger_multiple",
                    origin=[0, 0, 0],
                    properties={
                        "targetname": "climb_teleport",
                        "spawnflags": "1",
                        "climb_teleport_type": "1",
                        "climb_teleport_destination": "practice_reset",
                        "climb_teleport_delay": "0.1",
                    },
                )
                await edit(
                    "add_box",
                    min=[56, -88, 0],
                    max=[136, 88, 48],
                    material="tools/toolstrigger",
                    parent_id=bhop,
                    parent_kind="entity",
                )
                audit = await call("kz_audit", {"path": path})
                assert audit["valid"] and audit["complete"], audit
                measure = await call(
                    "kz_measure_jumps",
                    {"path": path, "start": {"id": first}, "end": {"id": second}},
                )
                assert (
                    measure["gap"] == 240 and measure["jumpstat_block_geometry"]
                ), measure
                compile = await call(
                    "compile_map",
                    {
                        "path": path,
                        "expected_revision": revision,
                        "mode": "fast",
                        "timeout": 180,
                    },
                )
                assert compile["bsp"]["version"] == 21
                bsp = Path(compile["bsp"]["path"]).read_bytes()
                offset, size = struct.unpack_from("<ii", bsp, 8)
                entities = bsp[offset : offset + size].decode("utf-8", errors="replace")
                required = (
                    "climb_mapping_api_version",
                    "climb_startzone",
                    "climb_endzone",
                    "climb_start",
                    "climb_anti_bhop",
                    "climb_teleport",
                    "climb_teleport_destination",
                    "practice_reset",
                )
                assert all(key in entities for key in required), entities
                report["bsp_verified_keys"] = required
                report.update(
                    revision=revision,
                    audit=audit,
                    measurement=measure,
                    compile=compile,
                    test_plan=await call("kz_test_plan", {"path": path}),
                )

    anyio.run(scenario)
    output = root / folder / "verification.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "receipt": str(output),
                "vmf": str(root / path),
                "bsp": report["compile"]["bsp"]["path"],
                "gap": report["measurement"]["gap"],
                "verification": "Actual MCP authoring/audit/measurement and Source compilation; editor rendering and in-game behavior require separate verification.",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
