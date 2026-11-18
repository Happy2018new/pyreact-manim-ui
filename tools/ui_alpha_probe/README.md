# Finite native UI carrier / alpha probe

This development-only experiment builds an isolated BP/RP under `.runtime`, reusing the calibrated PaperDoll entity geometry from `runtime_packet_probe`. It performs finite static draws only. Game Python does not write files. The host uses the existing owned noactivation launcher, a verified 60 FPS global cap and passive Windows Graphics Capture.

The user explicitly permits manually foregrounding the owned protected window. `host.py` preserves this exception through launch; it grants no agent activation or desktop input.

## Native results, 2026-11-18

Client: NetEase 3.10.0.467018, native 720×1080 for the completed r3 cases. Full state, fresh WGC receipts, screenshots and ROI statistics are in `.runtime/ui-alpha-native-20261118-r3/evidence/`.

| Test | Observed result |
| --- | --- |
| Ordinary writer, carrier value 42 / 201 | RGB `(42,38,166)` / `(201,38,166)` |
| Only the source Image moved to `(10000,10000)` | Values continue to change 201→42 while receiver stays onscreen |
| Restore source Image | Values continue to change 201→42 |
| Entire writer parent moved to `(10000,10000)` | Geometry still draws because the shader holds its NDC rectangle fixed; UI position is not a reliable raster cull in this path |
| Alpha-only writer, 42 / 201 | All 198,000 pixels in the inner ROI preserve the fixed backdrop RGB `(17,53,97)` |
| T0 / built-in T1 alpha diagnostics with UI backdrop hidden | Both report scene alpha 255 for writer hidden and writer 42 / 201; visible ordinary UI geometry remains on top of the diagnostic |
| Destination-alpha blend reader | Native OpenGL assertion: `Unknown blend target: 7`; no readable result obtained |

The source Image-to-`CURRENT_COLOR` handoff works even when only the Image is far outside the screen. The tested input is one scalar. A shared texture with indexed reads remains unverified. The fixed backdrop test establishes RGB preservation for that case. Separate real-scene frames were not pixel-identical, so the backdrop result does not establish a pixel-exact dynamic scene comparison. The T0 and T1 diagnostics sampled before UI drew over their visible output. End-to-end UI alpha readback remains unverified. The rain stage was conditional on basic alpha readback.

The failed destination-alpha run is preserved separately in `.runtime/ui-alpha-native-20261118-r1/evidence-r2/030_reader_assert.json`, with the exact generated material in that run's `project/`. The source builder now only permits the supported `SourceAlpha` arithmetic-control configuration, and the default runner omits the failed destination-alpha cases.

## Reproduce

Choose fresh output and evidence directories; the builder and launcher preserve prior artifacts. Use the installed client path explicitly, since the repository's historical `.mcdev.json` points at an older missing build.

```powershell
python -B -X utf8 tools/ui_alpha_probe/build_probe.py --output .runtime/ui-alpha-new/project --game-exe 'D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe'
python -B -X utf8 tools/ui_alpha_probe/host.py launch --project .runtime/ui-alpha-new/project --evidence .runtime/ui-alpha-new/evidence
python -B -X utf8 tools/ui_alpha_probe/host.py resize --project .runtime/ui-alpha-new/project --evidence .runtime/ui-alpha-new/evidence --width 720 --height 1080
python -B -X utf8 tools/ui_alpha_probe/runner.py --project .runtime/ui-alpha-new/project --evidence .runtime/ui-alpha-new/evidence
python -B -X utf8 tools/ui_alpha_probe/host.py stop --project .runtime/ui-alpha-new/project --evidence .runtime/ui-alpha-new/evidence
```

The resize uses `SWP_NOACTIVATE`; it refuses minimized or maximized windows. If ordinary owned cleanup cannot close the instance, inspect its session identity before using the same `stop` command with `--force`. Never operate another session.

Offline verification: Python compilation passed; `minecraft_py review` parsed all three generated runtime files with zero findings. This is a native POC only; no product integration, large array, continuous update or 60 FPS workload claim is made.
