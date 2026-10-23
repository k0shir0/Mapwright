---
name: mapwright-setup
description: Install/repair local Mapwright MCP and skills for Codex, Claude Code, OpenCode, Antigravity, pi or Hermes; scoped rollback.
compatibility: Python 3.11+ and a retained Mapwright checkout. Native readiness requires Windows with a logged-in graphics session and owned legacy CS:GO content.
---

# Set up Mapwright

Complete requested setup with `setup_agent.py`, resolved paths and preserved
unrelated settings. Scoped setup is authorized; inspecting its concrete preview
does not require another user confirmation. Read
[machine prerequisites](../../docs/setup.md#fresh-machine-prerequisites).

1. Locate the checkout and writable workspace. An installed skill's adjacent
   `installation.json` records `checkout`, `workspace`, `setup_script` and command.
   Validate those paths with the [resolver](../mapwright/scripts/resolve_installation.py);
   stale paths require setup from the current checkout. All `scripts/` commands
   below are relative to that checkout, not the map workspace or skill directory.
   Entrypoint: [setup_agent.py](../../scripts/setup_agent.py); inspect `--help` once.
   Resolve/reuse Python 3.11+ with working `venv`/`pip` (64-bit on Windows);
   provision missing Python per [this guide](../../docs/setup.md#python-provisioning).
   Installation is agent work; report concrete policy/elevation/package blockers.
   Recreate environments, local config, registration, skills and receipts after
   moving a checkout; keep machine paths/generated files out of Git.
2. Select the named/current client, default project scope; Hermes requires
   `--scope user` for its active profile. `--home PATH` isolates a profile;
   `--client auto` is appropriate only for requested detected-client setup.
   Preview resolved `--client`, `--workspace`, scope and native disposition, then
   rerun with `--yes`. Setup installs editable extras in an isolated checkout venv,
   repairs package inheritance, runs `pip check`, registers stdio MCP and bundles
   both skills and their linked task guides. Inspect failures; ordinary mapping
   needs no activation, global packages, Node or REA.
3. Inspect receipt/`doctor`. Native discovery prefers workspace config, checkout
   config, then owned local/Steam legacy CS:GO. Missing runtime permits offline
   VMF/MCP: report its limit. Use `--native required` for requested native readiness.
   Resume with `--runtime PATH` when entitled legacy content/stock VPKs exist;
   prepare a fresh native directory before backed-up config replacement. Preserve
   partial installs; never substitute CS2. Inspect `viewport_profile_ready` and
   the supported DLL profile in the native setup guide.
4. Verify actual stdio initialize, tools/list, resources/list and a read-only call
   using the registered absolute executable/workspace. Check skill discovery,
   installation markers and all bundled links, including refreshed copies.
   Use supported client reload; if unavailable here, continue immediately through
   installed CLI (registration loads in future sessions). Distinguish server
   smoke-test success from this client's actual MCP loading.
5. For requested native readiness with a runtime, use the checkout venv to run:
   `scripts/verify_native_session.py --run --workspace WORKSPACE` and
   `scripts/verify_kz.py --workspace WORKSPACE`. Inspect receipts/captured pixels;
   repair concrete failures and retry. `scripts/verify_backend.py --workspace
   WORKSPACE` exercises full fast VBSP/VVIS/VRAD; import its fresh BSP with
   `import-reference` to verify bundled BSPSource Java when copying is needed.
   Native checks require a logged-in Windows WinSta0/D3D9 session. Close owned
   sessions. Paths/doctor alone prove no rendering/gameplay.

Read [runtime troubleshooting](../../docs/setup.md#runtime-test-troubleshooting)
for separate client/server checks; setup does not install custom assets/GOKZ in
the game. Log native failures with artifacts/environment/limits in the
[problem log](../../docs/recovery.md#problem-log). Preserve client trust,
permissions, model settings and unrelated servers.

Repair: rerun the same scope (idempotent, backed up). Remove/restore:
`--rollback RECEIPT --yes`; interrupted rollback resumes from the same receipt
and refuses later edits. Never delete an entire profile or another checkout's skills.
