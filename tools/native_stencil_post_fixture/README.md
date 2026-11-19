# Original native bloom and depth-of-field fixture

These host helpers run each original native effect in its own **fresh carrier
startup variant**. They do not launch, activate, stop, or send input to a game.
The lifecycle owner remains `manim-native-stencil-compat`. Nothing in this
directory modifies installed game files or the frozen integrated shaders.

Build an ordinary carrier project with
`tools/native_stencil_compat_probe/build_probe.py`, then call
`assets.install_startup(project, "bloom", game_exe)` or
`assets.install_startup(project, "depthoffield", game_exe)` **before launch**.
Use a different generated project for each effect. The installer emits both
legacy and RNGL native post configurations, preserves original parameters and
pass arrays, changes only native enable flags, and gives the pack manifests
effect-specific identities. Its separate `native_post_startup.json` binds native
sources, outputs, exact enable changes, and the unchanged original pass math.
`validate_startup()` rechecks the installed variant after launch without writes.

The owner then launches at 60 FPS using the existing compatibility host. For a
fresh `native_stencil_compat_probe.runner.Experiment`, use:

```python
native_effects.initialize(experiment, "bloom")
result = native_effects.run(experiment, "bloom")
```

Use the corresponding `"depthoffield"` calls for the separate DOF variant.
`initialize()` replaces the normal experiment initialization because the normal
frozen `install_pipeline()` deliberately rejects startup-active native effects.
It registers the same three custom pass definitions through the public API and
reuses `finish_pipeline()`. Camera setup is split across render turns to avoid
reading `GetForward()` immediately after camera detachment. First a bounded host
preflight requires finite three-component position/forward values, nonzero
forward norm, and two valid observations on distinct render turns. A separate
call detaches and positions the camera. The same bounded preflight then requires
two valid render turns strictly after that request. Only afterward does another
call create the anchor from the validated vector literals and initialize the
clear actor/HUD; the frozen `prepare()` then sees complete initialized state.
Each preflight makes at most 20 reads separated by 0.25 seconds. Observations and
partial setup stages are saved on success or failure in
`native_<effect>_camera_preflight.json`,
`native_<effect>_camera_preflight_detached.json`, and
`native_<effect>_camera_setup.json`; partial failures are never retried as if an
existing origin proved complete preparation.
Native setters run before registration/reconnection
because they can rebuild the process chain. DOF uses its documented dedicated
setters. Bloom uses startup configuration because no public Bloom setter was
found in the current API index.

Each run observes writer **off / active / off** with the known analytic RGB
fixture. It captures original native output directly through the owner-bound
passive WGC host. The helper binds the session/project/PID, fresh native-size
frame, unchanged foreground, noactivation receipt, source hashes, process order,
exact enabled process set, fixture mode, writer visibility, and frozen actual
64 KiB payload/pages/generation. A separate late custom observer reads the
explicit pre-native encoded copy in T3 and restored reference in T4. It checks
all bytes in identity/dependent modes and all restored RGB pixels; those checks
do not claim that the native effect itself uses those attachments.

The original legacy bloom final samples raw T1 RGB; an opaque fixture suppresses
its threshold contribution. Original DOF at zero near/far scales also returns
raw T1. If final output matches the exact predicted encoded fixture while the
late T4 restored reference and payload checks pass, the helper reports
`original_raw_t1_bypass_detected`, with compatibility false. This is a preserved
research failure. If the identity controls fail (for example a different active
render route has a nonzero bloom contribution), the report keeps that failed
control instead of assuming the legacy identity model.

A restored final image alone does not prove native execution. Bloom has two
bounded alpha profiles plus an opaque return capture. DOF has at most two
nonzero blur/focus profiles and a return to zero scales. They must produce a
visible native response before a compatible result can be asserted. A Bloom
startup enable flag with no response after those controls is reported as
`native_stage_unproven`. The run returns its own status even after setup or
verification failure, so the lifecycle owner can continue its baseline or the
other effect. Bloom remains startup-enabled for owner shutdown; DOF cleanup
requests its dedicated disable API. No derived decoder, timing, capacity
expansion, or alpha packing is included.

For an already launched fresh startup variant, the optional CLI is:

```powershell
python -B -X utf8 tools/native_stencil_post_fixture/native_effects.py --project <project> --evidence <new-evidence> --previous-evidence <launch-evidence> --effect bloom --initialize
```

The CLI copies only the existing launch receipt; it never launches a game. To
resume an already initialized equivalent variant, omit `--initialize` and point
`--previous-evidence` at its `results.json` with the original uploaded input file.

Offline verification:

```powershell
python -B -X utf8 -m unittest discover -s tools/native_stencil_post_fixture -p "test_*.py" -v
```
