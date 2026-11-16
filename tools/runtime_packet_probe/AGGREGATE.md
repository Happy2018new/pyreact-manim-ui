# GPU packet atlas probe

This development-only probe tests Python parameters → small render targets → an
indexed atlas consumer. It does not capture JSON UI or use previous-frame data.
It is separate from the CURRENT_COLOR / transparent Image probe.
The measured game results, independent numeric protocol checks, evidence index,
and remaining bulk-transfer limits are recorded in
[the runtime data research report](../../docs/RUNTIME_PACKET_RESEARCH.md).

Each producer is one custom postprocess with one pass. Its `paras` order is
exactly `page`, `packet0`, `packet1`: `EXTRA_VECTOR1` is
`[page_index, page_count, 8, 0]`, and `EXTRA_VECTOR2..3` carry eight unsigned
24-bit integers normalized by `2^24` (24 bytes). The producer expands each integer into three
8-bit RGB channels. Page zero clears all other rows; later pages read the prior
producer's `TEXTURE_3`, replacing only their own row. Every frame rebuilds the
atlas, while unchanged Python parameters can remain retained by the engine.

`aggregate_config(page_count, screen_size, words)` accepts 1–1024 pages and
returns plain dictionaries for `AddPostProcess`, connection argument lists, producer names, and expected
bytes. The config explicitly sets `words_per_page=8`; receipts for this layout
must retain that field so byte verifiers can distinguish older 12-word evidence.
`words` is `page_count` lists of eight uint24 integers. The host generator
uses a deterministic diagnostic pattern when omitted. Supply the actual physical
screen size so the target ratios describe 32 × (4 × page_count) pixels.
Producer metadata and consumer query parameter ranges extend through 1024.
The target ratios clamp at 1.0: 1024 pages request a 32 × 4096 target, but a
1305-pixel-high physical screen creates a 32 × 1305 atlas. Every page requires
at least one atlas texel row, and exact-byte screenshots also require at least
one displayed pixel row per page. Therefore a 1024-page config on the default
720-pixel-high screen cannot represent every page. Supply the actual screen
size and a sufficiently tall display rectangle. The 1024-page generator limit
does not establish support for larger page counts.

This layout deliberately leaves `EXTRA_VECTOR4` unused. In the installed
3.10.0.448891 client, original postprocess shaders including
`vanilla_netease/shaders/glsl/gaussianblur_horizontal.fragment` and
`gaussianblur_vertical.fragment` identify U4 as engine ScreenInfo:
`[width, height, pixelWidth, pixelHeight]`. Earlier 12-word experiments put page
metadata in U4; their game GPU output repeatedly copied the connected black or
white `TEXTURE_3`, even while `GetParameter` returned the requested metadata.
Those results and captures remain evidence of the old layout's failure. The
revised layout has separate successful game captures described below. The generic documentation's sequential
`EXTRA_VECTOR1..4` description alone did not establish U4 ownership on this client.

The game-side runtime installs `config['processes']` in array order, using native
Python 2 byte-string definitions. It checks every `AddPostProcess` result and
keeps the new processes enabled. In a later host call/render turn, `finish()`
checks the installed order, restores metadata, generates/uploads fresh data in
game Python, and connects every five-element argument list with
`post.PostPassResultToOtherPass(*connection)`. Every connection must succeed.
Only then is the setup ready for benchmarking; API readiness does not establish
correct GPU pixels. Disable every process from the previous chain before
changing scale. Reused process names require restoring all control parameters.
Failed setup retains the touched names and attempts cleanup of all of them.

Updating a page uses `SetParameter(producer_name, 'packet0', values)` (and
`packet1`), where each `values` list has four `uint24 / 16777216.0`
numbers. These are dyadic fractions exact in float32, including the boundary
words 8388609 and 16777215. There is no `+0.5` in integer recovery. The final
consumer receives only page count/query geometry, never the producer payload.

The final display rectangle defaults to `[0.05, 0.05, 0.90, 0.90]` in top-left
screen coordinates. It contains `page_count` rows × 24 grayscale byte cells.
Each row shows eight words in high-byte, middle-byte, low-byte order. Sampling is at
the atlas cell centers, with point filtering. The consumer's `query` parameter
is `[page_count, row_shift, word_shift, byte_shift]`; nonzero offsets demonstrate
independent indexed reads of earlier pages. Its `display_rect` parameter sets
the visible rectangle. These parameters map to `EXTRA_VECTOR1` and
`EXTRA_VECTOR2`, respectively; the display shader uses a fixed eight words per
page and never reads U4. Outside the rectangle it samples original `TEXTURE_1`.

The diagnostic scales are 1, 4, 16, 64, 256, and 1024 producers
(24, 96, 384, 1536, 6144, and 24576 bytes respectively), plus one final display
pass. The upper two capacities are 6 KiB and 24 KiB. This scales payload capacity
but also native draw calls and framebuffer transitions; it is not a promise of 60 FPS. Record API timing,
frame timing, exact decoded bytes, and lifecycle behavior separately. A positive
API return does not prove correct pixels or RenderTarget retention. Desktop
OpenGL tests verify the codec/shader math and dependency chain only. Game-side
correctness and frame costs were measured separately under the conditions below.

The focused offline regression is:

```powershell
& '.venv-reference/Scripts/python.exe' -B -X utf8 -m unittest discover -s tests -p test_runtime_packet_aggregate.py -v
```

It compiles the actual producer and consumer fragment sources with the desktop
adapter, uploads the generated `paras` in order, renders to GPU framebuffers,
and compares every grayscale byte. The 1/4/16/64/256-page cases cover base reads,
row/word/channel query shifts including wrapping, and an explicitly bound black
texture in place of the final source. Multi-page cases also substitute black
for one intermediate source and check that earlier rows disappear while later
rows survive. These are deterministic wrong-source controls, not a simulation
of the engine's unspecified unconnected-slot contents. Separate GPU boundary
cases include 8388609 and 16777215, where adding 0.5 before `floor` would corrupt
some uint24 values. When `moderngl` is unavailable these GPU cases are skipped;
that outcome must not be reported as GPU verification. The harness calculates
actual atlas dimensions from the clamped ratios and screen size: the 256-page
default case uses a 32 × 720 atlas, not its requested 32 × 1024 target. The
1024-page regression uses a 32 × 1305 atlas and 24 × 1305 display, checks all
1305 physical display rows against the byte pattern, confirms every page is
represented, and binds a black final source as a negative control.

Offline run on 2026-11-17 after the 1024-page extension: all eleven tests passed,
including all seven GPU tests, with no skips. The standalone context reported `NVIDIA Corporation`,
`NVIDIA GeForce RTX 4060 Laptop GPU/PCIe/SSE2`, and
`3.3.0 NVIDIA 616.64`. This is desktop GPU evidence for the revised shader math
and atlas dependencies, separate from the earlier game captures.

Game tests on client `3.10.0.448891` verified every byte at 1/4/16/64/256/1024
pages: 24/96/384/1536/6144/24576 bytes. The 1024-page case passed static data,
the frozen final batch after dynamic updates, and row/word/byte query changes,
each checking all 24576 bytes. This establishes a maximum verified resident
batch of 24 KiB, not an unlimited runtime buffer. Dynamic runs validate the
frozen final batch rather than every intermediate frame. A later stream of
100000 float32 values passed in 17 separately verified batches, totaling
400000 effective bytes; it replaces the same atlas and does not make those
values simultaneously resident. The report above records the protocol and
independent per-batch verification.

At 1024 pages, the implementation renders 1024 producer passes plus one
consumer and performs 2048 payload `SetParameter` calls for each full update.
The background noactivation instance measured 18.57 FPS with static data and
13.02 FPS with data generated and uploaded on every render event; the same
environment's baseline was about 20 FPS. Its frame cap was configured to 60,
but these are measurements in a background environment, not evidence of
60 FPS operation. The RTX 4060 Laptop GPU test used a 2251 × 1305 WGC frame;
the 1024-page atlas was 32 × 1305. See the report for frame intervals, CPU timing,
sample counts, and evidence paths. SDK upload timing is CPU call time and does
not wait for GPU completion.

An isolated v11 sentinel experiment separately tested explicit source selection.
All old producers and displays were disabled. Only two single-page producers
A and B and one display consumer C were enabled, with execution order A < B < C.
A used a 32 × 4 target and B a 64 × 8 target; both used page metadata
`[0,1,8,0]`, so each wrote its entire target without sampling an input texture.
Before any connection, C differed from expected A at 21 of 24 bytes. The first
and only A→C connection then produced all 24 bytes exactly. Changing only A made
C follow the new A; changing only B left C equal to A. Setting C's word shift
to 3 and byte shift to 1 produced the exact queried permutation. The
`sentinel*` captures and reports in the v11 evidence support explicit selection
of a nonadjacent source independently of data upload correctness.

Two earlier v11 checks—reconnecting an existing consumer to the first producer,
and adding a new unconnected consumer—still showed a complete atlas. The old
display remained enabled, and execution order was not confirmed for those
checks, so neither counts as a valid missing-connection control. A subsequent
isolated unconnected-consumer check still had a wrong row; unconnected contents
are not a reliable source. Public documentation guarantees neither black
unconnected slots nor replacement semantics for repeated connections to a slot.
The successful sentinel experiment avoids both assumptions by using a fresh
consumer, one initial connection, distinct producer data, and one visible display.

Any game runtime that still builds three packet vec4 values,
uploads `[page, count, 12, 0]`, or omits receipt `words_per_page=8` must be migrated
before testing this revision. Existing generated probe copies are separate
assets and must not be mistaken for the updated source files.

## Documentation basis

Queried through `mcdk-assistant.minecraft_docs` before implementation:

- `read ModAPI/接口/后处理/自定义.md`: `AddPostProcess`, `SetParameter`,
  `SetEnableByName`, `PostPassResultToOtherPass`, `GetPostProcessOrder`.
- `api PostPassResultToOtherPass`: source pass must execute before destination;
  source/destination process may be identical; destination texture slot is 3–7.
  Slot 0 is prior pass color, 1 is original color, 2 is depth. This API documents
  forward pass dependencies, not feedback or previous-frame retention.
- `api InsertPassToPostprocess`: render target width/height are screen-relative
  fractions in `(0, 1]`; pass outputs are chained; only custom postprocesses.
- `read NeteaseGuide/mcguide/16-美术/7-材质与着色器/4-材质实战.md`:
  `paras` packs sequentially into `EXTRA_VECTOR1..4`; `bindTexture` binds fixed
  resource paths, with slots 2–7 if depth is disabled and 3–7 if enabled.
- `read NeteaseGuide/mcguide/16-美术/7-材质与着色器/3-材质配置说明.md`:
  `samplerStates`, `Point`, `Clamp`, and render states.

UI documentation does not state whether HUD/JSON UI are in the postprocess
inputs. `RenderEntity` and `RenderSkeletonModel` return success flags rather
than texture handles; `SetSprite` accepts a resource texture path. Searching
these docs did not establish a general UI-to-render-target interface. This is
a documentation gap, not a claim that the engine cannot support such a path.

For the UI route, separately render a known UI marker and sample its location
through `TEXTURE_0` / `TEXTURE_1` into a different screen region. Repeat with
ordinary HUD, paperdoll, and world-bound UI. A later UI overlay can otherwise
make a global inversion test appear misleading.
