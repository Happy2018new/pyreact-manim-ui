# Repeated static dimension diagnostic

This development-only wrapper extends the verified positive-pose natural-Nether
fixture to a bounded repeated-dimension sequence in one owned game session. The
default is **Overworld → Nether → Overworld → Nether → Overworld → End →
Overworld**: six transitions, within the unchanged candidate's eight-transition
limit. This tests recovery of one resident static payload. Continuous byte
updates, End portals, arbitrary poses, and capacity beyond 64 KiB are not tested.

Build a new project under the repository's `.runtime` directory:

```powershell
python -B tools/native_stencil_dimension_roundtrip_diagnostics/build_candidate.py --output NEW_PROJECT --game-exe GAME_EXE
```

The builder calls the existing fresh positive-pose builder and adds a separate
`dimension_roundtrip_receipt.json`. It never changes the reviewed candidate,
materials, shaders, geometry compiler, or prior projects. The generated project
has an empty world source and receives a fresh independent development world
through the existing managed launcher.

The parent alone owns launch, native lifecycle, and final stop. Once it has
launched the fresh project using the existing 60 FPS noactivation lifecycle:

```powershell
python -B tools/native_stencil_dimension_roundtrip_diagnostics/runner.py --project NEW_PROJECT --evidence NEW_RUN_EVIDENCE --previous-evidence LAUNCH_EVIDENCE --nether-repeats 2
```

The default includes one End round trip. `--nether-repeats 1` selects the shorter
Overworld → Nether → Overworld → End → Overworld plan. `--skip-end` omits the End.
All plans are finite and start from a fresh empty Overworld candidate. The runner
initializes once, uploads the actual 65,536-byte host payload once, and retains the
same identity, generation, page names, logical byte count, and native attempt
count through all legs. It prepares and restores only the 990-block Overworld
foothold. No terrain API is called for an inactive target dimension.

Every successful target leg requires the matching recovery serial and dimension
pair, then immediately takes a fresh passive WGC exact mode 1 image before any
host rearm. It next records actual client/server player position and dimension,
then performs the existing exhaustive mode 1 and mode 3 checks. The fixed camera
is `(8,72,5)`, with original camera-relative actors and effects; every direct SDK
dimension request uses integer head position `(8,72,8)`. Natural collision and
gravity may alter actual Y. Exact requested placement is recorded separately,
and admission requires observed target dimensions, positive finite Y and local
X/Z bounds. Failure never becomes pixel verification solely from API receipts.

The automatic image is the **first host capture after the matching ready
receipt**. It is not claimed to be the first GPU-rendered frame of a dimension.
The candidate performs its own automatic actor/effect reconstruction and native
postprocess relinking before publishing ready; no extra host rearm occurs
between that receipt and the automatic image.

After any outbound error, the runner attempts a direct SDK Overworld return in
`finally`, including a fallback if stale render entities prevent client
inspection. The first failure and return failure are retained separately. The
next trip is not attempted after a failure. Room restoration runs in an outer
`finally`; the parent retains ownership of final game cleanup. Top-level
`pixel_verified: true` in `roundtrip-status.json` requires all planned outbound
and return pixel checks, admission gates, and room restoration to pass.

The ModSDK `ChangePlayerDimension` documentation explicitly accepts dimension 2
for the End, integer target coordinates and a boolean return. It documents no
portal, dragon, prior activation or spawn-platform prerequisite. Documentation
does not guarantee platform creation or solid ground at this coordinate. Both
dimension event documents warn that returning through an End portal can report
event Y32767; this wrapper uses a direct SDK return and authoritative actual
client/server position reads instead of trusting event position.

The unchanged candidate's 20-second recovery timeout and host's 40 polls separated
by 0.6 seconds are diagnostic budgets, not documented engine completion
guarantees. First End generation can fail those budgets and is reported as a
failure with the return attempt preserved. No silent retry or later image is
substituted for a failed automatic result. Every inherited SDK transport is
separately bounded by the existing owned host; an outer parent deadline should
allow the full initial setup and all planned exact captures.

Offline checks:

```powershell
python -B -m unittest discover -s tools/native_stencil_dimension_roundtrip_diagnostics -p 'test_*.py' -v
python -B tools/native_stencil_dimension_roundtrip_diagnostics/build_candidate.py --help
python -B tools/native_stencil_dimension_roundtrip_diagnostics/runner.py --help
```
