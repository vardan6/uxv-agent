# Shadow Enhancement

## Purpose

This document records the durable shadow-rendering rules for the Panda3D
simulator.

The goal is stable, readable outdoor shadows without coupling the simulator to
a large custom-shader maintenance burden.

## Primary Shadow Rule

The shadow pass should use reverse culling rather than relying on aggressive
depth-offset tuning to hide acne.

Design rule:

- render back faces into the shadow map
- keep color writes off for the shadow pass
- use only a small depth offset as a safety net

Why this rule exists:

- front-face shadow casting causes self-shadow acne on terrain and other
  tessellated geometry
- reverse culling removes that failure mode at the geometry level instead of
  trying to bury it with bias
- large depth offsets create peter-panning, so they are not the primary fix

For single-sided terrain meshes, reverse culling also prevents the terrain
from self-shadowing into the shadow map.

## Lighting Intent

Outdoor lighting should preserve three visual properties:

- a directional sun that provides the main shadow shape
- ambient or fill lighting that keeps shadowed areas readable without washing
  out contrast
- a world-stable shadow frustum so artifacts do not appear to swim with the
  rover

Shadow quality improvements should keep those three properties intact.

## Shader Path Rule

The legacy Panda3D auto-shader remains the default render path.

`panda3d-simplepbr` is allowed only as an opt-in path for experimentation.

Reason:

- the current rover and terrain assets are vertex-color oriented and were not
  authored as a full PBR material stack
- enabling PBR by default changes scene color and shadow perception enough to
  count as an art-direction change, not just a shadow-quality change

Implication:

- if `simplepbr` is used, it must remain behind an explicit opt-in switch
- default visual acceptance should be judged against the legacy path

## Quality Ceiling And Escalation Path

The acceptable escalation order is:

1. fix acne and peter-panning with shadow-pass geometry rules first
2. add modest filtering or bias improvements only if the default path still
   needs them
3. consider PSSM or cascaded-shadow techniques only if the simulator needs a
   meaningfully larger quality jump

PSSM stays deferred because it requires a broader custom-shader commitment
across terrain, rover, and prop rendering.

## Durable Decision Summary

- reverse-cull shadow casting is the canonical acne fix
- depth offset is a minor safety control, not the main solution
- `simplepbr` stays opt-in until the art/material pipeline is intentionally
  reworked
- PSSM is a later-tier option, not the default next step
