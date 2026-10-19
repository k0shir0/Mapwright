# Research implementation follow-up

Input: the owner's complete 936-line `.local/research/research.md`, dated
2026-10-18. All sections were reviewed, including the error and edge-case
catalogs. It describes an earlier dirty tree, so its line numbers, tool counts,
untracked-file labels and missing-SDK claims are historical snapshots.
Current behavior comes from `schema`, `--help`, tests and native receipts.

## Requested capabilities

| Research item | Current disposition |
| --- | --- |
| 5.1 workspace operation log | Bounded cross-process JSONL, timestamps/session/call IDs, success/failure and revision metadata; paginated tool/CLI access |
| 5.2 recovery across files/folders | Explicit named checkpoints for arbitrary workspace files/folders, reverse checkpoints, interruption receipts/resume, revision/hash refusal, discoverable trash/snapshots |
| F1 CLI parity | `editor-action`, `copy-reference-objects`, spatial search flags, KZ/log/recovery commands |
| F2 edit schema | Eight flat `map_*` tools and CLI commands; existing atomic edit batch retained |
| F3 progress | MCP progress heartbeats during compile, import and checkpoint calls when the client supplies a progress token |
| F4 check semantics | Completed validation/audit returns `ok:true`, findings under `data`; invalid CLI checks still exit 1; exceptions remain tool errors |
| F5 resources | Read-only guide, log/index resources and artifact template; history reads no longer acquire the write lock or rewrite journals |
| F6 annotations/output | Shared result output schema; read/idempotent/destructive/open-world metadata reflect each operation |
| F7 CI | Compileall, pinned Black check and Windows desktop import smoke added alongside installed CLI/MCP tests |
| F8 workflow prompt | `kz_mapping_workflow` with path/task arguments, also available through the packaged mapping skill |
| K1 audit | Main/bonus names/classes, flags, course starts/angles, version, trigger geometry/client flags, overlapping starts |
| K2 anti-bhop | Box thickness/time, destination inclusion and measured floor clearance |
| K3 bhop | Types/delays, shared-destination review, explicit ordered route geometry/gaps and potential reset ground; trajectories remain in-game work |
| K4 jumps | Box/top-side edge gaps/delta-z, alignment, jumpstat thresholds, configurable MBH minimum and practice suggestions |
| K5 headhitters | Whole-map bounded box scan or selected corridor; standing/crouch and derived jump thresholds |
| K6 ladders | Material/owner, normals/dimensions, optional landing height; actual LAJ offset remains in-game measurement |
| K7 water | Level rectangular brush, top-only water/nodraw, owner, skyname and LOD advisory |
| K8 teleports | Destination resolution, speed/angles summary, relative/reorient caveat |
| K9 spawns | Team presence/parity, angles, box hull collisions, ceilings and start-zone overlap |
| K10 test plan | Current-revision findings, supported tester commands, intended-mode server recipe; sandbox cvars clearly distinguished |
| KZ authoring enablement | `kz-room`, per-face box materials, ordered multi-FGD catalog, pinned official GOKZ FGD and complete merged editor definitions |

## Other findings

- A/B discoverability: root AGENTS entry point, KZ contract and recovery docs,
  client guide renamed to avoid accidental AGENTS loading on Windows, explicit
  replacement-source and native-GUI limits, full command help and MCP guidance.
- C environment: doctor includes every FGD path/readiness; a missing config
  still permits offline authoring. Config paths remain workspace-relative or
  explicit tool paths. No automatic client configuration changes are made.
- D state/behavior: inspectable artifacts and lock owner/liveness, source
  snapshots, abandoned redo branches, prepared deletion/import receipts,
  explicit targetname mapping and asset-mount boundaries. Authored coordinates
  use +/-16384 compile bounds. Native UI failures and corrupt ZIPs are handled.
- E evidence: existing reference/native boundary tests retained, new KZ,
  checkpoint, schema and actual MCP discovery/error tests added. Native setup,
  compilation and viewport evidence is reported separately in verification.md.
- Sections 6-12 remain reference evidence rather than implementation orders:
  historical tables/error messages are not copied into live help. Unverified
  SDK availability, prefab ZIP contents and arbitrary editor features remain
  unclaimed. GOKZ primary Mapping API and FGD were refreshed for this change.

## Deliberate limits

Geometry analysis is exact for axis-aligned six-face boxes, reports unsupported
geometry, and never simulates movement. Agent access to arbitrary native VMF
features and editor controls remains available, without a guarantee that every
command or in-game feature has been tested. File restoration cannot undo
unsaved GUI state, is recoverable rather than multi-file atomic, and refuses
external changes. Renames retain separate per-path journals. Checkpoint and
snapshot garbage collection is manual; automatic deletion would erase recovery
evidence. Reference asset mounts and destination edits remain separate and
should be checkpointed together. Client hard timeouts still require appropriate
configuration; progress notifications alone cannot extend every client timeout.
