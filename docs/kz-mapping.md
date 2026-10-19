# KZ mapping contract

Mapwright targets legacy CS:GO Source 1 KZ first. GOKZ reads exact named entities
from the compiled BSP. A VMF check is an authoring aid; verify the compiled map
on the intended server and movement mode. CS2KZ and Momentum rules are separate.

## Authoring

`mapwright new maps/kz_example.vmf --template kz-room` creates a sealed,
lit starter room, one spawn per team, main start/end zones, `climb_start`
with destination angles and `worldspawn.climb_mapping_api_version=1`.
This is a starting fixture, not an approved course or a complete jumpstats room.

Long-jump blocks are ordinary world/func_detail brushes. An anti-bhop block
adds a separate trigger volume over the visual geometry. These values are
ordinary keyvalues, readable with `object` and writable with `set-properties`.
There are no hidden Hammer-only KZ settings.

| Feature | VMF contract |
| --- | --- |
| Main timers | `func_button` named `climb_startbutton` / `climb_endbutton`, or `trigger_multiple` named `climb_startzone` / `climb_endzone` |
| Bonus timers | `climb_bonus<N>_startbutton/endbutton` or `startzone/endzone`, positive integer N |
| Buttons | Enable Don't move (1) and Toggle (32), mask 33 |
| Zones | Enable Clients (1); starts on leaving, ends on entering; avoid simultaneous start-zone activation |
| Course starts | `info_teleport_destination` named `climb_start` / `climb_bonus<N>_start`, with `angles` |
| API | `worldspawn.climb_mapping_api_version` is a bare integer; pinned FGD is Version 1 |
| Teleports | `trigger_multiple` named `climb_teleport`, destination in `climb_teleport_destination`; no special `!` names |
| Bhop types | `climb_teleport_type`: 0 normal, 1 multi, 2 single, 3 sequential; bhop grounded delay >=0.08s, commonly 0.1 |
| Anti-bhop | `trigger_multiple` named `climb_anti_bhop`, `climb_anti_bhop_time` default 0.2s; 0 always active; each volume >=16u thick on every axis |
| Anti-bhop destinations | At least 4u above the actual floor beneath a destination inside the volume |
| Other modifiers | `climb_anti_pause`, `climb_anti_checkpoint`, `climb_anti_jumpstat`, `climb_bhop_reset`, all `trigger_multiple` |
| Ladders | `tools/toolsinvisibleladder` on a world/func_detail brush; LAJ top height matches landing, zero offset |
| Water | Rectangular level brush, water on top only, other faces nodraw; world or `func_water_analog`; inspect skybox/leaks and LOD |

Teleport defaults: use destination angles=1, reset speed=1, reorient=0,
relative=0. Reorient overrides the angle option; combining it with relative
offsets has a visible-lag caveat when destination yaw changes. Single/sequential
state resets on ground/ladder contact away from these triggers; Multi resets
it too. Do not add manual reset triggers without a concrete need.

Use `add-box --face-materials '{"top":"dev/dev_water2"}'` over nodraw for
water, or set the appropriate ladder face. Face keys are `top`, `bottom`,
`north` (+Y), `south` (-Y), `east` (+X), `west` (-X). Existing per-side
properties remain accessible. `add-entity` properties accept scalar values;
`set-properties` also accepts null to delete a key.

`fgd` in the local configuration accepts one filename or an ordered array.
Put the base CS:GO FGD first and the official GOKZ FGD second. The catalog
retains base fields and applies later field overrides. The setup script gives
Hammer a complete merged `csgo_kz.fgd`, preserving the base editor helpers;
this avoids stock-base-name differences in HammerAddons. Missing addon bases
are reported in catalog warnings while existing class fields remain available.
The FGD configures the editor, not the compiler.

## Checks

| CLI | MCP | Purpose |
| --- | --- | --- |
| `kz-audit PATH` | `kz_audit` | Main/bonus contract, exact names/classes, flags, destinations, anti-bhop and environment checks |
| `kz-check-antibhop PATH` | `kz_check_antibhop` | Trigger thickness/time and destination floor clearance |
| `kz-check-bhop PATH [--route @route.json]` | `kz_check_bhop` | Types/delays, shared destinations, ordered landing-block gaps and reset-ground candidates |
| `kz-measure PATH --start '{"id":47}' --end '{"id":54}'` | `kz_measure_jumps` | Edge gap, delta-z, block geometry and distance context; selectors may specify `kind:"side"` for a top face |
| `kz-check-headhitter PATH [--start JSON --end JSON]` | `kz_check_headhitter` | Floor/ceiling clearance, optionally in a selected corridor |
| `kz-check-ladders PATH [--landing JSON]` | `kz_check_ladders` | Material/ownership, normals/dimensions and optional LAJ height |
| `kz-check-water PATH` | `kz_check_water` | Top-only water, nodraw, ownership and sky/LOD context |
| `kz-check-teleports PATH` | `kz_check_teleports` | Destination resolution and angle/speed behavior |
| `kz-spawn-check PATH` | `kz_spawn_check` | Team presence/parity, angles, brush hull collision, ceilings and start zones |
| `kz-test-plan PATH` | `kz_test_plan` | Current-revision findings and an in-game verification recipe |

Every report includes the VMF revision and object-specific findings. `valid`
means no detected errors; `complete` describes supported geometry, and
`unsupported_geometry` identifies shapes requiring inspection. Warnings are
review aids, including intentional headhitters and shared teleport destinations.
The main audit omits the expensive whole-map headhitter scan; run that command
separately. Above 1000 collision boxes, select a corridor.

Geometry checks use exact plane equations for axis-aligned six-face boxes,
not arbitrary plane-point bounds. Slopes, displacements, prop collision,
instances and dynamic objects need editor/in-game verification. Ordered bhop
routes are explicit selections, not inferred player trajectories. Potential
reset-ground detection is a heuristic, not a continuity proof. Hidden objects
are excluded. Resource limits and unsupported selectors fail explicitly.

Jumpstat block checks require parallel flat aligned edges at equal height;
minimum block gap is 186u. BH 240u / MBH 300u are common server minimums,
not universal physics rules; `--minimum-mbh` makes the MBH threshold explicit.
GOKZ LJ tier starts are VNL 210u and SKZ/KZT 215u, with perfect thresholds
240u/270u. These are jumpstat thresholds, not map difficulty tiers. Practice
distances 210 through 245 by 5 are suggestions. Gaps >500u exceed the tracked
jumpstat maximum. None of these values proves a jump is possible.

Hull context: standing 72u, crouched 54u, width 32u. Derived head apexes are
129u/111u. Head hits can invalidate following bhops. Tick rate and movement
mode affect practical thresholds. Authored coordinates are limited to
the Source compile range of +/-16384u.

## Verify and recover

Read `validate` and KZ findings, compile a fresh BSP, inspect logs and a real
Hammer++ screen capture, then follow `kz-test-plan` on a 128-tick legacy server
with the intended GOKZ/DHooks/MovementAPI versions and VNL/SKZ/KZT mode. Local
`sv_airaccelerate 1000` sandbox cvars are exploratory and do not reproduce those
modes. There is no GOKZ `!zones` editor; zones are authored in Hammer.

Before GUI saves or multi-file work, create a named checkpoint of saved files
and folders. Use `checkpoint-state TOKEN` to obtain every current revision,
then `checkpoint-restore TOKEN --expected-revisions @revisions.json --dry-run`.
Actual restore keeps a reverse checkpoint and a resumable receipt; unrelated
external changes cause refusal. Unsaved GUI state still needs Hammer's undo.
See [recovery](recovery.md) and [agent connections](agent-connections.md).

## Sources

The owner's `.local/research/research.md` (2026-10-18) supplies the complete
research inventory; [the follow-up](research-followup.md) records dispositions.
Primary GOKZ contracts were refreshed for this implementation:

- [GOKZ Mapping API](https://github.com/KZGlobalTeam/gokz/wiki/Mapping-API)
- [Pinned GOKZ 3.6.3 Version 1 FGD](https://github.com/KZGlobalTeam/gokz/blob/3.6.3/kz_mapping_api.fgd)
- [Jumpstats](https://github.com/KZGlobalTeam/gokz/wiki/Jumpstats), [mode definitions](https://github.com/KZGlobalTeam/gokz/wiki/Modes), [tester commands](https://github.com/KZGlobalTeam/gokz/blob/master/COMMANDS.md)
- [Global map rules](https://devruto.github.io/globalapi-doc/nav.mapping/map-rules.html)

The pinned FGD SHA-256 is
`6274676b3093fc8a0194727c65fdd1bd438fb69d7c4d8d1dd4bea7c535d62e28`.
Update it only after reviewing upstream changes and the checks together.
