# Isolated static dimension diagnostic

The default plan is **Overworld → End → Overworld** in a fresh owned project.
`--target nether` selects **Overworld → Nether → Overworld**. There is no preceding
Nether trip that can prevent End coverage. This development host tool initializes
and uploads one 65,536-byte static payload once. It retains the same resident
identity, generation, cached pages and native attempt count. The reviewed runtime,
materials, shaders, positive fixture, and previous helper sources stay unchanged.
Only the 990-block Overworld foothold is prepared and restored.

```powershell
python -B tools/native_stencil_dimension_target_diagnostics/build_candidate.py --output NEW_PROJECT --game-exe GAME_EXE
```

The builder delegates the reviewed fresh roundtrip builder and adds
`dimension_target_receipt.json`. The output must be absent and under `.runtime`.
The parent alone owns the existing 60 FPS noactivation launch and final stop.
After that launch, using separate evidence directories:

```powershell
python -B tools/native_stencil_dimension_target_diagnostics/runner.py --project NEW_PROJECT --evidence NEW_RUN_EVIDENCE --previous-evidence LAUNCH_EVIDENCE --target end --passive-followups 3
```

The first image is the first host capture immediately after a matching ready
receipt, before any host SDK diagnostic or rearm. It is not claimed to be the
first GPU frame. After this image, client `GetBlock` samples the floored camera,
anchor and three effect positions and each 3×3×3 neighborhood. Shared coordinates
are deduplicated. Reads use only already loaded client terrain; unknown returns
are retained. There are no target chunk requests, terrain changes, or event
registrations. Terrain diagnostics are supplemental and cannot overwrite the
original automatic pixel failure. Actual client/server dimension and player
position admission is recorded. Standard mode 1 and mode 3 checks only run after
the first automatic image and terrain samples.

If an actual automatic image has a pixel mismatch, the default takes three further
passive images after successive host waits of 0.6, 1.2, and 2.4 seconds. Each image
requires the same ready serial, dimension pair, static identity, positive pose,
and automatic mode 1 output state. These observations only read state and capture
through the existing passive WGC path; they never configure, inspect, recreate,
relink or upload. A state/identity/capture gate failure ends the observations.
`--passive-followups 0` omits these images. Timeouts with no actual failed first
image do not receive substitute late images. Even if all later images pass, the
first mismatch remains the outbound failure and the overall run fails.

The unchanged candidate has a 20-second recovery budget, and the host allows 40
polls separated by 0.6 seconds. These are diagnostic bounds, not documented
engine completion guarantees. First End generation may exceed them. All outbound
errors still attempt direct SDK return to Overworld through the reviewed helper,
then restore the Overworld foothold in `finally`. Return errors and cleanup errors
are retained separately in `target-status.json`. The parent retains native
lifecycle ownership. This tool never launches, stops, activates or sends desktop
input to the game. It performs no runtime file writes or continuous updates.

Offline checks:

```powershell
python -B -m unittest discover -s tools/native_stencil_dimension_target_diagnostics -p 'test_*.py' -v
python -B tools/native_stencil_dimension_target_diagnostics/build_candidate.py --help
python -B tools/native_stencil_dimension_target_diagnostics/runner.py --help
```
