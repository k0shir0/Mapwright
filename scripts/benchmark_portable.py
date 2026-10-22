"""Measure portable synthetic workloads; accepts an optional checkout to compare."""

import argparse
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time
import tracemalloc
import hashlib
from unittest.mock import patch


def timed(fn, count=3):
    samples = []
    for _ in range(count):
        start = time.perf_counter()
        value = fn()
        samples.append(time.perf_counter() - start)
    return {
        "median_ms": round(statistics.median(samples) * 1000, 3),
        "samples_ms": [round(x * 1000, 3) for x in samples],
    }, value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Checkout whose code to measure",
    )
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))
    from cli.hammerplusplus import api, timeline, workspace, vmf, delivery, reference
    from cli.hammerplusplus.project import Project, digest

    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        p = Project(root)
        for i in range(100):
            (root / f"f{i:03}.txt").write_bytes(b"before")
        cp = workspace.checkpoint(p, [f"f{i:03}.txt" for i in range(100)])
        for i in range(100):
            (root / f"f{i:03}.txt").write_bytes(b"after")
        expected = workspace.checkpoint_status(p, cp["token"])["current_revisions"]
        original = sqlite3.connect
        connections = []
        commits = []

        def connect(*args, **kwargs):
            db = original(*args, **kwargs)
            connections.append(1)
            db.set_trace_callback(
                lambda sql: commits.append(1) if sql.upper() == "COMMIT" else None
            )
            return db

        start = time.perf_counter()
        with patch.object(timeline.sqlite3, "connect", side_effect=connect):
            api.execute(
                p,
                {},
                "restore_checkpoint",
                {"token": cp["token"], "expected_revisions": expected},
            )
        out["restore_100_files"] = {
            "connections": len(connections),
            "commits": len(commits),
            "ms": round((time.perf_counter() - start) * 1000, 3),
        }
        # Deterministic entities with source preservation, a cycle for selection.
        text = vmf.new_map() + "".join(
            vmf.block(
                "entity",
                {
                    "id": i + 2,
                    "classname": "logic_relay",
                    "origin": f"{i} 0 0",
                    "targetname": f"n{i}",
                    "target": f"n{(i+1)%500}",
                },
            )
            for i in range(500)
        )
        ops = [
            {"op": "translate", "id": i + 2, "kind": "entity", "delta": [1, 2, 3]}
            for i in range(500)
        ]
        costs, edited = timed(lambda: vmf.mutate_many(text, ops))
        out["translate_500"] = {**costs, "sha256": digest(edited[0].encode())}
        (root / "map.vmf").write_text(text)

        def page_sequence():
            project = Project(root)
            offset = 0
            rows = []
            while offset is not None:
                page = project.inspect("map.vmf", offset, 20)
                rows += page["objects"]
                offset = page["next_offset"]
            return rows

        with patch.object(vmf, "parse", wraps=vmf.parse) as parse:
            cost, rows = timed(page_sequence)
        out["inspect_501_objects_26_pages"] = {
            **cost,
            "parse_calls_per_sequence": parse.call_count // 3,
            "count": len(rows),
        }
        (root / "destination.vmf").write_text(vmf.new_map())
        cost, result = timed(
            lambda: reference.copy_objects(
                p,
                "map.vmf",
                "destination.vmf",
                digest(text.encode()),
                digest(vmf.new_map().encode()),
                [{"id": 2, "kind": "entity"}],
                prefix="bench_",
                dry_run=True,
            )
        )
        out["copy_500_cyclic_links"] = {
            **cost,
            "count": len(result["copied"]),
            "revision": result["revision"],
        }
        # Response budget comparison.
        huge = vmf.set_properties(
            vmf.new_map(),
            vmf.parse(vmf.new_map()).blocks("world")[0],
            {"message": "x" * 200000},
        )
        (root / "huge.vmf").write_text(huge)
        result = api.execute(
            p, {}, "inspect_object", {"path": "huge.vmf", "id": 1, "kind": "world"}
        )
        out["object_response_bytes"] = len(
            json.dumps(result, separators=(",", ":"), ensure_ascii=True).encode()
        )
        # Package peak Python allocations, 48 MiB of inputs created before measurement.
        build = root / "build"
        build.mkdir()
        receipt = {"assets": {"complete": True}}
        for kind in ("bsp", "nav"):
            path = build / ("map." + kind)
            with path.open("wb") as stream:
                for _ in range(24):
                    stream.write(b"x" * 1048576)
            h = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1048576), b""):
                    h.update(block)
            receipt[kind] = {"path": str(path), "revision": h.hexdigest()}
        (build / "receipt.json").write_text(json.dumps(receipt))
        tracemalloc.start()
        start = time.perf_counter()
        result = delivery.package_map(p, "build", "output.zip")
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        out["package_48MiB"] = {
            "peak_python_bytes": peak,
            "ms": round((time.perf_counter() - start) * 1000, 3),
            "verified": result["verified"],
        }
        # Long-history selected-path reconstruction, retaining all baselines.
        ledger = timeline.Timeline(p)
        with ledger.connect() as db:
            previous = timeline.ROOT
            for i in range(1000):
                action = f"{i+1:032x}"
                db.execute(
                    "INSERT INTO actions(id,parent,tool,status,pid,session,started,arguments,finalized) VALUES (?,?,'fixture','completed',0,'','','{}',1)",
                    (action, previous),
                )
                db.executemany(
                    "INSERT OR IGNORE INTO paths(path,baseline,first_action) VALUES (?,NULL,?)",
                    [(f"p{j:03}.txt", action) for j in range(100)],
                )
                db.executemany(
                    "INSERT INTO files(action,path,after_hash,after_known) VALUES (?,?,?,1)",
                    [(action, f"p{j:03}.txt", f"{i:064x}") for j in range(100)],
                )
                previous = action
        cost, value = timed(lambda: ledger.state(previous, ["p050.txt"]))
        out["selected_path_100000_versions"] = {**cost, "result": value}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
