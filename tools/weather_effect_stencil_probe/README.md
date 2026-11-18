# Tiny geometry → stencil → late SFX probe

This is a bounded, one-bit experiment. It does not establish a new 512 KiB path or performance result. The generated project uses a 128×128 ROI at `[96,192]` in a 720×1080 client. The game runtime only constructs memory-resident palettes and calls public ModSDK APIs.

The material schema is documented in `NeteaseGuide/mcguide/16-美术/7-材质与着色器/3-材质配置说明.md`, sections `Stencil 蒙版测试`, `states`, and blend factors. The designated bit is `128`.

- An opaque geometry page writes only stencil bit 128 as zero. A blend geometry page conditionally writes that bit as one, using the existing compact8 vertex attribute path and fragment discard. Both disable RGBA and depth writes.
- A layer 14 `sequence` frame effect writes a cyan diagnostic background. A distinct layer 15 `point_sequence` frame effect writes magenta only where `(stencil & 128) == 128`. Its operations keep stencil, preserve alpha, and disable depth writes.
- A `point_sequence_add` variant with an `Always` test supplies a yellow positive for the same point-filtered shader route. The probe explicitly overrides its blending to One/Zero.
- The default layer 1 reader is a supplementary early control. Its background effect is stopped, so a different effect path cannot overwrite valid magenta. Its negative pixels are checked for absence of exact magenta, rather than expected scene color.

The writer iterates zero, checkerboard A, inverse, all ones, and zero again. The runner also records a no-writer clear control and a no-clear/no-writer observation; it does not assume frame clears or stale stencil semantics. Native post effects are configured off and their nine runtime flags are checked. Rain testing is gated by all clear late-reader cases.

This is not a stencil allocation API. Native resources already use stencil for shadows, selection overlays, entity outlines, and UI clipping. Bit 128 is an experimental choice, not a reserved bit. A pass at one stage may clear or replace the stencil attachment before another stage. The opaque clear and transparent writer order is itself part of the pixel-tested hypothesis.

Builds require a new directory and never start Minecraft:

```powershell
python -B -X utf8 tools/weather_effect_stencil_probe/build_probe.py --output .runtime/weather-stencil-new/project --game-exe D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe
```

Native launch, resize, runner, and stop use the existing owner-bound passive host with owner `manim-weather-stencil`. Schedule this experiment after other owned native runs have stopped because renderer settings and options can be shared. No desktop input or window activation is used.

```powershell
python -B -X utf8 tools/weather_effect_stencil_probe/host.py launch --project .runtime/weather-stencil-new/project --evidence .runtime/weather-stencil-new/evidence
python -B -X utf8 tools/weather_effect_stencil_probe/host.py resize --project .runtime/weather-stencil-new/project --evidence .runtime/weather-stencil-new/evidence --width 720 --height 1080
python -B -X utf8 tools/weather_effect_stencil_probe/runner.py --project .runtime/weather-stencil-new/project --evidence .runtime/weather-stencil-new/evidence
python -B -X utf8 tools/weather_effect_stencil_probe/host.py stop --project .runtime/weather-stencil-new/project --evidence .runtime/weather-stencil-new/evidence
```

If the late pattern is absent, the conclusion is only “the stencil bridge was not established” unless the controls separately establish a working conditional writer/reader. `Always` rendering alone cannot prove that the geometry and late SFX share an uncleared stencil attachment.
