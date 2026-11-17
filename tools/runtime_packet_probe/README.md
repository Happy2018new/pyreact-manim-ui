# Runtime packet probe resources

This directory is an isolated research fixture, not a production transport. It
tests whether a transparent native JSON UI Image's `SetSpriteColor` survives in
`CURRENT_COLOR` for the immediately following paperdoll draw. The custom shader
does not repair, emulate, or replace that inheritance. A reset, quantization, or
cross-draw leak must remain observable as a failed comparison.

The completed study also tests a postprocess atlas and large numeric streams.
See [the research report](../../docs/RUNTIME_PACKET_RESEARCH.md) and
[compact evidence](../../docs/evidence/runtime-packets/summary.json) for actual
game results: 24 KiB in one batch, and 100,000 float32 values / 400,000 bytes in
17 independently verified replacement batches. The complete stream is never
simultaneously resident. The historical 24 KiB dynamic path ran at about 13 FPS
against a 20 FPS baseline while the user had imposed an external frame limit.
That external limit has since been removed; these measurements do not establish
the cost after its removal or a limit caused by background execution. The later
portrait atlas and split-uniform experiments are documented in
[the 2D research report](../../docs/RUNTIME_PACKET_2D_RESEARCH.md).

## Build the resource project

```powershell
python tools/runtime_packet_probe/build_probe.py --output .runtime/runtime-packet-probe --slots 8
```

The standard-library-only builder creates small independent `behavior_pack` and
`resource_pack` directories, manifests with probe-specific UUIDs, and
`probe_resources.json`. No production resources or large textures are copied.
The Python entry point is `build(output, slots=8, block_fallback=False)`. The
default build includes each slot's carrier and entity canvas. Add
`--block-fallback` to generate the additional native block-geometry diagnostic:

```powershell
python tools/runtime_packet_probe/build_probe.py --output .runtime/runtime-packet-probe-block --slots 8 --block-fallback
```

The output must be empty or carry this builder's ownership marker with matching
slot count and options. The ownership marker and `probe_resources.json` options
record `block_fallback` and `initial_panel_offset`. Use a fresh output directory
when the configuration differs, including when switching the block fallback on
or off; an incompatible owned output is rejected before files are changed.
It includes `behavior_pack/packet_probe/{__init__,modMain,runtime,
aggregate_runtime,numeric_payload,numeric_runtime,spatial_runtime}.py`, copied from the local research runtime. The generated
runtime's `LIMIT` is set from `--slots`; the builder does not modify the source
runtime or start Minecraft.

The builder intentionally does not create `graphics_settings/post_process.json`:
that path replaces the engine's global postprocess configuration, so a file
containing only custom processes removes the built-in process definitions.
Rebuilding an older owned output that still contains that file fails before any
files are changed. Use a fresh output directory to preserve the previous failing
experiment and avoid carrying its global override into a new test.

`--slots` defaults to 8 and accepts 1–4096 independent entity identifiers:
`pmanim_packet:slot_000` through `pmanim_packet:slot_4095`. Names use a minimum
of three digits, so index 1000 naturally becomes `slot_1000`. Every identifier uses
the same one-face/four-vertex plane and shader. The geometry follows the existing
screen-mapped canvas design under a separate `geometry.pmanim_packet` namespace.

## Runtime contract

Register the native screen definition `pmanim_packet_probe.main`. Each slot has
`/slot_<index>/carrier` (Image) followed by `/slot_<index>/canvas` (paperdoll), and a parent
`/slot_<index>` panel. Exact paths, initial offsets, sizes, and identifiers are in
`probe_resources.json`. Every parent panel starts hidden at offset `(0,0)`, with
an initial size of 270×16 logical pixels. This keeps the creation-time layout
bounded even when thousands of slots are present. Runtime `configure` applies
the actual screen rectangle to visible panels and canvases before drawing them.
`configure(0)` leaves all panels hidden and produces no records.

The eight-slot layout retains the verified `(16,32,527,23)` first rectangle at
logical screen size 563×327. Up to 64 slots use readable columns with bounded
gaps. Above 64 slots, `packet_rectangles` chooses columns from the square root of
`count * available_width / (9 * available_height)`: nine horizontal byte cells
make each slot nine times wider than tall. Dense grids use integer logical
rectangles and zero gap, keeping the marker's top 32 pixels clear. A screen too
small for positive dense rectangles is rejected before layout changes.

At logical screen size 563×327 and capture size 2251×1305, the layout stages are:

| Slots | Payload per frame | Columns × rows | Slot size (logical pixels) | Smallest byte cell (physical pixels) |
| --- | --- | --- | --- | --- |
| 8 | 72 bytes | 1 × 8 | 527 × 23 | 234.12 × 91.79 |
| 32 | 288 bytes | 2 × 16 | 261.5 × 14.3828125 | 116.17 × 57.40 |
| 64 | 576 bytes | 4 × 16 | 128.75 × 14.3828125 | 57.20 × 57.40 |
| 256 | 2304 bytes | 8 × 32 | 66 × 9 | 29.32 × 35.92 |
| 1024 | 9216 bytes | 14 × 74 | 37 × 3 | 16.44 × 11.97 |
| 4096 | 36864 bytes | 29 × 142 | 18 × 2 | 8.00 × 7.98 |

These are offline layout and capacity checks. Resource count and screen capacity
do not establish runtime throughput. The runtime records setup time separately
from per-frame payload generation, SDK upload time, and render-frame intervals.

The reports under `.runtime/runtime-packet-scale-report-*` describe the earlier
builder, which always included block fallback controls and assets and used a
different initial layout. Their file counts, resource sizes, and generation
times are legacy measurements and do not describe the current default build.

`python -m unittest discover -s tests -p test_runtime_packet_scale.py -v` checks
every stage's bounds and every byte's 3×3 sample support, the actual runtime's
rectangle/scissor/uniform agreement, four-digit resource names, global layer
pairs, initial hidden panels, and protected-output refusal. It performs one
complete 4096-slot build without starting Minecraft.

The carrier is a white 1×1 RGBA texture with texture alpha zero, while its control
alpha remains one. This avoids explicitly hiding the control or setting control
alpha zero. It does not prove that the engine emits a draw for a transparent
texture; that is part of the experiment. `carrier` and `canvas` receive consecutive
global layers `10+2*i` and `11+2*i`. The screen root stays at layer 1000, isolating
the pairs from ordinary HUD draws that could otherwise overwrite `CURRENT_COLOR`
between a carrier and its consumer. The runtime should also test a visible white
carrier texture to distinguish transparent-draw omission from color reset.

For three integers `r`, `g`, `b` in `[0, 2**24-1]`, call
`carrier.SetSpriteColor((r / 16777216.0, g / 16777216.0, b / 16777216.0))`.
Use different values for every slot and repeat with new values across frames.
Configure the entity uniforms as follows:

| Uniform | Values | Purpose |
| --- | --- | --- |
| `EXTRA_ACTOR_UNIFORM1` | packed R, packed G, packed B, mode | Mode 0 reads `CURRENT_COLOR`; mode 1 directly reads this uniform as a positive control. |
| `EXTRA_ACTOR_UNIFORM3` | left, top, width, height in NDC | Positions the plane at the actual UI rectangle. |

For screen logical size `(W,H)` and absolute canvas rectangle `(x,y,w,h)`, NDC is
`(2*x/W-1, 1-2*y/H, 2*w/W, 2*h/H)`. Keep the paperdoll control rectangle aligned
because native scissor still applies. The shader produces nine equal-width gray
cells: R high/middle/low byte, G high/middle/low byte, B high/middle/low byte.
Each output is `byte/255`, with output alpha one. Sample cell centers with WGC.
The receipt, native panel/canvas sizes, and shader rectangle all use the same
logical rectangle. Capture verification uses those declared coordinates without
searching offsets. The dense 4096-slot boundary still supports the verifier's
full 3×3 interior samples for every byte at the screen/capture sizes above.
The decoder intentionally omits `+0.5`: in float32 that would corrupt odd packed
integers above `2**23`. Any payload channel outside `[0,1)` produces solid magenta
as an invalid-domain sentinel. In particular, default renderer white `1.0` must
remain distinguishable from the valid packed value `0xffffff / 2**24`.

The positive control proves the entity draw, rectangle mapping, decoder, and
capture coordinates work; it does not establish Image-to-entity inheritance.
Record all nine bytes per slot and frame, including mixed-channel values, zero,
`0xffffff`, odd integers above `2**23`, and alternating slot order.

## Two-pass postprocessing diagnostic

`probe_resources.json.postprocess.process` contains the definition for the
disabled effect `pmanim_packet_post`. When explicitly testing postprocessing,
pass that dictionary to `AddPostProcess`, preserving the engine's existing
process list. The API documentation warns that `AddPostProcess` starts the
postprocessing system, so do not call it merely to prepare a UI-only test.
Pass 0 copies `TEXTURE_0` at full resolution; pass 1 copies it again with
configurable inversion. Parameter `invert` occupies
`EXTRA_VECTOR1.x`: zero copies, one returns `1-RGB`, preserving alpha. Both passes
use point filtering and the built-in `shaders/uv_fullscreen.vertex`.

Enable the effect and compare inversion off/on with the scene and the native UI's
red `/post_marker`. A red-to-cyan UI marker would demonstrate that this UI draw is
inside the sampled postprocess path. A changed world with unchanged UI is a useful
negative result. This simple copy/invert probe does not alone establish arbitrary
render-target routing or the precise binding of original versus previous-pass
textures; use an additional pass marker before claiming that capability.

The builder also merges the independent `aggregate_assets.py` producer/display
materials and installs `aggregate.fragment` and `aggregate_display.fragment`.
Their default four-page runtime configuration is stored under `aggregate` in
`probe_resources.json`; these processes are added dynamically by the runtime and
are separate from the copy/invert effect. This lets one cold-started probe
test different producer counts without changing installed shader resources.

## Native block-geometry fallback

This diagnostic is opt-in. Build with `--block-fallback` (or Python
`block_fallback=True`) to add a hidden `/slot_<index>/block_canvas` at the same
layer as each entity canvas. Show only one canvas type per slot. The option also
installs one hidden
`pmanim_packet:block_quad` block, one native block model with a single top-face
quad, the dedicated `terrain.material` routes, and separate `packet_block`
shaders. These block controls, block-specific assets, material, and shaders are
omitted from the default build. All slots can share one combined block
geometry model; there is no need to create hundreds of identical native meshes.

`netease:render_layer` accepts a fixed set of material routes, not arbitrary
material names. The independent `pmanim_packet_block` material therefore requires
redirecting the four `netease_block_as_mesh_blend*` entry points inside this
isolated RP's new `terrain.material`. This affects block geometry using those
routes in this probe pack. It must not be merged into a production RP. Existing
entity and postprocess material definitions are separate.

The minimal Python 2 runtime sequence uses byte `str` keys and identifiers:

```python
import mod.client.extraClientApi as clientApi

factory = clientApi.GetEngineCompFactory()
level = clientApi.GetLevelId()
palette = factory.CreateBlock(level).GetBlankBlockPalette()
palette_data = {
    'extra': {}, 'actor': {}, 'void': False,
    'volume': (2, 2, 2),
    'common': {('pmanim_packet:block_quad', 0): [0]},
    'eliminateAir': True,
}
if palette is not None and palette.DeserializeBlockPalette(palette_data):
    geometry_name = factory.CreateBlockGeometry(level).CombineBlockPaletteToGeometry(
        palette, 'pmanim_packet_quad', 0)
    if geometry_name:
        # Repeat only this control setup for each slot; reuse geometry_name.
        ui.GetBaseUIControl('/slot_000/canvas').SetVisible(False, False)
        carrier = ui.GetBaseUIControl('/slot_000/carrier').asImage()
        carrier.SetSpriteColor((0x123456 / 16777216.0,
                                0x789abc / 16777216.0,
                                0xdef123 / 16777216.0))
        target = ui.GetBaseUIControl('/slot_000/block_canvas')
        target.SetVisible(True, False)
        ok = target.asNeteasePaperDoll().RenderBlockGeometryModel({
            'block_geometry_model_name': geometry_name,
            'scale': 1.0, 'init_rot_x': 90.0,
            'init_rot_y': 0.0, 'init_rot_z': 0.0,
        })
```

Rebuild the combined mesh on each game entry, as required by the API. Cache it
within that session. This fallback deliberately does not depend on `GetModelId`
or actor uniforms: the documented paperdoll `GetModelId` contract describes
skeletal models and does not guarantee block-geometry support.

The block vertex keeps native `WORLDVIEWPROJ` XY framing and removes unrelated
depth clipping by setting clip-space Z to zero. It derives strip coordinates
from the calibrated first BBE grid quad (`POSITION.xz + 1`) instead of atlas UVs.
The fragment reads only `CURRENT_COLOR`, emits the same nine byte strips, and
uses magenta for out-of-domain values including `1.0`.

Initially use one larger control (for example 180×180), rotation X=90, and a
payload whose nine bytes are visibly different. Find the rendered plane's true
left/right edges from the capture, then sample nine evenly spaced centers within
that plane. Native framing does not guarantee that the plane fills the control;
adjust control position/scale only after observing its bounds. The `(2,2,2)`
palette dimensions and source quad origin must stay unchanged while validating
`POSITION.xz + 1`. Reverse strip order or clipped/missing cells must be recorded,
not treated as a successful byte comparison. This is a separate inheritance
test, not evidence that the entity route works.

## Sources and verification boundary

The resource field shapes follow the existing `tools/ui_canvas_probe` fixture.
MCDK documentation was checked for `SetSpriteColor`, JSON UI Image fields,
custom postprocess `pass_array`/`render_target`/`paras`, and vanilla
`uniformShaderConstants.h` (`CURRENT_COLOR`). The API documentation guarantees
RGB values in `[0,1]`; it does not guarantee exact float precision or inheritance
between renderer types. Desktop GLSL compilation/decoding checks are separate
from real Minecraft/WGC acceptance. No game pass is implied by generating files.

Offline validation on 2026-11-17 compiled the packet vertex and all three packet
fragments under desktop GLSL 330, 400, and 450. For each dialect, OpenGL readback
matched all nine bytes for 291 triples in both CURRENT_COLOR and actor-uniform
modes (5,238 byte cells per dialect), including every low byte above `0x800000`,
boundary values, and deterministic random values. `1.0` produced the magenta
sentinel in both modes. This adapts the engine includes and does not verify
Minecraft's actual CURRENT_COLOR inheritance. Aggregate shader verification is
tracked independently by the aggregation fixture owner.

## Owned runtime and numeric experiments

`host.py` wraps launch/call/capture/stop with the `manim-runtime-packets` owner,
project and process identity checks, protected background windows and a 60 FPS
configuration cap. A launch requires this repository's existing background tool
configuration and a valid `.mcdev.json` in the generated project. It never
activates the game. A configured 60 FPS cap does not imply measured 60 FPS.
Use a fresh evidence directory for a new launch; do not overwrite previous
launch receipts or retry timed-out mutations without inspecting current state.

`run_case.py` measures an already owned instance. UI cases open/configure the
screen; aggregate cases require the chosen chain to have completed setup and
`finish()` on a later render turn. The final capture checks every byte of one
frozen payload and does not verify every frame during the timing interval.

`numeric_payload.py` is a pure Python 2/3 float32 codec. `numeric_runtime.py`
adds a 16-byte in-band header, uploads all allocated pages and clears unused
capacity. It rejects NaN/Inf, malformed values and overcapacity before uploading.
SDK failure invalidates/disables the chain instead of exposing mixed batches.
It preserves float32 bits; shader arithmetic decoding is not part of the test.

After explicitly installing/finishing a chain with up to 1024 pages:

```powershell
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/run_numeric_stream.py --project .runtime/runtime-packet-study/project-v11 --evidence .runtime/runtime-packet-study/v11 --total 100000
```

The command generates each chunk inside game Python, waits for a fresh background
WGC capture, checks all cells and independently reconstructs expected float32
bytes with `struct`. It reuses the existing launch receipt in the evidence
directory, refuses an existing stream result, and hashes the reassembled observed
payload. Wall time includes RPC/capture and must not be reported as bandwidth.
The sample v11 instance is now stopped; the command above documents the recorded
run, not a promise that the old session remains available.

`verify_numeric_sequence.py --help` describes offline independent rechecking of
the nine saved v11 variable-length/special-value captures and recorded commands.
It rereads PNG pixels and never uses uploaded words as its expected data.

Runtime tests, protocol negative tests, resource bounds and desktop GPU tests:

```powershell
.venv-reference/Scripts/python.exe -B -X utf8 -m unittest discover -s tests -p 'test_runtime_packet*.py' -v
```

Generated resources and full raw evidence stay in `.runtime/`; only source,
tests, compact reports and small capture examples are committed. The optional
block fallback, copy/inversion/UI inclusion diagnostic and new bulk PNG/RawPath
candidate do not acquire game validation from the atlas/carrier results.

## Portrait 2D atlas and split-uniform experiments

These experiments default to a **720×1080 physical client area**. This is a
desktop portrait test profile, not actual mobile hardware. Build every required
shader, material, entity and UI definition before a cold launch; Python reload
does not install new resource paths. The base builder supplies `spatial_runtime`;
`build_uniform_ui_assets` additionally installs `uniform_ui_runtime`.

| Builder/configuration | Data path | Cost represented by the configuration |
| --- | --- | --- |
| `atlas2d_assets.build_atlas2d_assets` / `atlas2d_config` | Eight uint24 words per page accumulate in a 2D render target; one consumer selects display windows | Two payload vec4 values per producer; one producer pass per page plus the consumer |
| `uniform_split_assets.build_uniform_split_assets` / `uniform_split_config` | Independently named postprocesses draw their own tiles and copy `TEXTURE_0` elsewhere | Two payload vec4 values per process; every process still draws the full screen |
| `uniform_ui_assets.build_uniform_ui_assets` / `uniform_ui_config` | Independent actor uniforms drive paperdoll tiles, with zero Image carriers and no postprocess | At most 64 paperdoll slots per screen, each with a parent panel; multiple small screens are created in separate render turns |

Split mode `shader_mode='shared'` uses one shader/material resource;
`'distinct'` generates separate shader/material paths per process. Both have
independent process parameter names. Neither increases one shader's uniform
capacity or proves that the driver creates distinct machine code. Generator
allocation guards and splitting screens do not establish an engine-wide limit.

The following host-only PowerShell example builds all three resource families
and writes install commands. Use a fresh project directory. The modest counts
make the example reproducible; change them before launch for a new scale.

```powershell
@'
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path('tools/runtime_packet_probe').resolve()))
from build_probe import build
from atlas2d_assets import build_atlas2d_assets
from uniform_split_assets import build_uniform_split_assets
from uniform_ui_assets import build_uniform_ui_assets

project = build(Path('.runtime/runtime-packet-2d-example'), slots=8)
resource = project / 'resource_pack'
commands = project / 'commands'
commands.mkdir(exist_ok=True)
configs = {
    'atlas2d_128': build_atlas2d_assets(resource, 128, screen_size=(720, 1080), display_count=64),
    'split_shared_64': build_uniform_split_assets(resource, 64, shader_mode='shared'),
    'split_distinct_64': build_uniform_split_assets(resource, 64, shader_mode='distinct'),
    'uniform_ui_128': build_uniform_ui_assets(resource, 128, slots_per_screen=64),
}
for name, config in configs.items():
    (project / (name + '.config.json')).write_text(json.dumps(config, indent=2), encoding='utf-8')
    code = "if probe.run is not None:\n    raise RuntimeError('Finish active benchmark first')\n"
    if config['transport'] == 'uniform_ui':
        code += 'from packet_probe.uniform_ui_runtime import UniformUIProbe\nprobe.close()\n'
        code += 'probe.aggregation=UniformUIProbe(%r,54321)\n' % config
        code += '_result=json.dumps(probe.aggregation.snapshot())\n'
    else:
        code += '_result=json.dumps(probe.setup_aggregate(%r,54321))\n' % config
    (commands / (name + '_install.py')).write_text(code, encoding='utf-8')
(commands / 'finish.py').write_text('_result=json.dumps(probe.aggregation.finish())\n', encoding='utf-8')
(commands / 'create_next.py').write_text(
    "if any(not screen.ready for screen in probe.aggregation.screens):\n"
    "    raise RuntimeError('Wait for the previous Create callback')\n"
    "probe.aggregation.create_next()\n_result=json.dumps(probe.aggregation.snapshot())\n", encoding='utf-8')
'@ | .venv-reference/Scripts/python.exe -B -X utf8 -
```

Configure the generated project's `.mcdev.json` to load its BP/RP using the
existing launcher setup; `host.py launch` also requires this repository's
`background-tools.local.json`. Cold-launch, resize through the owner-bound host,
and confirm both the returned client dimensions and a fresh WGC PNG are exactly
720×1080 before installing a case. `GetScreenSize()` can report different logical
UI dimensions; the config's `screen_size` and verifier use physical pixels.

```powershell
$packetProject = '.runtime/runtime-packet-2d-example'
$packetEvidence = '.runtime/runtime-packet-2d-example-evidence'
$packetCommands = "$packetProject/commands"
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/host.py launch --project $packetProject --evidence $packetEvidence
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/host.py resize --project $packetProject --evidence $packetEvidence --width 720 --height 1080
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/host.py capture --project $packetProject --evidence $packetEvidence --label portrait_ready
.venv-reference/Scripts/python.exe -c "from PIL import Image; im=Image.open('$packetEvidence/portrait_ready.png'); print(im.size); assert im.size==(720,1080)"
```

For atlas2d or either split variant, `setup_aggregate` automatically selects
`SpatialProbe`. Install the chosen config, allow a later render turn, then call
`finish()` and require `ready=true`, `enabled=true`, `error=null` before running.
The same sequence applies to `split_shared_64_install.py` and
`split_distinct_64_install.py`; use fresh case names for each result.

```powershell
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/host.py call --project $packetProject --evidence $packetEvidence --label atlas_install --code "$packetCommands/atlas2d_128_install.py"
# After a later render turn:
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/host.py call --project $packetProject --evidence $packetEvidence --label atlas_finish --code "$packetCommands/finish.py"
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/run_spatial_case.py --project $packetProject --evidence $packetEvidence --name atlas_static --seconds 12 --static
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/run_spatial_case.py --project $packetProject --evidence $packetEvidence --name atlas_dynamic --seconds 12
```

For direct UI uniforms, install `uniform_ui_128_install.py`, then call
`create_next.py` **once per render turn**, checking that the preceding screen's
Create callback completed. The 128-slot example needs two such calls, creating
one screen with 64 paperdoll slots each. Use unique labels such as `ui_create_0` and
`ui_create_1`; preserve their receipts. Do not use `create_all()` for this
experiment. In another render turn, call `finish.py`; only after all slices are
ready may the same runner measure separate static and dynamic 12-second cases.

```powershell
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/host.py call --project $packetProject --evidence $packetEvidence --label ui_install --code "$packetCommands/uniform_ui_128_install.py"
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/host.py call --project $packetProject --evidence $packetEvidence --label ui_create_0 --code "$packetCommands/create_next.py"
# After that screen's Create callback and a later render turn:
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/host.py call --project $packetProject --evidence $packetEvidence --label ui_create_1 --code "$packetCommands/create_next.py"
# After all Create callbacks complete, in a later render turn:
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/host.py call --project $packetProject --evidence $packetEvidence --label ui_finish --code "$packetCommands/finish.py"
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/run_spatial_case.py --project $packetProject --evidence $packetEvidence --name ui_static --seconds 12 --static
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/run_spatial_case.py --project $packetProject --evidence $packetEvidence --name ui_dynamic --seconds 12
```

`run_spatial_case.py` requires an installed, finished, enabled payload. It freezes
the final generation after timing, independently reconstructs every expected word
from the recorded seed, and uses `verify_spatial.py` to check every byte with zero
tolerance at fixed declared coordinates. Atlas pagination changes only the consumer
query; it never replaces the payload between windows. Complete coverage includes
the last partial window and a combined observed/expected payload digest. Split
and UI cases check all tiles in one capture. This verifies all resident bytes of
one frozen generation, not every timed frame or a GPU-to-Python readback API.

The runner persists `<name>.case.json` on success or handled failure, including
`status`, `stage`, `error` and cleanup results; retain command logs and partial
captures when a case fails. Setup failures before invoking the runner must also
be recorded with their stage/error rather than counted as a throughput result.
The launcher configures a 60 FPS cap; report actual render intervals and a fresh
baseline after external frame limits change. No example here promises 60 FPS,
mobile-device performance, a universal engine limit, or production readiness.

Before writing, the runner requires `HideCrossHairGUI(True)` to succeed. The
native crosshair can invert pixels after the postprocess output; hiding it keeps
the fixed-coordinate RGB/alpha checks strict. The first contaminated 1024-page
capture remains recorded as a failed case, separately from its successful rerun.

An independent verifier can recheck the saved evidence without importing the
production oracle or using receipt words as expected pixel values:

```powershell
.venv-reference/Scripts/python.exe -B -X utf8 tools/runtime_packet_probe/verify_spatial_evidence.py --evidence .runtime/runtime-packet-study2d --output docs/evidence/runtime-packets2d/independent-verification.json
```
