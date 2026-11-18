# Scene codec compatibility research helpers

Development-only helpers for the RGB/32-alpha transport experiment. They do
not alter product resources or other repositories. Game payloads and fixtures
are constructed in memory; runtime Python does not write files. Host builders
write isolated resource packs and evidence.

`build_overlay.py` copies the original legacy native post-process config and
derives only the bloom/DOF final material references. Raw `TEXTURE_1.rgb` is
decoded inside a fixed writer ROI; original alpha, other textures, parameters,
pass counts, target sizes and native math are preserved. RNGL and another
capacity/ROI are rejected. `--identity-baseline` constructs a separate
writer-free control; construction alone does not establish native execution
or visual equivalence.

`runtime_client.py` and `scene_server.py` prepare actual water/glass, rain,
emissive/glint and translucent-particle cases. `compat_runner.py` uses an
already owned noactivation session; it checks project identity, saves commands
and states, and captures passively. It does not launch or activate Minecraft.
Requested native effect switches are distinct from actual getters: a native
switch can rebuild the chain and remove dynamic processes, so the runner waits
and reconnects them. A named request is not proof the requested state applied.

`analyze_historical_rgb.py` independently compares the preserved early RGB
failures and the strict identical-double-blend model. It does not assign a
cause merely because a later natural scene changed elsewhere.

Offline helper tests, from the repository root:

```powershell
python -B -X utf8 -m unittest discover -s tools/scene_codec_compat_probe/tests -v
```

The 2026-11-18 actual results and evidence are in the
[research report](../../docs/SCENE_CODEC_512K_RESEARCH.md). Water/glass,
glint/emissive and visible-particle 64 KiB samples passed; rain failed payload
readback despite alpha restoration passing. DOF final execution was proven by
a sentinel; native bloom replacement and writer-free identity equivalence
remain unproven. These helpers are not a production compatibility guarantee.
