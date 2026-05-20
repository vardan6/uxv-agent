# Rover Physics Tuning

## Purpose

This document records the simulator-side implementation targets for rover physics tuning. It exists to keep tuning work scoped, observable, and repeatable while preserving the agreed operator-facing behavior.

For requirements, see: [../requirements.md](../requirements.md)
For implementation context, see: [./technical-details.md](./technical-details.md)

## Current Intent

The simulator should tune the rover around a fixed manual route with four checkpoints:

1. Straight bump test
2. Uphill climb
3. Side-slope traverse
4. Downhill turn

Each tuning pass is evaluated against the same route and the same acceptance rules.

The first tuning loop using this route is now complete and accepted. This document therefore records both the tuning method and the resulting baseline.

## Acceptance Behavior

- Hill climbing must remain at least as capable as the current baseline. No hidden limiter is allowed.
- Suspension should show one main rebound and at most one small follow-up motion after a bump, drop, or landing.
- Low-speed steering should keep strong bite for precise placement and climbing.
- Medium-speed and high-speed turning may drift, with the rear stepping out first in a mild progressive way.
- Side-slope behavior should slide mildly before wheel lift or rollover when near the limit.
- Downhill turns should remain placeable with steering and throttle, not wash out uncontrollably.

## Observability

- Physics debug telemetry remains the low-level readout for pitch, roll, wheel contacts, throttle, and steering.
- The simulator UI should surface the fixed manual test route and short pass/fail reminders so the operator can validate the same behavior every time.
- Visual-only geometry changes, such as the tower, should stay decoupled from current rover dynamics conclusions unless explicitly promoted into physics.

## Implemented Baseline

The accepted rover baseline now includes the following simulator-side decisions.

### Geometry And Visual Baseline

- `HALF_W = 0.48`
- `HALF_L = 0.72`
- `HALF_H = 0.18`
- `WHEEL_RADIUS = 0.30`
- `BODY_VISUAL_BOTTOM_Z = -0.30`
- `BODY_VISUAL_Z_OFFSET` and `BODY_VISUAL_TOP_Z` are derived from `BODY_VISUAL_BOTTOM_Z` so attached rover visuals move together
- visual-only tower present with thicker post/base/head than the first mast pass
- tower height reduced from the first mast pass
- POV camera raised to use the higher visual camera point

### Dynamics Baseline

- `CHASSIS_MASS = 160.0`
- `MAX_ENGINE_FORCE = 620.0`
- `SUSPENSION_STIFFNESS = 56.0`
- `SUSPENSION_DAMPING_RELAX = 5.0`
- `SUSPENSION_DAMPING_COMPRESS = 6.4`
- `WHEEL_FRICTION = 3.6`
- `ROLL_INFLUENCE = 0.17`
- `CHASSIS_ANGULAR_DAMPING = 0.50`
- `CHASSIS_ANGULAR_FACTOR = 0.65`
- `GROUND_STICK_FORCE_PER_KMH = 6.5`
- steering is rate-limited with `STEERING_RESPONSE = 7.5`

### UI/Observability Baseline

- physics debug can be shown/hidden from the `Simulation` menu
- the HUD shows the four-checkpoint route reminder when physics debug is visible
- the HUD shows condensed pass/fail guidance for quick repeatable validation

## Tuning Sequence Used

The accepted baseline was produced in this order:

1. visual/body-height and tower cleanup
2. manual route/checkpoint reminder added to the HUD
3. suspension settling pass
4. drift/slip pass
5. side-slope stability pass
6. steering cleanup pass

This sequence matters because the later passes were intentionally narrow and built on the earlier accepted checks.

## Tuning Order

1. Suspension settling
2. Turn and drift balance
3. Hill traction and climb
4. Side-slope stability

This order is intentional because slip balance changes can invalidate climb and side-slope results if introduced later.

## Not Implemented

- Automatic checkpoint detection
- Automatic scoring or route verdicts
- Tower mass or collision contribution
- Extreme rock-crawling targets
