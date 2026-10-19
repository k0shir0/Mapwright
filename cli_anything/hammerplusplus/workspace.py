"""Workspace audit, inspectable artifacts and recoverable multi-file checkpoints."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid

from .project import atomic_write, digest
from .vmf import MapError


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value):
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise MapError("Invalid checkpoint/recovery token")
    return value


@contextmanager
def audit_lock(project):
    lock = project.confined(".hammer-agent/audit.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def log(project, event):
    """Bounded JSONL, cross-process serialized; never silently truncate a source into logs."""
    with audit_lock(project):
        path = project.confined(".hammer-agent/operations.jsonl")
        if path.exists() and path.stat().st_size >= 4 * 1024 * 1024:
            oldest = path.with_name(path.name + ".3")
            oldest.unlink(missing_ok=True)
            for n in (2, 1):
                old = path.with_name(path.name + f".{n}")
                if old.exists():
                    os.replace(old, path.with_name(path.name + f".{n+1}"))
            os.replace(path, path.with_name(path.name + ".1"))
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                json.dumps(
                    {
                        "timestamp": now(),
                        "session_id": project.session_id,
                        "pid": os.getpid(),
                        **event,
                    },
                    ensure_ascii=True,
                    allow_nan=False,
                )
                + "\n"
            )
            stream.flush()


def summary(args):
    raw = json.dumps(args, sort_keys=True, ensure_ascii=True, default=str).encode()
    result = {"arguments_revision": digest(raw)}
    if not isinstance(args, dict):
        return result
    for key in (
        "path",
        "source",
        "destination",
        "output",
        "expected_revision",
        "source_revision",
        "token",
        "pid",
        "action",
        "dry_run",
    ):
        if key in args and isinstance(args[key], (str, int, bool)):
            if isinstance(args[key], str) and (
                len(args[key]) > 2048 or "\n" in args[key] or "\r" in args[key]
            ):
                result[key + "_revision"] = digest(args[key].encode())
            else:
                result[key] = args[key]
    if isinstance(args.get("operations"), list):
        result["operations"] = [
            str(op.get("op"))[:100]
            for op in args["operations"][:1000]
            if isinstance(op, dict)
        ]
    return result


def operations(project, offset=0, limit=100):
    if project.confined(".hammer-agent/timeline/actions.sqlite3").exists():
        from .timeline import Timeline

        return Timeline(project).operations(offset, limit)
    rows = []
    with audit_lock(project):
        for suffix in (".3", ".2", ".1", ""):
            path = project.confined(".hammer-agent/operations.jsonl" + suffix)
            if path.exists():
                for line in path.read_text("utf-8").splitlines():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        rows.append(
                            {
                                "status": "incomplete_record",
                                "message": "Interrupted log append; retained for inspection",
                            }
                        )
    return {
        "events": rows[offset : offset + limit],
        "total": len(rows),
        "next_offset": offset + limit if offset + limit < len(rows) else None,
        "retention": "Current log plus three rotated files, 4 MiB per file; snapshots and checkpoints are retained until explicitly removed.",
    }


ARTIFACTS = {
    "history",
    "snapshots",
    "trash",
    "references",
    "builds",
    "imports",
    "checkpoints",
    "recovery",
    "timeline",
    "native-sessions",
}


def artifact_path(project, name):
    path = project.confined(name)
    parts = path.relative_to(project.root).parts
    if (
        not parts
        or parts[0] != ".hammer-agent"
        or len(parts) < 2
        or (
            parts[1] not in ARTIFACTS
            and not re.fullmatch(r"operations\.jsonl(?:\.[1-3])?", parts[1])
        )
    ):
        raise MapError(
            "Only workspace history, snapshots, logs, trash, receipts, imports and checkpoint artifacts are readable"
        )
    return path


def artifacts(project, category="", offset=0, limit=100):
    if category and category not in ARTIFACTS | {"logs"}:
        raise MapError("Unknown artifact category")
    base = project.confined(".hammer-agent")
    rows = []
    if base.exists():
        roots = [base / category] if category and category != "logs" else [base]
        for root in roots:
            for folder, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = [
                    d
                    for d in sorted(dirs)
                    if (Path(folder) / d).resolve().is_relative_to(base)
                    and (Path(folder) != base or d in ARTIFACTS)
                    and category != "logs"
                ]
                for name in sorted(files):
                    p = Path(folder) / name
                    try:
                        artifact_path(project, p)
                    except MapError:
                        continue
                    rows.append(
                        {
                            "path": p.relative_to(project.root).as_posix(),
                            "bytes": p.stat().st_size,
                        }
                    )
    return {
        "artifacts": rows[offset : offset + limit],
        "total": len(rows),
        "next_offset": offset + limit if offset + limit < len(rows) else None,
    }


def read_artifact(project, path, offset=0, limit=100000):
    source = artifact_path(project, path)
    # Read bounded bytes, including binary BSPs/PNGs as base64 instead of decoding blindly.
    with source.open("rb") as stream:
        stream.seek(offset)
        raw = stream.read(limit)
    import base64

    try:
        content = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        content = base64.b64encode(raw).decode("ascii")
        encoding = "base64"
    size = source.stat().st_size
    return {
        "path": source.relative_to(project.root).as_posix(),
        "content": content,
        "encoding": encoding,
        "offset": offset,
        "total_bytes": size,
        "next_offset": offset + len(raw) if offset + len(raw) < size else None,
    }


EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", ".agents", ".codex", ".aws"}


def recovery_path(project, name):
    lexical = project.root / name
    for item in (lexical, *lexical.parents):
        if item == project.root:
            break
        if item.is_symlink():
            raise MapError("Checkpoint scopes cannot contain symlinks")
    p = project.confined(name)
    parts = p.relative_to(project.root).parts
    if any(x.casefold() in EXCLUDED for x in parts) or (
        parts[0].casefold() == ".hammer-agent"
        and (len(parts) < 2 or parts[1] not in {"builds", "imports"})
    ):
        raise MapError(
            "Checkpoint scope must exclude Git, environments, credentials and recovery metadata"
        )
    if p.is_symlink() or any(
        (project.root / Path(*parts[:i])).is_symlink() for i in range(1, len(parts) + 1)
    ):
        raise MapError("Checkpoint scopes cannot contain symlinks")
    return p


def collect(project, paths):
    names = set()
    for name in paths:
        p = recovery_path(project, name)
        if p.is_dir():
            for folder, dirs, files in os.walk(p, followlinks=False):
                dirs[:] = [
                    d
                    for d in sorted(dirs)
                    if d.casefold() not in EXCLUDED
                    and not (Path(folder) / d).is_symlink()
                ]
                for file in files:
                    child = recovery_path(project, Path(folder) / file)
                    names.add(child.relative_to(project.root).as_posix())
                    if len(names) > 10000:
                        raise MapError("Checkpoint exceeds 10000 files")
        elif p.exists():
            names.add(p.relative_to(project.root).as_posix())
    if len(names) > 10000:
        raise MapError("Checkpoint exceeds 10000 files")
    total = 0
    rows = {}
    for name in sorted(names):
        p = recovery_path(project, name)
        size = p.stat().st_size
        total += size
        if size > 128 * 1024 * 1024 or total > 512 * 1024 * 1024:
            raise MapError("Checkpoint limit: 128 MiB per file, 512 MiB total")
        from .timeline import store_file

        revision = store_file(project, p)
        rows[name] = revision
    return rows


def checkpoint(project, paths, label=""):
    with project.locked():
        rows = collect(project, paths)
        token = uuid.uuid4().hex
        receipt = {
            "token": token,
            "label": label,
            "timestamp": now(),
            "paths": [
                recovery_path(project, p).relative_to(project.root).as_posix()
                for p in paths
            ],
            "files": rows,
        }
        atomic_write(
            project.confined(f".hammer-agent/checkpoints/{token}.json"),
            json.dumps(receipt, indent=2).encode(),
            exclusive=True,
        )
    return receipt


def load_checkpoint(project, token):
    return json.loads(
        project.confined(
            f".hammer-agent/checkpoints/{identifier(token)}.json"
        ).read_text("utf-8")
    )


def checkpoint_status(project, token):
    receipt = load_checkpoint(project, token)
    names = set(receipt["files"])
    for name in receipt["paths"]:
        p = recovery_path(project, name)
        if p.is_dir():
            for folder, dirs, files in os.walk(p, followlinks=False):
                dirs[:] = [
                    d
                    for d in dirs
                    if d.casefold() not in EXCLUDED
                    and not (Path(folder) / d).is_symlink()
                ]
                names.update(
                    recovery_path(project, Path(folder) / n)
                    .relative_to(project.root)
                    .as_posix()
                    for n in files
                )
        elif p.exists():
            names.add(p.relative_to(project.root).as_posix())
        if len(names) > 10000:
            raise MapError("Checkpoint scope exceeds 10000 files")
    current = {}
    total = 0
    for n in sorted(names):
        p = recovery_path(project, n)
        if p.is_file():
            size = p.stat().st_size
            total += size
            if size > 128 * 1024 * 1024 or total > 512 * 1024 * 1024:
                raise MapError("Checkpoint scope exceeds read limits")
            current[n] = digest(p.read_bytes())
        else:
            current[n] = None
    return {
        **receipt,
        "current_revisions": current,
        "changes": [
            {"path": n, "before": current.get(n), "after": receipt["files"].get(n)}
            for n in sorted(names)
            if current.get(n) != receipt["files"].get(n)
        ],
    }


def restore_checkpoint(project, token, expected_revisions, dry_run=False):
    from .timeline import file_hash

    with project.locked():
        receipt = load_checkpoint(project, token)
        status = checkpoint_status(project, token)
        current = status["current_revisions"]
        if current != expected_revisions:
            raise MapError(
                "Checkpoint revision conflict; inspect checkpoint again and supply every current_revision including null for missing files"
            )
        changes = status["changes"]
        if dry_run:
            return {"token": token, "dry_run": True, "changes": changes}
        # Verify before writing; reverse snapshots and a pending receipt make
        # interruption recoverable without retaining all file payloads in RAM.
        for change in changes:
            if change["after"] is not None:
                blob = project.confined(
                    f'.hammer-agent/checkpoints/blobs/{change["after"]}'
                )
                if file_hash(blob) != change["after"]:
                    raise MapError("Checkpoint blob checksum mismatch")
        before = collect(project, receipt["paths"])
        reverse = uuid.uuid4().hex
        atomic_write(
            project.confined(f".hammer-agent/checkpoints/{reverse}.json"),
            json.dumps(
                {
                    "token": reverse,
                    "label": "before restore " + token,
                    "timestamp": now(),
                    "paths": receipt["paths"],
                    "files": before,
                }
            ).encode(),
            exclusive=True,
        )
        recovery = uuid.uuid4().hex
        pending = {
            "token": recovery,
            "checkpoint": token,
            "reverse_checkpoint": reverse,
            "status": "pending",
            "changes": changes,
            "timestamp": now(),
        }
        pending_path = project.confined(f".hammer-agent/recovery/{recovery}.json")
        atomic_write(
            pending_path, json.dumps(pending, indent=2).encode(), exclusive=True
        )
        apply_recovery(project, pending)
        pending["status"] = "complete"
        atomic_write(pending_path, json.dumps(pending, indent=2).encode())
    return {
        "token": token,
        "dry_run": False,
        "changes": changes,
        "reverse_checkpoint": reverse,
        "recovery_token": recovery,
        "status": "complete",
    }


def restore_saved_file(project, name, revision, expected):
    from .timeline import restore_file

    restore_file(project, name, revision, expected)


def apply_recovery(project, receipt):
    from .timeline import file_hash

    # Validate the entire interrupted batch before resuming any part of it.
    for change in receipt["changes"]:
        p = recovery_path(project, change["path"])
        if p.exists() and not p.is_file():
            raise MapError(
                "A checkpoint file was replaced by a directory; inspect before recovery"
            )
        if p.is_file() and p.stat().st_size > 128 * 1024 * 1024:
            raise MapError("Changed recovery file exceeds 128 MiB")
        for parent in p.parents:
            if parent == project.root:
                break
            if parent.exists() and not parent.is_dir():
                raise MapError("A checkpoint parent directory was replaced by a file")
        current = file_hash(p)
        if current not in (change["before"], change["after"]):
            raise MapError(
                "External changes detected during checkpoint recovery; inspect artifacts before proceeding"
            )
        if change["after"] is not None:
            blob = project.confined(
                f'.hammer-agent/checkpoints/blobs/{change["after"]}'
            )
            if file_hash(blob) != change["after"]:
                raise MapError("Checkpoint blob checksum mismatch")
    for change in receipt["changes"]:
        p = recovery_path(project, change["path"])
        current = file_hash(p)
        if current == change["after"]:
            continue
        if current != change["before"]:
            raise MapError(
                "File changed during checkpoint restore; recovery receipt retained"
            )
        restore_saved_file(project, change["path"], change["after"], current)


def resume_recovery(project, token):
    with project.locked():
        path = project.confined(f".hammer-agent/recovery/{identifier(token)}.json")
        receipt = json.loads(path.read_text("utf-8"))
        if receipt["status"] != "complete":
            apply_recovery(project, receipt)
            receipt["status"] = "complete"
            atomic_write(path, json.dumps(receipt, indent=2).encode())
    return receipt


def lock_status(project):
    path = project.confined(".hammer-agent/write.lock")
    if not path.exists():
        return {"locked": False}
    raw = path.read_bytes()
    try:
        owner = json.loads(raw)
        owner = owner if isinstance(owner, dict) else {"pid": int(owner)}
        pid = int(owner["pid"])
        if pid <= 0:
            raise ValueError
        if os.name == "nt":
            import ctypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x1000, False, pid)
            if handle:
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                kernel.CloseHandle(handle)
                alive = True
            else:
                alive = False if ctypes.get_last_error() == 87 else None
        else:
            try:
                os.kill(pid, 0)
                alive = True
            except ProcessLookupError:
                alive = False
            except PermissionError:
                alive = None
    except (ValueError, KeyError, TypeError):
        owner = {}
        alive = None
    return {
        "locked": True,
        "owner": owner,
        "alive": alive,
        "revision": digest(raw),
        "recoverable": alive is False,
    }


def recover_lock(project, expected_revision):
    with audit_lock(project):
        status = lock_status(project)
        if not status.get("recoverable") or status.get("revision") != expected_revision:
            raise MapError(
                "Lock recovery requires the inspected unchanged lock and a confirmed dead owner"
            )
        path = project.confined(".hammer-agent/write.lock")
        if digest(path.read_bytes()) != expected_revision:
            raise MapError("Lock changed; inspect again")
        path.unlink()
    return {"recovered": True, "previous_owner": status["owner"]}
