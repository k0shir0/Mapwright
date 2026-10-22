# MCP performance and recovery review

Reviewed 2026-10-22 against upstream commit
[`95c7217b005478299e0a82781f376a321f4c6ff7`](https://github.com/k0shir0/Mapwright/commit/95c7217b005478299e0a82781f376a321f4c6ff7).
This review covers all 55 text files: 25 production/script Python files, 14 test
files, both skills, documentation, configuration, examples and CI. The banner PNG
was excluded from source analysis. Source was obtained through the authenticated
GitHub connection and tested locally. Findings below distinguish implemented fixes
from remaining recommendations.

## Assessment

Mapwright already has substantial recovery safeguards: optimistic revisions,
exclusive creation, immutable checksummed blobs, pending journals, retained
branches, resumable checkpoint/checkout plans, and process-crash tests. Ordinary
map undo/redo and timeline checkout pass the portable tests. Recovery nevertheless
had reproducible gaps in checkpoint scopes and installer rollback, now fixed here.
Saved-file recovery does not restore unsaved editor memory or arbitrary external
tool effects, and multi-file restoration is recoverable rather than atomic.

The largest context costs are the 58-tool advertisement and several large default
or unpaginated results. The main scaling costs are repeated parsing/scanning,
permanent receipt/blob I/O and whole-file packaging. The small-map measurements
do not establish a major latency problem, and native performance cannot be
certified on this Linux host.

## Reproduced issues fixed in this change

| Priority | Finding and evidence | Change |
| --- | --- | --- |
| P1 | Checkpoints accepted `.hammer-agent/builds/` and `imports/` files, but both dispatcher tracking and the shared restore helper rejected them. A valid restore failed with `Timeline metadata cannot be included in file checkout`. | Align the timeline allowlist with these explicit checkpoint scopes. Databases, receipts and blob metadata remain protected. Regression covers restore, reverse restore and timeline checkout for both directories. |
| P1 | Explicit installer rollback was not resumable: after restoring one file and failing on the next, the receipt remained `applied`; retry rejected the already-restored file. | Persist `rolling-back` before restoring; accept only recorded before/after states on resume, preflight all files and skip completed restores. |
| P1 | Installer rollback checked hashes once before the loop. An edit to a later file between restoration steps was overwritten. | Recheck each file immediately before writing/deleting. Regression injects an external edit between two restores and verifies refusal/preservation. This narrows the race; it cannot lock unrelated writers. |
| P1 | Automatic installation unwinding could mark a receipt `rolled-back` before its own writes completed. A crash during forward installation left an `applying` receipt that explicit rollback rejected. | Mark unwinding pending until complete. Permit guarded recovery of `applying`, `rolling-back` and `rollback-conflict` receipts. Regressions cover failed unwinding and a partial forward install. |
| P1 | Compiler error/leak detection read only the first 1 MiB of logs. A synthetic zero-exit compiler with a fresh header fixture and a later `ERROR:` or leak marker was accepted. | Scan the full log through a read-only memory map. Return the actual last 6,000 bytes on failure; `log_truncated` describes this bounded tail. Tests cover both late markers. This tests the compiler boundary, not native compilation. |
| P2 | JSON-schema errors echoed entire invalid inputs. One invalid 100,000-character classname produced a 100,078-character error, repeated through transport/receipts. | Replace messages longer than 320 characters with the failing constraint and schema guidance; retain the argument path. Regression checks a bounded error and unchanged map. This does not bound every possible backend error. |
| P2 | `Action.finish()` opened a FULL-synchronous SQLite transaction for every file's final hash. | Publish observed hashes, final action state, HEAD and completion event in one transaction after snapshots succeed. A restore of 100 files uses 521 connections rather than 621. Snapshot checks and durable receipts remain. |

Other implemented reductions:

- Shorten both skills and repeated tool descriptions. Move detailed Python
  provisioning to a linked guide that is bundled by the existing installer.
- Recommend small object/source/artifact pages and require all source pages before
  whole-source replacement. Existing API defaults and schemas remain compatible.
- Use compact JSON for MCP text/resource results. Retain equivalent text and
  structured results for existing clients; PNGs remain typed image content.
- Remove six unused imports and seven obsolete private GUI input parameters.
  Remove a duplicate Source-tools check, duplicate editor checkpoint before close,
  and an unchanged BSP re-read/hash when packing is disabled. When packing changes
  the BSP, its final bytes are still revalidated and hashed.
- Add checks for every light's origin/emitting surface/aperture clearing solid
  objects and every visible block's faces/materials in both the mapping skill and
  MCP workflow guide. These are authoring/visual verification instructions, not a
  new geometric proof implemented by `validate_map`.

## Context measurements

| Item | Upstream | Revised | Reduction |
| --- | ---: | ---: | ---: |
| Mapping skill, UTF-8 bytes | 6,069 | 4,926 | 18.8% |
| Setup skill, UTF-8 bytes | 6,732 | 3,898 | 42.1% |
| Combined skill bytes | 12,801 | 8,824 | 31.1% |
| Combined whitespace-separated words | 1,694 | 1,024 | 39.6% |
| Compact tools/list JSON bytes, 58 tools | 53,438 | 51,498 | 3.6% |

Byte and word counts are reproducible text measurements, not model-specific token
counts. Tools/list size was measured by constructing the same SDK `Tool` and
`ToolAnnotations` objects as the server, serializing with `exclude_none=True` and
compact JSON, without JSON-RPC envelope overhead. Client/model token accounting
and whether both result representations enter model context vary by client.

The modest tools/list reduction is intentional: schemas, revision guards, typed
IDs, error semantics and compatibility were retained. Description trimming alone
cannot eliminate the cost of advertising 58 full schemas. A task-specific tool
profile or client tool-search support would provide a larger reduction.

The mapping skill retains invocation/discovery, exact GOKZ semantics, revision
checks, atomic edit boundaries, unsupported geometry, reference provenance,
dependency packing, verification scope and recovery. The added visual checks
account for some of its remaining size. Setup retains automated provisioning,
scope isolation, verification, client reload fallback and rollback requirements.
Linked guides are loaded on demand; bundling them does not require reading all of
them into every task's context.

## Remaining findings, in recommended order

### R1 — P2: case-sensitive maps share a case-folded undo journal

[`Project.journal_path`](../cli/hammerplusplus/project.py#L376) case-folds paths
on every platform. On Linux, distinct `A.vmf` and `a.vmf` resolve to the same
journal. Reproduced by comparing the two journal paths. Revision guards often
turn this into an undo refusal, but independent per-map histories are not assured.

Use platform-appropriate identity and design migration for existing journals
before changing hashes. Add independent edit/undo tests for case-distinct paths
on a case-sensitive filesystem. This is **not fixed** by the recovery changes above.

### R2 — P2: default responses still have substantial context costs

[`Project.source`](../cli/hammerplusplus/project.py#L167) and
[`read_artifact`](../cli/hammerplusplus/workspace.py#L209) default to 100,000
characters/bytes. An otherwise ordinary read can consume much of an agent's
context. The skill now requests 8,000-unit pages; API defaults remain unchanged.

Several responses have no useful content budget: `inspect_object` includes a full
object source span, `map_history` returns all entries, `inspect_checkpoint`
duplicates file hashes across receipt/current/changes, KZ results return all
findings, and compile receipts include every embedded dependency and 64 BSP lump
records. `operation_log` is paginated but can include complete small argument
objects in each event. Entry limits alone do not bound serialized bytes.

Add summary/detail modes and explicit pagination or bounded artifact links. Always
retain failure status, revision, finding counts, incomplete/unsupported indicators,
recovery IDs and a route to full evidence. Do not silently truncate findings or
drop compatibility text without checking supported clients.

### R3 — P2: permanent history makes every read a write workload

[`timeline.run`](../cli/hammerplusplus/timeline.py#L861) creates a durable action,
preparation event and final event even for metadata reads. Constructor/schema
checks, event exports and many short SQLite connections add overhead; finalization
batching removes only part of it. `store_file` copies/hashes to a temporary file
and verifies an existing blob on deduplication. This repeats for tracked before
and after states, including no-op or rejected mutations. Tracking currently
precedes argument validation, so invalid requests may do unnecessary snapshot I/O.

An empty-map sample of 30 direct and 30 dispatched inspections measured medians
of about 0.13 ms and 1.8 ms respectively. This demonstrates the durable-receipt
cost on a tiny map, not a universal slowdown ratio. A restore of 100 six-byte files
used 621 connections upstream and 521 after batching (16.1% fewer). Single-run
wall times were about 157 ms upstream and 151–163 ms revised; **no reliable wall
time speedup is claimed**.

Next: validate schemas before expensive tracking while retaining failed-request
receipts, reuse request-local DB connections, batch export bookkeeping, and
measure representative maps/disks. Preserve `synchronous=FULL`, checksum checks
and the existing permanent-history contract unless deliberately redesigned.
`Timeline.state()` also reconstructs ancestry/windowed file versions before its
final path filter; push selected-path filtering into that work and examine query
plans on long histories. Retained blobs/events have no expiry: provide disk usage
visibility and an explicit reference-aware maintenance design rather than deleting
history implicitly.

### R4 — P2: paging often repeats whole-map work

Each source page reads/decodes/hashes the entire VMF. Each inspect/find page parses
the entire source; file/artifact searches build complete collections before
slicing. Small output pages reduce context but do not proportionally reduce CPU,
RAM or disk reads. Permanent artifact growth makes repeated directory scans more
expensive over time.

Consider revision-keyed parsed indexes, stable cursors and streamed/indexed
artifact listings. Cache reuse must detect external edits, encoding changes and
workspace/mount changes; optimistic revisions must remain authoritative.

### R5 — P2: edit and KZ inner loops still scale poorly

[`vmf.mutate_many`](../cli/hammerplusplus/vmf.py#L568) saves parsing for independent
translations, but calls `mutate` on the full text for every item and reconstructs
full strings repeatedly. General mixed batches reparse per operation. The
1,000-operation/64 MiB limits do not imply a small memory or CPU budget.

In [`kz.py`](../cli/hammerplusplus/kz.py), `volumes()` scans all solids repeatedly,
`select()` walks the tree and scans solids for each route selector, and several
checks nest entity/ground scans. The whole-map headhitter check already has a
1,000-box guard and is excluded from default audit; retain that safeguard.

Build owner/typed-ID indexes once per `Analysis`. For independent edits collect
span changes directly and reconstruct once, preserving untouched bytes, duplicate
keys and sequential semantics for overlapping or mixed edits.

### R6 — P2: reference selection and catalogs repeat expensive work

[`reference.copy_objects`](../cli/hammerplusplus/reference.py#L330) uses list
membership/deep dataclass equality while growing linked selections and removes
contained selections with nested scans. Cyclic entity links terminate because
already-selected entities are not appended again, but large selections can still
perform quadratic work. Use identity/typed-ID sets alongside ordered lists.

FGD parsing/base merging and filesystem/VPK indexing repeat per catalog query.
Cache with explicit invalidation for include files, ordered addon FGDs, VPKs and
gameinfo mounts. Reference spatial bounds use plane-point extrema; they are not
a proof of arbitrary sloped brush extent. Resolve ambiguous selections using
source/editor evidence, as the skill requires.

### R7 — P2: packaging and downloads can duplicate large payloads in memory

[`delivery.py`](../cli/hammerplusplus/delivery.py) holds whole BSP/pak/archive
buffers and dependency contents; `package_map()` retains BSP/NAV bytes plus ZIP
buffers and verification reads. Native setup downloads use `response.read()` and
then re-read cached archives for hashing. Existing file limits do not bound the
combined peak memory of all copies.

Stream downloads and ZIP members through confined temporary files with incremental
hashes, exclusive publication and readback verification. Preserve the existing
PAK-only BSP update: a generic BSP round-trip can change absolute game-lump offsets.

### R8 — P2: native request discovery grows with session history

The broker scans/sorts all `request-*.json` files on every wake and skips those
with responses. A long-lived session therefore revisits completed requests. Keep
pending/completed queues or an index while retaining addressable evidence.
Private runtime preparation also walks/copies a tool tree per session; a carefully
versioned immutable cache could reduce repeated startup work.

Static positives: idle IPC waits on Windows events, the editor has an idle CPU
cap, immutable runtime files are hardlinked where possible, and viewport capture
uses a bounded disposable worker. Actual startup, GPU readback, memory/CPU and
cleanup behavior still require the opt-in Windows lane.

## Dead code and circularity

Ruff's F checks identified six unused imports, all removed. Vulture at 80%
confidence identified four obsolete GUI arguments; review of the same private
signature identified three more obsolete input arguments, also removed. Both
checks now pass on `cli` and `scripts`.

An AST import-graph scan found no top-level eager import cycles. Including deferred
imports produces one coupled group: backend, catalog, delivery, desktop,
native_session, render_capture, timeline, windows and workspace. These are lazy
integration dependencies, not evidence of infinite function recursion. Preserve
the deferred boundaries when refactoring or separate shared primitives first.

Recursive parsing/traversal, menu traversal and the CLI REPL are intentional;
parser/menu depth guards and task-group cancellation bound the relevant paths.
No unintended infinite call cycle was confirmed. Dynamic dispatch/native callbacks
prevent a static tool from proving that every definition is reachable. In
particular, `desktop.editor_action` is reached through dispatch; the legacy
workspace log reader/writer supports pre-timeline artifacts and should not be
deleted solely because new requests use SQLite.

## Validation and limits

- Baseline: 140 tests, passing with three skips.
- Revised: 147 tests, passing with the same three skips, including actual stdio
  MCP transport, every advertised tool's portable/fixture contract, rejected
  requests, concurrent metadata calls and real subprocess-crash recovery tests.
- Seven new regression tests cover checkpoint artifact scopes, four installer
  rollback/interruption cases, oversized validation errors and late compiler log
  failures. Each reproduced the old defect before the corresponding fix.
- `pip check`, compileall, Black 26.3.1, Ruff F checks, Vulture at 80% confidence,
  `git diff --check` and the installed CLI demo pass.
- Tested here on Linux/Python 3.12.14, MCP 1.29.0 and srctools 2.7.0. CI's Windows
  and Python 3.11/3.13 combinations were not run locally.
- Skips: Windows extended-path behavior and two opt-in actual native toolchain
  scenarios. Compiler/native fixtures test contracts, not real Hammer++, Source
  compilation, rendering, GOKZ physics or gameplay. No such native claim is made.
- This sandbox required its supported network-enabled execution mode for asyncio
  stdio tests/formatter operation. Restricted-mode hangs were environment failures;
  the completed test results above are from the working mode.

Reproduce portable validation with the README/CI commands and installed CLI on
PATH. For dead-code checks, additionally install the development-only `ruff` and
`vulture` tools and run `ruff check cli scripts --select F` and
`vulture cli scripts --min-confidence 80`; they are not new runtime dependencies.

Priority for the next iteration: resolve the case-sensitive journal migration,
add bounded result modes, then profile long-history reconstruction and large-map
edits/catalogs before changing durability or native session behavior.
