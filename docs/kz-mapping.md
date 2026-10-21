# GOKZ contract

GOKZ reads exact named entities from the compiled BSP. Author zones in Hammer;
there is no GOKZ in-game zone editor. Long-jump blocks are ordinary geometry;
anti-bhop adds a separate trigger volume. Use legacy CS:GO rules, not CS2KZ or
Momentum conventions.

## Required map files

This delivery workflow requires `maps/<name>.bsp` and `maps/<name>.nav` together,
with the same basename. GOKZ replay setup checks NAV presence; an empty file
meets presence only, not parsed navigation or bot pathfinding.
For example, deliver both `kz_example.bsp` and `kz_example.nav`.

`compile_map` / `compile` returns `bsp.path` and `nav.path` in its fresh build
directory. It keeps a NAV produced by the toolchain, otherwise copies the NAV
beside the source VMF, or creates an empty NAV when neither exists. An empty NAV
is a placeholder, not a generated navigation mesh. Install both files in the
game's `maps` directory. Nonempty source/compiler NAVs are preserved but marked
`not_parsed`; rebuilding geometry does not regenerate navigation.

Compilation embeds discovered material/sky/prop dependencies using the `source`
extra, including files in custom editor mounts. Missing dependencies fail with
their game-relative paths. Engine shaders and dynamic/plugin resources still
need runtime verification. `--no-pack-assets` produces a development build;
`package_map` refuses builds without verified assets.

Run `mapwright package BUILD_DIR OUTPUT.zip` after compilation. It verifies the
receipt's BSP/NAV hashes, writes a new ZIP, and decompresses every entry for a
byte comparison. Existing output names are refused. Receipts distinguish
compilation, embedded assets, NAV presence/parsing, editor rendering, gameplay
and replay-bot verification. A compile receipt never certifies gameplay.

## Entities

| Purpose | Required values |
| --- | --- |
| Main buttons | `func_button`: `climb_startbutton`, `climb_endbutton`; Don't move=1 + Toggle=32; physical +use buttons also need Use Activates=1024 (combined 1057) |
| Main zones | `trigger_multiple`: `climb_startzone`, `climb_endzone`; Clients flag=1. Start on leaving, end on entering; avoid simultaneous start-zone activation |
| Bonus buttons | `climb_bonus<N>_startbutton`, `climb_bonus<N>_endbutton`; positive integer N; same class/flags as main buttons |
| Bonus zones | `climb_bonus<N>_startzone`, `climb_bonus<N>_endzone`; same class/flags as main zones |
| Course starts | `info_teleport_destination`: `climb_start`, `climb_bonus<N>_start`; finite `angles` |
| API version | `worldspawn.climb_mapping_api_version`: bare positive integer matching the configured GOKZ FGD header |
| Teleports | `trigger_multiple` named `climb_teleport`; `climb_teleport_destination` resolves to an existing name, excluding special `!` names |
| Bhop teleports | `climb_teleport_type`: 0 normal, 1 multi, 2 single, 3 sequential; bhop grounded delay `climb_teleport_delay` >=0.08s, commonly 0.1 |
| Anti-bhop | `trigger_multiple` named `climb_anti_bhop`; each volume >=16u on every axis; `climb_anti_bhop_time` default 0.2s, zero always active |
| Anti-bhop destinations | Teleport destinations inside the volume must be >=4u above the actual floor |
| Modifiers | `trigger_multiple`: `climb_anti_pause`, `climb_anti_checkpoint`, `climb_anti_jumpstat`, `climb_bhop_reset` |

Enable Clients=1 on trigger volumes. Teleport defaults:
`climb_teleport_use_dest_angles=1`, `climb_teleport_reset_speed=1`,
`climb_teleport_reorient_player=0`, `climb_teleport_relative=0`. Reorient
overrides destination-angle selection; relative/reorient combinations can
visibly lag after destination-yaw changes.

Single/sequential state resets on ground/ladder contact away from these
triggers; Multi resets it too. Manual `climb_bhop_reset` is rarely necessary.

## Geometry

- Source units, Z up, coordinate limit +/-16384. Hull: 32u wide, 72u standing,
  54u crouched; derived jump head apexes 129u/111u.
- Jumpstat blocks: parallel flat aligned edges, equal top height, gap >=186u.
  Common server minimums: BH=240u, MBH=300u; override MBH with `--minimum-mbh`.
  GOKZ LJ tier starts: VNL=210u, SKZ/KZT=215u; perfect thresholds 240u/270u.
  Gaps >500u exceed the tracked jumpstat maximum. These do not predict reachability.
- Ladders: `tools/toolsinvisibleladder` on world/`func_detail`, not `func_ladder`.
  LAJ requires equal ladder/landing top height and zero offset.
- Water: rectangular, level, top-only water material; other faces nodraw.
  Use world or `func_water_analog`; inspect skybox, leaks and LOD.
- `add_box.face_materials` keys: top, bottom, north=+Y, south=-Y, east=+X, west=-X.
  `add_entity` properties are scalar; `set_properties` accepts null for deletion.

## Checks

Start with `kz-audit PATH`, then `kz-check-antibhop`, `kz-check-bhop`,
`kz-check-teleports`, `kz-check-headhitter`, `kz-check-ladders`,
`kz-check-water`, or `kz-spawn-check`. Use `schema` for MCP names/options.
Measure solids or top faces with:

```text
mapwright kz-measure MAP.vmf --start '{"id":47,"kind":"solid"}' --end '{"id":54,"kind":"solid"}'
```

Reports include revision, object findings, `valid`, `complete` and
`unsupported_geometry`. Exact analysis covers axis-aligned six-face boxes;
hidden objects are excluded. Slopes, displacements, props, instances and
dynamic collision need native verification. Bhops use explicit ordered routes;
reset-ground detection is heuristic. Maps with more than 1000 collision boxes
require start/end selectors for the headhitter scan. Warnings can describe intentional features.

For a brief requiring physical timers, use `kz-audit --timer-profile buttons`.
The default `either` continues to accept zone-only maps. The physical profile
requires paired main/bonus buttons and Use Activates; reachability and timer
operation still need a playtest. Spawn checks test a 32x72 box hull and floor
support beneath the origin within 18u, with `--minimum-t-spawns` and
`--minimum-ct-spawns` for the intended capacity. Unsupported geometry remains
visible and can make support uncertain. Route access is never inferred from
clear spawns. Ordered routes accept 2..1000 nodes and retain every adjacent gap.

## SKZ and replay verification

Use the actual server's `gokz-mode-simplekz` and `gokz-replays` versions,
MovementAPI and configured dependencies. Record `sm plugins list`, map/build,
tick rate, mode, console errors, and server settings. Test both initial team
spawns, `!m`, physical +use timers, the first jump, every lane/turn, representative
falls and the finish in SKZ. Record a completed run and play it back with the
replay plugin at the expected concurrent load. Check the installed plugin's bot
limit first; upstream GOKZ 3.8.0 defines `RP_MAX_BOTS=4` in its replay include.
Replay bots are driven by replay data, not NPC navigation. Leave ordinary
combat-bot quota at zero. There is no special required bot-only spawn entity.
The server/engine client limit bounds concurrent replay bots, not an arbitrary
map-specific cap; spawn counts alone do not prove replay operation. Plugin limits
can be lower than the engine's client limit.

Mapwright automates static checks, compilation, packaging and Hammer captures.
Its tool catalog does not control a game client. Record runtime evidence
separately; an editor image cannot certify in-game lighting, movement or timers.

Validate, compile, inspect rendered captures, then follow `kz-test-plan` on the
intended 128-tick GOKZ server/mode. Sandbox cvars do not reproduce VNL/SKZ/KZT.
Head hits can invalidate following bhops. Compilation does not prove playability.

Authoritative definitions: [Mapping API](https://github.com/KZGlobalTeam/gokz/wiki/Mapping-API),
[Jumpstats](https://github.com/KZGlobalTeam/gokz/wiki/Jumpstats).
