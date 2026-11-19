# Positive-altitude dimension diagnostic

This development-only follow-up tests the unchanged 64 KiB static dimension
candidate in a controlled, loaded room at a height shared by the Overworld and
Nether. It distinguishes the original negative-Y fixture from a dimension
recovery failure. An exact positive result establishes only this fixed pose and
payload; the diagnostic does not prove why the earlier pose failed.

The host prepares both rooms before uploading bytes or creating native render
entities. Each room occupies `(4,69,3)` through `(12,78,13)`: a stone shell with an
air interior. Every room block is inside chunk `(0,0)`. The player starts at feet
`(8.5,70,8.5)`, the camera is fixed at `(8,72,5)`, and both dimension destinations
use integer head position `(8,72,8)`.
Actors and late effects use the original camera-relative anchors. Room creation
and restoration each use documented asynchronous chunk loading, check the four
room corners with `CheckChunkState`, verify block readbacks, and retain 1,980
original block backups in server memory and host evidence.

Version 2 prepares the dimensions sequentially. A write callback is followed by
a separate delayed host command that requests a fresh chunk callback for full
verification. A mismatch retries only the affected positions, up to three write
attempts. Backups use copied block dictionaries and a `(dimension, position)`
index, so retries never replace originals. Verification history retains the
position, requested block, actual block, original block, and preceding
`SetBlockNew` return value for up to 16 examples per attempt. A duplicate or late
callback cannot repeat writes or overwrite readiness. Restoration cancels
pending preparation with an epoch guard before scheduling its own serial
write/verify requests.

The first native positive-altitude attempt stopped during room setup after five
verified Nether blocks. The sixth position was `(-4,69,0)`, where the old fixture
crossed a chunk boundary. The old receipt did not preserve the actual mismatching
block, so chunk availability is a lead, not an established cause. No payload was
uploaded and all 996 attempted block backups restored exactly in that attempt.
Version 2 avoids that boundary and records enough evidence to diagnose a further
setup failure. It does not require an extra dimension transition before upload;
the unchanged candidate rejects empty-state transitions.

Build into an absent directory using the existing installed game executable:

```powershell
python -B tools/native_stencil_dimension_diagnostics/build_candidate.py --output NEW_PROJECT --game-exe GAME_EXE
```

Alternatively, `--project FRESH_PROJECT` installs the fixture receipt on a newly
generated, never-launched carrier, installing the original dimension candidate
first when needed. It rejects a second fixture installation and altered frozen
files. Do not point this command at an existing prepared matrix case. Neither
mode copies an existing project or world. All new implementation lives in this
directory; the installed candidate source, materials, shaders, and geometry
compiler remain unchanged. The saved `.mcdev.json` explicitly has
`world_source_path: ""`, and a project containing `level.dat` is rejected. The
existing instance launcher creates a fresh `PYR_<instance UUID>` development
world for this project.

The parent owns launch, session, native testing, and cleanup. After launching the
fresh project through the existing 60 FPS noactivation lifecycle, run:

```powershell
python -B tools/native_stencil_dimension_diagnostics/runner.py --project NEW_PROJECT --evidence NEW_RUN_EVIDENCE --previous-evidence LAUNCH_EVIDENCE --repeats 2
```

For the final bounded natural-Nether diagnostic, use the same fresh build and
add `--nether-natural`:

```powershell
python -B tools/native_stencil_dimension_diagnostics/runner.py --project NEW_PROJECT --evidence NEW_RUN_EVIDENCE --previous-evidence LAUNCH_EVIDENCE --nether-natural
```

This mode permits exactly one Nether round trip. It prepares and restores only
the 990-block Overworld foothold. It does not request, inspect, or edit inactive
Nether terrain, and it does not require a Nether room or a successful inactive
Nether chunk check. The dimension destination remains `(8,72,8)` and the fixed
camera/geometry/effect pose remains positive. Matching candidate readiness is
followed immediately by the automatic passive capture, using the same static
bytes and cached geometry. Player admission never blocks that image.

The matching client state records the player's actual head position. A read-only
server request after the automatic image records `GetEntityDimensionId()` and
`GetPos()`, including when pixel verification fails. Admission requires both
native dimension observations to match, finite head Y in `[1,126]`, and X/Z
within four blocks of the requested destination. Natural terrain may alter Y;
the exact requested head-coordinate match is recorded separately with tolerance
0.05 and is not assumed. Invalid admission fails the trip after preserving the
automatic image. No player reposition, terrain edit, manual rearm, or recovery
mutation is performed after matching readiness.

The preceding v2 run completed its Overworld room, then its Nether async callback
reported all four `CheckChunkState` values false. No Nether block writes or
payload upload occurred. The natural mode removes that setup dependency without
changing the candidate. Build a new project because the reviewed host source
hashes changed; preserve both earlier runs and their prepared projects.

The runner owns no launch or stop. It requires fresh empty Overworld state,
keeps preserved launch evidence unchanged, and writes host evidence only. The
default two controlled-room round trips are bounded; `--repeats` accepts 1, 2, or 3
there and only 1 in natural mode. End recovery
and continuous updates are outside this diagnostic.

For each transition, the runner arms mode 1 before the server request, waits for
the matching recovery serial and dimension pair, and checks the same payload
identity, generation, cached page names, logical byte count, and native attempt
count. It also records the actual camera, geometry anchor, and three late effect
positions. The first image after matching readiness is a fresh passive WGC
capture with no intervening configure, inspect, geometry reattachment, effect
restart, or postprocess relink. It requires every decoded payload pixel and
guard pixel to match. The existing exact mode 1 and mode 3 checks follow this
automatic image. API readiness alone never counts as pixel verification.

The return to the Overworld runs in a `finally` block after any outbound failure.
Room restoration also runs in `finally`, with its own asynchronous load, later
verification and bounded retries. Cancellation prevents a pending preparation
callback from writing after restoration begins. The fresh owned game remains
for parent cleanup. The runner
does not restore the original negative-Y camera/player fixture; the final tested
positive pose remains observable until the parent stops the owned instance.

`positive-pose-status.json` preserves the first failure, per-trip outbound and
return failures, cleanup failure, static identity, pose receipts, exact pixel
reports, source hashes, and preserved-evidence hashes. Exit code 0 and top-level
`pixel_verified: true` require every automatic/standard image and room cleanup to
pass. Offline tests and successful API receipts do not mark native verification.

Offline verification:

```powershell
python -B -m unittest discover -s tools/native_stencil_dimension_diagnostics -p 'test_*.py' -v
python -B tools/native_stencil_dimension_diagnostics/build_candidate.py --help
python -B tools/native_stencil_dimension_diagnostics/runner.py --help
```
