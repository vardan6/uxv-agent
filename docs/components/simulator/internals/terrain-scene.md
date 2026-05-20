# Terrain Scene Manifest

## Purpose

The terrain scene manifest is the single source of truth for the current `3d-env` world geometry and map data.

Authoritative file:
- `config/terrain_scene.v1.json`

Validation file:
- `config/terrain_scene.schema.json`

Generator:
- `tools/generate_terrain_scene.py`

Validator:
- `tools/validate_terrain_scene.py`

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

Runtime code should not invent object names, counts, coordinates, or dimensions. The simulator and GCS should read them from `terrain_scene.v1.json`.

## Virtual GPS

The scene uses local metric coordinates as the authoritative position model:
- `x`: east in meters
- `y`: north in meters
- `z`: altitude in meters

`coordinate_system.georeference` defines an artificial GPS anchor for compatibility with rover telemetry fields. The current conversion is a local tangent-plane approximation: moving one meter north in the simulator changes latitude by roughly one real meter, and moving one meter east changes longitude by roughly one real meter at the configured origin latitude.

This GPS is not read from the operator laptop or browser. It is deterministic mock GPS derived from the rover's virtual 3D position.

## Why JSON Is Used Here

JSON is used as the project source-of-truth format because both Python simulator code and JavaScript/browser-facing GCS code can consume it directly. It is also easy to validate and review in Git.

Future CAD/simulator exports can be generated from this manifest:
- `.usda` for NVIDIA Isaac Sim / OpenUSD workflows
- `.glb` or `.gltf` for simulation-ready visual meshes
- collision mesh files for physics
- STEP or other CAD references for authoritative engineering assets

The manifest remains the composition/index file even when individual objects later reference professional CAD-derived assets.

## Generate Or Regenerate

From the repository root:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
python3 tools/generate_terrain_scene.py
```

This reads the legacy compact seed file:
- `config/terrain_scene.json`

and writes:
- `config/terrain_scene.v1.json`

The generator exists to preserve the current deterministic world while making the final object list explicit.

## Source And Pipeline Discipline

Do not fix terrain, charging-station geometry, roads, or colliders by only patching
`config/terrain_scene.v1.json`. Treat that file as a generated runtime artifact.

When redesigning the start hub, charging station, flat apron, roads, or physics
collision proxies:

1. Update the source that owns the scene design first. In the current pipeline
   this is `config/terrain_scene.json` plus `tools/generate_terrain_scene.py`.
2. Regenerate `config/terrain_scene.v1.json`.
3. Run the scene validator.
4. Run the simulator and test rover driving from spawn, docking-area exit, road
   entry, object collision, and no floating/buried station parts.
5. When a broader map database or BUS-style synchronization pipeline exists,
   run that pipeline after the source update so every map representation is
   rebuilt from the same source design.

Future map synchronization work may add files such as a transformation config
and synchronization generator. If that happens, document the exact command here
and keep the rule the same: update the source, build all derived map versions,
validate the final `terrain_scene.v1.json`, then test in the simulator.

## Center Redesign And Rover Physics Sequence

The charging-station/home-base redesign is the first implementation step for
the current flip/stuck/pass-through problem, but it is not the whole physics
fix. The rover physics pass remains a required follow-up.

Sequence the work this way:

1. Redesign the center terrain, charging station, flat apron, road transitions,
   and station colliders first. This removes unrealistic geometry, floating or
   buried parts, cliff-like pad edges, and missing solid objects from the test
   environment.
2. Manually test the rover from spawn through home-base exits, road entry,
   return approach, and charger collision behavior.
3. Then tune the rover itself against the corrected environment: chassis size
   and center of mass, wheel radius and track width, suspension rest length,
   spring/damping values, friction, roll influence, angular damping, engine
   force, braking, and timestep/substep settings.

Do not treat the center redesign as a substitute for rover physics work. The
home base is being fixed first because bad local geometry currently contaminates
the physics diagnosis and makes rover tuning unreliable.

## Validate

From the repository root:

```bash
cd /mnt/c/Users/vardana/Documents/Proj/remote-rover
python3 tools/validate_terrain_scene.py
```

Expected result:

```text
terrain scene valid: .../config/terrain_scene.v1.json
```

## Runtime Consumers

Current runtime readers:
- `3d-env/simulator/terrain.py`
- `3d-env/simulator/main.py`
- `gcs_server/scene_map.py`

The simulator uses the manifest to build terrain, static scene geometry, spawn position, and obstacle/collider objects.

The GCS uses the same manifest for replay scene-map payloads and future route/map functionality.

## Editing Rule

For now, edit the compact generator input only when you intentionally want to regenerate the whole scene.

If the manifest is hand-edited, run the validator before using it. Long term, the compact seed file should either be removed or clearly archived after the expanded manifest becomes the only maintained source.
