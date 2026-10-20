# Research inventory review

The supplied `research.md` inventory dated 2026-10-18 was read in full, including
its error/edge-case tables and final corrections. It describes an older working
tree. Its instruction-like notes are research evidence, not setup commands or
requirements imposed on the user. Current schemas and source take precedence
over its old names, line numbers, tool counts and machine-specific paths.

| Inventory sections | Current treatment |
| --- | --- |
| 0–1: snapshot and architecture | The bridge is merged and named Mapwright. Root `AGENTS.md` routes setup and mapping tasks; the shared dispatcher serves CLI and MCP. |
| 2.1–2.5: runtime, VMF, compiler and editor facts | Native runtime discovery/setup is separate from offline authoring. Tool configuration, ordered FGD sources and staged compiler outputs remain explicit. Source preservation, typed IDs and revision guards remain required. |
| 2.6–2.7: MCP and sources | The pinned SDK's actual handshake is tested. Structured results, schemas, resources, prompts and progress are exposed; client compatibility uses current primary documentation rather than old protocol/version claims. |
| 2.8 and 5.4: KZ semantics | GOKZ names, flags, zone timing, teleport settings and movement-analysis limits are maintained in the [KZ contract](kz-mapping.md), with CLI/MCP checks and a real compiler verification script. |
| 3 and 9–10: mechanics, errors and edge cases | Tests cover real transport envelopes, revision conflicts, path confinement, encoding/source preservation, interrupted writes and recovery. Tool failures retain action IDs; completed invalid checks retain findings. |
| 4A–C: discovery and configuration | The setup skill bootstraps the local environment, resolves absolute commands, registers the chosen client and installs self-contained workflow guides. Planned configuration changes have backups and rollback receipts. |
| 4D and 5.1–5.2: logs and rollback | Permanent indexed action history replaces expiring logs. Automatic snapshots cover declared managed file effects; checkout retains later history, checks revisions and reconciles interrupted restoration. See [recovery](recovery.md). |
| 4E, 6 and 11: tests and help | Subcommand and argument help comes from the shared contract and contextual descriptions. Transport tests exercise behavior and artifacts; native verification is identified separately from fixture tests. |
| 5.3: MCP recommendations | CLI counterparts, flat single-edit tools, output schemas, annotations, resources, prompts, progress and formatter/import CI checks are present. |
| 7–8: local evidence and uncertainties | Historical captures/build receipts establish only those runs. Fresh native verification records its own artifacts; installation, rendering and gameplay have separate evidence. Local SDKs/binaries/captures stay ignored. |
| 12: fact-check corrections | Removed or uncertain numbers are not reintroduced into help. The current client setup guide links primary client sources. Static geometry checks do not establish movement feasibility. |

## Native control investigation

The [CLI-Anything harness procedure](https://github.com/HKUDS/CLI-Anything/blob/34f519533bc175d2fe287ab8316b0dd99bb9cc43/cli-anything-plugin/HARNESS.md)
guides the use of native formats and real backends. The native bridge uses real
Hammer++ on a private Windows desktop, semantic control messages, staged VMFs
and the actual Source compiler executables. It does not send keyboard/mouse
input to the user's desktop.

REA inspected the installed 8864 DLL's PE resources and its architecture.
The observed resource inventory contained 363 resources, including menus and
dialogs. A separate PE import inventory found D3D9 in `shaderapidx9.dll`.
Neither a resource inventory nor a successful factory lookup proves a callable
private document API or a rendered viewport.

Valve publishes an [editor shell protocol](https://github.com/ValveSoftware/source-sdk-2013/blob/be57e3d01ac7d7aa6a2cacbfef187c0b46616db0/src/public/editor_sendcommand.cpp)
using `WM_COPYDATA`, but the expected receiver window was absent in the tested
map-loaded 8864 session. The implementation therefore uses inspected native
menus and standard controls. This is a bounded observation, not a claim that
all private interfaces have been ruled out.

The private-desktop experiment loaded a real VMF, inspected the actual editor,
handled its recovery dialog, captured its window and shut it down. The input
desktop and sampled foreground window stayed unchanged, and the owned job
reported zero active processes after cleanup. PrintWindow omitted GPU viewport
content; a separate render-thread readback now returns actual native pixels.
UI chrome alone is not rendering evidence. Windows provides
[desktop selection at process creation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/ns-processthreadsapi-startupinfow),
while actual D3D9 readback has [separate surface constraints](https://learn.microsoft.com/en-us/windows/win32/api/d3d9/nf-d3d9-idirect3ddevice9-getrendertargetdata).

Rollback preserves managed document/file states. Native UI undo stacks, camera
position and arbitrary external programs are separate from those saved states.
CPU/memory claims must come from a live session measurement, not the number
of imported modules or configured limits. Heavy REA analysis is a development
activity and is not an always-running Mapwright service.

## Verification on 2026-10-19

On Windows with Python 3.11, the installed-command suite passed 120 tests with
the native MCP lane enabled. The 57 advertised tools have explicit portable
success scenarios or a real native scenario; fixture-only native transport
checks remain labelled separately. The real native lane compiled a fresh BSP,
ran REA, inspected and controlled Hammer++, captured real viewport pixels and
its owned UI window, saved
with revision checks, rejected a stale save, restored an action's exact source
bytes, reopened the hidden document and closed its owned process tree.
Process-crash tests exercise interrupted mutation, partial checkout and abrupt
MCP host death. The broker observed the dead host without polling, closed the
hidden editor and recorded zero active processes in its owned job.
An actual stdio session also completed 24 parallel metadata requests with
unique action receipts and no pending actions. Windows extended path prefixes
are normalized after junction resolution; outside-workspace paths stay refused.

Setup was applied for all six clients in a disposable user profile with a map
workspace containing spaces. The registered executable completed an actual MCP
handshake, advertised 57 tools and reported the existing native runtime ready.
The receipt then rolled back those files. This verifies configuration generation
and server connectivity; it does not establish that all six client applications
loaded this development checkout in live conversations.

A three-second idle sample after GPU capture measured about 0.52% of one CPU
for Hammer++, with roughly 275 MiB working set; its waiting broker used about
26 MiB and no sampled CPU. The disposable capture worker peaked near 116 MiB
and exited before returning its receipt. These are observations on this machine,
not minimum requirements or universal performance promises. Cleanup reported
zero active processes in the owned job, with the sampled input desktop,
foreground window and cursor unchanged.

REA/Frida observed the material-system factory and native render callbacks.
The public
[CS:GO SDK interface](https://github.com/alliedmodders/hl2sdk/blob/csgo/public/materialsystem/imaterialsystem.h)
was insufficient to assume the installed ABI: binary inspection showed a
seventh optional texture argument on ReadPixels. Passing it explicitly enabled
real GPU readback on the normal Windows D3D9 backend. A D3D9-to-Vulkan experiment
also ran in an isolated runtime, but no graphics wrapper is needed or installed
by Mapwright.

Hammer's 2D helper panes can swap cleared buffers before the populated camera
pane. The capture worker examines at most eight owned frame events, reuses its
RGB buffer, selects a populated pane and detaches. Loaded DLL hashes and x86
architecture must match the verified profile before native interface calls.
Unknown profiles are refused; `auto` reports any UI-only fallback explicitly.
Uniform actual frames remain available with warnings. The real native test
requires visible image variation for its generated room, checks all three
capture modes, and preserves the PNG for content review. The resulting image
was inspected and showed the room, player models and KZ brush geometry.
These tests do not establish gameplay.
