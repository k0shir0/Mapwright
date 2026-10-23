---
name: mapwright-setup
description: Check/provision missing Python, legacy CS:GO SDK/runtime and Hammer++; use existing installers for local Mapwright MCP and skills, preserving existing settings.
compatibility: Python 3.11+ and a retained Mapwright checkout. Native readiness requires Windows with a logged-in graphics session and owned legacy CS:GO content.
---

# Set up Mapwright

Use the existing `setup_agent.py` and `setup_local.py` infrastructure. The agent
handles discovery, missing prerequisites, decisions and verification; do not
write another setup script or replace the installers with manual configuration.
Scoped setup is authorized; inspecting its concrete preview does not require
another user confirmation. Read
[machine prerequisites](../../docs/setup.md#fresh-machine-prerequisites).

Preserve existing settings, Steam installations/branches, launchers, shortcuts
and editor installs on every machine. Native sources are read-only; new tools
and generated Hammer settings belong in a fresh workspace-local installation.
Writes are limited to the checkout's Mapwright `.venv`/local setup artifacts,
the selected workspace's local tools/config/assets/verification artifacts, and
the requested client's MCP entry/managed skills. Inspect these locations first;
reuse valid settings unchanged. If setup would replace existing settings or
unknown files, use a fresh workspace/checkout or distinct `--name` instead.
Preserve malformed/stale files; backups alone do not authorize overwriting them.

1. Locate the checkout and writable workspace. An installed skill's adjacent
   `installation.json` records `checkout`, `workspace`, `setup_script` and command.
   Validate those paths with the [resolver](../mapwright/scripts/resolve_installation.py);
   stale paths require setup from the current checkout. All `scripts/` commands
   below are relative to that checkout, not the map workspace or skill directory.
   Entrypoint: [setup_agent.py](../../scripts/setup_agent.py); inspect `--help` once.
   Resolve/reuse Python 3.11+ with working `venv`/`pip` (64-bit on Windows);
   provision missing Python per [this guide](../../docs/setup.md#python-provisioning).
   With `uv`, `uv run --no-project --python 3.13 scripts/setup_agent.py` runs
   the same installer even without Python; append the same setup flags below.
   Installation is agent work; report concrete policy/elevation/package blockers.
   Recreate environments, local config, registration, skills and receipts after
   moving a checkout; keep machine paths/generated files out of Git.
2. Select the named/current client, default project scope; Hermes requires
   `--scope user` for its active profile. `--home PATH` isolates a profile;
   `--client auto` is appropriate only for requested detected-client setup.
   Run without `--yes`; inspect resolved `--client`, `--workspace`, scope,
   native disposition and file list against the allowed writes above. Check
   native prerequisites in step 3 before applying any native install, then
   rerun the acceptable plan with `--yes`. Setup installs editable extras in
   an isolated checkout venv, repairs package inheritance, runs `pip check`,
   registers stdio MCP and bundles both skills and their linked task guides.
   Inspect failures; ordinary mapping needs no activation,
   global packages, Node or REA.
3. Follow the [native prerequisite checks](../../docs/setup.md#native-prerequisite-checks).
   Check existing config/receipts first, then discover owned Hammer/SDK/runtime
   locations read-only. Automatic discovery is limited; an `offline` result is
   a reason to investigate, not proof that nothing is installed. If no SDK or
   Hammer exists, provision only the missing prerequisite as described there.
   Use a verified `--runtime PATH` with the existing installer to obtain isolated
   Hammer++/compilers/FGDs; a separate SDK is unnecessary when runtime/content
   already satisfy the checklist. Preserve working/partial installs; never
   substitute CS2 or change an existing Steam branch. Missing entitlement,
   authentication or Windows session must be reported with the exact blocker;
   complete portable VMF/MCP setup with `--native off` meanwhile, using a fresh
   workspace if existing native config is broken. Requested native readiness
   stays incomplete until `--native required` and real checks pass.
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
