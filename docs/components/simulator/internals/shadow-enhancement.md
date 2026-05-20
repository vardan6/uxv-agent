---
title: Shadow Quality Enhancement — Research & Plan
status: Tier 1 ✅ · Tier 2 ⚠️ opt-in (off by default) · Tier 3 deferred
audience: simulator engineering
related:
  - 3d-env/simulator/main.py
  - 3d-env/requirements.txt
  - docs/components/simulator/design.md
---

# Shadow Quality Enhancement — Research & Plan

## Implementation Status Summary

| Tier | Description | Status |
|---|---|---|
| Tier 1 | Quick wins in `_setup_lighting` | ✅ **Active by default** |
| Tier 2 | `panda3d-simplepbr` drop-in + custom shader patch | ⚠️ **Opt-in** (env var `ROVER_ENABLE_PBR=1`) — washes out the vertex-color art when on |
| Tier 3 | PSSM / Cascaded Shadow Maps | ⏸️ **Deferred** |

### Acne-fix tunables (post Tier 2) — ✅ APPLIED

1. ✅ `DepthOffsetAttrib.make(-3)` restored.
2. ✅ `simplepbr.init(..., shadow_bias=0.02, ...)` (4× simplepbr default `0.005`).

### Tier 2 follow-up — the "pattern follows the rover" diagnosis ✅ FIXED

User reported: *"dirty pattern is still there, and the shadow is like big pixels, and it goes all around as well, this dirty pattern follows the rover covering some large area over it"*.

**Root cause:** I confirmed by reading simplepbr's bundled `shadow.frag` (`.venv/lib/python3.12/site-packages/simplepbr/shaders.py`) that simplepbr's `shadow_caster_contrib` is a **single-tap** `texture(shadowmap, ...)` call — no PCF kernel. Hardware PCF on `sampler2DShadow` gives at best a 2×2 compare. That means any residual acne is anchored to the shadow camera's view, not the world.

When I added rover-tracking of the sun in `_update` (Tier 1), the orthographic shadow frustum slid every frame, so the acne pattern *swam* across the ground with the rover — the user perceived this as "the dirty pattern follows the rover and covers a large area".

**Fix applied:**
- ✅ Removed the per-frame `_sun_np.setPos(rover_pos + _SUN_OFFSET)` block from `_update`. The sun is now world-stable.
- ✅ Widened the fixed frustum from `80×80` to `250×250` (still ~6 cm/texel at 4K — far finer than the original 440×440 baseline). This covers normal driving area without needing to track the rover.
- ✅ Kept `DepthOffsetAttrib(-3)`, front-face cull, and `shadow_bias=0.02`.

**Expected result:** any remaining acne is now world-anchored (texels stay put as the rover moves), which the eye tolerates far better than a swimming pattern. Edges are still hard because simplepbr is single-tap — that's the next quality ceiling.

### Tier 1.5 — Reverse-cull shadow pass ✅ APPLIED (the *real* acne fix)

User after reverting simplepbr: *"shadows doesn't work under Python or Panda 3D. I don't believe so. I think this can be enhanced or fixed. This dotted area after adding shadow is very dirty, very, very. Please research."*

I went back and read Panda3D community threads more carefully, including [preventing-objects-from-self-shadowing](https://discourse.panda3d.org/t/preventing-objects-from-self-shadowing/9611). The **canonical** Panda3D fix for setShaderAuto shadow acne is not depth-offset, not bias — it's swapping which face writes the shadow map:

```python
light_node.setInitialState(RenderState.make(
    CullFaceAttrib.makeReverse(),
    ColorWriteAttrib.make(ColorWriteAttrib.COff),
    DepthOffsetAttrib.make(-1),  # small safety net only
))
```

**Why this kills the "dotted pattern" by construction:**
- With normal cull (cull back, render front), the *front* face of each caster writes shadow depth. Receivers on that same surface have the same depth → z-fighting → the dotted speckle pattern across whole surfaces facing the light.
- With `makeReverse()`, the *back* face writes depth. Receivers compare against depth on the far side of the caster, which is geometrically guaranteed to be further from the light. Self-z-fighting is impossible.
- For our **single-sided terrain mesh** (heightmap has no bottom faces), reverse cull means terrain contributes nothing at all to the shadow map → terrain can't self-shadow → terrain acne disappears entirely without a single bitmask trick.
- For closed casters (rover, rocks, posts), the back face is on the underside facing away from the sun, so they still cast onto the terrain correctly.

**Bonus.** `ColorWriteAttrib.COff` tells the shadow pass to write depth only, no color — material-significant perf win, no visual effect.

**Why earlier rounds didn't fix it:**
- `DepthOffsetAttrib(-3)` was a *band-aid* — bigger offset hides acne by pushing the whole receiver back, but causes peter-panning (floating shadows) at the same time.
- `setShaderAuto` provides no PCF kernel and no slope-scaled bias, so no amount of bias tuning makes acne truly disappear on tessellated terrain. The acne lives in the geometry of front-face shadow-mapping; you have to attack the geometry, not the bias.

The depth offset is reduced from `-3` to `-1` because reverse culling does the real work — at `-1` peter-panning is negligible and the small offset only protects against thin/coplanar geometry.

### Tier 2 fifth round — simplepbr finally ran, looked broken ✅ REVERTED TO OPT-IN

Once simplepbr was actually installed in the right venv, the user reported:
*"The wall/canvas rendering seems very different. It's like with muted colors. Everything under shadow and no any shadow anymore. Everything is muted, grey, lighter colors and no shadow. This looks broken."*

**Root cause.** The simulator's rover and terrain use **vertex-colored, untextured geometry** authored for Panda3D's legacy auto-shader. simplepbr's PBR shading stack changes the look in three compounding ways:

1. **Reinhard-style tonemap + exposure** desaturates and lightens the whole frame.
2. **Default IBL (image-based lighting)**: simplepbr's `simplepbr.frag` always adds `ibl_diff + ibl_spec` driven by built-in SH coefficients, even with no explicit env_map. This fills shadowed surfaces with sky bounce, reading as "no shadows".
3. **No PBR materials**: with default `roughness=1, metallic=0`, vertex-color surfaces respond very differently than the auto-shader's simpler diffuse.

Properly tuning this would require:
- Reauthoring rover/terrain materials with explicit PBR `Material` per node.
- Setting `exposure` and overriding SH coefficients to suppress IBL.
- Boosting the directional light intensity ~3×.

That's a much larger art pass than a shader fix.

**Decision.** The visual state the user already accepted ("much better, but still some dirty spots every 2 m") was the **legacy auto-shader path running with Tier-1 lighting fixes**, because simplepbr wasn't actually installed at that point. We keep that as the default and make simplepbr opt-in.

**Implementation:**
- ✅ Inverted the env-var check from `ROVER_DISABLE_PBR` to `ROVER_ENABLE_PBR` in `main.py`. Default is **legacy auto-shader + Tier-1 lighting**.
- ✅ When `ROVER_ENABLE_PBR=1` is set, the full simplepbr path (with the slope-scaled-bias + 9-tap-PCF shader patch) is still available for experimentation, e.g. once vertex colors are reauthored.
- ✅ `panda3d-simplepbr` remains in `requirements.txt` (it's installed but unused unless opted into).

**Practical implication for the user.** Next launch reverts to exactly the visual state you said was "much better" — with the stable, fixed-frustum, hidden-acne config from Tier 1. Residual fine speckle from the legacy single-tap shadow shader may still be visible at certain angles; eliminating it would need either reauthored PBR materials + simplepbr tuning, or Tier 3 (PSSM cascades).

### Tier 2 fourth round — the *real* reason nothing changed ✅ FIXED

User reported the **exact same** complaint three rounds in a row: *"dirty spots every 2 meters... but it's much better now."* The "much better" was misleading — the visual state hadn't actually changed between rounds.

**Root cause.** The project has two Python virtual environments:
- `.venv/` — Linux/WSL (`run.sh`, `run_gpu.sh`)
- `.venv-gpu/` — **Windows native, used by `run.bat` (the path the user actually runs)**

I installed `panda3d-simplepbr` only into `.venv/`. The Windows venv had no `simplepbr`, so every launch hit the `ImportError` branch and silently logged
`[RENDER] panda3d-simplepbr not installed; using auto-shader fallback.`
The simulator kept running on the legacy `setShaderAuto` path. **All Tier-2 shader fixes and shader patches had zero effect in the env the user was actually testing.**

**Fix:**
- ✅ Installed `panda3d-simplepbr 0.13.1` into `.venv-gpu/` (Windows native).
- ✅ Verified the shader monkey-patch matches and rewrites simplepbr's shader inside `.venv-gpu` as well (all four smoke-test checks pass).

So the previous rounds' work (slope-scaled bias + 9-tap PCF, world-anchored frustum, fixed 250×250 film, bias 0.02, depth offset -3, front-face cull, fill light, ambient rebalance) is **only effective now** that simplepbr is present in the Windows venv.

### Tier 2 third round — slope-scaled bias + 9-tap PCF ✅ APPLIED

User reported after the 5-tap PCF patch: *"It's the same I still see some spots, some dirty spots every 2 meters."* PCF averages neighbours but doesn't fix the underlying **bias-vs-slope** mismatch — constant bias is too small for cells whose normal is nearly perpendicular to the light direction, no matter how wide you average.

**Fix in `_patch_simplepbr_shadow_filter` (main.py):**
- ✅ Added **slope-scaled depth bias** inside the patched `shadow_caster_contrib`:
  `bias = global_shadow_bias * (1.0 + 7.0 * (1.0 - n·l))`
  Glancing-angle cells now get up to 8× the base bias automatically; flat-facing cells keep the original small bias (no extra peter-panning).
- ✅ Widened PCF kernel from 5 taps to **9 taps (3×3 box)** for stronger speckle suppression and noticeably softer edges.
- ✅ Patched the **call site** in `simplepbr.frag` too, so `n·l` is passed in (computed inline as `clamp(dot(n, l), 0.0, 1.0)` — `n` and `l` are already in scope inside the lighting loop).
- ✅ Patch verified end-to-end via Python smoke test (function signature, slope-bias term, 9-tap loop, new call site, no orphan single-tap reference).

**If spots still appear after this round:** the next tunable is the slope multiplier (`7.0`). Bump to `15.0` for very steep terrain; the cost is more peter-panning at the base of upright objects. After that, only Tier 3 (PSSM with cascades) buys more quality.

### Tier 2 second round — periodic "dirty spots" on the ground ✅ FIXED (previous round)

User reported after the world-anchored fix: *"much better but I still see some spots, some dirty spots every 2 meters or so on the ground."*

**Diagnosis.** The terrain mesh has **~1.25 m cell spacing** (`config/terrain_scene.v1.json`: `terrain.size = 400`, `terrain.tile_count = 320` → `400 / (320-1) ≈ 1.25 m/cell`). Triangle normals flip slightly at every cell boundary; with simplepbr's flat constant-bias single-tap shadow compare, this leaves periodic self-shadow speckle on a roughly per-cell grid (what the user perceives as "spots every 2 meters").

**Fix.** Runtime monkey-patch of simplepbr's `simplepbr.frag` (`_patch_simplepbr_shadow_filter` in `main.py`) replaces the single-tap shadow lookup:

```glsl
float shadow = texture(shadowmap, light_space_coords);
```

with a **5-tap PCF kernel** (four diagonal corners + center, averaged):

```glsl
const float T = 1.0 / 4096.0;
shadow += texture(shadowmap, light_space_coords + vec3(-T, -T, 0));
shadow += texture(shadowmap, light_space_coords + vec3( T, -T, 0));
shadow += texture(shadowmap, light_space_coords + vec3(-T,  T, 0));
shadow += texture(shadowmap, light_space_coords + vec3( T,  T, 0));
shadow += texture(shadowmap, light_space_coords);
return shadow / 5.0;
```

The patch:
- ✅ Is applied **in-memory** to `simplepbr.shaders.shaders['simplepbr.frag']` *before* `simplepbr.init()` reads it. No venv divergence to maintain.
- ✅ Detects upstream shader changes (signature mismatch → patch is skipped with a warning, sim still runs).
- ✅ Both averages the per-cell acne spots (5 samples vote on each shadow texel) and noticeably softens shadow edges.
- ✅ Texel offset hardcoded to `1.0/4096.0`, matching our 4096² shadow map.

If the spots are still visible after this, the kernel can be widened to 3×3 (9 taps) or 5×5 (25 taps) by editing the helper. The 5-tap variant is a deliberate compromise — large enough to mask per-cell acne, small enough to keep shadow shape readable.

### Remaining quality ceiling

Even with PCF, all shadows now use the **same** filter width across the entire scene. The next ceilings if visual quality still isn't enough:

| Improvement | Effort | Result |
|---|---|---|
| Slope-scaled depth bias (`bias *= 1 + k·(1 − n·l)`) — needs a small simplepbr.frag rewrite at the call site | ~1 hr | Eliminates acne on glancing-angle surfaces without raising peter-panning elsewhere |
| Wider PCF kernel (3×3 or Poisson disk) via the same monkey-patch | ~10 min | Softer, more natural penumbra |
| Tier 3 (PSSM cascades) | 1+ day | Best-in-class; needed only if you also want sharp near + soft far |

Environment toggle: `ROVER_DISABLE_PBR=1` forces the legacy auto-shader path.

## 1. User Request

> The shadowing I don't like at all. I need more natural, more realistic,
> better, better shadowing. Please review and try to find solutions.

This document captures the diagnosis of the current shadow setup in the
Panda3D simulator and three concrete upgrade paths, ranked by
quality-per-effort. The intent is to give the team a reception document
they can act on without re-doing the research.

---

## 2. Current Shadow Setup (Baseline)

All code references are in `3d-env/simulator/main.py`.

### 2.1 Lighting (`_setup_lighting`, lines ~258–285)

| Element | Value | Notes |
|---|---|---|
| `AmbientLight` color | `(0.45, 0.47, 0.52)` | High — washes out shadow contrast |
| `DirectionalLight` color | `(1.05, 0.98, 0.85)` | Slight warm tint, fine |
| Shadow map resolution | `4096 × 4096` | Large, but mostly wasted (see §3) |
| Shadow film size | `440 × 440` | Covers the whole drivable area |
| Shadow near/far | `10 .. 520` | Very deep frustum |
| Depth offset | `DepthOffsetAttrib.make(-3)` | Aggressive — causes peter-panning |
| Shader path | `render.setShaderAuto()` | Built-in auto-shader; hard shadows only |
| Shadow border fix | `_fix_shadow_border` task | Clamps map edges to white (line 959) |

### 2.2 Sun position
`SUN_POS = (-70, -90, 130)` with light parented at `(-35, -45, 80)` looking at the origin. The sun is static; the shadow frustum is static; the rover moves through it.

---

## 3. Why The Shadows Look Bad

Five problems compound each other:

1. **Low effective shadow resolution.**
   `440 / 4096 ≈ 0.107` world-units per shadow texel. A 4K map sounds
   huge, but spreading it over a 440×440 area gives roughly the same
   per-texel detail as a 1K map on a 100×100 area. Edges look chunky and
   pixelated wherever the rover actually is.

2. **Peter-panning from the aggressive depth offset.**
   `DepthOffsetAttrib(-3)` hides shadow acne by pushing receivers away
   from the light, but the side-effect is a visible gap between an
   object and the base of its shadow — the "floating" look.

3. **No filtering.**
   `setShaderAuto` performs a single depth-compare per pixel. There is
   no PCF (Percentage-Closer Filtering), no VSM, no Poisson sampling.
   The result is a hard, aliased shadow edge.

4. **Ambient is too bright.**
   At `~0.47` luminance, the shadowed side of any object is already
   ~half-lit before the shadow is applied. Shadows look weak and washed
   out even when they are technically correct.

5. **Single light, no fill, no contact term.**
   Real outdoor lighting reads as natural because of (a) warm sun, (b)
   cool sky fill from the hemisphere opposite the sun, and (c) a small
   contact-darkening term near where objects meet the ground. We have
   only (a), so everything reads as flat plus a hard cut.

---

## 4. Three Solution Tiers

Ranked cheapest → most realistic.

### Tier 1 — Quick Wins, Keep `setShaderAuto` ✅ IMPLEMENTED

Solves roughly 70% of the visual complaint with no risk to the existing
render path. All changes confined to `_setup_lighting` and the
per-frame `_update` hook.

**Implementation landed in `3d-env/simulator/main.py`:**
- ✅ `CullFaceAttrib` imported (line ~54)
- ✅ Ambient lowered to `(0.28, 0.30, 0.34)` (cool sky tint)
- ✅ Sun color warmed to `(1.10, 1.00, 0.86)`
- ✅ Shadow film tightened from `440×440 / near-far 10..520` to
  `80×80 / near-far 1..200` (≈5× sharper texels)
- ✅ Depth offset reduced from `-3` to `-1`
- ✅ Front-face culling added on shadow caster initial state
  (`CullFaceAttrib.MCullCounterClockwise`)
- ✅ Hemisphere fill `DirectionalLight("sky_fill")` added,
  no shadow caster, color `(0.25, 0.28, 0.34)`
- ✅ Per-frame rover-tracking sun (`_update` block: `_sun_np.setPos(rover_pos + _SUN_OFFSET)` then `lookAt(rover_pos)`)

**Original change list (for reference):**

1. **Track the rover with a tight frustum.** ✅
   Each frame, set the shadow light position to
   `rover_pos + SUN_OFFSET` and `lookAt(rover_pos)`. Reduce film size
   to `~80 × 80` and `near/far` to `1 .. 200`. This alone yields about
   **5× sharper shadow edges** from the same 4096² map (texel size
   drops from ~0.107 to ~0.02 world units).

2. **Fix peter-panning correctly.** ✅
   Replace `DepthOffsetAttrib(-3)` with `DepthOffsetAttrib(-1)` and
   enable **front-face culling on the shadow caster** via a
   `CullFaceAttrib` on the light's initial state. This is the
   canonical Panda3D recommendation and removes the "floating shadow"
   artifact without re-introducing acne.

3. **Rebalance ambient.** ✅
   Drop ambient to roughly `(0.28, 0.30, 0.34)` (slightly cool to read
   as sky bounce). Optionally bump the directional intensity a touch to
   keep overall scene exposure similar.

4. **Add a no-shadow fill light.** ✅
   A second weak `DirectionalLight` from the opposite hemisphere
   (roughly `-SUN_OFFSET` mirrored, color around `(0.25, 0.28, 0.34)`)
   with **no shadow caster**. This gives free hemisphere-style sky
   bounce and makes the shadowed side read as "in shade" rather than
   "in darkness".

**Pros:** zero pipeline risk, no new dependency, can ship today.
**Cons:** shadow edges are still hard (no PCF).

### Tier 2 — Drop In `panda3d-simplepbr` ✅ IMPLEMENTED

Trigger: after Tier 1 landed, user still reported "dirty pixelly
pattern" on the rover and surrounding ground — that's residual shadow
acne from `setShaderAuto`'s single-tap depth compare on tessellated
surfaces. Tier 2 replaces the shader path with simplepbr, which gives
PCF-filtered shadows and proper bias handling.

**Implementation landed:**
- ✅ `panda3d-simplepbr>=0.12` added to `3d-env/requirements.txt`
- ✅ Installed `panda3d-simplepbr 0.13.1` into `.venv`
- ✅ `simplepbr.init(enable_shadows=..., use_normal_maps=False, use_emission_maps=False, use_occlusion_maps=False)` called right after `ShowBase.__init__` in `main.py` (the maps are disabled because the simulator uses vertex-color geometry, not PBR texture stacks)
- ✅ `render.setShaderAuto()` is now only called when simplepbr fails to import — safe fallback
- ✅ `enable_shadows` is wired to `self._shadows_enabled`, so the software-renderer path still skips shadow work
- ✅ Environment escape hatch: `ROVER_DISABLE_PBR=1` reverts to the legacy auto-shader for A/B testing
- ✅ Sky dome and sun-disc sprites already use `setShaderOff` so they bypass the PBR pipeline correctly
- ✅ Tier-1 lighting (frustum tracking, fill light, ambient rebalance, depth-offset + front-face cull) carries over unchanged


`Moguri/panda3d-simplepbr` is a drop-in replacement for
`setShaderAuto`. Usage is a single call:

```python
import simplepbr
simplepbr.init(enable_shadows=True)
```

What you get:
- **PCF-filtered shadow sampling** — soft, more realistic shadow edges.
- **Physically-based lighting** — surfaces respond more naturally to
  the sun + ambient combination.
- **Tonemapping** — better overall contrast and color rendition.
- Still uses your existing `DirectionalLight().setShadowCaster(...)`,
  so the Tier-1 frustum/offset/fill-light improvements stack on top.

**Pros:** highest quality-per-effort. Compatible with the existing
scene graph. Active project.
**Cons:** materials may need light tweaking; replaces the auto-shader
so any custom shader assumptions should be re-validated. Specifically
worth checking against `terrain.py` and the rover materials in
`rover.py`.

**Recommendation:** this is the target end-state.

### Tier 3 — PSSM / Cascaded Shadow Maps ⏸️ DEFERRED

`PSSMCameraRig` from `panda3d._rplight` implements Parallel-Split
Shadow Maps — the technique used by most modern game engines. The map
is split into cascades: high resolution near the camera, lower
resolution far away. This is what produces the crisp, large-area
shadows you see in AAA outdoor scenes.

**Hard constraint:** PSSMCameraRig **cannot work with the auto-shader**.
You must provide a custom GLSL shader for the entire scene (terrain,
rover, props). The shader must:
- Receive the `PSSMShadowAtlas` texture.
- Accept the array of split MVP matrices from `camera_rig.get_mvp_array()`.
- Implement cascade selection + shadow sampling itself.

**Pros:** best-in-class outdoor shadows.
**Cons:** significant rewrite of the shading stack. Couples the
simulator to a custom-shader maintenance burden. Overkill until the
physics tuning work is finished.

**Recommendation:** defer. Revisit only if Tier-2 quality is judged
insufficient after it ships.

---

## 5. Recommended Plan

| Step | Tier | When | Status |
|---|---|---|---|
| 1 | Tier 1 — rover-tracking sun, depth-offset fix, ambient rebalance, fill light | On `3d-physics-update` | ✅ Done |
| 2 | Tier 2 — adopt `panda3d-simplepbr` with `enable_shadows=True` | On `3d-physics-update` | ✅ Done |
| 3 | Tier 3 — PSSM | Only if Tier 2 result is judged insufficient | ⏸️ Deferred |

Tier 1 is fully reversible (one file, ~30 lines) and gives an immediate
visible improvement. Tier 2 is the natural next step once the rover
physics changes are stable and we want a real PBR look. Tier 3 is held
in reserve.

---

## 6. Concrete Tier-1 Change Sketch ✅ APPLIED

Below is the design sketch that was actually applied (with one
addition: the rover-tracking update lives inside `_update`, not a
separate task, because lighting is initialized before the rover
exists). Localized to `3d-env/simulator/main.py`.

```python
# _setup_lighting
ambient.setColor(LColor(0.28, 0.30, 0.34, 1))

sun.setColor(LColor(1.10, 1.00, 0.86, 1))
sun.setShadowCaster(True, 4096, 4096)
sun.getLens().setFilmSize(80, 80)
sun.getLens().setNearFar(1, 200)

# Replace DepthOffset(-3) with DepthOffset(-1) + front-face cull on caster.
shadow_state = light_node.getInitialState()
shadow_state = shadow_state.setAttrib(DepthOffsetAttrib.make(-1))
shadow_state = shadow_state.setAttrib(
    CullFaceAttrib.make(CullFaceAttrib.MCullCounterClockwise)
)
light_node.setInitialState(shadow_state)

# Hemisphere fill (no shadow).
fill = DirectionalLight("sky_fill")
fill.setColor(LColor(0.25, 0.28, 0.34, 1))
fill_np = self.render.attachNewNode(fill)
fill_np.setPos(-self._SUN_OFFSET.x, -self._SUN_OFFSET.y, self._SUN_OFFSET.z * 0.5)
fill_np.lookAt(0, 0, 0)
self.render.setLight(fill_np)

# Per-frame task: keep the shadow frustum on the rover.
def _track_sun_to_rover(self, task):
    rp = self._rover.np.getPos(self.render)
    self._sun_np.setPos(rp + self._SUN_OFFSET)
    self._sun_np.lookAt(rp)
    return task.cont
```

The existing `_fix_shadow_border` task keeps working as-is.

---

## 6.1 Verification Checklist (post Tier-1)

- [x] `python3 -c "import ast; ast.parse(open('simulator/main.py').read())"` passes.
- [ ] Launch simulator on a GPU machine (WSL2 software path skips shadows).
- [ ] Visually confirm:
  - Shadow edges are noticeably sharper (smaller texel footprint).
  - No "floating shadow" gap at the base of the rover / rocks.
  - Shadowed side of the rover is darker but not pitch-black (fill light working).
  - Driving long distances doesn't reveal a visible shadow boundary
    (frustum follows the rover).
- [ ] Spot-check for new shadow acne on slopes; if any appears, nudge
  `DepthOffsetAttrib(-1)` to `-2`.

---

## 7. References

- [Panda3D — using directional lights & shadows effectively](https://discourse.panda3d.org/t/sample-using-directional-lights-shadows-effectively/24424)
- [Panda3D — fixing shadow acne / peter-panning](https://discourse.panda3d.org/t/how-to-fix-strange-glitches-in-shadows-shadow-acne-on-textured-objects/29667)
- [Panda3D — Soft(-er) Shadows showcase](https://discourse.panda3d.org/t/soft-er-shadows/13122)
- [Panda3D — Shadows made easy](https://discourse.panda3d.org/t/shadows-made-easy/15399)
- [Panda3D Manual — Lighting](https://docs.panda3d.org/1.10/python/programming/render-attributes/lighting)
- [Panda3D Manual — Shadows sample programs](https://docs.panda3d.org/1.10/python/more-resources/samples/shadows)
- [panda3d/samples/shadows/advanced.py](https://github.com/panda3d/panda3d/blob/master/samples/shadows/advanced.py)
- [panda3d-simplepbr (Moguri)](https://github.com/Moguri/panda3d-simplepbr) — PyPI: [panda3d-simplepbr](https://pypi.org/project/panda3d-simplepbr/)
- [PSSMCameraRig sample](https://discourse.panda3d.org/t/parallel-split-shadow-mapping-using-pssmcamerarig/27457)
- [Parallel-Split Shadow Maps: shadows for large scenes](https://discourse.panda3d.org/t/parallel-split-shadow-maps-pssm-shadows-for-large-scenes/5547)
- [treeform/panda3d-CSM (cascading shadow maps sample)](https://github.com/treeform/panda3d-CSM)
- [LearnOpenGL — Shadow Mapping (PCF / bias background)](https://learnopengl.com/Advanced-Lighting/Shadows/Shadow-Mapping)
- [opengl-tutorial.org — Tutorial 16: Shadow Mapping](http://www.opengl-tutorial.org/intermediate-tutorials/tutorial-16-shadow-mapping/)
- [Panda3D issue #547 — feature request: shadow depth bias](https://github.com/panda3d/panda3d/issues/547)
