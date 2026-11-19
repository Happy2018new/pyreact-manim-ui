# Static independent particle candidate

This is an offline-built research candidate for Windows OpenGL client
`3.10.0.467018`. It replaces the integrated probe's three late FrameAni draws
and its controlled RGBA reference with independently named China-particle
materials. It leaves the original probe source unchanged. It has **no native
acceptance result yet** and does not fix or claim to fix the early geometry
stencil/native-shadow conflict.

The existing compact8 upload, clear/writer geometry, resident pages, and three
postprocess stages remain unchanged. The generated project's `sfx.material`
overlay is removed entirely. `particles_netease.material` copies every native
entry from the selected installed client and appends five unique materials:
`base`, `bit64`, `bit128`, `reference`, and `reference_opaque`. Only one of the
two layer-12 reference modes can exist at once, so the maximum is four
simultaneous capacity-one emitters. This preserves every ordinary SFX route;
other packs can still conflict with this candidate's particle material file.

## Composable offline installation

The caller owns the fresh generated project and any other fixture composition:

```python
receipt = build_candidate.install(
    project, game_exe,
    viewport=(720, 1080), roi=(8, 128, 512, 512))
```

The default holds 65,536 actual host bytes. The builder also accepts fixed
larger layouts within the frozen 512 KiB limit. Every private fragment and the
client config contains the same compiled viewport/ROI; `load_begin` refuses a
different layout before uploading. The per-pixel payload remains in the
existing uploaded geometry, not in these shader constants. There is no
runtime file output, private texture upload, live shader generation, or
continuous update.

The project must already be an integrated carrier under this repository's
`.runtime`, with `behavior_pack/stencil_large/runtime.py`,
`integrated_runtime.py`, the existing white texture and manifests. Install
once, **before launch**. It replaces only the generated `modMain.py` entry
with a client-side registration of
`stencil_large.particle_candidate_runtime.ProbeSystem`. It never edits the
installed client or the frozen builder/runtime source. The receipt records
native sources, frozen runtime hashes and every generated candidate asset.
The original carrier receipts remain historical; the final composition is
described by `particle_candidate_receipt.json` and the `particle_candidate`
section in `probe_resources.json`.

Example, from the repository root, with the existing native compatibility
carrier builder:

```powershell
$project = '.runtime/native-particle-review/project'
$game = 'D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe'
python -B -X utf8 tools/native_stencil_compat_probe/build_probe.py --output $project --game-exe $game --variant carrier --include-enchanted
python -B -X utf8 tools/native_stencil_particle_candidate/build_candidate.py --project $project --game-exe $game
```

The second command only builds. It does not launch or attach to Minecraft.
Do not install into an already running deployed project; the client class and
material definitions must be loaded from the new build.

## Owner-bound acceptance

The lifecycle owner launches and ultimately stops the project with the
existing `tools/native_stencil_compat_probe/host.py`. The owner is exactly
`manim-native-stencil-compat`, the session must match the project, the cap is
60 FPS, and all captures remain passive WGC/noactivation. This runner does
not launch or stop a game and sends no desktop input.

After a successful owned launch into `launch_evidence`, run:

```powershell
python -B -X utf8 tools/native_stencil_particle_candidate/runner.py --project $project --evidence '.runtime/native-particle-review/acceptance' --previous-evidence '.runtime/native-particle-review/launch-evidence'
```

The evidence directory must be new. `--previous-evidence` copies the launch
receipt linking the existing session, then the runner initializes the fixed
camera, resizes/centers the owned window, submits the actual host input with
memory preflights, and links the existing pipeline. The standalone initializer
supports the existing 64 KiB, 256 KiB and 512 KiB fixed layouts; use
`--skip-frameani` for larger layouts because the ordinary FrameAni witness is
fixed to 720x1080. For an already initialized resident instance, pass
`--resume-resident --previous-evidence <completed_evidence>`; this requires
the previous actual input file, SHA256 identity and same resident pages.

For an outer pack-order matrix, import this module with `importlib`, create
`ParticleExperiment(args)` (also exported as `Experiment`), and compose:

```python
experiment = candidate_runner.ParticleExperiment(args)
experiment.initialize()  # resize/prepare/load; no launch
# Install/open the independent canary on this owned instance here.
result = candidate_runner.run(experiment, previous_evidence=launch_evidence)
assert result['pass'] is True
```

`args.project` and `args.evidence` are resolved `Path` values. The evidence
directory must contain its `launch.json` but not an existing `commands/`
directory when constructing the Experiment. The composable `run` does **not**
resize, prepare the camera, allocate payload pages, launch, or stop. It writes
`particle-candidate-status.json` and normal `results.json`. Every emitted PNG
is listed in `experiment.reports`. At 64 KiB every diagnostic begins at Y650;
the native UI canary at `(632,160)` remains above diagnostics and outside the
reference ROI. Weather toggles and the FrameAni helper's reversible static
world backdrop occur during acceptance. The helper's existing `finally` path
calls this candidate's restoration hook: it restores all 100 actual block
snapshots, then corrects only the witnessed `minecraft:torch` aux0 orientation
residual via public `GetBlockStatesFromAuxValue` and `SetBlockStates`. The
mapping must be exactly `{'torch_facing_direction':'unknown'}`, the current
block must still be a torch, and the accepted state plus final name/aux must
match. It then reads **all 100 positions again**, rejecting any remaining
residual or state-call failure. This changes only the freshly imported helper
object; the frozen `frameani_runner.py` source is untouched. The verified
native command is archived under
`.runtime/native-stencil-compat-20261119-r1/order-first-recovery-r2/wall-recovery-state-evidence/`,
with the subsequent full readback under `wall-final-readback-evidence/`.

Optional arguments are `include_frameani=False` (CLI `--skip-frameani`) and
`stock_evidence=<successful stock fixture directory>` (CLI
`--stock-evidence`). Supplying stock evidence additionally compares all eight
stock on states and off-background patches to both candidate configurations.
Without it, all sixteen analytic native sprite positives and the same-frame
payload/sprite gates are still mandatory. `previous_evidence` is provenance,
not a claim that this different candidate inherits another run's acceptance.

Acceptance first plays the reference and checks every source pixel plus
output guards. It crosses real render turns before explicitly pausing, then
rechecks. It tests complete actual payload bytes, raw source symbols, analytic
RGBA restoration, alpha preservation, and two consecutive paused repetitions.
The analytic nonzero reference also detects extra base blending, which a
constant overwrite marker would not detect. Clear/rain/clear reads require a
real nonopaque source-alpha witness. The ordinary FrameAni helper records
failures rather than raising on them; this wrapper requires all sixteen
positives and independently replays both complete data PNGs per case while
checking the visible sprite in those same PNGs. Success is only
`particle-candidate-status.json: pass=true` with `complete=true` and no
failure. API success, a nonempty emitter, an FPS cap, or `frameani-status.json`
being complete is not sufficient.

## Public sources and remaining unknowns

The documentation library explicitly supports
`particleeffect.materialname.value` in
`NeteaseGuide/mcguide/16-美术/9-特效/70-中国版特效属性详细说明.md:518`
and the China-particle section of
`NeteaseGuide/mcguide/16-美术/7-材质与着色器/3-材质配置说明.md:193`.
Custom material names bypass the built-in depth/blend/filter/material-color
switches, so every private material specifies its own states. The installed
`materials/common.json` already registers `particles_netease.material`.
`common_particle` and `shaders/glsl/common_particle.vertex` provide Position,
Color and UV0. The emitter template is the selected installed client's
`effects/emote/xy_s2blackhole_emote_1.json`, with animation/fade/size changes
removed, fixed nonzero size, zero movement, maximum one particle and TTL999.

The public APIs used are `CreateEngineParticle(path,pos)`,
`CreateParticleControl(id)`, `SetLayer`, `SetGlobal`, `SetFadeDistance`, `Play`,
`Pause`, `Stop`, `GetParticleMaxNum`, `GetParticleEmissionRate`, and
`DestroyEntity`. Creation/configuration/getters do not prove a live particle.
Pause is requested only after a positive playing pixel gate and a later
render turn; its pixel result must independently pass. No undocumented
FrameAni material selector or particle uniform setter is assumed.

`SetLayer` documents effect-to-effect ordering, not scheduling relative to
native weather or postprocessing. Actual UV coverage, CPU culling, MSAA,
after-weather behavior and device support remain native questions. Passing
this bounded acceptance proves its captured layouts, not a universal render
schedule. The original early stencil writers still exist and the known native
shadow conflict remains. The runner does not measure performance, claim a
512 KiB 60 FPS result, test mobile, or imply a shadow repair.

## Offline checks

```powershell
python -B -X utf8 -m unittest discover -s tools/native_stencil_particle_candidate/tests -p 'test_*.py' -v
python -B -X utf8 tools/native_stencil_particle_candidate/runner.py --help
```

The fake SDK tests verify client lifecycle and forbid runtime file calls.
Builder tests verify source preservation, omitted shared SFX, static layout,
receipt hashes and rejection before invalid composition. They do not replace
the native acceptance above.

The focused wall mock executes the actual generated server command. It
reproduces the two auto-oriented torch values (aux2/aux5), requires both to
be restored to aux0 with the public state API and checks all 100 positions.
Unrelated mismatches, nonzero original torch aux, rejected setters,
unexpected state mappings and partial/duplicate backups remain failures.
