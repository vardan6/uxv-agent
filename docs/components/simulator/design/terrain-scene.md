# Terrain Scene Manifest

## Purpose

The terrain scene manifest is the single source of truth for the current `3d-env` world geometry and map data.

Authoritative artifact: `config/terrain_scene.v1.json` (validated against `config/terrain_scene.schema.json`).

## Current Model

The manifest is a text-based JSON file that contains the final expanded scene representation.

It explicitly defines:
- terrain size and heightfield samples
- terrain coordinate frame and artificial GPS georeference
- road centerlines and widths
- spawn points
- pads
- solar panels and frames
- building parts
- start-hub and charger parts
- rocks and boulders
- trees
- collision proxies and route-planning metadata where available

Runtime code must not invent object names, counts, coordinates, or dimensions. The simulator and GCS read them from `terrain_scene.v1.json`.

## Virtual GPS

The scene uses local metric coordinates as the authoritative position model:
- `x`: east in meters
- `y`: north in meters
- `z`: altitude in meters

`coordinate_system.georeference` defines an artificial GPS anchor for compatibility with rover telemetry fields. The conversion is a local tangent-plane approximation: moving one meter north in the simulator changes latitude by roughly one real meter, and moving one meter east changes longitude by roughly one real meter at the configured origin latitude.

This GPS is not read from the operator laptop or browser. It is deterministic mock GPS derived from the rover's virtual 3D position.

## Why JSON Is Used Here

JSON is the project source-of-truth format because both Python simulator code
and JavaScript/browser-facing GCS code can consume it directly, and it remains
easy to validate and review in Git. Future CAD or simulator exports may be
generated from this manifest, but the manifest stays the composition/index file.

## Source And Pipeline Discipline

Do not fix terrain, charging-station geometry, roads, or colliders by only patching `config/terrain_scene.v1.json`. Treat that file as a generated runtime artifact.

When redesigning the start hub, charging station, flat apron, roads, or physics collision proxies:

1. Update the source that owns the scene design first (currently the compact seed file plus the generator script).
2. Regenerate `config/terrain_scene.v1.json`.
3. Run the scene validator.
4. Run the simulator and test rover driving from spawn, docking-area exit, road entry, object collision, and no floating/buried station parts.
5. When a broader map database or BUS-style synchronization pipeline exists, run that pipeline after the source update so every map representation is rebuilt from the same source design.

If a future map-synchronization layer adds more build steps, the rule stays the
same: update the source, regenerate derived artifacts, validate the final
manifest, then test in the simulator.
