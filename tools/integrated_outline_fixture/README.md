# Native outline fixture

This is a documented native material/render-controller outline on one custom static BB cube. It references the installed client's `netease_entity_alphatest_outline_base` and `netease_entity_alphatest_outline`; it does not replace native materials or shaders. Native stencil reference/read/write mask `117` shares bit `64` with the data transport's mask `192`.

The host integration calls `build_fixture.build_assets(output, game_exe)` for an isolated output below this repository's `.runtime`. The helper copies `runtime.py` into `behavior_pack/stencil_large/outline_fixture.py`, writes the dedicated entity assets, and returns a receipt with installed native source hashes. Host-only code may write build outputs; game runtime never writes files.

The integrated client uses:

```python
from stencil_large.outline_fixture import OutlineFixture

fixture = OutlineFixture(probe)
off_before = fixture.create()  # probe.roi, probe.viewport; cube straddles ROI right edge
on = fixture.set_enabled(True)
off_after = fixture.set_enabled(False)
fixture.destroy()
```

The probe supplies `factory`, `level`, `camera`, `roi`, `viewport`, `CreateClientEntityByTypeStr`, and `DestroyClientEntity`. Creation uses `Camera.GetWorldRayFromScreenPoint`; each snapshot reads `Pos.GetFootPos` and projects the same eight world corners with `Camera.WorldToScreenPoint`. No tick listener, animation, per-frame movement, resource rebuild, private API or convenience outline API is used. The body remains visible when outline is off. The shared native query switches its body material from ordinary alpha-test to the native stencil-writing outline base, and controls visibility of the second native outline controller. This disables both parts of the outline stencil recipe in the off state.

Capture a fixed-camera **off → on → off** sequence with the ordinary copy-only profile first. Wait for the integration's frame fence after each toggle. Save SDK snapshots and native screenshots through the host. `verify.compare_snapshots` verifies registration, query readback, unchanged entity/position/camera and eight visible front-facing corner projections. `verify.compare_outline` requires newly visible magenta pixels within the projected cube window, on both sides of an ROI boundary, including a shell outside the body's projected bounds, while the neutral body stays visible. It also requires stable off replays. Pass the first snapshot's `projected_bounds` to the pixel verifier. The positive control fails for an invisible outline, a body-only magenta tint, or an outline that does not cross the ROI. Fog and raster edges mean exact RGB equality is not required.

Payload compatibility is a separate result. Compare the native outline-on copy-only control with the restored transport-on frame, and run the integrated probe's native data checks on that same frozen state. A successful query setter, projection receipt or visible-outline control does not prove payload correctness. The verifier deliberately leaves `native_data_compatibility` unknown.

Public references authenticated through `minecraft_docs`:

- `read NeteaseGuide/mcguide/16-美术/7-材质与着色器/2-内置材质清单.md`: the native alpha-test outline pair, `overlay_color`, `ignore_lighting`, `smooth_normal`.
- `read ModAPI/接口/实体/molang.md`: QueryVariable Register/Set/Get/UnRegister.
- `api CreateClientEntityByTypeStr`, `api DestroyClientEntity`, `api GetActorRenderParams`, `api SetEntityShadowShow`, `api GetFootPos`, `api WorldToScreenPoint`, `api GetWorldRayFromScreenPoint`.

Run offline regressions with `python -m unittest discover -s tools/integrated_outline_fixture -p test_fixture.py`. They exercise the actual installed native source receipt, build schemas, SDK lifecycle with a fake client, and fail-closed synthetic screenshot cases. These checks do not start MC and do not establish native visible-outline or data-compatibility acceptance.
