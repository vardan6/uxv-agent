# 0017. Simulator Shadows: Reverse-Cull Auto-Shader Path; `simplepbr` Stays Opt-In

Date: 2026-05-26
Status: Accepted

## Context

Outdoor shadows in the Panda3D simulator need to be stable and readable without committing the project to a large custom-shader pipeline. Two failure modes dominate the default path: self-shadow acne on terrain and other tessellated geometry, and peter-panning when depth offset is pushed hard enough to hide that acne.

`panda3d-simplepbr` offers a more modern shader stack, but the current rover and terrain assets are vertex-color oriented and were never authored against a full PBR material stack. Turning PBR on by default changes scene color and shadow perception enough to count as an art-direction change rather than a shadow-quality fix. PSSM / cascaded shadow techniques would deliver a meaningfully larger quality jump but require a custom-shader commitment across terrain, rover, and prop rendering.

## Decision

Three rules govern simulator shadow rendering:

1. **Reverse-cull shadow pass.** Render back faces into the shadow map, keep color writes off, and use only a small depth offset as a safety net. Reverse culling removes self-shadow acne at the geometry level instead of relying on bias.
2. **Legacy auto-shader stays default.** The legacy Panda3D auto-shader is the canonical render path. Default visual acceptance is judged against it.
3. **`simplepbr` is opt-in only.** It is allowed for experimentation but must remain behind an explicit switch until the art / material pipeline is intentionally reworked.

The escalation order for any future quality improvement is: (1) shadow-pass geometry rules first, (2) modest filtering or bias improvements only if needed, (3) PSSM/cascaded techniques only if a meaningfully larger jump is required.

## Consequences

- Acne and peter-panning are addressed by geometry, not by bias tuning — the bias remains a small safety control.
- Single-sided terrain meshes do not self-shadow into the shadow map.
- Visual baseline stays stable across sessions; PBR experiments cannot accidentally redefine "looks right".
- PSSM stays deferred; if quality demands force it later, the broader shader commitment is a separate decision.

## Alternatives Considered

- **Front-face shadow casting with large depth offset.** Rejected: trades acne for peter-panning.
- **Enable `simplepbr` by default.** Rejected: changes art direction silently and breaks the vertex-color asset assumption.
- **Jump straight to PSSM.** Rejected: too much custom-shader maintenance for the current quality gap.

## Follow-Ups

- Companion design lives in [`docs/components/simulator/internals/shadow-enhancement.md`](../../components/simulator/internals/shadow-enhancement.md).
