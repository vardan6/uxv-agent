# Rover Physics Tuning

## Purpose

This document defines the simulator-side tuning method and acceptance behavior
for rover physics.

It exists to keep tuning work repeatable without freezing transient parameter
values into documentation.

For requirements, see [../requirements.md](../requirements.md). For adjacent
simulator design context, see [./technical-details.md](./technical-details.md).

## Fixed Evaluation Route

The rover should be tuned against one fixed manual route with four checkpoints:

1. straight bump test
2. uphill climb
3. side-slope traverse
4. downhill turn

Each tuning pass should be evaluated against the same route and the same
acceptance rules.

## Acceptance Behavior

- hill climbing must remain at least as capable as the accepted baseline
- suspension should show one main rebound and at most one small follow-up
  motion after a bump, drop, or landing
- low-speed steering should keep strong bite for precise placement and climbing
- medium-speed and high-speed turning may drift, with the rear stepping out
  first in a mild progressive way
- side-slope behavior should slide mildly before wheel lift or rollover when
  near the limit
- downhill turns should remain placeable with steering and throttle, not wash
  out uncontrollably

## Observability

- physics debug telemetry remains the low-level readout for pitch, roll, wheel
  contacts, throttle, and steering
- the simulator UI should surface the fixed manual test route and short
  pass/fail reminders so the operator validates the same behavior every time
- visual-only geometry changes should stay decoupled from rover-dynamics
  conclusions unless explicitly promoted into physics

## Tuning Sequence

The accepted order of work is:

1. suspension settling
2. turn and drift balance
3. hill traction and climb
4. side-slope stability

This order is intentional because slip-balance changes can invalidate climb and
side-slope results if introduced later.

## Non-Goals

These are outside the scope of this tuning document:

- automatic checkpoint detection
- automatic scoring or route verdicts
- tower mass or collision contribution
- extreme rock-crawling targets
