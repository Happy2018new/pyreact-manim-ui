# Finite UI texture-binding probe

This development-only fixture compares a 32-byte UI geometry producer with a later UI texture sampler in a separate screen region. It also checks HUD and world-bound UI against a postprocess oracle in an uncovered bottom region. It does not implement a product transport path.

The host builds an isolated project under `.runtime`, uses the managed owner `manim-ui-texture-binding`, verifies the native global 60 FPS cap, preserves noactivation protection and captures fresh frames with Windows Graphics Capture. The explicitly authorized user-foreground exception permits manual user observation; the agent does not activate windows or send desktop input. The game runtime does not write files or continuously update payloads.

## Native findings, 2026-11-18

One owned NetEase 3.10.0.467018 instance was used at a verified physical 720×1080 client size. Raw evidence is in `.runtime/ui-texture-binding-native-20261118-r1/evidence/`, including `results.json`, `audit.json`, state snapshots, exact host commands, WGC receipts and PNGs. The generated project preserves the exact sources used for the run.

A separate replay checked all 45 passive capture receipts and compared 3×3 RGB pixel neighborhoods for the 32 sample cells in the decisive controls. The nine positive resource controls account for 288 exact indexed reads. The [small evidence index](../../docs/evidence/ui-texture-binding/summary.json) records hashes for the native results and selected captures.

| Test | Result |
| --- | --- |
| Three explicitly bound 32×1 static textures, sequential / permuted / dependent indexed queries | All 9 cases recover all 32 bytes exactly |
| Producer sequence seeded 42, then 201 | Each 32-byte visible GPU output exactly matches the independent host oracle |
| Default receiver slots 0, 1, 2: producer hidden / seed42 / seed201 | Each receiver's complete 32-cell RGB vector remains identical across the three states |
| Requested receiver-before-producer draw order | Complete receiver vectors remain identical; layer setters are request receipts, not a GPU draw trace |
| Alternate source Y convention | No candidate begins matching the producer |
| Preceding receiver Image resource A / B | All three receiver vectors remain identical |
| HUD UI → separate bottom postprocess T0 / T1 oracle | Neither slot recovers the producer; unchanged scene RGB is observed |
| World-bound UI created with `bindWorldPosition` | Its producer passes the visible 32-byte positive control, but postprocess T0 / T1 still read unchanged scene RGB |
| Post Alpha oracle | 255 for both HUD and world-bound cases |

The default slot-0 result matches the receiver's own static resource. Slots 1 and 2 produce other engine-bound values whose identities are not established here. The fact that explicit static bindings support arbitrary dependent lookup does not establish any binding from a prior UI draw to a later UI material. No supported public UI-render-target binding was found in the consulted API documentation. These default-slot observations are exploratory and apply to this client/backend/configuration.

The Image A/B control records documented `SetSprite` requests for two known resources. Its one-pixel Image is subsequently covered by the receiving geometry, so these captures do not independently expose that Image's GPU texel or establish which internal texture was bound for its draw.

The producer is hidden by an actual control visibility change; captured producer pixels then match the backdrop `(17,53,97)`. Each default candidate's off→42, 42→201 and requested-order comparisons changes **0 of 32 RGB cells**. The reader's modes 1–3 never consume the producer seed or `CURRENT_COLOR`; only producer mode 0 does. Shader controls specify the slot, query, source UV rectangle and receiver rectangle.

No dynamic candidate reached a valid random/dependent read. Consequently, this experiment did not expand beyond 32 bytes and did not run rain or continuous-update tests. Static resource textures are offline positive controls, not an upload bank or a replacement for GPU producer output.

## Reproduce

Use a fresh output/evidence directory. Never attach these commands to another project's session.

```powershell
python -B -X utf8 tools/ui_texture_binding_probe/build_probe.py --output .runtime/ui-texture-new/project --game-exe 'D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe'
python -B -X utf8 tools/ui_texture_binding_probe/host.py launch --project .runtime/ui-texture-new/project --evidence .runtime/ui-texture-new/evidence
python -B -X utf8 tools/ui_texture_binding_probe/host.py resize --project .runtime/ui-texture-new/project --evidence .runtime/ui-texture-new/evidence --width 720 --height 1080
python -B -X utf8 tools/ui_texture_binding_probe/runner.py --project .runtime/ui-texture-new/project --evidence .runtime/ui-texture-new/evidence
python -B -X utf8 tools/ui_texture_binding_probe/runner.py --project .runtime/ui-texture-new/project --evidence .runtime/ui-texture-new/evidence --image-only
python -B -X utf8 tools/ui_texture_binding_probe/host.py stop --project .runtime/ui-texture-new/project --evidence .runtime/ui-texture-new/evidence
```

The builder and launcher preserve existing artifacts. `--image-only` appends the finite preceding-Image A/B checks to the same instance after the main matrix. Normal close is attempted first; use `--force` only for the verified owned session if it cannot close. All static and candidate sampling uses existing safe sampler and blend settings; no unsupported blend enums or implicit framebuffer alias API are introduced.
