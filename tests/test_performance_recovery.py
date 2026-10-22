"""Portable correctness and scaling regressions; native integration needs Windows."""

import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from unittest.mock import patch
import zipfile

from cli.hammerplusplus import (
    api,
    catalog,
    delivery,
    native_session,
    reference,
    timeline,
    vmf,
)
from cli.hammerplusplus.cache import Cache
from cli.hammerplusplus.project import Project, digest
from cli.hammerplusplus.results import MAX_RESULT_BYTES, serialized
from cli.hammerplusplus.streams import BUFFER, copy_hash, file_digest, publish_stream
from scripts import setup_local

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".local/test-runs"
RUNS.mkdir(parents=True, exist_ok=True)


class PerformanceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=RUNS)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = Project(self.root)

    def call(self, tool, **args):
        return api.execute(self.project, {}, tool, args)

    def edit(self, path, value):
        return self.call(
            "map_set_properties",
            path=path,
            id=1,
            kind="world",
            expected_revision=self.project.inspect(path)["revision"],
            properties={"message": value},
        )

    def case_maps(self):
        self.call("create_map", path="A.vmf")
        (
            self.call("create_map", path="a.vmf")
            if not (self.root / "a.vmf").exists()
            else None
        )
        if (self.root / "A.vmf").samefile(self.root / "a.vmf"):
            self.skipTest("Filesystem aliases these spellings")

    def legacy(self, name, *, recorded=True):
        path = self.root / name
        journal = self.project.journal_path(path)
        state = json.loads(journal.read_text())
        if not recorded:
            state.pop("path", None)
        state.pop("journal_version", None)
        legacy = self.project.confined(
            ".hammer-agent/history/" + digest(name.casefold().encode()) + ".json"
        )
        legacy.write_text(json.dumps(state))
        journal.unlink()
        return legacy, state

    def test_case_distinct_histories_undo_redo_checkout_and_external_refusal(self):
        self.case_maps()
        first = self.edit("A.vmf", "upper")
        lower = self.edit("a.vmf", "lower")
        self.assertNotEqual(
            self.project.journal_path(self.root / "A.vmf"),
            self.project.journal_path(self.root / "a.vmf"),
        )
        self.call("undo_map", path="A.vmf", expected_revision=first["revision"])
        self.assertEqual(self.project.inspect("a.vmf")["revision"], lower["revision"])
        current = self.project.inspect("A.vmf")["revision"]
        self.call("redo_map", path="A.vmf", expected_revision=current)
        self.assertEqual(self.project.inspect("A.vmf")["revision"], first["revision"])
        self.call(
            "checkout_action",
            target=first["timeline"]["action_id"],
            expected_head=timeline.Timeline(self.project).head(),
        )
        self.assertEqual(self.project.history("A.vmf")["position"], 1)
        self.assertEqual(self.project.history("a.vmf")["position"], 0)
        self.edit("a.vmf", "new lower")
        path = self.root / "A.vmf"
        path.write_bytes(path.read_bytes() + b"\n// external\n")
        with self.assertRaisesRegex(vmf.MapError, "External map changes"):
            self.call("undo_map", path="A.vmf", expected_revision=file_digest(path))
        self.assertTrue(path.read_bytes().endswith(b"// external\n"))

    def test_explicit_legacy_owner_migrates_and_preserves_evidence(self):
        self.case_maps()
        first = self.edit("A.vmf", "old")
        legacy, old = self.legacy("A.vmf")
        self.assertEqual(self.project.history("a.vmf")["position"], 0)
        self.assertEqual(self.project.history("A.vmf")["entries"], old["entries"])
        second = self.edit("A.vmf", "new")
        self.assertEqual(json.loads(legacy.read_text())["entries"], old["entries"])
        self.assertIn("migrated_to", json.loads(legacy.read_text()))
        self.call("undo_map", path="A.vmf", expected_revision=second["revision"])
        self.assertEqual(self.project.inspect("A.vmf")["revision"], first["revision"])
        self.call("undo_map", path="A.vmf", expected_revision=first["revision"])
        self.assertEqual(self.project.history("A.vmf")["path"], "A.vmf")
        # A removed migrated journal stays removed instead of resurrecting legacy history.
        self.project.journal_path(self.root / "A.vmf").unlink()
        self.assertEqual(self.project.history("A.vmf")["position"], 0)

    def test_fieldless_legacy_migration_and_ambiguity(self):
        self.call("create_map", path="only.vmf")
        self.edit("only.vmf", "old")
        legacy, old = self.legacy("only.vmf", recorded=False)
        self.edit("only.vmf", "new")
        self.assertEqual(self.project.history("only.vmf")["total"], 2)
        self.assertEqual(json.loads(legacy.read_text())["entries"], old["entries"])
        self.case_maps()
        self.edit("A.vmf", "ambiguous")
        legacy, old = self.legacy("A.vmf", recorded=False)
        before = legacy.read_bytes()
        for name in ("A.vmf", "a.vmf"):
            with self.assertRaisesRegex(vmf.MapError, "Ambiguous legacy history"):
                self.project.history(name)
        self.assertEqual(legacy.read_bytes(), before)

    def test_fieldless_legacy_external_edit_is_not_claimed(self):
        self.call("create_map", path="map.vmf")
        self.edit("map.vmf", "old")
        legacy, _ = self.legacy("map.vmf", recorded=False)
        path = self.root / "map.vmf"
        path.write_bytes(path.read_bytes() + b"// external\n")
        with self.assertRaisesRegex(vmf.MapError, "external map changes"):
            self.project.history("map.vmf")
        self.assertNotIn("migrated_to", json.loads(legacy.read_text()))

    def test_legacy_migration_resumes_on_either_side_of_publication(self):
        from cli.hammerplusplus import project as module

        for phase in ("before", "after"):
            name = phase + ".vmf"
            self.project.create(name)
            self.edit(name, "old")
            legacy, old = self.legacy(name)
            destination = self.project.journal_path(self.root / name)
            original = module.atomic_write

            def interrupt(path, data, **options):
                if path == destination and phase == "before":
                    raise OSError("migration interrupted")
                if path == legacy and phase == "after" and b"migrated_to" in data:
                    raise OSError("migration interrupted")
                return original(path, data, **options)

            with patch.object(module, "atomic_write", side_effect=interrupt):
                with self.assertRaisesRegex(vmf.MapError, "migration interrupted"):
                    self.edit(name, "new")
            self.assertIn("migration_pending", json.loads(legacy.read_text()))
            self.edit(name, "resumed")
            self.assertEqual(self.project.history(name)["total"], 2)
            self.assertEqual(json.loads(legacy.read_text())["entries"], old["entries"])
            self.assertIn("migrated_to", json.loads(legacy.read_text()))

    def test_filesystem_aliases_share_identity(self):
        self.project.create("Alias.vmf")
        actual = self.root / "Alias.vmf"
        alias = self.root / "alias.vmf"
        if alias.exists() and alias.samefile(actual):
            self.assertEqual(
                self.project.journal_path(actual), self.project.journal_path(alias)
            )
        else:
            # Resolved aliases also exercise confinement on portable hosts.
            try:
                alias.symlink_to(actual)
            except OSError:
                self.skipTest("Symlinks unavailable")
            self.assertEqual(
                self.project.journal_path(actual), self.project.journal_path(alias)
            )

    def large_map(self):
        self.project.create("map.vmf")
        self.project.apply(
            "map.vmf",
            self.project.inspect("map.vmf")["revision"],
            [
                {
                    "op": "set_properties",
                    "id": 1,
                    "kind": "world",
                    "properties": {"message": "\u6c34\\" * 30000 + "end"},
                }
            ],
        )

    def evidence(self, result):
        info = result["response"]["artifact"]
        chunks, offset = [], 0
        while offset is not None:
            page = self.call("read_artifact", path=info["path"], offset=offset)
            self.assertLessEqual(len(serialized(page)), MAX_RESULT_BYTES)
            chunks.append(page["content"].encode(page["encoding"]))
            offset = page["next_offset"]
        raw = b"".join(chunks)
        self.assertEqual(len(raw), info["bytes"])
        self.assertEqual(digest(raw), info["revision"])
        return json.loads(raw)

    def test_large_results_are_bounded_and_all_evidence_is_pageable(self):
        self.large_map()
        result = self.call("inspect_object", path="map.vmf", id=1, kind="world")
        self.assertLessEqual(len(serialized(result)), MAX_RESULT_BYTES)
        self.assertFalse(result["source_complete"])
        full = self.evidence(result)
        explicit = self.call(
            "inspect_object", path="map.vmf", id=1, kind="world", response_mode="full"
        )
        self.assertEqual(full["source"], explicit["source"])
        self.assertEqual(full["properties"], explicit["properties"])
        self.assertEqual(full["revision"], result["revision"])
        with patch(
            "cli.hammerplusplus.backend.compile_map",
            return_value={
                "valid": False,
                "complete": False,
                "unsupported_geometry": [
                    {"id": i, "reason": "x" * 100} for i in range(1000)
                ],
                "warnings": ["warning" * 100] * 1000,
                "recovery_token": "c" * 32,
            },
        ):
            result = self.call(
                "compile_map", path="map.vmf", expected_revision=full["revision"]
            )
        self.assertFalse(result["valid"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["recovery_token"], "c" * 32)
        self.assertEqual(result["response"]["totals"]["unsupported_geometry"], 1000)
        self.assertEqual(len(self.evidence(result)["warnings"]), 1000)

    def test_source_and_history_pages_detect_changed_revisions(self):
        self.project.create("map.vmf", "kz-room")
        first = self.call("read_map_source", path="map.vmf")
        self.assertEqual(len(first["source"]), 8000)
        self.assertFalse(first["source_complete"])
        self.assertIsNotNone(first["next_offset"])
        chunks = [first["source"]]
        offset = first["next_offset"]
        while offset is not None:
            page = self.call(
                "read_map_source",
                path="map.vmf",
                offset=offset,
                expected_revision=first["revision"],
            )
            chunks.append(page["source"])
            offset = page["next_offset"]
        self.assertEqual("".join(chunks), self.project.read("map.vmf")[2])
        for i in range(4):
            self.edit("map.vmf", str(i))
        history = self.call("map_history", path="map.vmf", limit=2)
        next_page = self.call(
            "map_history",
            path="map.vmf",
            offset=2,
            limit=2,
            expected_history_revision=history["history_revision"],
        )
        self.assertEqual(
            history["entries"] + next_page["entries"],
            self.project.history("map.vmf")["entries"],
        )
        self.edit("map.vmf", "changed")
        with self.assertRaisesRegex(vmf.MapError, "History revision conflict"):
            self.call(
                "map_history",
                path="map.vmf",
                expected_history_revision=history["history_revision"],
            )
        with self.assertRaisesRegex(vmf.MapError, "Revision conflict"):
            self.call(
                "read_map_source", path="map.vmf", expected_revision=first["revision"]
            )

    def test_large_error_preserves_full_message_and_recovery_ids(self):
        from cli.hammerplusplus.backend import BackendError

        self.project.create("map.vmf")
        message = "\u6c34" * 30000
        details = {"warnings": ["warning" * 1000] * 100, "recovery_token": "d" * 32}
        with patch(
            "cli.hammerplusplus.backend.compile_map",
            side_effect=BackendError(message, details),
        ):
            with self.assertRaises(BackendError) as caught:
                self.call(
                    "compile_map",
                    path="map.vmf",
                    expected_revision=self.project.inspect("map.vmf")["revision"],
                )
        result = {
            "ok": False,
            "error": str(caught.exception),
            "details": caught.exception.details,
        }
        self.assertLessEqual(len(serialized(result)), MAX_RESULT_BYTES)
        self.assertEqual(result["details"]["recovery_token"], "d" * 32)
        evidence = self.evidence(result["details"])
        self.assertEqual(evidence["full_error"], message)
        self.assertEqual(evidence["warnings"], details["warnings"])

    def test_validation_precedes_tracking_and_retains_failed_receipt(self):
        self.project.create("map.vmf")
        with patch.object(
            timeline.Action,
            "track",
            side_effect=AssertionError("tracking invalid input"),
        ):
            with self.assertRaisesRegex(
                vmf.MapError, "Invalid map_set_properties"
            ) as error:
                self.call(
                    "map_set_properties",
                    path="map.vmf",
                    expected_revision="x",
                    id=1,
                    properties={},
                )
        ledger = timeline.Timeline(self.project)
        receipt = ledger.inspect(error.exception.details["action_id"])
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["files"], [])
        self.assertTrue(receipt["finalized"])

    def test_request_reuses_connection_with_full_synchronization(self):
        self.project.create("map.vmf")
        original = sqlite3.connect
        with patch.object(timeline.sqlite3, "connect", wraps=original) as connect:
            self.edit("map.vmf", "receipt")
        self.assertEqual(connect.call_count, 1)
        ledger = timeline.Timeline(self.project)
        with ledger.connect() as db:
            self.assertEqual(db.execute("PRAGMA synchronous").fetchone()[0], 2)
        self.assertEqual(
            ledger.state(ledger.head(), ["map.vmf"]),
            {"map.vmf": self.project.inspect("map.vmf")["revision"]},
        )
        self.assertEqual(ledger.state(ledger.head(), []), {})

    def test_parsed_pages_reuse_work_and_detect_same_stat_external_edits(self):
        self.project.create("map.vmf", "kz-room")
        # Fresh Project avoids the view created by create().
        self.project = Project(self.root)
        with patch.object(vmf, "parse", wraps=vmf.parse) as parse:
            first = self.project.inspect("map.vmf", limit=2)
            pages, offset = list(first["objects"]), first["next_offset"]
            while offset is not None:
                page = self.project.inspect("map.vmf", offset, 2)
                pages.extend(page["objects"])
                offset = page["next_offset"]
            self.assertEqual(parse.call_count, 1)
        self.assertEqual(
            pages, vmf.inspect(self.project.read("map.vmf")[2], limit=1000)["objects"]
        )
        with patch.object(
            reference, "search_objects", wraps=reference.search_objects
        ) as search:
            first = reference.search(self.project, "map.vmf", limit=1)
            reference.search(self.project, "map.vmf", offset=1, limit=1)
            self.assertEqual(search.call_count, 1)
        path = self.root / "map.vmf"
        stat = path.stat()
        path.write_bytes(path.read_bytes().replace(b"sky_dust", b"sky_test"))
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        changed = self.project.inspect("map.vmf")
        self.assertNotEqual(changed["revision"], first["revision"])
        self.assertEqual(changed["objects"][0]["properties"]["skyname"], "sky_test")
        self.assertLessEqual(self.project._views.bytes, self.project._views.budget)
        cache = Cache(1024)
        cache.put("small", "ok")
        cache.put("large", "x" * 10000)
        self.assertIsNone(cache.get("large"))
        self.assertEqual(cache.get("small"), "ok")

    def test_independent_translations_reconstruct_once_with_sequential_oracle(self):
        text = (
            vmf.new_map()
            + '\r\n// caf\u00e9 untouched\r\nunknown { "duplicate" "a" "duplicate" "b" }\r\n'
        )
        for i in range(30):
            text, _ = vmf.mutate(
                text,
                {"op": "add_entity", "classname": "logic_relay", "origin": [i, 0, 0]},
            )
        operations = [
            {"op": "translate", "id": i, "kind": "entity", "delta": [1, 2, 3]}
            for i in range(2, 32)
        ]
        expected, expected_results = text, []
        for op in operations:
            expected, result = vmf.mutate(expected, op)
            expected_results.append(result)
        with patch.object(vmf, "replace", wraps=vmf.replace) as reconstruct:
            observed, results = vmf.mutate_many(text, operations)
            self.assertEqual(reconstruct.call_count, 1)
        self.assertEqual(observed, expected)
        self.assertEqual(results, expected_results)
        self.assertIn('unknown { "duplicate" "a" "duplicate" "b" }', observed)
        repeated = [operations[0], operations[0]]
        expected, _ = vmf.mutate(vmf.mutate(text, repeated[0])[0], repeated[1])
        self.assertEqual(vmf.mutate_many(text, repeated)[0], expected)

    def test_fgd_cache_tracks_includes_content_and_addon_order(self):
        include = self.root / "base.fgd"
        include.write_text(
            '@BaseClass = Base\n[\n targetname(string) : "Name" : "old"\n]\n'
        )
        primary = self.root / "main.fgd"
        primary.write_text(
            '@include "base.fgd"\n@PointClass base(Base) = logic_relay : "Relay"\n[\n]\n'
        )
        config = {"fgd": str(primary)}
        one = catalog.entity_definitions(self.project, config)
        self.assertIs(catalog.entity_definitions(self.project, config), one)
        stat = include.stat()
        include.write_text(include.read_text().replace('"old"', '"new"'))
        os.utime(include, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        two = catalog.entity_definitions(self.project, config)
        self.assertIsNot(two, one)
        self.assertEqual(two["logic_relay"].kv["targetname"].default, "new")
        addon = self.root / "addon.fgd"
        addon.write_text(
            '@PointClass = logic_relay : "Addon"\n[\n targetname(string) : "Override" : "addon"\n]\n'
        )
        result = catalog.entity_definitions(
            self.project, {"fgd": [str(primary), str(addon)]}
        )
        self.assertEqual(result["logic_relay"].kv["targetname"].default, "addon")
        include.unlink()
        with self.assertRaises((FileNotFoundError, KeyError)):
            catalog.entity_definitions(self.project, config)

    def test_pending_discovery_ignores_archived_receipts_and_recovers_publication_gap(
        self,
    ):
        directory = self.root / "session"
        pending = directory / "pending"
        pending.mkdir(parents=True)
        for i in range(100):
            (directory / f"request-old{i}.json").write_text("{}")
            (directory / f"response-old{i}.json").write_text("{}")
        for value in ("live", "expired", "completed"):
            (pending / f"request-{value}.json").write_text("{}")
        (directory / "response-completed.json").write_text("{}")
        paths = list(native_session.pending_requests(directory))
        self.assertEqual([p.stem for p in paths], ["request-expired", "request-live"])
        self.assertTrue((directory / "request-completed.json").exists())
        self.assertEqual(list(native_session.pending_requests(directory)), paths)
        for call in (
            {"secret": "wrong", "deadline": time.time() + 30},
            {"secret": "owned", "deadline": time.time() - 1},
        ):
            with self.assertRaisesRegex(vmf.MapError, "expired or belongs"):
                native_session.validate_request(call, {"secret": "owned"})

    def test_stream_downloads_validate_before_publication_and_clean_interruptions(self):
        class BoundedRead(io.BytesIO):
            def read(self, size=-1):
                self_test.assertGreater(size, 0)
                self_test.assertLessEqual(size, BUFFER)
                return super().read(size)

        self_test = self
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("tool/file.txt", b"x" * (2 * BUFFER))
        data = buffer.getvalue()
        with (
            patch.dict(
                setup_local.ARCHIVES,
                {"fixture.zip": ("https://example.invalid/archive", digest(data))},
            ),
            patch.object(
                setup_local.urllib.request, "urlopen", return_value=BoundedRead(data)
            ),
        ):
            target = setup_local.archive(self.project, "fixture.zip", "install")
        self.assertEqual((target / "tool/file.txt").stat().st_size, 2 * BUFFER)
        destination = self.root / "bad"
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            publish_stream(
                destination, BoundedRead(b"bad"), expected="0" * 64, exclusive=True
            )
        self.assertFalse(destination.exists())

        class Interrupted:
            def read(self, size):
                raise OSError("interrupted")

        with self.assertRaisesRegex(OSError, "interrupted"):
            publish_stream(destination, Interrupted(), exclusive=True)
        self.assertFalse(list(self.root.glob(".hammer-agent-*")))

    def test_large_package_has_bounded_peak_memory_and_preserves_outputs(self):
        build = self.root / "build"
        build.mkdir()
        receipt = {"assets": {"complete": True}}
        for kind in ("bsp", "nav"):
            path = build / ("map." + kind)
            with path.open("wb") as output:
                for _ in range(24):
                    output.write(b"x" * BUFFER)
            receipt[kind] = {"path": str(path), "revision": file_digest(path)}
        (build / "receipt.json").write_text(json.dumps(receipt))
        tracemalloc.start()
        try:
            result = delivery.package_map(self.project, "build", "package.zip")
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 8 * BUFFER)
        self.assertTrue(result["verified"])
        with zipfile.ZipFile(self.root / "package.zip") as archive:
            for kind in ("bsp", "nav"):
                with archive.open("maps/map." + kind) as stream:
                    self.assertEqual(copy_hash(stream), receipt[kind]["revision"])
        original = file_digest(self.root / "package.zip")
        with self.assertRaisesRegex(vmf.MapError, "new ZIP"):
            delivery.package_map(self.project, "build", "package.zip")
        self.assertEqual(file_digest(self.root / "package.zip"), original)
        (build / "map.bsp").write_bytes(b"corrupt")
        with self.assertRaisesRegex(vmf.MapError, "revision changed"):
            delivery.package_map(self.project, "build", "corrupt.zip")
        self.assertFalse((self.root / "corrupt.zip").exists())
        self.assertFalse(list(self.root.glob(".hammer-agent-*")))

    def test_cli_and_actual_mcp_preserve_text_structured_evidence_contract(self):
        self.large_map()
        command = [
            sys.executable,
            "-m",
            "cli.hammerplusplus",
            "--workspace",
            str(self.root),
        ]
        cli = subprocess.run(
            [*command, "--json", "object", "map.vmf", "1", "--kind", "world"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(cli.returncode, 0, cli.stderr)
        result = json.loads(cli.stdout)
        self.assertLess(len(cli.stdout.encode()), MAX_RESULT_BYTES + 1000)
        self.assertIn("response", result["data"])
        full = subprocess.run(
            [
                *command,
                "object",
                "map.vmf",
                "1",
                "--kind",
                "world",
                "--response-mode",
                "full",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(full.returncode, 0, full.stderr)
        self.assertNotIn("response", json.loads(full.stdout)["data"])
        import anyio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def scenario():
            async with stdio_client(
                StdioServerParameters(
                    command=sys.executable, args=command[1:] + ["mcp"]
                )
            ) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    response = await client.call_tool(
                        "inspect_object", {"path": "map.vmf", "id": 1, "kind": "world"}
                    )
                    self.assertFalse(response.isError)
                    self.assertEqual(
                        json.loads(response.content[0].text), response.structuredContent
                    )
                    self.assertLess(
                        len(response.content[0].text.encode()), MAX_RESULT_BYTES + 1000
                    )
                    info = response.structuredContent["data"]["response"]["artifact"]
                    chunks, offset = [], 0
                    while offset is not None:
                        page = await client.call_tool(
                            "read_artifact", {"path": info["path"], "offset": offset}
                        )
                        text = json.loads(page.content[0].text)
                        self.assertEqual(text, page.structuredContent)
                        data = text["data"]
                        chunks.append(data["content"].encode("ascii"))
                        offset = data["next_offset"]
                    self.assertEqual(digest(b"".join(chunks)), info["revision"])

        anyio.run(scenario)
