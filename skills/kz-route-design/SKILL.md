---
name: kz-route-design
description: Design or revise legacy CS:GO KZ routes with tier-appropriate long jumps, meaningful technical jumps, and realistic takeoff and landing regions. Use before spacing route surfaces or reviewing trivial filler jumps; excludes CS2 calibration.
---

# KZ route design

Establish the movement mode, tickrate, tier and completion line. Use matching
measured references or a reviewed provisional authoring envelope. Keep source
geometry, performed jumpstats and player acceptance distinct. When available,
read the KZ gameplay skill's matching tier and technique ranges.

## Give every jump a purpose

Make tier-appropriate long-jump difficulty the ordinary jump baseline throughout
the route. Every intended jump must be a normal long jump or a specific technical
jump. A separate LJ room, colored block or key entry does not satisfy this rule.

Use shorter gaps for a concrete demand: an enforced bhop continuation, an air
turn around masonry, a restricted landing/exit, a high-jump setup, a ladder or
surf transfer, or another specified technique. Inspect the geometry and trigger
logic that creates that demand. A small rise, optional bhop, color, or renamed
easy hop alone does not establish a technical jump.

Vary pressure within the approved technique envelope. Lower-end jumps remain
meaningful at the intended tier; "filler" must never mean a trivial gap with no
movement demand. Use continuous walking architecture for positioning or rest.
Merge, remove or redesign purposeless intermediary hops.

## Place the landing from the player's approach

Start with the preceding landing and its stance, run-up, speed and exit heading.
Determine a plausible **takeoff region for the player origin** on the actual
support polygon, then a supported landing region with a usable next exit.
Account for the player hull, setbacks, curved edges, slopes, nearby collision,
rise/drop, turn and active trigger state.

Record the physical edge gap and origin-to-origin travel from those regions.
For straight aligned surfaces, a takeoff centre 12u inside its edge and a landing
centre 20u inside the destination require `gap + 12 + 20` units of travel. This
is an example of geometry, not an automatic 32u conversion or official LJ stat.
Derive offsets from each approach; extreme last-contact overhang is a separate
limit case, not the assumed normal takeoff on every jump.

Size the next architectural member from the credible takeoff region and the
matching technique's reach envelope. Check early, intended and late departures,
including speed available after the previous landing. When a case needs more
reach or setup than the preceding phrase supplies, change the layout or technique.
Mark unmeasured speed and reach as provisional. A clear analytical arc or nearest
edge distance does not prove movement feasibility.

## Review the whole route

Keep an ordered record for **every** transition: normal LJ or named technical
purpose, tier/mode, source and destination IDs, actual support polygons,
takeoff/landing regions, edge gap, required travel interval, rise/drop, speed
and run-up assumptions, turns, clearance, timing, recovery and evidence status.
Reject ordinary jumps below their approved baseline and short jumps without
their stated technical constraint. Keep long jumps ordinary in the visual key;
reserve special cues for mechanics players actually need to recognize.

Use structural column tops, wall cuts, cornices, beams and galleries as landings.
Update source and mechanic markers together. Validate collision, compile, verify
packaging and inspect a native render with the map-authoring tools. Test the
connected route in the intended movement setup before claiming playability or
a player-assigned tier.
