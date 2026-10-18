"""Workspace boundary, optimistic revisions, durable history and atomic writes."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from . import vmf


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode(data: bytes) -> tuple[str, str]:
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252"), "cp1252"


def atomic_write(path: Path, data: bytes, *, exclusive: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".hammer-agent-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Project:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise vmf.MapError("Workspace must be an existing directory")

    def confined(self, name: str | Path) -> Path:
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise vmf.MapError("Path must be inside the configured workspace")
        return path

    def map_path(self, name: str) -> Path:
        path = self.confined(name)
        if (
            path.suffix.lower() != ".vmf"
            or ".hammer-agent" in path.relative_to(self.root).parts
        ):
            raise vmf.MapError(
                "Map path must end in .vmf and stay outside .hammer-agent"
            )
        return path

    @contextmanager
    def locked(self):
        state = self.confined(".hammer-agent")
        state.mkdir(exist_ok=True)
        lock = self.confined(".hammer-agent/write.lock")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise vmf.MapError(
                "Workspace is locked by another write; after a crash verify its owner before removing .hammer-agent/write.lock"
            ) from exc
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(str(os.getpid()))
            yield
        finally:
            lock.unlink()

    def read(self, name: str) -> tuple[Path, bytes, str, str]:
        path = self.map_path(name)
        if path.stat().st_size > 64 * 1024 * 1024:
            raise vmf.MapError("VMF exceeds the 64 MiB editing limit")
        data = path.read_bytes()
        text, encoding = decode(data)
        return path, data, text, encoding

    def inspect(self, name: str, offset: int = 0, limit: int = 100) -> dict:
        path, data, text, _ = self.read(name)
        return {
            "path": str(path),
            "revision": digest(data),
            **vmf.inspect(text, offset, limit),
        }

    def object(self, name: str, object_id: int) -> dict:
        _, data, text, _ = self.read(name)
        node = vmf.find_id(vmf.parse(text), object_id)
        return {
            "revision": digest(data),
            **vmf.describe(node),
            "source": text[node.start : node.end],
        }

    def validate(self, name: str) -> dict:
        _, data, text, _ = self.read(name)
        return {"revision": digest(data), **vmf.validate(text)}

    def create(self, name: str, template: str = "empty") -> dict:
        if template not in ("empty", "csgo-room"):
            raise vmf.MapError("template must be empty or csgo-room")
        with self.locked():
            path = self.map_path(name)
            if path.exists():
                raise vmf.MapError("Map already exists; create never overwrites")
            text = vmf.new_map()
            if template == "csgo-room":
                operations = [
                    dict(op="add_room", min=[-512, -512, 0], max=[512, 512, 256]),
                    dict(
                        op="add_entity",
                        classname="info_player_terrorist",
                        origin=[-128, 0, 16],
                        properties={"angles": "0 0 0", "enabled": "1"},
                    ),
                    dict(
                        op="add_entity",
                        classname="info_player_counterterrorist",
                        origin=[128, 0, 16],
                        properties={"angles": "0 180 0", "enabled": "1"},
                    ),
                    dict(
                        op="add_entity",
                        classname="light",
                        origin=[0, 0, 192],
                        properties={
                            "_light": "255 244 220 600",
                            "_constant_attn": "0",
                            "_linear_attn": "0",
                            "_quadratic_attn": "1",
                        },
                    ),
                ]
                for op in operations:
                    text, _ = vmf.mutate(text, op)
            data = text.replace("\n", "\r\n").encode("utf-8")
            # Publish the completed file exclusively, never an incomplete new map.
            atomic_write(path, data, exclusive=True)
        return self.inspect(name)

    def journal_path(self, path: Path) -> Path:
        key = digest(str(path.relative_to(self.root)).casefold().encode())
        return self.confined(f".hammer-agent/history/{key}.json")

    def snapshot(self, revision: str, data: bytes | None = None) -> bytes:
        if len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
            raise vmf.MapError("Invalid snapshot revision")
        path = self.confined(f".hammer-agent/snapshots/{revision}.vmf")
        if data is not None:
            if digest(data) != revision:
                raise vmf.MapError("Snapshot checksum mismatch")
            if not path.exists():
                atomic_write(path, data)
        result = path.read_bytes()
        if digest(result) != revision:
            raise vmf.MapError("Snapshot checksum mismatch")
        return result

    def load_history(self, path: Path) -> dict:
        journal = self.journal_path(path)
        if not journal.exists():
            return {"entries": [], "position": 0}
        state = json.loads(journal.read_text("utf-8"))
        if "pending" in state:
            pending = state["pending"]
            current = digest(path.read_bytes())
            if current == pending["after"]:
                state = pending["state"]
            elif current == pending["before"]:
                state.pop("pending")
            else:
                raise vmf.MapError(
                    "Interrupted transaction and external edit detected; snapshots retained for manual recovery"
                )
            atomic_write(journal, json.dumps(state).encode())
        return state

    def publish(self, path: Path, before: bytes, after: bytes, old: dict, state: dict):
        before_hash, after_hash = digest(before), digest(after)
        self.snapshot(before_hash, before)
        self.snapshot(after_hash, after)
        if path.read_bytes() != before:
            raise vmf.MapError("Map changed during transaction; inspect and retry")
        journal = self.journal_path(path)
        pending = {
            **old,
            "pending": {"before": before_hash, "after": after_hash, "state": state},
        }
        atomic_write(journal, json.dumps(pending).encode())
        if path.read_bytes() != before:
            atomic_write(journal, json.dumps(old).encode())
            raise vmf.MapError("Map changed during transaction; inspect and retry")
        atomic_write(path, after)
        atomic_write(journal, json.dumps(state).encode())

    def apply(
        self,
        name: str,
        expected_revision: str,
        operations: list[dict],
        dry_run: bool = False,
    ) -> dict:
        if not isinstance(operations, list) or not 1 <= len(operations) <= 1000:
            raise vmf.MapError("operations must be an array of 1 to 1000 edit objects")
        with self.locked():
            path, before, text, encoding = self.read(name)
            if digest(before) != expected_revision:
                raise vmf.MapError(
                    "Revision conflict; inspect the map again before editing"
                )
            results = []
            for operation in operations:
                text, result = vmf.mutate(text, operation)
                results.append(result)
            validation = vmf.validate(text)
            if not validation["valid"]:
                raise vmf.MapError(
                    "Transaction would produce invalid VMF: "
                    + "; ".join(validation["errors"])
                )
            try:
                after = text.encode(encoding)
            except UnicodeEncodeError as exc:
                raise vmf.MapError(
                    f"Edited values cannot be encoded as {encoding}"
                ) from exc
            revision = digest(after)
            if not dry_run and after != before:
                old = self.load_history(path)
                entries = old["entries"][: old["position"]]
                entries.append(
                    {
                        "before": expected_revision,
                        "after": revision,
                        "operations": operations,
                    }
                )
                self.publish(
                    path,
                    before,
                    after,
                    old,
                    {"entries": entries, "position": len(entries)},
                )
        return {
            "path": str(path),
            "previous_revision": expected_revision,
            "revision": revision,
            "dry_run": dry_run,
            "results": results,
            "validation": validation,
        }

    def history(self, name: str) -> dict:
        with self.locked():
            path, data, _, _ = self.read(name)
            state = self.load_history(path)
            return {"revision": digest(data), **state}

    def restore(self, name: str, expected_revision: str, direction: str) -> dict:
        if direction not in ("undo", "redo"):
            raise vmf.MapError("direction must be undo or redo")
        with self.locked():
            path, before, _, _ = self.read(name)
            if digest(before) != expected_revision:
                raise vmf.MapError("Revision conflict; inspect the map again")
            old = self.load_history(path)
            entries, pos = old["entries"], old["position"]
            if direction == "undo":
                if pos == 0:
                    raise vmf.MapError("Nothing to undo")
                entry, dest, source = entries[pos - 1], "before", "after"
                new_pos = pos - 1
            else:
                if pos == len(entries):
                    raise vmf.MapError("Nothing to redo")
                entry, dest, source = entries[pos], "after", "before"
                new_pos = pos + 1
            if entry[source] != expected_revision:
                raise vmf.MapError(
                    "External map changes detected; history cannot overwrite them"
                )
            after = self.snapshot(entry[dest])
            self.publish(
                path, before, after, old, {"entries": entries, "position": new_pos}
            )
        return {
            "path": str(path),
            "revision": digest(after),
            "direction": direction,
            "position": new_pos,
        }
