# Simulator Internals

Implementation-level documentation for the simulator component. Each file covers one specific engineering topic.

For the component overview, requirements, and design, see the parent [simulator/](../) folder.

## Files

| File | Topic |
|---|---|
| [terrain-scene.md](./terrain-scene.md) | Terrain scene manifest format, generation pipeline, source discipline |
| [technical-details.md](./technical-details.md) | MQTT integration details, publish gating logic, rover runtime baseline |
| [rover-physics-tuning.md](./rover-physics-tuning.md) | Physics tuning method, accepted parameter values, test checkpoint sequence |
| [rover-sim-next-phase-1.md](./rover-sim-next-phase-1.md) | Phase 1 implementation work packages and acceptance criteria for `rover-sim-next` |
| [shadow-enhancement.md](./shadow-enhancement.md) | Shadow quality implementation: Tier 1 active, Tier 2 opt-in, Tier 3 deferred |
