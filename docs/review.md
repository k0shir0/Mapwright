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

## Reference-map follow-up review

The same independent GPT-6.1 SOL/xhigh reviewers examined changes since
`42e432a`, including the installer and updated requirements.

Standards: fixed embedded asset precedence/conflicts by comparing hashes
against all mounted providers before publishing, prepending safe mounts, and
checking the gameinfo snapshot under lock. Fixed omitted CS:GO sidelist fields,
including info_no_dynamic_shadow.sides and info_overlay_transition.sides2,
while preserving unrelated numeric sides properties. The reviewer independently
probed all face classes and confirmed the final snapshot ordering.

Spec: fixed entity-valued output parameters and their dependency closure,
including FGD-defined inputs, and normalized native PID/handle failures into
the shared JSON error contract. A second probe caught source-FGD lookup after
target renaming; the type is now captured before rewriting. The reviewer
confirmed both fixes. Also preserved documented GOKZ protocol names and
teleport links, with regressions.

No remaining concrete finding in the reviewed fixes. The parent ran the
50-test suite and actual editor/compiler verification separately.
