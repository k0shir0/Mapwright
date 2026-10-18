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

## Results, 2026-10-18

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

The actual backend verification script exited 1: vbsp is missing. No BSP
compilation, editor launch, editor capture or in-game playability is verified.
Mocked compiler tests above check failure handling and staging only.
Cross-platform CI is configured separately and was pending at this local run.

## GitHub Actions

The [first published CI run](https://github.com/k0shir0/hammerplusplus-agent/actions/runs/39155488502)
passed on Windows and Ubuntu with Python 3.11 and 3.13 at commit `399870b`.
CI reported deprecated Node 20 action runtimes. The workflow was updated to
the verified official checkout v7.0.1 and setup-python v7.0.0 commits, both
using Node 24; the follow-up run is attached to PR #1.
