"""Permanent action receipts and revision-checked checkout of managed saved files.

SQLite is the indexed authority; immutable JSON event receipts are its readable
export. Blobs share the checkpoint store. No editor memory/undo stack is captured.
"""

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid

from .backend import BackendError
from .project import atomic_write
from .vmf import MapError

ROOT = "0" * 32
MAX_FILES = 10000
MAX_BYTES = 128 * 1024 * 1024
BUFFER = 1024 * 1024
_active = ContextVar("mapwright_action", default=None)


def now():
    return datetime.now(timezone.utc).isoformat()


def file_path(project, name):
    """Allow saved authoring files and narrowly defined editor/journal files."""
    from .workspace import EXCLUDED

    lexical = project.root / name
    for item in (lexical, *lexical.parents):
        if item == project.root:
            break
        if item.is_symlink():
            raise MapError("Timeline paths cannot contain symlinks")
    path = project.confined(name)
    parts = path.relative_to(project.root).parts
    if any(p.casefold() in EXCLUDED for p in parts):
        raise MapError("Timeline cannot manage Git, environments or credentials")
    if parts[0].casefold() == ".hammer-agent":
        native = (
            len(parts) == 5
            and parts[1] == "native-sessions"
            and parts[3] == "document"
            and path.suffix.lower() == ".vmf"
        )
        journal = (
            len(parts) == 3
            and parts[1] == "history"
            and len(path.stem) == 64
            and all(c in "0123456789abcdef" for c in path.stem)
            and path.suffix == ".json"
        )
        # Explicit checkpoints may include build/import evidence. Use the same
        # scope here so tracking and restore accept every permitted checkpoint.
        evidence = len(parts) >= 3 and parts[1] in {"builds", "imports"}
        if not native and not journal and not evidence:
            raise MapError("Timeline metadata cannot be included in file checkout")
    if path.exists() and not path.is_file():
        raise MapError("Timeline managed paths must be files")
    return path


def file_hash(path):
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise MapError("Timeline files must be regular files no larger than 128 MiB")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(BUFFER), b""):
            digest.update(block)
    return digest.hexdigest()


def store_file(project, path):
    """Hash/copy once using bounded memory, publishing immutable checkpoint blobs."""
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise MapError("Timeline files must be regular files no larger than 128 MiB")
    folder = project.confined(".hammer-agent/checkpoints/blobs")
    folder.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=folder)
    try:
        digest = hashlib.sha256()
        size = 0
        before = path.stat()
        with os.fdopen(descriptor, "wb") as output, path.open("rb") as source:
            for block in iter(lambda: source.read(BUFFER), b""):
                size += len(block)
                if size > MAX_BYTES:
                    raise MapError("Timeline file grew past 128 MiB during snapshot")
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            raise MapError("File changed during timeline snapshot; retry")
        revision = digest.hexdigest()
        destination = folder / revision
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if file_hash(destination) != revision:
                raise MapError("Timeline blob checksum mismatch")
        return revision
    finally:
        Path(temporary).unlink(missing_ok=True)


def restore_file(project, name, revision, expected):
    path = file_path(project, name)
    if file_hash(path) != expected:
        raise MapError("File changed during checkout; recovery receipt retained")
    if revision is None:
        path.unlink(missing_ok=True)
        return
    blob = project.confined(f".hammer-agent/checkpoints/blobs/{revision}")
    if file_hash(blob) != revision:
        raise MapError("Timeline blob checksum mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".hammer-agent-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output, blob.open("rb") as source:
            for block in iter(lambda: source.read(BUFFER), b""):
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if file_hash(path) != expected:
            raise MapError("File changed during checkout; recovery receipt retained")
        if expected is None:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.GetExitCodeProcess.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_ulong),
            ]
            kernel.GetExitCodeProcess.restype = ctypes.c_int
            try:
                code = ctypes.c_ulong()
                if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return None
                return (
                    code.value == 259
                )  # STILL_ACTIVE; an exited object can retain handles.
            finally:
                kernel.CloseHandle(handle)
        return False if ctypes.get_last_error() == 87 else None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None


class Timeline:
    def __init__(self, project):
        self.project = project
        self.folder = project.confined(".hammer-agent/timeline")
        self.folder.mkdir(parents=True, exist_ok=True)
        self.database = self.folder / "actions.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS actions (
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                  id TEXT UNIQUE NOT NULL, parent TEXT, tool TEXT NOT NULL,
                  status TEXT NOT NULL, pid INTEGER NOT NULL, session TEXT NOT NULL,
                  started TEXT NOT NULL, elapsed REAL, arguments TEXT NOT NULL,
                  result TEXT, error TEXT, details TEXT, target TEXT,
                  finalized INTEGER NOT NULL DEFAULT 0,
                  changed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS files (
                  action TEXT NOT NULL, path TEXT NOT NULL,
                  before_hash TEXT, after_hash TEXT,
                  after_known INTEGER NOT NULL DEFAULT 0,
                  PRIMARY KEY(action,path)
                );
                CREATE TABLE IF NOT EXISTS paths (
                  path TEXT PRIMARY KEY, baseline TEXT, first_action TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS refs (
                  name TEXT PRIMARY KEY, action TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                  action TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
                  exported INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS pending_actions ON actions(finalized);
                CREATE INDEX IF NOT EXISTS files_by_path ON files(path,action);
                CREATE INDEX IF NOT EXISTS unexported_events ON events(exported,sequence);
                """)
            db.execute(
                "INSERT OR IGNORE INTO actions "
                "(sequence,id,tool,status,pid,session,started,arguments,finalized) "
                "VALUES (0,?,'baseline','completed',0,'',?,'{}',1)",
                (ROOT, now()),
            )
            db.execute("INSERT OR IGNORE INTO refs VALUES ('HEAD',?)", (ROOT,))
        self.export_events()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def export_events(self):
        # A committed DB event is authoritative if a crash interrupts its export.
        while True:
            with self.connect() as db:
                rows = db.execute(
                    "SELECT * FROM events WHERE exported=0 ORDER BY sequence LIMIT 100"
                ).fetchall()
            if not rows:
                return
            for row in rows:
                path = self.folder / "events" / f"{row['sequence']:012d}.json"
                payload = json.loads(row["payload"])
                payload["event_sequence"] = row["sequence"]
                raw = (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode()
                try:
                    atomic_write(path, raw, exclusive=True)
                except FileExistsError:
                    if path.read_bytes() != raw:
                        raise MapError("Immutable timeline event checksum mismatch")
                with self.connect() as db:
                    db.execute(
                        "UPDATE events SET exported=1 WHERE sequence=?",
                        (row["sequence"],),
                    )

    def event(self, db, action, status, **extra):
        payload = {
            "action_id": action,
            "call_id": action,
            "session_id": self.project.session_id,
            "pid": os.getpid(),
            "status": status,
            "timestamp": now(),
            **extra,
        }
        db.execute(
            "INSERT INTO events(action,status,payload) VALUES (?,?,?)",
            (action, status, json.dumps(payload, ensure_ascii=True, allow_nan=False)),
        )

    def head(self):
        with self.connect() as db:
            return db.execute("SELECT action FROM refs WHERE name='HEAD'").fetchone()[0]

    def begin(self, tool, arguments):
        from .workspace import summary

        action = uuid.uuid4().hex
        values = summary(arguments)
        try:
            raw_arguments = json.dumps(
                arguments, sort_keys=True, ensure_ascii=True, allow_nan=False
            ).encode("ascii")
        except (TypeError, ValueError):
            # Invalid requests still need an addressable attempt before validation.
            values["invalid_arguments"] = repr(arguments)[:4000]
        else:
            replaces_source = tool == "map_replace_source" or (
                isinstance(arguments, dict)
                and isinstance(arguments.get("operations"), list)
                and any(
                    isinstance(op, dict) and op.get("op") == "replace_source"
                    for op in arguments["operations"]
                )
            )
            if replaces_source:
                values.pop("source", None)
            if len(raw_arguments) > 16384 or replaces_source:
                revision = hashlib.sha256(raw_arguments).hexdigest()
                artifact = self.folder / "arguments" / (revision + ".json")
                try:
                    atomic_write(artifact, raw_arguments, exclusive=True)
                except FileExistsError:
                    if file_hash(artifact) != revision:
                        raise MapError("Immutable action arguments checksum mismatch")
                values["arguments_artifact"] = artifact.relative_to(
                    self.project.root
                ).as_posix()
                values["arguments_bytes"] = len(raw_arguments)
            else:
                values["values"] = arguments
        with self.connect() as db:
            db.execute(
                "INSERT INTO actions(id,parent,tool,status,pid,session,started,arguments) "
                "VALUES (?,?,?,'attempted',?,?,?,?)",
                (
                    action,
                    self.head(),
                    tool,
                    os.getpid(),
                    self.project.session_id,
                    now(),
                    json.dumps(values, ensure_ascii=True),
                ),
            )
            self.event(db, action, "attempted", tool=tool, arguments=values)
        self.export_events()
        return Action(self, action)

    def inspect(self, action_id, offset=0, limit=100):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM actions WHERE id=?", (action_id,)
            ).fetchone()
            if row is None:
                raise MapError("Unknown action ID")
            files = db.execute(
                "SELECT path,before_hash,after_hash,after_known FROM files "
                "WHERE action=? ORDER BY path LIMIT ? OFFSET ?",
                (action_id, limit + 1, offset),
            ).fetchall()
        data = dict(row)
        for key in ("arguments", "result", "details"):
            if data[key] is not None:
                data[key] = json.loads(data[key])
        data["files"] = [dict(row) for row in files[:limit]]
        data["next_offset"] = offset + limit if len(files) > limit else None
        return data

    def history(self, after=0, limit=100):
        with self.connect() as db:
            rows = db.execute(
                "SELECT sequence,id,parent,tool,status,started,elapsed,changed,error "
                "FROM actions WHERE sequence>? ORDER BY sequence LIMIT ?",
                (after, limit + 1),
            ).fetchall()
        return {
            "actions": [dict(row) for row in rows[:limit]],
            "next_after": rows[limit - 1]["sequence"] if len(rows) > limit else None,
            "head": self.head(),
        }

    def operations(self, offset=0, limit=100):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM events ORDER BY sequence LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = db.execute("SELECT count(*) FROM events").fetchone()[0]
        return {
            "events": [json.loads(row[0]) for row in rows],
            "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
            "retention": "Permanent indexed events with immutable JSON receipts; no automatic expiry",
        }

    def status(self):
        with self.connect() as db:
            pending = db.execute(
                "SELECT id,tool,status,pid FROM actions WHERE finalized=0 "
                "ORDER BY sequence LIMIT 100"
            ).fetchall()
            count = db.execute(
                "SELECT count(*) FROM actions WHERE sequence>0"
            ).fetchone()[0]
            paths = db.execute("SELECT count(*) FROM paths").fetchone()[0]
        return {
            "head": self.head(),
            "actions": count,
            "managed_files": paths,
            "pending": [dict(row) for row in pending],
            "scope": "Saved managed file bytes/presence; native editor memory and undo stacks are excluded",
            "retention": "Permanent action records and blobs; no automatic expiry",
        }

    def state(self, action_id, names=None):
        with self.connect() as db:
            action = db.execute(
                "SELECT finalized FROM actions WHERE id=?", (action_id,)
            ).fetchone()
            if not action or not action[0]:
                raise MapError("Checkout requires a finalized action ID")
            # Only state-changing actions are parents, so read traffic does not
            # lengthen reconstruction. Baselines record first-managed scope.
            selected = (
                ""
                if names is None
                else " WHERE p.path IN (" + ",".join("?" for _ in names) + ")"
            )
            rows = db.execute(
                """WITH RECURSIVE ancestry(id,depth) AS (
                     SELECT ?,0 UNION ALL
                     SELECT a.parent,t.depth+1 FROM actions a JOIN ancestry t ON a.id=t.id
                     WHERE a.parent IS NOT NULL
                   ), versions AS (
                     SELECT f.path,f.after_hash,
                       row_number() OVER (PARTITION BY f.path ORDER BY t.depth) AS rank
                     FROM files f JOIN ancestry t ON f.action=t.id WHERE f.after_known=1
                   ) SELECT p.path,
                     CASE WHEN v.rank=1 THEN v.after_hash ELSE p.baseline END AS revision
                     FROM paths p LEFT JOIN versions v ON v.path=p.path AND v.rank=1
                     """ + selected + " ORDER BY p.path LIMIT ?",
                (action_id, *(names or []), MAX_FILES + 1),
            ).fetchall()
        if len(rows) > MAX_FILES:
            raise MapError("Timeline exceeds 10000 managed files")
        return {row["path"]: row["revision"] for row in rows}

    def reconcile(self, config=None):
        """Retain observed results from dead owners; resume a known checkout plan."""
        with self.connect() as db:
            pending = db.execute(
                "SELECT id,pid,status FROM actions WHERE finalized=0 ORDER BY sequence"
            ).fetchall()
        dead = [row for row in pending if alive(row["pid"]) is False]
        if not dead:
            return
        from . import workspace

        lock = workspace.lock_status(self.project)
        if lock.get("recoverable"):
            workspace.recover_lock(self.project, lock["revision"])
        with self.project.action_locked():
            for row in dead:
                action = Action(self, row["id"])
                if row["status"] == "restoring":
                    try:
                        action.resume_checkout(config or {})
                    except MapError as exc:
                        action.finish(
                            "conflicted",
                            error=str(exc),
                            details={
                                "recovery": "Observed files preserved; inspect this action before retrying checkout"
                            },
                        )
                else:
                    action.finish(
                        "interrupted",
                        error="Owner stopped before recording completion; observed saved files retained",
                    )


class Action:
    def __init__(self, timeline, action_id):
        self.timeline = timeline
        self.project = timeline.project
        self.id = action_id
        self.start = time.monotonic()

    def track(self, name):
        path = file_path(self.project, name)
        name = path.relative_to(self.project.root).as_posix()
        with self.timeline.connect() as db:
            if db.execute(
                "SELECT 1 FROM files WHERE action=? AND path=?", (self.id, name)
            ).fetchone():
                return
            if db.execute("SELECT count(*) FROM paths").fetchone()[0] >= MAX_FILES:
                if not db.execute(
                    "SELECT 1 FROM paths WHERE path=?", (name,)
                ).fetchone():
                    raise MapError("Timeline exceeds 10000 managed files")
        revision = store_file(self.project, path)
        with self.timeline.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO paths(path,baseline,first_action) VALUES (?,?,?)",
                (name, revision, self.id),
            )
            db.execute(
                "INSERT INTO files(action,path,before_hash) VALUES (?,?,?)",
                (self.id, name, revision),
            )
            self.timeline.event(db, self.id, "snapshot", path=name, before=revision)
        self.timeline.export_events()
        if path.suffix.lower() == ".vmf" and ".hammer-agent" not in path.parts:
            self.track(self.project.journal_path(path))

    def prepare(self):
        with self.timeline.connect() as db:
            db.execute(
                "UPDATE actions SET parent=?,status='prepared' WHERE id=?",
                (self.timeline.head(), self.id),
            )
            self.timeline.event(db, self.id, "prepared", parent=self.timeline.head())
        self.timeline.export_events()

    def finish(self, status, result=None, error=None, details=None):
        with self.timeline.connect() as db:
            files = db.execute(
                "SELECT path,before_hash FROM files WHERE action=? ORDER BY path",
                (self.id,),
            ).fetchall()
            parent = db.execute(
                "SELECT parent FROM actions WHERE id=?", (self.id,)
            ).fetchone()[0]
        expected_state = (
            self.timeline.state(parent or ROOT, [row["path"] for row in files])
            if files
            else {}
        )
        changed = False
        observed = []
        for row in files:
            after = store_file(self.project, file_path(self.project, row["path"]))
            # A failed checkout can still preserve previously external bytes as
            # a new state, making the next guarded checkout possible.
            changed |= after != expected_state[row["path"]]
            observed.append((after, self.id, row["path"]))
        result = result or {}
        kept = {
            key: result[key]
            for key in (
                "path",
                "revision",
                "status",
                "pid",
                "build_dir",
                "token",
                "recovery_token",
                "reverse_checkpoint",
                "verification",
                "checkpointed",
                "document_reversible",
                "session",
                "staged",
                "warnings",
                "artifacts",
                "native_reload",
                "session_id",
                "staged_map",
                "runtime",
                "idle_cpu_policy",
                "cleanup_complete",
                "job_active_processes",
                "graceful",
                "method",
                "width",
                "height",
                "backbuffer_width",
                "backbuffer_height",
                "capture_worker_pid",
                "capture_worker_exited",
                "viewport_capture_error",
                "content_has_variation",
                "frames_examined",
                "capture_worker_peak_working_set_bytes",
            )
            if key in result
        }
        with self.timeline.connect() as db:
            # Finalize all observed hashes and HEAD together, instead of one
            # FULL-synchronous SQLite transaction per tracked file.
            db.executemany(
                "UPDATE files SET after_hash=?,after_known=1 WHERE action=? AND path=?",
                observed,
            )
            db.execute(
                "UPDATE actions SET status=?,finalized=1,changed=?,elapsed=?,result=?,error=?,details=? "
                "WHERE id=?",
                (
                    status,
                    int(changed),
                    round(time.monotonic() - self.start, 3),
                    json.dumps(kept, ensure_ascii=True),
                    error,
                    json.dumps(details or {}, ensure_ascii=True),
                    self.id,
                ),
            )
            if changed:
                # Never remove the previous tip, including descendants of a checkout.
                previous = db.execute(
                    "SELECT action FROM refs WHERE name='HEAD'"
                ).fetchone()[0]
                db.execute(
                    "INSERT OR IGNORE INTO refs VALUES (?,?)",
                    ("retained/" + previous, previous),
                )
                db.execute("UPDATE refs SET action=? WHERE name='HEAD'", (self.id,))
            self.timeline.event(
                db,
                self.id,
                status,
                changed=changed,
                result=kept,
                error=error,
                details=details or {},
            )
        self.timeline.export_events()
        return {
            "action_id": self.id,
            "head": self.timeline.head(),
            "status": status,
            "changed": changed,
        }

    def fail(self, exc):
        with self.timeline.connect() as db:
            row = db.execute(
                "SELECT status,finalized FROM actions WHERE id=?", (self.id,)
            ).fetchone()
        if row[1]:
            return
        if row[0] != "restoring":
            try:
                self.finish(
                    "failed", error=str(exc), details=getattr(exc, "details", {})
                )
                return
            except Exception:
                # The durable attempt remains recoverable if after-snapshot or
                # receipt publication fails, including a full disk.
                with self.timeline.connect() as db:
                    if db.execute(
                        "SELECT finalized FROM actions WHERE id=?", (self.id,)
                    ).fetchone()[0]:
                        return
                    db.execute(
                        "UPDATE actions SET status='snapshot_required' WHERE id=?",
                        (self.id,),
                    )
        with self.timeline.connect() as db:
            db.execute(
                "UPDATE actions SET pid=0,error=? WHERE id=?", (str(exc), self.id)
            )
            self.timeline.event(db, self.id, "recovery_required", error=str(exc))
        self.timeline.export_events()

    def checkout(self, target, expected_head, config, dry_run=False):
        if expected_head != self.timeline.head():
            raise MapError(
                "Timeline HEAD conflict; inspect timeline_status before checkout"
            )
        specs = []
        if not dry_run:
            from . import native_session

            specs = native_session.quiesce(
                self.project, config, self.timeline.state(target)
            )
        try:
            result = self._checkout(target, expected_head, dry_run, specs)
        except Exception:
            with self.timeline.connect() as db:
                state = db.execute(
                    "SELECT status FROM actions WHERE id=?", (self.id,)
                ).fetchone()[0]
            # A partially restored document stays closed until reconciliation.
            if state != "restoring" and specs:
                self.reload_native(config, specs)
            raise
        if specs:
            result["native_reload"] = self.reload_native(config, specs)
        return result

    def reload_native(self, config, specs):
        from . import native_session

        try:
            return {"sessions": native_session.reload(self.project, config, specs)}
        except Exception as exc:
            return {"error": str(exc), "saved_files_restored": True}

    def _checkout(self, target, expected_head, dry_run, native_specs):
        if expected_head != self.timeline.head():
            raise MapError(
                "Timeline HEAD conflict; inspect timeline_status before checkout"
            )
        target_state = self.timeline.state(target)
        current_state = self.timeline.state(expected_head)
        for name in target_state:
            self.track(name)
        with self.timeline.connect() as db:
            rows = db.execute(
                "SELECT path,before_hash FROM files WHERE action=?", (self.id,)
            ).fetchall()
        external = [
            dict(row)
            for row in rows
            if row["before_hash"] != current_state[row["path"]]
        ]
        if external:
            # Before blobs are permanent even if the client loses the error response.
            raise BackendError(
                "External changes preserved in this action; checkout refused. Inspect action and retry using its HEAD",
                {"preserved_action": self.id, "files": external},
            )
        changes = [
            {
                "path": row["path"],
                "before": row["before_hash"],
                "after": target_state[row["path"]],
            }
            for row in rows
            if row["before_hash"] != target_state[row["path"]]
        ]
        if dry_run:
            return {"target": target, "changes": changes, "dry_run": True}
        with self.timeline.connect() as db:
            for change in changes:
                db.execute(
                    "UPDATE files SET after_hash=?,after_known=1 WHERE action=? AND path=?",
                    (change["after"], self.id, change["path"]),
                )
            db.execute(
                "UPDATE actions SET status='restoring',target=?,details=? WHERE id=?",
                (target, json.dumps({"native_reopen": native_specs}), self.id),
            )
            self.timeline.event(
                db, self.id, "restoring", target=target, changes=changes
            )
        self.timeline.export_events()
        self.apply_checkout(changes)
        return {
            "target": target,
            "changes": changes,
            "dry_run": False,
            "scope": "Saved file bytes/presence only",
        }

    def apply_checkout(self, changes):
        # Validate every file/blob before the first write, with bounded payload RAM.
        for change in changes:
            path = file_path(self.project, change["path"])
            current = file_hash(path)
            if current not in (change["before"], change["after"]):
                raise MapError(
                    "External changes during checkout; preserved pending receipt requires reconciliation"
                )
            if change["after"] is not None:
                blob = self.project.confined(
                    f".hammer-agent/checkpoints/blobs/{change['after']}"
                )
                if file_hash(blob) != change["after"]:
                    raise MapError("Timeline blob checksum mismatch")
        for change in changes:
            path = file_path(self.project, change["path"])
            current = file_hash(path)
            if current != change["after"]:
                restore_file(
                    self.project, change["path"], change["after"], change["before"]
                )

    def resume_checkout(self, config):
        with self.timeline.connect() as db:
            rows = db.execute(
                "SELECT path,before_hash AS before,after_hash AS after FROM files "
                "WHERE action=? AND after_known=1",
                (self.id,),
            ).fetchall()
            details = json.loads(
                db.execute(
                    "SELECT details FROM actions WHERE id=?", (self.id,)
                ).fetchone()[0]
                or "{}"
            )
        from . import native_session

        specs = details.get("native_reopen", [])
        more = native_session.quiesce(
            self.project, config, [row["path"] for row in rows]
        )
        specs = list({s["session_id"]: s for s in [*specs, *more]}.values())
        self.apply_checkout([dict(row) for row in rows])
        result = {"native_reload": self.reload_native(config, specs)} if specs else {}
        return self.finish("reconciled", result)


def track_file(project, path):
    """Native/session adapters call this before changing a staged saved document."""
    active = _active.get()
    if active is not None:
        if active.project.root != project.root:
            raise MapError("Cannot attach another workspace to an active action")
        active.track(path)


def known_files(project, config, tool, args):
    if not isinstance(args, dict) or args.get("dry_run"):
        return []
    name = None
    if tool in {
        "create_map",
        "delete_map_file",
        "edit_map",
        "undo_map",
        "redo_map",
    } or (tool.startswith("map_") and tool != "map_history"):
        name = args.get("path")
    elif tool == "copy_reference_objects":
        names = (
            [args["destination"]] if isinstance(args.get("destination"), str) else []
        )
        game = config.get("game_dir")
        if isinstance(game, str):
            candidate = (project.root / game).resolve() / "gameinfo.txt"
            if candidate.is_relative_to(project.root):
                names.append(candidate)
        return names
    elif tool == "import_reference_map":
        name = args.get("output")
    elif tool in ("capture_editor", "package_map"):
        name = args.get("output")
    elif tool == "restore_map_file" and isinstance(args.get("token"), str):
        token = args["token"]
        from .workspace import identifier

        identifier(token)
        receipt = project.confined(f".hammer-agent/trash/{token}.json")
        name = json.loads(receipt.read_text("utf-8"))["path"]
    elif tool in ("restore_checkpoint", "resume_recovery"):
        from . import workspace

        if tool == "restore_checkpoint":
            state = workspace.checkpoint_status(project, args.get("token", ""))
            return list(state["current_revisions"])
        token = workspace.identifier(args.get("token", ""))
        receipt = project.confined(f".hammer-agent/recovery/{token}.json")
        return [
            change["path"]
            for change in json.loads(receipt.read_text("utf-8"))["changes"]
        ]
    return [name] if isinstance(name, (str, Path)) else []


def run(project, config, tool, arguments, callback, mutating=False):
    timeline = Timeline(project)
    action = timeline.begin(tool, arguments)
    token = None
    failed = False
    try:
        timeline.reconcile(config)
        with project.action_locked() if mutating else nullcontext():
            try:
                token = _active.set(action)
                for name in known_files(project, config, tool, arguments):
                    action.track(name)
                action.prepare()
                result = callback()
                receipt = action.finish(
                    (
                        "dispatched"
                        if result.get("status") == "dispatched"
                        else "completed"
                    ),
                    result,
                )
                return {**result, "timeline": receipt}
            except Exception as exc:
                action.fail(exc)
                failed = True
                raise
    except Exception as exc:
        if not failed:
            action.fail(exc)
        raise BackendError(
            str(exc),
            {
                **getattr(exc, "details", {}),
                "action_id": action.id,
                "head": timeline.head(),
            },
        ) from exc
    finally:
        if token is not None:
            _active.reset(token)


def checkout(project, config, **arguments):
    active = _active.get()
    if active is None:
        raise MapError("Checkout must run through the shared action dispatcher")
    return active.checkout(config=config, **arguments)
