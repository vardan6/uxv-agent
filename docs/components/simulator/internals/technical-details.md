# Simulator Technical Details

## Purpose

This document records the durable simulator runtime rules that shape how the
simulator interacts with MQTT and the GCS.

## MQTT Runtime Contract

The simulator uses MQTT for three distinct responsibilities:

- subscribe to control input
- publish rover state telemetry
- publish camera frames

Telemetry should continue to include the current GCS-facing essentials:

- timestamp
- position
- GPS-compatible location
- orientation
- speed/velocity
- camera mode metadata
- power placeholders

Camera publication remains a separate MQTT media path, but it is governed by
the same publish policy as state telemetry.

## GCS Presence Semantics

The simulator treats a GCS as active only when all of these are true:

- the presence payload marks it as active
- the payload contains a recent timestamp
- that timestamp is still inside `gcs_presence_timeout_ms`

Presence should remain keyed by `gcs_id`.

## Publish Gating Rule

The simulator uses one outbound publish gate for all MQTT publishing.

Design rule:

- state telemetry publish is blocked when policy disallows outbound publishing
- camera-frame publish is blocked by the same policy

This rule is important because allowing camera publication while blocking state
telemetry would still leak bandwidth and partially bypass operator policy.

## Rover Baseline Boundaries

The accepted rover baseline currently assumes:

- graded dirt roads, pads, and light uneven ground are in scope
- extreme rock crawling is out of scope
- the tower remains visual-only in this phase and does not contribute mass,
  inertia, or collision

These boundaries should remain explicit while simulator tuning continues.

## Current Practical Limits

These limits are still part of the runtime boundary:

- camera transport is still MQTT JPEG publishing
- power values remain placeholders rather than a modeled power system
- the tuning route is an operator reminder, not an in-world checkpoint system
