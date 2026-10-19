# Local logs and recovery

All paths below live under the workspace's ignored `.hammer-agent` directory.

`logs` / `operation_log` reads JSONL events across maps and tool calls. Events
contain UTC time, PID/session/call ID, tool name, argument hash, selected path
and revision metadata, started/completed/failed status and duration. Whole VMF
source and GUI text are not copied into logs. Calls that terminate abruptly
may retain only a started event. Reading logs, artifacts, history, checkpoint
status and lock status does not generate more log events.

The log rotates at 4 MiB with three older files. Audit write failures appear
as `audit_warning` in successful tool data; they do not make a completed map
write appear to have failed. Failure returns retain the original operation
error. Snapshot/checkpoint retention is explicit: nothing automatically deletes
recoverable map state. Monitor storage with `artifacts`; no automatic GC runs.

`artifacts [--category history|snapshots|trash|references|builds|imports|checkpoints|recovery|logs]`
lists paginated evidence. `artifact PATH` reads bounded bytes (text or base64).
Trash receipts list deletion tokens even after a client loses the original
response. A prepared deletion receipt may describe an interrupted deletion;
inspect whether its map still exists before restoring. Restore refuses overwrite.

Map history still supports revision-checked undo/redo. History reads now resolve
pending state without writing; the next writer reconciles the journal. New
edits after undo retain the abandoned branch as a separate history artifact.
Replacement-source bodies remain hash-redacted in history, with exact bytes
accessible through the before/after snapshots. Renaming a file still starts a
separate path-based history; checkpoints and the operation log retain context.

## Files and folders

```text
mapwright checkpoint maps assets mapwright.local.json --label before-gui-save
mapwright checkpoint-state TOKEN
mapwright checkpoint-restore TOKEN --expected-revisions @revisions.json --dry-run
mapwright checkpoint-restore TOKEN --expected-revisions @revisions.json
```

`revisions.json` is the exact `current_revisions` object from checkpoint-state,
including null for missing files. Review the returned changes before restoring.
New files under checkpointed folders are removed, deleted files are recreated,
and changed files are restored. Empty directories may remain. Files of any
format can be protected, including BSP, RMF, assets, captures and local config.
Scopes may include `.hammer-agent/builds` and `imports`, but exclude Git,
environments, credential directories, symlinks and recovery metadata. Limits:
10,000 files, 128 MiB per file, 512 MiB total.

Each restore first verifies revisions and stored hashes, keeps the current
state as a reverse checkpoint, and persists a recovery receipt. Multi-file
restoration is not atomic. If interrupted, read its receipt in `recovery/`
and call `resume-recovery TOKEN`. Recovery accepts only the recorded before
or after hash for every file and refuses external changes. To reverse a
completed restore, inspect and restore its `reverse_checkpoint` normally.

Keep the editor from saving concurrently with restoration. Checkpoints protect
saved files, not Hammer's in-memory state. GUI undo, selection, and camera state
remain editor operations. Checkpoint the map, owned local gameinfo and asset
folders before reference-copy asset mounting; mounts and map writes are
separate operations. External installation files are outside this boundary.

## Stale write locks

`lock-status` reports owner/liveness and a lock revision. `recover-lock --expect
LOCK_HASH` removes it only when the owner is confirmed dead and the lock is
unchanged. Unknown liveness, PID reuse or permission-denied inspection fails
closed. Active editor state is separate from the bridge write lock.

MCP resources expose `hammer://guide/kz`, `hammer://workspace/artifacts`,
`hammer://workspace/operations` and `hammer://artifact/{path}` (URL-encode the
workspace-relative artifact path). Tools provide pagination and larger reads.
