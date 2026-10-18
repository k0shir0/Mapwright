# Independent review

Two Codex reviewers used GPT-6.1 SOL with xhigh reasoning, reviewing against
the new repository's original default branch and `docs/requirements.md`.
They made no product edits. Findings below were fixed before publication.

## Standards

- P1: Global ID lookup rejected native VMFs with IDs reused between object
  namespaces. Validation now separates entity/world, solid, side and group
  IDs; selectors accept a kind. Imported source is not renumbered.
- P2: Six-digit coordinate formatting rounded geometry and zero translations.
  Numeric formatting now uses round-trip precision for coordinates, texture
  shifts and output delays.
- P2: Translation traversed unknown extension fields named origin/plane/axis.
  It now targets recognized entity origins and solid/side geometry only.

Follow-up review ran independent probes for native IDs, typed side lookup and
precise zero translation. All findings resolved; no remaining concrete issue
found in these fixes. No worthwhile additional code-smell findings.

## Spec

- P1: Native ID namespaces prevented the promised authoring workflow on
  ordinary imported maps. Fixed with typed lookup and namespace validation.
- P2: Coordinate rounding discarded requested fractional moves. Fixed with
  round-trip formatting and an independent srctools geometry regression.
- P2: Entity origins could exceed the coordinate bounds enforced for brushes.
  A shared bounded-position check now covers creation and structural
  validation, including edits made through property updates.

Follow-up review reran the focused in-memory reproductions. All findings
resolved; no further concrete issue found in these fixes. The unavailable
real editor/compiler lane remains explicitly disclosed in the requirements.

Summary: three original findings per axis, including one P1 in each; all
resolved and covered by the parent's successful 32-test suite. Neither
review establishes actual editor rendering or in-game playability.
