# In-memory RGB input and 32-alpha scene codec experiment

This isolated research package tests the combination of an in-memory geometry
RGB carrier and an independently decoded alpha block. It does not modify the
older `tools/geometry_atlas_probe` or product resources. Game Python builds a
`bytearray`, packs its symbols into the existing compact8 block palette, and
calls the public native geometry APIs. Game Python never writes a file.

The native writer blends RGB using SourceAlpha/OneMinusSrcAlpha and preserves
the scene alpha. With k=1/2, each 32-pixel block transports 12/24 payload bytes.
The next shader restores RGB, stores a 4-byte exception mask and four alpha
exceptions, and moves the transported bytes into the remaining 24 alpha slots.
The decoder rejects blocks with more than four exceptions. A separate consumer
supports identity, indexed and dependent byte reads from the private texture.
The alpha storage capacity and RGB input bandwidth do not add together.

`codec.py` supplies the pure CPU oracle. `layout.py` plans a finite rectangular
ROI in the native 720x1080 target and separates logical, block-aligned and
allocated bytes. The consumer wraps addresses at the logical length; padding
is zero. The 65,536-byte cases allocate:

| k | Block-aligned bytes | Allocated bytes | Padding | Pixels | ROI columns x rows |
|---|---:|---:|---:|---:|---:|
| 1 | 65,544 | 65,556 | 20 | 174,816 | 288 x 607 |
| 2 | 65,544 | 65,568 | 32 | 87,424 | 128 x 683 |

Native correctness evidence from 2026-11-18 is under
`.runtime/scene-codec-native/evidence-v2`. The following results are verified
from passive WGC captures, with a 60 FPS cap and an owned noactivation game:

- `setup2.results.json`: byte calibration passes for 1,024 large cells and
  1,024 native pixels. All 673,920 pixels in the safe diagnostic rectangle
  match their expected `gl_FragCoord`; four encoded ScreenInfo values match
  width=720, height=1080 and the reciprocal pixel sizes. Every comparison has
  zero channel error. The data rectangle is x=[0,720), y=[128,1064), excluding
  developer overlays and bottom window corners.
- `alpha2.results.json`: the 673,920 safe-region alpha samples display byte
  255, with zero off-byte-grid flags at the shader's 0.0001-byte threshold and
  zero displayed residual. All 21,060 complete blocks have zero exceptions
  against base 255. This gives 505,440 conditional alpha payload bytes in this
  sampled region. It does not establish arbitrary-scene alpha compressibility
  or the underlying texture format.
- `fixtures2.results.json`: 32 captures pass. Both k values restore the ideal
  fixture RGB, original alpha and packed header for zero/four exceptions. All
  three query modes match the independent byte formula. Five-exception and
  varying-alpha fixtures explicitly reject with magenta in decoder/consumer.
  This fixture computes ideal RGB codes in a shader; it is separate from the
  native material blend test.
- `native3k2.results.json`: both native geometry variants recover all 3,072
  bytes in three query modes. Hiding the writer rejects the payload. Repeated
  RGB baselines are stable; restored maximum channel errors are 1/2 for k=1/2.
  Writer-off/on alpha and same-frame decoded alpha comparisons have zero error.
- `native64k2.results.json`: both variants recover all 65,536 logical bytes in
  each query mode and reject the hidden writer. Alpha comparisons have zero
  error. k=1 restores 174,816 pixels with maximum RGB error 1. The first k=2
  restored capture has 1,356 pixels beyond tolerance 2, maximum error 52; this
  failed capture remains in the evidence and is not overwritten.
- `k2_rgb_followup.results.json` and
  `k2_rgb_followup_native_blend_math.json`: without rebuilding geometry, the
  three writer-off captures match each other and the original k=2 baseline.
  The intervening restored capture has maximum error 2. Its native encoded
  RGB matches the integer blend oracle in all 87,424 pixels and all channels,
  including padding, with zero error. This is evidence against repeated
  blending in that steady capture.
- `k2_rgb_steady.results.json`: two further writer-on captures stay within
  error 2; the later writer-off capture differs from the previous baseline in
  555 pixels, maximum error 166. The natural scene can change locally. The
  initial k=2 failure remains unassigned; separated captures do not provide an
  atomic original-RGB baseline.

The native 64 KiB baselines contain 501/701 distinct RGB triples for k=1/2.
They do not exhaust the original byte x=0..255 times every payload symbol. The
observed error bounds therefore apply to these captures. The experiment does
not prove atomic GPU publication, continuous updates or native reclamation.

Formal static FPS uses a new owned instance after the other benchmark has
stopped. Every case holds the same allocated geometry, with 2 seconds warmup
and 25 seconds of samples. The four profiles are plain scene with every native
geometry attachment hidden through `SetActorBlockGeometryVisible` (zero custom
post passes), writer only with only the current native attachment visible
(zero), combo restore
(raw/encode/decode: three), and combo dependent query (those three plus the
consumer: four). The last profile produces 65,536 dependent query results each
frame.
Historical attachments stay hidden. Native visibility receipts record accepted
setter calls; no visibility getter or GPU fence is claimed. The runtime receipt
records actual enabled processes and allocation. Identity/dependent checks run
before measurement and a dependent check runs afterwards, each with 65,536
results and zero byte error. The dependent query reads 48,449 distinct final
addresses; its initial indexed reads visit all 65,536 addresses. It is not a
direct after-measurement identity comparison. No continuous payload uploads
are performed.

The v3 formal results are in `static_k1.results.json` and
`static_k2.results.json`. Every profile has 100 engine FPS samples and
1,500/1,501 render intervals after warmup. Actual pass/visibility controls match
the declared profiles and geometry identity is unchanged. The observations are:

| Profile | Custom passes | k1 mean FPS | k1 interval p99 (ms) | k2 mean FPS | k2 interval p99 (ms) |
|---|---:|---:|---:|---:|---:|
| Baseline, native attachments hidden | 0 | 60.0682 | 18.1193 | 60.0596 | 18.2341 |
| Native writer only | 0 | 60.0775 | 18.1226 | 60.0689 | 18.2397 |
| Combo restore | 3 | 60.0775 | 18.1052 | 60.0752 | 18.2655 |
| Combo dependent query | 4 | 60.0775 | 18.2245 | 60.0729 | 18.3277 |

All eight interval means are near 16.67 ms and none of the sampled intervals
exceeds 25 ms; the largest individual interval is 24.2669 ms. This is a capped
static observation for this device/scene, not a GPU headroom estimate. k1 holds
one native name and 174,816 records. k2 retains the hidden k1 allocation and
holds two names, 262,240 records total; each k2 profile uses the same allocation.
Native reclamation is unverified.

`formal_quiesce.state.json` records no active owned post effects, both native
attachments hidden, entity destroyed and no active measurement/updates.
`formal_exit_check.json` records PID 35024 absent from Win32_Process after
owner-verified shutdown. The launch receipt verifies the 60 FPS cap and owned
noactivation session. Single-benchmark scheduling was coordinated by the root
agent after the alpha benchmark exited; this package does not contain a
separate prelaunch census of all processes.

Host-only commands, from the repository root:

```powershell
.venv-reference/Scripts/python.exe -B -m unittest discover -s tools/scene_codec_probe/tests
.venv-reference/Scripts/python.exe -B tools/scene_codec_probe/build_probe.py --output .runtime/scene-codec-native/project-v3
```

`host.py launch` creates one owner-bound instance named `manim-scene-codec`;
launch requires a fresh evidence directory. `runner.py` never launches a game.
Run its `setup`, `alpha`, `fixtures`, `native` or `static` stage against an
already owned instance. `static --bits 1/2 --bytes 65536 --seconds 25` requires
the static-measurement runtime in project-v3. Game calls and captures are
passive; the explicit user-foreground exception does not allow agent focus,
activation, window restoration or desktop input.
