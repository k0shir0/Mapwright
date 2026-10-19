# Verification plan

Write this plan before test implementation, following CLI-Anything's harness.

## Core tests

Use stdlib unittest. Approximately 20 focused checks for native VMF round trips,
unknown data/comments, duplicate outputs, plane winding and IDs, atomic batches,
revision conflicts, snapshots/undo, path escapes, lock conflicts, malformed
requests and compile error handling. Use srctools as an independent VMF oracle
when installed; it is the optional source extra, not the editing backend.

## Workflow tests

Invoke the installed CLI from outside the repo. Create a sealed CS:GO room,
add team spawns and a light, move a brush, inspect and validate, undo/redo,
verify no mutation after a stale revision or failed operation.

Use an actual MCP SDK stdio client to initialize, list tools, inspect/create/
edit a map and exercise errors. Verify no protocol noise on stdout.

The opt-in `scripts/verify_backend.py` must invoke configured real compilers
and verify a fresh VBSP output. Missing compilers fail that check; core tests
cannot establish compilation or runtime playability. Open a generated VMF
in the actual Hammer++ editor and capture its window where dependencies allow.

Record actual results and unresolved backend requirements below after checks.

## Initial results, 2026-10-18, before toolchain installation

Historical results below are superseded by the follow-up verification section.

Windows, Python 3.11.9, MCP SDK 1.26.0, srctools 2.7.0.
Installed commands were required through CLI_ANYTHING_FORCE_INSTALLED=1.
The suite ran outside the filesystem sandbox because its Windows temporary
directory restrictions blocked normal file resolution and atomic renames.

```text
test_leak_stops_later_stages_even_with_zero_exit (test_backend.BackendTests.test_leak_stops_later_stages_even_with_zero_exit) ... ok
test_stage_arguments_and_receipt_use_fresh_build (test_backend.BackendTests.test_stage_arguments_and_receipt_use_fresh_build) ... ok
test_timeout_kills_and_reaps_compiler (test_backend.BackendTests.test_timeout_kills_and_reaps_compiler) ... ok
test_zero_exit_without_fresh_bsp_fails (test_backend.BackendTests.test_zero_exit_without_fresh_bsp_fails) ... ok
test_actual_mcp_sdk_stdio_session (test_cli_mcp.CLITests.test_actual_mcp_sdk_stdio_session) ... ok
test_complete_editing_workflow_and_stale_revision (test_cli_mcp.CLITests.test_complete_editing_workflow_and_stale_revision) ... ok
test_help_schema_errors_and_missing_backend (test_cli_mcp.CLITests.test_help_schema_errors_and_missing_backend) ... ok
test_installed_command_outside_repo (test_cli_mcp.CLITests.test_installed_command_outside_repo) ... ok
test_bsp_header_rejects_empty_and_wrong_version (test_core.FormatTests.test_bsp_header_rejects_empty_and_wrong_version) ... ok
test_invalid_geometry_and_mutation (test_core.FormatTests.test_invalid_geometry_and_mutation) ... ok
test_parser_rejects_malformed_input (test_core.FormatTests.test_parser_rejects_malformed_input) ... ok
test_validator_detects_duplicate_ids_and_bad_planes (test_core.FormatTests.test_validator_detects_duplicate_ids_and_bad_planes) ... ok
test_batch_is_atomic_on_late_failure (test_core.ProjectTests.test_batch_is_atomic_on_late_failure) ... ok
test_catalog_fgd_inheritance_and_vpk (test_core.ProjectTests.test_catalog_fgd_inheritance_and_vpk) ... ok
test_entity_origin_bounds_for_creation_and_property_edits (test_core.ProjectTests.test_entity_origin_bounds_for_creation_and_property_edits) ... ok
test_external_edit_cannot_be_overwritten_by_undo (test_core.ProjectTests.test_external_edit_cannot_be_overwritten_by_undo) ... ok
test_failed_map_publication_retains_original (test_core.ProjectTests.test_failed_map_publication_retains_original) ... ok
test_imported_vmf_namespaces_and_qualified_selectors (test_core.ProjectTests.test_imported_vmf_namespaces_and_qualified_selectors) ... ok
test_missing_backend_fails_without_fake_artifacts (test_core.ProjectTests.test_missing_backend_fails_without_fake_artifacts) ... ok
test_paths_locks_and_overwrite (test_core.ProjectTests.test_paths_locks_and_overwrite) ... ok
test_pending_journal_recovers_after_map_published (test_core.ProjectTests.test_pending_journal_recovers_after_map_published) ... ok
test_pending_journal_recovers_before_map_published (test_core.ProjectTests.test_pending_journal_recovers_before_map_published) ... ok
test_precise_geometry_and_zero_translation (test_core.ProjectTests.test_precise_geometry_and_zero_translation) ... ok
test_room_and_independent_geometry_oracle (test_core.ProjectTests.test_room_and_independent_geometry_oracle) ... ok
test_schema_validation_at_shared_boundary (test_core.ProjectTests.test_schema_validation_at_shared_boundary) ... ok
test_stale_revision_and_dry_run (test_core.ProjectTests.test_stale_revision_and_dry_run) ... ok
test_symlink_escape (test_core.ProjectTests.test_symlink_escape) ... ok
test_targeted_edits_preserve_unknown_comments_and_encoding (test_core.ProjectTests.test_targeted_edits_preserve_unknown_comments_and_encoding) ... ok
test_translation_moves_planes_origin_and_texture_lock (test_core.ProjectTests.test_translation_moves_planes_origin_and_texture_lock) ... ok
test_translation_preserves_unknown_extension_fields (test_core.ProjectTests.test_translation_preserves_unknown_extension_fields) ... ok
test_undo_redo_and_new_branch (test_core.ProjectTests.test_undo_redo_and_new_branch) ... ok
test_unique_ids_duplicate_outputs_and_brush_entity (test_core.ProjectTests.test_unique_ids_duplicate_outputs_and_brush_entity) ... ok

----------------------------------------------------------------------
Ran 32 tests in 19.957s

OK
```

32 tests passed, zero skipped, 19.957 seconds. The Windows junction test
verified path escape rejection without requiring symbolic-link privileges.

Additional completed checks: Python compileall, Black format check, bundled
skill validation, installed-CLI demo from outside the checkout, actual REA
PE resource inspection through the bridge, and material lookup against the
installed CS:GO pak01_dir.vpk (two matching development materials).

At the initial 32-test run, the backend script failed because VBSP was missing.
That historical limitation was resolved by the actual toolchain follow-up
below. In-game playability remains unverified. Mocked compiler tests check
failure handling and staging, separately from actual native verification.

## GitHub Actions

The [first published CI run](https://github.com/k0shir0/Mapwright/actions/runs/39155488502)
passed on Windows and Ubuntu with Python 3.11 and 3.13 at commit `399870b`.
CI reported deprecated Node 20 action runtimes. The workflow was updated to
the verified official checkout v7.0.1 and setup-python v7.0.0 commits, both
using Node 24; the follow-up run is attached to PR #1.

## Reference and editor follow-up, 2026-10-18

50 tests passed, zero skipped, in 24.203 seconds on Windows/Python 3.11.9.
The installed CLI was required. The actual MCP stdio test now includes
reference import/search/copy and recoverable file deletion/restoration.
Regressions cover raw source editing/undo, stale source revisions, linked
entity names and repeated outputs, FGD-typed entity input parameters,
GOKZ protocol names/teleport destinations, all pinned CS:GO sidelist entities,
displacement start translation, safe embedded asset extraction, collision
refusal before map/config mutation, and native error normalization.

Actual integration work is separate from mocked compiler unit tests:
`scripts/setup_local.py` installed the isolated toolchain; actual MCP calls
decompiled an installed KZ BSP, copied two tile brushes into a room, and invoked
VBSP++/VVIS++/VRAD++ to create a fresh version-21 HDR BSP. Hammer++ visibly
rendered the copied item, independently reported 8 solids/3 point entities/48
faces, saved a separate VMF through its native dialog, and reopened it. The
saved file validated with the expected counts. Mounted VPK and complete FGD
catalog calls succeeded. See [verification.md](../docs/verification.md) for
local evidence locations and reproduction commands.

## KZ research implementation

69 tests passed, zero skipped, in 42.439 seconds on Windows/Python 3.11.9
with `CLI_ANYTHING_FORCE_INSTALLED=1`. New behavior checks cover GOKZ contract
typos/pairs/flags, anti-bhop thickness/clearance/delay, teleport types/options,
box/top-face measurement, plane-point versus vertex bounds, water/ladder and
headroom rules, unsupported geometry, compiled coordinate bounds and finite
JSON inputs. Workspace tests cover cross-map success/failure logs and source
redaction, folder restoration, stale revisions, reverse checkpoints, checksum
failure and interrupted-batch resume with external-edit refusal.

Actual MCP sessions verify resources/templates/prompts, output schemas,
annotations, progress callbacks and successful check calls with invalid
findings. The setup merge regression preserves original FGD fields/comments
when stock base names are absent. Black, compileall and skill validation ran.
The actual KZ MCP/compiler/BSP-entity lane is recorded in
[verification.md](../docs/verification.md); it does not certify gameplay.
