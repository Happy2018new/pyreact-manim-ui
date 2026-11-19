# Static dimension stage isolation

This host-only diagnostic defaults to **Overworld → End → Overworld**. It uses
the unchanged target fixture and candidate, initializes once, and uploads the
same actual 64 KiB payload once. The parent alone owns the 60 FPS noactivation
launch and final stop. No runtime, material, shader, or previous helper is edited.

```powershell
python -B tools/native_stencil_dimension_stage_diagnostics/build_candidate.py --output NEW_PROJECT --game-exe GAME_EXE
python -B tools/native_stencil_dimension_stage_diagnostics/runner.py --project NEW_PROJECT --evidence NEW_RUN --previous-evidence LAUNCH --target end
```

Run the builder into a fresh absent `.runtime` directory, then perform the
parent-owned launch before invoking the runner. `--target nether` selects one
isolated Nether trip instead. The first automatic target image and subsequent
terrain/admission reads use the unchanged reviewed target transit. A failed
automatic image remains a failure even if any later intervention succeeds.
Without an actual automatic image, stage observations are skipped.

After this first result the runner deliberately changes controls and records
21 stage observations: seven physical stages × consumers 1, 3, and 7. All stages
use explicit visibility receipts for each cached page, and Play/Stop receipts for
each late effect. Geometry pages share an actor, so per-page visibility selects
planes; actor uniforms remain enabled. Every control change is followed by a
0.6-second host wait, a matching identity/serial/pose receipt and passive WGC.

| Stage | Clear | Writer pages | Late effects |
|---|---|---|---|
| off | Hidden | Hidden | Stopped |
| base | Shown | Hidden | Unconditional base only |
| bit64 | Shown | Bit 64 | Base + stencil reader 64 |
| bit128 | Shown | Bit 128 | Base + stencil reader 128 |
| all | Shown | Both | All three |
| writers_only | Shown | Both | Stopped |
| readers_only | Shown | Hidden | All three |

Consumer 1 decodes complete byte markers. Consumer 3 exposes raw red symbols,
alpha and the green/blue range flag. Consumer 7 exposes raw encoded texture RGB.
Its output is explicitly moved to Y650 after inspect, preserving the original
screen ROI at `[8,128,512,512]`. Each mode-7 PNG contains both the original screen
ROI and exported T3 RGB from the same frame, with separate hashes and a complete
pixel comparison. Modes 1 and 3 retain output Y128.
Modes 1 and 3 record comparison to the full actual payload without requiring it
to match in intentional partial stages. Mode 7 has no analytic natural-scene
reference. Every image records full data RGB statistics/hashes and guard errors.
No partial image is treated as a pixel pass just because capture succeeds.
Expected bit-plane bytes, when the paired routes work, are payload & 0x55 for
bit64 and payload & 0xAA for bit128. Off and writers-only preserve arbitrary
natural scene high bits and therefore have no zero-byte expectation.

Three additional mode-7 controls enable the existing layer-12 known RGB fixture
with carrier off, base only, and all stages. The raw fixture has an analytic
reference, while base/all have compression-and-symbol predictions with one RGB
level tolerance. The screen ROI and exported T3 each receive the same analytic
fixture oracle separately, separating source-SFX evidence from copy/link evidence.
These use the fixture already present in the unchanged package,
and disable it in `finally` before any dimension return. They distinguish the
independent fixture SFX route from the specialized base/bit-reader routes.

A final independent manual sequence tests cumulative checkpoints: **A** explicitly
relinks the three existing postprocess connections; **B** destroys and recreates
only the current late effects; **C** hides and destroys only the current client
actors, recreates holders and reattaches their same cached geometry pages. Each
checkpoint waits for a later render frame and observes modes 1 and 3 with all
stages enabled. The sequence stops at the first checkpoint where both are exact,
or after checkpoint C. It never invokes phase-sensitive automatic
recovery internals, forges dimension events, changes the recovery serial/history,
combines new geometry, or replaces/uploads payload bytes. Manual exact mode 1/3
results are reported separately and cannot promote a failed automatic result.
The matrix and fixture controls already apply configure/inspect commands. An exact
A result identifies the first exact manual checkpoint after those interventions;
it does not prove relinking alone caused recovery.

The matrix separates unconditional base RGB compression from the paired stencil
paths and exposes geometry-only/reader-only controls. A failed paired bit route
alone does not uniquely distinguish writer submission from reader submission.
There is no new constant-stencil material or all-one geometry fixture in this
bounded suite. Occupied terrain remains a separately recorded condition.

The runner always attempts the reviewed direct Overworld return and restores
only the 990-block Overworld foothold. `stage-status.json` distinguishes the
original outbound failure, stage/fixture/manual failures, completion of the
bounded observations, returned exact pixels, cleanup and evidence-save failures.
An outer parent deadline should allow initial setup, up to 30 diagnostic captures,
return captures and cleanup. No launch, stop, activation, desktop input,
continuous update or game file write is performed by this runner.

```powershell
python -B -m unittest discover -s tools/native_stencil_dimension_stage_diagnostics -p 'test_*.py' -v
python -B tools/native_stencil_dimension_stage_diagnostics/runner.py --help
python -B tools/native_stencil_dimension_stage_diagnostics/build_candidate.py --help
```

For a separate fresh run, `--sfx-routing` replaces the matrix, three fixture
controls and A/B/C sequence with a smaller camera-culling routing comparison:

```powershell
python -B tools/native_stencil_dimension_stage_diagnostics/runner.py --project NEW_PROJECT --evidence NEW_RUN --previous-evidence LAUNCH --target end --sfx-routing
```

Before the initial exact carrier arm, this path verifies the existing fixture
with carrier off in Overworld, using the screen ROI and Y650 T3 analytic oracles.
It then checks Stop and DestroyEntity acceptance and resets the fixture reference
before the authentic End transit. End's original automatic image is preserved.
The End baseline creates a fresh fixture once and captures fixture-only mode 7
and all-carrier modes 1/3. The next checkpoint only calls public
`FrameAniControl.SetGlobal(True)` on that same fixture ID and the same three late
effect IDs. The identical three views follow; no metadata is reapplied by their
fixture visibility changes. If not all exact, a separate later-frame cumulative
checkpoint reapplies the identical FaceCamera, Loop, Layer and MixColor values,
then explicit Play, without another SetGlobal or any recreation/relink.

If metadata still does not recover all views, a final cumulative checkpoint only
calls `FrameAniTrans.SetPos` on those same four IDs, placing them at the actual
client player position plus camera forward × 4. Camera, geometry anchor, pages,
layers, metadata and links remain unchanged. Its dedicated gate preserves the
original camera/geometry/static identity and verifies all four moved positions
against the recorded target, rather than applying the fixed diagnostic Y bounds.
The same fixture-only mode 7 and all-carrier modes 1/3 follow.

There are at most thirteen additional captures including the Overworld positive.
The documented SetGlobal effect is exemption from camera-view culling; accepted
calls do not guarantee dimension rendering. Both comparison checkpoints share
the same diagnostic mode-selection and playback sequence. `result.routing`
records baseline/global/metadata observations, accepted public calls, unchanged
IDs and the first exact routing checkpoint. `result.routing_overworld_positive`
records the analytic admission test and explicit destruction. The original
automatic failure still controls top-level pixel verification. The default CLI
continues to run the complete stage suite above.
