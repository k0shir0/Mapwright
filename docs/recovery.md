# Recovery

State lives in the workspace's ignored `.hammer-agent/` directory.

## Maps and evidence

- `history PATH`, `undo PATH --expect HASH`, `redo PATH --expect HASH`:
  revision-checked map transactions; external edits cause refusal. History
  is per path. New edits after undo retain the abandoned branch as an artifact.
- `delete-file PATH --expect HASH` returns a token; `restore-file TOKEN`
  recreates the map without overwrite. Lost tokens are in trash receipts.
- `logs` reads workspace operation outcomes. Source bodies are hashed;
  snapshots retain exact prior VMF bytes. Logs rotate; snapshots persist.
- `artifacts` lists history, snapshots, trash, builds, imports and recovery
  records. `artifact PATH` reads bounded bytes as UTF-8 or base64. Source
  offsets use characters; artifact offsets use bytes.

Prepared receipts or started-only log events can indicate interrupted work;
inspect current files before recovery. `audit_warning` means logging failed,
not that the completed map operation failed.

## File/folder checkpoints

```text
mapwright checkpoint maps assets mapwright.local.json --label before-edit
mapwright checkpoint-state TOKEN
mapwright checkpoint-restore TOKEN --expected-revisions @revisions.json --dry-run
mapwright checkpoint-restore TOKEN --expected-revisions @revisions.json
```

`revisions.json` must be the exact `current_revisions` object, including null
for absent files. Restore recreates/deletes/rewrites files to match the captured
scope, including removing newly added files under captured folders. Review
`changes` first. Empty directories can remain. See `schema` for size/path limits.

Restoration keeps a `reverse_checkpoint` and a recovery receipt. It is
recoverable, not multi-file atomic. After interruption, read `recovery/` and
run `resume-recovery TOKEN`; unexpected file hashes cause refusal. To reverse
a completed restore, inspect/restore its reverse checkpoint normally.

Checkpoints protect saved files. Use Hammer undo for unsaved GUI state and
prevent concurrent editor saves during file restoration.

## Locks and MCP resources

`lock-status` reports the lock revision and owner liveness.
`recover-lock --expect LOCK_HASH` removes only an unchanged lock with a confirmed dead owner.

Resources: `hammer://workspace/artifacts`, `hammer://workspace/operations`,
`hammer://artifact/{path}`. URL-encode the workspace-relative artifact path;
use tools for pagination.
