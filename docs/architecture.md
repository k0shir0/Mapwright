# Hammer++ agent bridge

Target: legacy CS:GO, Source 1 VMF and VBSP. The official Hammer++ CS:GO
build is frozen at 8864. CS2 VMAP and Source 2 tools are incompatible.

## Approach

Apply CLI-Anything's harness workflow: inspect the real backend and document
its data model, expose discoverable JSON commands, edit native project files,
then invoke the actual editor and Valve compilers for backend verification.
The Python core uses the standard library. The optional MCP transport uses
the official Python MCP SDK. The CLI and MCP call the same project methods.

VMF is the reliable map authoring interface. A source-span KeyValues parser
keeps duplicate keys, comments, unknown Hammer++ blocks and unedited bytes.
Transactions validate all operations before publishing, require the current
SHA-256, keep snapshots and acquire a project lock. Undo refuses external edits.
Agents edit a workspace copy, then open that copy in Hammer++ for inspection.
There is no claim of a documented live Hammer++ RPC protocol.

REA is a separate, optional local interoperability investigation tool. Use its
readiness report before selecting a provider. Native analysis needs a working
Ghidra, IDA or Hopper provider. Native Windows process capture is unsupported
upstream. Keep binaries and detailed REA output in ignored `.local/` storage.
Do not patch/inject DLLs, attach to a running game, or invent editor commands.

## Boundaries

- VMF editing: brushes, rooms, point/brush entities, keyvalues, outputs,
  translation, deletion, inspection, structural validation, history and undo.
- Build: explicit configured Source 1 VBSP/VVIS/VRAD paths, bounded subprocesses,
  staged outputs, logs, leak diagnostics and BSP header checks.
- Editor: explicit executable, game directory and VMF path; actual launch and
  Windows editor-window capture. No implicit reloading of unsaved work.
- Agent access: local stdio MCP, workspace-confined map paths and the same CLI.

## Sources

- [CLI-Anything harness](https://github.com/HKUDS/CLI-Anything/blob/main/cli-anything-plugin/HARNESS.md)
- [REA CLI](https://github.com/morluto/rea/blob/main/docs/cli.md)
- [REA Windows capture limitation](https://github.com/morluto/rea/blob/main/docs/process-capture.md)
- [Hammer++ official downloads](https://ficool2.github.io/HammerPlusPlus-Website/download.html)
- [Valve VMF specification](https://developer.valvesoftware.com/wiki/VMF_(Valve_Map_Format))
- [Official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
