# Verification plan

Write this plan before test implementation, following CLI-Anything's harness.

## Core tests

Use stdlib unittest. Approximately 20 focused checks for native VMF round trips,
unknown data/comments, duplicate outputs, plane winding and IDs, atomic batches,
revision conflicts, snapshots/undo, path escapes, lock conflicts, malformed
requests and compile error handling. Use srctools as an independent VMF oracle
when installed; it is a verification extra, not the editing backend.

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
