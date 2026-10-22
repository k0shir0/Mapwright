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

## Follow-up implementation

The portable follow-up resolves the journal collision and implements the concrete
scaling changes below. The original P2 recommendations included optional larger
redesigns; those are distinguished from the fixes and measurements here.

| Item | Implemented behavior | Evidence and limits |
| --- | --- | --- |
| R1: journal identity | Versioned exact-spelling keys use filesystem resolution and actual aliases. Migrate recorded owners or unique path/revision matches; retain ambiguous journals with a diagnostic. Keep original entries and resumable migration markers. Every new undo/redo state records its path. | Case-distinct edits, independent undo/redo, timeline checkout, alias handling, fieldless/explicit legacy ownership, interruptions on both sides of publication and external-edit refusal. Case-sensitive tests skip when the filesystem aliases the names. |
| R2: response context | Source/artifact transport defaults are 8,000 units; history is paged with a history-revision guard. Oversized results become explicit bounded summaries linked to immutable, checksummed, byte-pageable full evidence. `response_mode=full` preserves access to original result shapes. | Real installed CLI and stdio MCP verify equivalent text/structured results and reconstruct all evidence. Preserve `valid`, `complete`, unsupported counts, revisions, warnings/errors and recovery IDs. A summary does not make source complete. Direct Python `Project.source()` keeps its previous default for compatibility. |
| R3: durable I/O | Validate after recording an attempt and before tracking saved files. Reuse one request-local SQLite connection, preserve nested transaction boundaries and FULL synchronization, and batch exported-event bookkeeping. Filter selected paths inside version reconstruction as well as final output. | Existing crash/concurrency and future-history tests pass. Invalid requests retain addressable failed receipts without snapshots. A 100-file restore still commits 207 durable transactions; no durability tradeoff or automatic blob expiry. |
| R4: repeated paging work | Content-hash-keyed decoded text, parsed object/typed-ID indexes and complete reference-search results use bounded process-local LRUs. Every read checks actual bytes, including same-size/same-mtime external edits. | Entire page sequences reuse parsing/search work. Accounted cache budgets are 8 MiB decoded, 32 MiB views, 8 MiB searches, 16 MiB FGD; each also has a 32-entry cap. Oversized entries bypass caching. Source hashing and exact directory/artifact enumeration still perform I/O; no claim that pagination eliminates those costs. |
| R5: edit/KZ loops | Collect independent translation spans and reconstruct once. Ordered nonoverlapping replacements use one join; overlapping/mixed edits keep historical sequential behavior. Analysis builds owner-volume and typed object/solid/side indexes once. | Batched output matches a sequential source oracle, including unknown blocks/duplicate keys. Existing geometry, encoding, hidden/unsupported and KZ checks pass. Preserve output order, typed namespaces and the 1,000-box whole-map headhitter guard. |
| R6: references/catalogs | Use identity sets plus ordered linked selections and a source-span sweep to eliminate contained selections, including parents discovered through links. Cache merged FGDs by ordered configuration and checksums of every recursively parsed include. | Cycles, linked parents, typed IDs, GOKZ names, face remapping, external-reference warnings, conflicts and dry runs have regression coverage. Content changes, deleted includes and reordered/configured FGDs invalidate reuse. Asset filesystem/VPK discovery remains fresh; no stale mount cache was introduced. |
| R7: streams | Hash downloads incrementally and validate before exclusive cache publication. Stream BSP/NAV archive members, readback and final hashing through temporary files; publish only verified packages. Append only the PAK lump via streamed copy and patch its header entry. BSP/NAV receipt hashing is incremental. | Corrupt/interrupted streams and changed/existing outputs leave no partial publication. Existing PAK-only byte/offset and dependency regressions pass. Synthetic package peak Python memory is measured below. srctools dependency analysis/PAK internals can still retain asset data; no constant-memory claim for native packing. |
| R8: native queue | New brokers advertise a pending directory; completed requests move to the addressable receipt directory after response publication. Discovery recovers the response/archive interruption gap without replaying a completed mutation. New clients retain the root-queue protocol for existing old brokers. Expiry/secret guards remain; a released completion event no longer ends the broker. | Portable tests cover discovery, archival, expiry and session ownership guards. Actual event/PID/desktop/editor behavior still needs the opt-in Windows lane. Immutable runtime caching remains a separate, unmeasured proposal; private mutable settings and existing idle/capture safeguards remain. |

### Portable measurements

Compared against the initial implementation commit `bccc52b` in this PR, using
Linux/Python 3.12.14, MCP 1.30.0 and srctools 2.7.0. These are controlled synthetic
workloads on this host, not native-editor or production latency guarantees.

| Workload | Initial PR implementation | Follow-up |
| --- | ---: | ---: |
| Restore 100 six-byte files: SQLite connections | 521 | 1 |
| Same restore: durable COMMIT statements | 207 | 207 |
| Translate 500 independent entities: median of 3 | 727.410 ms | 20.742 ms |
| Inspect 501 objects, all 26 pages: median of 3 | 298.095 ms | 36.656 ms |
| Parses per complete inspect sequence | 26 | 1 |
| Copy 500 cyclic linked entities, dry run: median of 3 | 85.658 ms | 62.912 ms |
| Selected path from 100,000 versions: median of 3 | 165.905 ms | 3.615 ms |
| Inspect world with 200,000-character property: compact result bytes | 400,512 | 829 plus full-evidence artifact |
| Package two 24 MiB files: peak traced Python allocations | 106,434,911 bytes | 3,289,172 bytes |

Translation hashes, copied destination revisions and selected-path results match
across both implementations. Package readback verifies exact members/hashes. Package
wall time in this single memory probe was 304 ms before and 355 ms after: the goal
was bounded memory and verified publication, not a packaging speedup. The single
restore sample was 225 ms before and 164 ms after; connection/commit counts are the
reliable structural evidence, not a wall-time guarantee. `tracemalloc` measures
Python allocations during packaging, excluding precreated inputs and native RSS.

Reproduce with the installed environment:

```sh
python scripts/benchmark_portable.py
python scripts/benchmark_portable.py --source /path/to/checkout-at-bccc52b
```

The script creates isolated temporary workspaces and fixtures, includes entire
page sequences, retains three timing samples per loop workload and prints hashes,
counts and memory evidence. It does not exercise Hammer++, compilation or rendering.

The explicit compatibility switch and pagination guards increase compact 58-tool
advertisement JSON from 51,498 to 60,948 bytes (same SDK-object method described
above). This is a measured tradeoff for discoverable result semantics. Tool profiles
or client-side tool search remain an optional separate redesign. Skill measurements
above describe the initial review; the mapping skill now also documents bounded
result evidence and source pagination guards.

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

The initial review ran 147 tests (144 passed, three skipped). The follow-up ran
166 tests: 163 passed and three skipped on Linux/Python 3.12.14. The installed CLI,
real stdio MCP, crash/concurrency regressions, dependency validation, compileall,
pinned Black, Ruff F checks, Vulture at 80% confidence, installed demo and whitespace
checks pass. See the PR for the GitHub Linux/Windows matrix results.

Linux tests cannot establish real Hammer++, compiler, GPU, GOKZ movement or replay
behavior. The Windows extended-path check and two opt-in actual native scenarios
require their corresponding environments. Native fixtures establish contracts only.
Use a logged-in Windows session with an owned legacy CS:GO runtime/content,
WinSta0/private-desktop access and a verified renderer DLL profile before claiming
native readiness. Follow [setup](setup.md), [recovery](recovery.md) and the
[verification scope](kz-mapping.md#verification-scope); configure
`MAPWRIGHT_NATIVE_E2E_CONFIG` for the real native MCP tests and run the relevant
`scripts/verify_native_session.py`, `scripts/verify_kz.py` and
`scripts/verify_backend.py` with the actual workspace. Inspect captures and saved
receipts, check save/reopen and cleanup, and close owned sessions.

Further optional work remains: client tool search/profiles, indexed artifact/file
listing, persistent/reference-aware storage maintenance, spatial acceleration for
remaining nested geometry checks, mount-aware asset catalog caching and immutable
native-runtime caching. These need separate measurements and invalidation/recovery
designs; this change does not silently delete retained evidence or weaken checksums.
