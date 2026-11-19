# Resource order and ordinary FrameAni compatibility findings

Source state: repository commit `0c8800c`; installed game resources
`D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/data/resource_packs/vanilla_netease`.
These are source and documentation findings. Native render validation belongs
to the single lifecycle runner and is not implied by this report.

## The current resource overlay affects ordinary native FrameAni

The stock `materials/sfx.material` contains four ordinary FrameAni routes:

| Route | Stock meaning | Current generated probe use |
| --- | --- | --- |
| `sequence:billboard_base` | Bilinear, normal alpha blend | Base RGB scaling |
| `point_sequence:sequence` | Point, normal alpha blend | Stencil bit 64 reader |
| `point_sequence_add:point_sequence` | Point, additive | Stencil bit 128 reader |
| `sequence_add:sequence` | Bilinear, additive | Integrated known fixture |

The stock vertex shader computes `WORLDVIEWPROJ * POSITION` and passes UV.
The fragment shader calculates atlas UV with `EXTRA_VECTOR1.xy/zw` and
`EXTRA_VECTOR2.xy`, samples texture 0, optionally applies the alpha-test
threshold in `EXTRA_VECTOR2.zw`, then multiplies by `EXTRA_VECTOR3` mix RGBA.

`tools/weather_stencil_large_probe/build_probe.py::sfx_override` changes the
first three routes globally. The new vertex shader uses UV to make a
fullscreen quad. The fragment shader interprets mix color as packed viewport,
ROI and role data. A normal white mix `(1,1,1,1)` decodes its viewport to
`(4096,0)` and its role to 3, so the current shader discards it. Hiding all
data geometry does not undo this resource overlay.

The integrated known fixture changes the fourth route in
`tools/weather_stencil_integrated_probe/known_fixture_assets.py`. Its fragment
shader rejects mix alpha greater than 0.875, including normal white mix.

A metadata sentinel with stock vertex/fragment fallback would still leave
fixed-function changes: stencil Equal64/128, changed RGB/alpha blend factors,
disabled depth testing and disabled alpha writes. A shader branch cannot
restore those states. Material inheritance also matters: unchanged child
dictionary text does not imply unchanged inherited behavior.

The SDK documents `SetDeepTest` and `SetUsePointFiltering` for FrameAni. The
examined FrameAni API table exposes no arbitrary material selector. The 288
installed effect JSON files examined contain no `material`, `depth_write` or
`alpha_test` fields. An undocumented field or `SetMaterial` call must not be
assumed to work.

Stock `sequence` has `no_depth_test`, `depth_write`, `alpha_test` and combined
variants. Keeping stock base routes and using only a `no_depth_test` probe
variant is a limited candidate, because ordinary depth-test-disabled effects
would still use that variant. General isolation requires an independently
selectable material carrier, with all four stock routes preserved.

## Cheap installed effect controls

- `effects/pet_cat/cs_cat_s2blackhole_wb.json`: point filtering, normal blend,
  face-camera, loop, no frame-color animation.
- `effects/2024s4/cs_s2blackhole_zhuchengruchang_glow21.json`: point filtering,
  additive blend, no frame-color animation.

Use `CreateEngineSfxFromEditor`, force face-camera, looping and white mix,
then pause after a visible frame. Toggle point filtering on each effect to
exercise all four routes. Preserve a stock baseline at the same camera and
world position. The dedicated ordinary FrameAni fixture supplies a more
controlled texture and pixel oracle. Record the first native failure before
trying a routing repair.

## What the extra pack proves

The host's `instances.py::prepare_config` preserves `included_mod_dirs` input
order, and `prepare_world` connects the world's local resource packs to the
assigned private runtime resource pack directory. Input order alone does not
prove the engine's conflict priority. Record the actual assigned world's
`world_resource_packs.json` UUID list for each case.

This helper verifies both UUIDs occur exactly once, the actual relative order,
and every deployed extra resource file hash. The two cases must reverse the
actual relative UUID order. Its independent JSON UI canary establishes that
the extra pack's unique assets loaded even if ordinary FrameAni disappears.
The default benign variant contains no conflicting material or shader
definitions, so it does not establish which conflicting definition wins.

The separate explicit `stock_sfx_conflict` variant copies the selected game's
installed `materials/sfx.material` byte for byte and uses distinct UUIDs. It
introduces a real shared-material conflict without modifying installed source
files or the carrier. The two actual order cases must preserve both ordinary
FrameAni visuals and payload decoding results. The expected alternatives are
stock native effects with broken payload, or exact carrier payload with broken
ordinary effects. Treat mixed route behavior separately. An input-list index
or a correct unique UI canary alone is insufficient to name the winner.

The finite matrix is stock, carrier with data hidden, then carrier with data
active, repeated for both actual pack relations. Failure already present with
data hidden identifies the resource overlay; activation is a separate variable.

## Documented UI, pause and target APIs

Retrieved through the Minecraft documentation tool using the exact commands
below. All are client-side; only the lifecycle owner should invoke actions.

| Purpose | Documented API and contract | Query |
| --- | --- | --- |
| Observe native/custom top UI | `api.GetTopUI()` returns its name; `api.GetTopUINode()` returns its ScreenNode. Both include native UI and PushScreen UI; GetTopScreen only includes PushScreen UI. | `api GetTopUI --top 3` |
| Open native pause | `api.OpenPauseGui(isForce=False)`, no return. Existing `is_showing_menu=true` UI requires `isForce=True`. Observe the top UI/event after calling. | `api OpenPauseGui --top 3` |
| Close native/custom top UI | `api.PopTopUI()` returns bool. Includes native UI and PushScreen UI. At most one pop per frame; `PopScreen` only closes PushScreen UI. | `api PopTopUI --top 3` |
| Create independent HUD | RegisterUI then `api.CreateUI(namespace,key,{'isHud':1})`. Use a unique key. Receipt contains the canary's actual class/definition names. | `api CreateUI --top 1` |
| Observe UI stack changes | `PushScreenEvent`: screenName/screenDef. `PopScreenAfterClientEvent`: fully popped; parameters describe the new top UI. | `event PushScreenEvent --top 1`, `event PopScreenAfterClientEvent --top 1` |
| Observe resize | `ScreenSizeChangedClientEvent` has beforeX/Y and afterX/Y; PC only. | `event ScreenSizeChangedClientEvent --top 1` |
| Record screen geometry | Game `GetScreenSize()` returns width/height; `GetScreenViewInfo()` returns aligned view width/height and x/y offsets. Record physical capture size separately. | `api GetScreenSize --top 1`, `api GetScreenViewInfo --top 2` |
| Observe actual crosshair target | Camera `PickFacing()` returns type Block, Entity or None, plus target data. Entity hitPosXYZ is the entity foot center due to an engine limitation. | `api PickFacing --top 2` |
| Project world points | Camera `WorldToScreenPoint(x,y,z)` returns screenX/Y, depth and isInScreen; top-left screen origin, pixel units. | `api WorldToScreenPoint --top 2` |
| Request selected-block highlight | PlayerView `HighlightBoxSelection(True)`, no return. Wraps video outline behavior without changing the stored setting; resets after restart. | `api HighlightBoxSelection --top 2` |

`SetDeepTest(False)` explicitly means an effect remains visible through
blocking objects/blocks. `SetUsePointFiltering(True/False)` selects point or
bilinear filtering and returns success. Those are documented behavioral
controls, not arbitrary material bindings.
