# Native JSON UI clipping compatibility fixture

This is an isolated resource overlay for the integrated stencil probe. It uses ordinary native `image` children under a rectangular `panel`, with `clips_children` as the sole changed clipping variable. It does not replace the HUD, use a custom UI shader, send input, or operate a game instance. The builder writes resources on the host; game Python does not write files.

The four cards cover source-inside/source-outside × clipped/unclipped. Each has an opaque blue `[0,0,255]` backdrop and an opaque yellow `[255,255,0]` child that crosses all four sides of its parent. Both variants retain `allow_clipping:true` and `clip_offset:[0,0]`; card/root panels do not clip. Ordinary image properties are white tint, alpha 1, no bilinear filtering, no nine-slice and no rotation. No extra scissor switch is introduced.

## Build and runtime integration

From an existing host builder, import `build_fixture.py` and call:

```python
receipt = fixture.install(
    resource_pack, behavior_pack / 'stencil_large',
    source_roi=[8, 128, 512, 512],
    diagnostic_rects=[[408, 704, 296, 304]],
    physical=(720, 1080), package_name='stencil_large')
```

The function appends its file to `_ui_defs.json` while preserving existing entries and other keys. It creates `ui/integrated_ui_clip_fixture.json`, two one-pixel PNGs, `stencil_large/ui_clip_fixture.py`, its generated configuration, and project-root `ui_clip_fixture_receipt.json`. It refuses to overwrite a previous fixture install. `diagnostic_rects` means rectangles to exclude during a UI-visible compatibility frame; the example excludes the late composite bar shape. Actual data-diagnostic frames keep this UI hidden.

The generated game module exposes:

```python
from stencil_large.ui_clip_fixture import UiClipFixture
self.ui_clip = UiClipFixture(self)
self.ui_clip.open()             # RegisterUI + CreateUI(isHud=1)
# A later managed call, after NativeClipScreen.Create has completed:
self.ui_clip.configure(True)    # Show only for UI compatibility captures
self.ui_clip.configure(False)   # Hide for exhaustive data diagnostics
self.ui_clip.snapshot()
self.ui_clip.destroy()          # ScreenNode.SetRemove in parent cleanup
```

The fixture starts hidden. It uses `GetScreenSize()` as logical UI dimensions and converts every physical position/size by logical/physical scale. Receipts record logical dimensions, the physical target, `GetScreenViewInfo()`, actual control positions/sizes and visible state. This follows this repository's observed UI-coordinate convention; screen size alone is not evidence of physical WGC dimensions.

## Fixed geometry and exact oracle

At 720×1080 with the arguments above, cards are:

| Case | Physical `[x,y,w,h]` |
| --- | --- |
| source inside, clipped | `[16,136,96,64]` |
| source inside, unclipped | `[120,136,96,64]` |
| source outside, clipped | `[520,128,96,64]` |
| source outside, unclipped | `[520,200,96,64]` |

Each card has a clip panel at local `[24,16,48,32]`. Its child is parent-relative `[-16,-12,80,56]`, so without clipping the child occupies local `[8,4,80,56]`. These cards avoid the top 128 physical pixels, bottom 56 pixels and the supplied late composite shape.

| Patch, relative to card | Rectangle | Clipped expected | Unclipped expected |
| --- | --- | --- | --- |
| child inside | `[28,20,40,24]` | Yellow | Yellow |
| left outside | `[12,24,8,16]` | Blue | Yellow |
| right outside | `[76,24,8,16]` | Blue | Yellow |
| top outside | `[32,8,32,4]` | Blue | Yellow |
| bottom outside | `[32,52,32,4]` | Blue | Yellow |
| backdrop positive | `[2,2,4,4]` | Blue | Blue |

`verify.verify(image_or_path, receipt)` checks every pixel in these 24 patches: **5,952 comparisons, zero byte tolerance, fixed coordinates, no alignment or color search**. The four outside-child patches stay at least four physical pixels from clip and child edges. The separate corner proves the backdrop exists, inside yellow proves the child exists, and unclipped outside yellow proves the overflow is drawable. A missing child or always-on clipping cannot pass all controls.

CLI verification is also available:

```powershell
python -B -X utf8 tools/integrated_ui_clip_fixture/verify.py `
  --image '<fresh-owned-WGC.png>' --receipt '<project>/ui_clip_fixture_receipt.json' `
  --output '<evidence>/ui-clipping.json'
```

The verifier checks an image, not process provenance. The lifecycle owner must also validate the existing fresh WGC/noactivation/720×1080 receipt. Run the same oracle with the native data/composite pipeline off and on; keep UI hidden in the separate exhaustive payload captures. Passing this fixture establishes compatibility for this ordinary rectangular panel→image case, not all native UI masks or scrolling controls.

## Verification status and references

Host-only offline validation is saved under `.runtime/integrated-ui-clip-offline-20261119-r1/`. It generated a synthetic reference image and passed all 5,952 comparisons. A missing-child mutation failed 960 pixels; a mutation that wrongly clipped the unclipped control failed 512 pixels. Existing `_ui_defs.json` entries and an unrelated key were preserved. The two generated Python files parsed and passed scoped `minecraft_py review` with zero findings. These checks do not claim native execution; native results belong to the integrated probe owner's evidence.

MCP `wiki clips_children` documents the visual clipping property, `allow_clipping` and `clip_offset`. Installed 3.10.0.467018 resources also use `clips_children:true`, including `vanilla_netease/ui/chatExtensionMainScreenMsg.json`, `chatExtensionMainScreenMsgNew.json`, `netease_chat_screen_extension.json`, and `vanilla/ui/chat_settings_menu_screen.json`. Public MCP API references used are `RegisterUI`, `CreateUI`, `GetBaseUIControl`, `SetPosition`, `SetSize`, `GetPosition`, `GetSize`, `GetVisible`, `SetVisible`, `GetScreenSize`, `GetScreenViewInfo`, and `ScreenNode.SetRemove`.
