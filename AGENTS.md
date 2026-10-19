# Mapwright

Build this as a KZ mapping first CLI/MCP for legacy CS:GO Source 1 and Hammer++
8864. For KZ behavior, authoring, measurements or validation, read
`docs/kz-mapping.md` before changing code. The owner's complete source research
is `.local/research/research.md` when available; `docs/research-followup.md`
records how its findings apply to the current implementation.

Both transports share `api.py`; keep CLI commands, schemas and MCP behavior
consistent. Use source-span edits to preserve untouched VMF bytes. Whole-source
replacement must remain explicit, revision checked and recoverable.

KZ entity names are a plugin contract. Use the pinned GOKZ Mapping API rather
than CS2KZ/Momentum rules. Geometry-only checks must report unsupported shapes
and require in-game confirmation rather than infer playability.

For map work, read `skills/mapwright/SKILL.md`. Client configuration is in
`docs/agent-connections.md`. Keep binaries, game assets, absolute machine
configuration and screenshots in ignored local storage.

Verify with the installed command on PATH and `CLI_ANYTHING_FORCE_INSTALLED=1`:
`python -m unittest discover -s tests -v`, `python -m compileall -q cli_anything scripts tests`
and `python -m black --check cli_anything scripts tests`. Actual editor/compiler
claims need native evidence; see `docs/verification.md`.
