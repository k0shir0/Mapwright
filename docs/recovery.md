# Recovery

State lives in the workspace's ignored `.hammer-agent/` directory.

## Problem log

When a failure affects delivery, keep a concise issue record in the ignored task
workspace: failing action/build ID, observed versus expected behavior, confirmed
diagnosis, resolution, and verification limits. Link existing action receipts,
logs and captures instead of copying them into another research document. Preserve
original evidence and label hypotheses, inconclusive checks and unverified claims.
Use the [verification scope](kz-mapping.md#verification-scope) for delivery claims.

## Permanent action timeline

CLI/MCP source and artifact pages default to 8,000 characters/bytes. Source pages
return `source_complete`; keep the first `revision` as `expected_revision` on later
pages. Map history defaults to 100 entries and returns `history_revision`;
use `expected_history_revision` on later pages (`history --expected-history-revision`).
Restart pagination on a revision conflict. Never replace whole source using an
incomplete page.

Results larger than 32 KiB of compact ASCII JSON return an explicit
`response.truncated` summary, collection totals and a checksummed immutable JSON
artifact under `.hammer-agent/results/`. Status, revision, validity, completeness
and recovery identifiers remain available. Findings/warnings may be previews:
inspect `response.omitted_fields` and use `read_artifact` with `field=NAME`
(or CLI `artifact PATH --field NAME --limit 20`) to read needed fields. Field
offsets count entries/characters; follow `next_offset` and `next_call`. Read all
relevant findings before verification claims. Byte pages remain available to
recover the exact full result. Evidence artifacts are ASCII JSON, so byte pages
concatenate without splitting UTF-8 characters. Existing arbitrary binary artifacts
still use base64 when a page is not UTF-8. CLI `--response-mode full` or MCP
`response_mode=full` returns the original full result. Text and structured MCP
representations remain equivalent. The 32 KiB budget covers result data; transport
envelopes add a small overhead. Explicit source/artifact limits remain available.

Map journals now use the filesystem's resolved path spelling. Distinct `A.vmf`
and `a.vmf` have distinct histories on sensitive filesystems; actual path aliases
share a journal. Legacy case-folded journals migrate on the next write when their
recorded owner, or a unique matching path/revision, identifies the map. Original
entries remain in the legacy journal with a migration marker. Interrupted migration
resumes, and timeline checkout retains both journal states. An ambiguous or
unidentified legacy journal produces an error naming the retained evidence; identify
its owner before manually recovering it. Do not assign shared evidence to a map by
guessing or discard it to clear an error.

Every shared CLI/MCP tool request receives an action ID before execution,
including failed/rejected requests and metadata reads. Results include
`data.timeline` with `action_id`, `head`, `status` and `changed`. Failed calls
return the action ID and current HEAD in error `details`. HEAD advances when
managed saved files differ from the previous state; read-only requests share
that state without moving HEAD.

```text
mapwright timeline-status
mapwright action-history --after 0 --limit 100
mapwright action ACTION_ID
mapwright checkout-action ACTION_ID --expected-head CURRENT_HEAD --dry-run
mapwright checkout-action ACTION_ID --expected-head CURRENT_HEAD
```

MCP names are `timeline_status`, `action_history`, `inspect_action` and
`checkout_action`. Checkout restores the saved after-state of any finalized
action, including failed/read-only actions. Redo uses the same checkout command
with a retained future action ID. Future actions and their blobs remain available
after checkout or editing a new branch. Checkout also restores the affected
per-map undo journals, so map undo/redo follows the restored document.

The indexed ledger is `timeline/actions.sqlite3`. Human-readable immutable JSON
receipts live under `timeline/events/`; committed events whose export was
interrupted are exported on the next request. Neither expires automatically.
History uses a sequence cursor and bounded pages; `logs` reads indexed lifecycle
events. Small requests retain their exact arguments, including edit values and
native command labels. Source replacements and larger requests link an immutable
`timeline/arguments/*.json` artifact, readable with `artifact` / `read_artifact`.
Source bodies are hashed in receipts; exact saved bytes reside in the
content-addressed checkpoint blob store. Audit/snapshot persistence must succeed
before a managed mutation proceeds.
Native receipts also retain capture mode, fallback warnings, worker/resource
metadata, session IDs and owned-job cleanup results.

Automatic tracking covers affected VMFs and their active journals, VMF imports,
deletion/restoration, checkpoint restore scopes, capture output files, and local
`gameinfo.txt` changes made while copying reference assets. Native adapters also
track saved documents under `native-sessions/*/document/`. Before/after snapshots
include absence, allowing creation/deletion to be reversed. A failed multi-file
operation retains its observed partial state and error rather than claiming it
had no effects. Build/import jobs and their logs remain evidence artifacts;
checkout does not remove their directories or undo external tool side effects.

Tracking begins when a file is first managed. Its then-current bytes become its
baseline for older actions; the ledger does not reconstruct earlier unobserved
external versions or scan/copy a complete SDK. `inspect_action` lists each
action's tracked files. Limits are 10,000 managed files and 128 MiB per file.
Snapshots/restoration stream file contents; there is no automatic retention quota.
Unique retained content consumes disk. Back up the state directory and do not
delete blobs or edit the ledger/immutable receipts independently.

If current files differ from HEAD, checkout first preserves those bytes as the
failed action's addressable state and refuses to overwrite them. Inspect that
action, then retry with the new HEAD to restore the desired action. Checkout
requires every affected file to match inspected before/after hashes. It uses a
durable per-file plan; multi-file publication is recoverable, not atomic.

On the next request, actions whose owner is confirmed dead are reconciled
automatically. Interrupted ordinary actions retain observed saved files with
`interrupted` status. An interrupted checkout resumes only when all files match
its planned before/after hashes. Unexpected external bytes are preserved with
`conflicted` status. Confirmed dead bridge locks are recovered during this
reconciliation; ambiguous/live owners are never removed. Process-crash recovery
does not establish hardware/power-loss durability.

Checkout closes affected owned editor sessions before restoring their staged
documents and reopens them automatically afterward. Reopen failures are reported
as `native_reload.error`; a staged document absent at the restored action stays
closed. Saved-file restoration remains separately recorded.
An interrupted checkout retains the reopen specification for reconciliation.
Only saved document bytes/presence are versioned. Editor memory, selection,
camera state, undo stacks, arbitrary dialogs, registry state and gameplay/server
state are outside this guarantee. A native action reported as `dispatched` or
`document_reversible=false` has not proved an in-memory rollback capability.

## Maps and evidence

- `history PATH`, `undo PATH --expect HASH`, `redo PATH --expect HASH`:
  revision-checked map transactions; external edits cause refusal. History
  is per path. New edits after undo retain the abandoned branch as an artifact.
- `delete-file PATH --expect HASH` returns a token; `restore-file TOKEN`
  recreates the map without overwrite. Lost tokens are in trash receipts.
- `logs` reads permanent indexed action events. Pre-timeline rotated logs remain
  readable as artifacts; new action receipts and snapshots do not expire.
- `artifacts` lists history, snapshots, trash, builds, imports and recovery
  records. `artifact PATH` reads bounded bytes as UTF-8 or base64. Source
  offsets use characters; artifact offsets use bytes.

Prepared receipts or attempted-only events can indicate interrupted work.
Use `timeline-status`, `action-history` and `action ACTION_ID` to inspect the
reconciled outcome before continuing.

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

Explicit checkpoints may include saved files under `.hammer-agent/builds/` and
`.hammer-agent/imports/`; these files are tracked when restored. Timeline databases,
checkpoint receipts/blobs and other recovery metadata remain excluded from restore.

Checkpoints protect saved files. For editor-only changes, inspect and invoke
Hammer's Edit/Undo command through the native control API, then verify staging.
Coordinate saves from any independently opened editor before file restoration.

## Locks and MCP resources

`lock-status` reports the lock revision and owner liveness.
`recover-lock --expect LOCK_HASH` removes only an unchanged lock with a confirmed dead owner.

Resources: `hammer://workspace/artifacts`, `hammer://workspace/operations`,
`hammer://artifact/{path}`. URL-encode the workspace-relative artifact path;
use tools for pagination.

## Installer rollback

`python scripts/setup_agent.py --rollback RECEIPT --yes` restores the selected
registration, skills and configuration. It retains downloaded tools and maps.
Rollback verifies all current hashes and backup checksums before starting, records
`rolling-back` before writing, and rechecks each file immediately before restoring.
After an interrupted installation or rollback, rerun the same receipt: files already restored are skipped;
unexpected external edits cause refusal. Keep the receipt and backups until the
transaction reaches `rolled-back`. Coordinate other writers; per-file checks do
not lock independently running editors or make multi-file restoration atomic.
Interrupted automatic unwinding retains `rolling-back`; preserved external edits
retain `rollback-conflict`. Both remain recoverable through the receipt once all
files match their recorded before/after bytes. An `applying` receipt can likewise
be rolled back after a process crash during installation.
