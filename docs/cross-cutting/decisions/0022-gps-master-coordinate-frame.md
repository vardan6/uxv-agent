# 0022. GPS-Master Coordinate Frame: WGS84 Is The Stored Truth, Local Metres Is Derived, Origin Per Mission

Date: 2026-05-30
Status: Accepted

## Context

The initial coordinate model made local scene metres (`{x, y, z}`,
`L.CRS.Simple`) authoritative, with WGS84 produced only at `.plan` export via a
flat-earth projection from one georeference owned by the simulator scene.

Two pressures broke that model once real-rover work became a planned target
(roadmap direction "(C)": make decisions now so real hardware is not a rewrite):

1. **No scene, no origin.** A real rover in a field has no terrain-scene manifest
   to borrow an origin from. Under that model a real-world mission cannot
   be represented — there is nowhere for the georeference to come from.
2. **GPS is the real truth on hardware.** On a real rover the autopilot, home
   point, and telemetry are all WGS84. Treating lat/lon as a last-second
   export-time derivation inverts what is authoritative in the field.

The operator also wants both representations visible simultaneously (real GPS
*and* local metres). GPS and local metres are two views of one physical point,
losslessly inter-convertible given the origin; "show both" is a rendering choice
and does not require storing both as independent truth (storing both
independently creates a cross-layer unit-drift bug).

## Decision

1. **WGS84 lat/lon/alt is the stored, authoritative coordinate for each
   waypoint.** Local scene metres become a *derived, displayed* view, not the
   master record.

2. **Each Mission carries its own origin (datum):** `{origin_lat, origin_lon,
   origin_alt}`. In the simulator the origin is seeded from the terrain scene's
   georeference; on a real rover it comes from the rover's GPS / home position.
   The origin is the single link used to convert between WGS84 and local metres.

3. **Local metres is always derivable and always shown alongside GPS.** The
   simulator continues to render and run physics in local metres by converting
   from WGS84 through the Mission origin (typically once per overlay load). The
   UI surfaces both numbers.

4. **Do not persist both representations as independent fields.** Persist WGS84 +
   origin; compute metres on demand. This preserves the anti-drift guarantee.

5. **`.plan` export consumes the stored WGS84 directly** instead of projecting at
   the boundary; export-time projection is removed.

## Consequences

- A real-world mission is now representable without any simulator scene.
- Real GPS is first-class and visible throughout, not faked at export time.
- The simulator pays a conversion cost (WGS84 → local metres) at overlay load
  rather than at export; acceptable and bounded.
- The flat-earth approximation is still used (now WGS84 → metres for display),
  which stays sub-metre-accurate over a rover's working area; large-area or
  multi-site accuracy is an Open Question.
- Touch points: revision/mission storage, route planner output, AI tool results,
  map-widget overlay load, and `MissionExportService`. This is a real change to
  the storage truth, scheduled as soft/incremental per roadmap direction (C).
- WGS84 is the internal frame, not a distinct export-only widget mode.

## Alternatives Considered

- **Keep metres as master with origin from the sim scene.** Rejected: cannot
  represent a real-rover mission; origin has no source off-scene.
- **Metres master, but move the origin onto each Mission (Design 1).** Viable and
  cheaper, but inverts what is authoritative on hardware and keeps GPS as a
  derived value; rejected in favour of matching the field reality now under (C).
- **Store both WGS84 and metres as independent fields.** Rejected: reintroduces
  cross-layer unit drift.

## Open Questions

- Projection accuracy bound: at what mission extent does flat-earth need to give
  way to a proper projection (e.g. local tangent plane / UTM)?
- Altitude semantics for a ground rover (alt is ignored by ArduPilot Rover) vs.
  storing real AMSL/relative alt for future aerial use.
- Where the real-rover origin comes from operationally (first GPS fix, surveyed
  home, operator-set datum) and whether it is mutable mid-mission.

## Follow-Ups

- `docs/components/ai-agent/design.md` § "Coordinate frame split" and
  `docs/components/gcs/design.md` § "Coordinate System" to be updated as the
  storage change lands.
- Reconcile with the map-technology decision (a WGS84 basemap is now the natural
  render target rather than a separate mode).
