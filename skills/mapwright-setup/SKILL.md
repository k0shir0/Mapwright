---
name: mapwright-setup
description: Set up this Mapwright checkout for persistent local MCP and portable mapping skills in Codex, Claude Code, OpenCode, Antigravity, pi, or Hermes. Use for initial installation, client registration, setup repair, and scoped rollback.
---

# Set up Mapwright

When the user asks to set up local Mapwright MCP, complete the setup in the
requested client and scope. Do not hand the user placeholder config or manual
copy/paste steps. Use the setup script to resolve paths and preserve unrelated
settings. The request authorizes the scoped setup; do not add a second
confirmation merely because the script supports preview mode.

Resolve an existing Python 3.11+ interpreter (`python`, `py -3`, or an available
`uv` managed Python) and verify its version. If Windows has none, provision
per-user Python through the installed WinGet client using
`winget install --id Python.Python.3.13 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity`.
Resolve and verify the installed executable before continuing; the current
shell may retain its old PATH. Do not hand off a Python installation step to
the user. If policy or unavailable package infrastructure prevents provisioning,
report that specific failure and retain the usable terminal/offline path.
WinGet's [installation flags](https://learn.microsoft.com/en-us/windows/package-manager/winget/install)
describe silent user-scope installation. Do not reinstall a working interpreter.

1. Locate the checkout containing this skill. In an installed skill, read the
   adjacent `installation.json` for `checkout`, `workspace`, and `setup_script`.
   The repository entrypoint is [setup_agent.py](../../scripts/setup_agent.py).
   Run its `--help` once to inspect available options.
2. Use the client named by the user or the current agent. Default to project
   scope; Hermes uses the active user/profile configuration, so select
   `--scope user` for Hermes. An explicit isolated home uses `--home PATH`.
   Use `--client auto` only when setup for detected clients matches the request.
3. Run the script with the resolved `--client`, `--workspace`, and scope, first
   without `--yes`. Inspect its concrete paths and native-tool disposition,
   then run the same command with `--yes`. This creates/reuses the checkout
   virtual environment, installs editable Python extras, registers stdio MCP,
   and bundles both skills with their guides. No shell activation, Node,
   CLI-Anything, or REA is required for normal mapping.
4. Read the setup receipt and `doctor` results. Native setup reuses an existing
   workspace configuration, then the checkout configuration, then detects owned
   local/Steam legacy CS:GO files. If none exists, VMF/MCP setup still completes;
   report the precise missing runtime. Use `--native required` when native
   readiness is part of the request. Resume with `--runtime PATH` after an
   entitled installation is available; do not substitute CS2 binaries.
5. Verify a real stdio MCP initialize, tools/list, resources/list, and one
   read-only tool call using the registered absolute executable/workspace.
   Use the current client's MCP reload if supported. If this conversation cannot
   reload servers, continue immediately through the installed CLI; the persistent
   registration loads in future client sessions. Do not hand the reload limit
   back to the user as a required setup task.
   Confirm mapping skills are discoverable and every bundled guide resolves.
6. When native readiness is requested and the runtime is present, run the
   checkout's `scripts/verify_native_session.py --run --workspace WORKSPACE`
   and `scripts/verify_kz.py --workspace WORKSPACE` using its virtual environment.
   These exercise a private desktop, actual GPU capture, cleanup and compilation
   without user input. Inspect the receipts and captured image. On failure,
   read the report/native logs, repair the concrete dependency or profile issue,
   and retry; path existence alone does not establish native readiness.

Existing trust, permissions, model settings and unrelated MCP servers remain
client-controlled. Do not weaken them to make a smoke test pass. A working
stdio test establishes server behavior; report separately whether this client
session actually loaded it. Native `doctor` checks paths, not rendering or
gameplay; compile and in-editor/in-game verification need their own evidence.

For repair, rerun setup with the same scope. It is idempotent and backs up
changed files. For removal/recovery, run `--rollback RECEIPT --yes` using the
receipt path from setup. Rollback refuses files edited afterward. Do not
remove the whole agent profile or another checkout's skill directory.
