# Large in-memory RGB /32-alpha codec

This directory is separate from `tools/scene_codec_probe`. It snapshots that
probe's pure CPU codec and alpha encode/decode shaders at build time, hashes the
explicit input list in `source_manifest.json` and embeds that bundle identity in
runtime receipts. The bundle does not cover every transitive base-builder input
or by itself identify the complete generated package. It never changes the
source probe. The builder and tests do not start Minecraft. Native execution
must wait for the root agent's phase3 authorization, after the RGB investigation
and real-alpha/native-effects compatibility work finish.

The large writer has its own fixed-k2 fragment and reads no actor uniforms.
In particular`G4.w`is exclusively the vertex page base; experimental background
branches in the earlier probe cannot interpret nonzero page bases as switches.
The builder and a regression enforce this shader contract.

The format is RGB k2: each pixel transports6bits through native material blend.
The alpha encoder restores low-precision RGB, stores a4-byte exception mask and
four alpha exceptions in8alpha slots, and moves24payload bytes into the other24
slots of each32-pixel block. Blocks with more than4exceptions explicitly reject.
Payload transport and compressed-alpha storage describe the same bytes; their
capacities are not additive. Original alpha precision and native-effects
compatibility remain governed by the earlier phase's evidence.

## Dimensions and geometry bounds

512KiB requires `ceil(524288/24)*32 = 699072` source pixels. The native720×1080
safe band y=[128,1064) has673920pixels, conditionally505440payload bytes, which
does not fit. This fixture uses1080×1440 and controlled704-column source rows:

| Logical bytes | Source ROI `[x,y,width,height]` | Source records | Allocated payload | Padding | Geometry pages |
|---:|---|---:|---:|---:|---:|
|262144 (256KiB)|`[8,128,704,497]`|349888|262416|272|6|
|524288 (512KiB)|`[8,128,704,993]`|699072|524304|16|11|

A geometry page has at most65536 Qrecords, or49152payload bytes (48KiB), and
always starts/ends on32-pixel/24-byte block boundaries. A logical64KiB page
would require87382records and raise the current encoder stride to512. The
record-bounded choice keeps stride≤256 and palette height16. The final page
is partial but block aligned. No block header crosses pages. `G4.w` adds the
global record base after local bounds checking; `G4.z=2` remains RGB k.

Game Python generates the real payload in memory from seed54321,generation1
and the global byte address, packs Qrecords and calls Deserialize/Combine/attach
once per page. Tail padding is zero and is not addressable as logical data.
Each page gets an anchor and a unique native geometry name. There is no game
payload file output. Page content sum32, geometry identity and upload serial
are recorded; the host separately generates per-page SHA256 values.

Temporary Python payload+symbols are bounded to49152+65536bytes per page, plus
the existing encoder's lists/dicts/integers. Native allocation size and GPU
vertex format are unknown. Declared palette volume is a coordinate-space
bound, not a native memory measurement. Historical geometry is retained and
hidden. The two-capacity run therefore ends with17allocated pages/anchors;
every static profile of a particular capacity uses the same allocations.

CPU tests exhaust every logical address for256/512KiB using independent
integer arithmetic and float32 simulations. The indexed mapping uses131j+29
modN, which is a permutation for both power-of-two lengths. Its initial
multiply is at most16*(524287)<2^23; all later intermediates stay below2^24.
The dependent address uses the first sampled byte. Tests also cover every
source pixel center, full-array page packing/unpacking, nonzero global page
offsets, zero tail padding, alpha masks/overflow and final-pixel/border errors.
CPU correctness is not a native blend/texture precision claim.

## Native correctness and static profiles

The diagnostic uses1024columns starting at[8,128], one native pixel per query.
512KiB needs512diagnostic rows. Source integrity diagnostics remap all699072
records, including header and padding, into the same1024-column diagnostic
grid. Every valid pixel and every nonquery pixel of guard[0,128,1080,1408) is
checked at zero tolerance. Developer UI above128 and bottom window corners
are outside this guard; no data pixel is excluded.

Each capacity is checked before and after static measurements with full
identity and dependent scans, plus same-frame decoded-alpha/raw-alpha
integrity over every source record. Hidden native attachments must break the
payload; restoring them must pass. A different-generation oracle must reject
the same native PNG. Every query and measurement freezes seed/generation,
all page names/entities, byte fingerprints, bases and upload serials. No
continuous updates or automatic replay of timed-out mutations is supported.

| Static profile | Native writer | Enabled custom passes | Diagnostic gathers |
|---|---|---|---|
|copy baseline|All attachments natively hidden|raw copy:1|0|
|writer + copy|Current dataset pages|raw copy:1|0|
|restore|Current dataset pages|raw/encode/decode:3|0|
|dependent|Current dataset pages|those3+consumer:4|Ndependent queries/frame|

Default windows are2s warmup+25s sampling, with raw GetFps values and render
interval vectors retained for independent recomputation. The global cap is60.
Baseline retains the same memory and anchors as the other profiles of that
dataset. Previous dataset attachments remain hidden in every profile.
The copy pass remains enabled during profile changes so the engine does not
rebuild the dynamic chain after the last custom process stops. Actual process
order and enabled getters are saved and checked before captures and sampling.
Native post effects must actually be disabled before exact correctness or
isolated static comparison. `SetEnableByName('bloom',False)` can return success
while bloom stays enabled and all dynamic processes disappear. Use
`--native-effects-off-data-root <native data>` for the isolated build: it copies
the native post-process config and changes only each process's enable flag to
false. Source/generated hashes, native names and preservation of render order
are recorded. Runtime receipts record original and actual states; the runner
rejects any enabled native effect before correctness or FPS. This isolation
does not establish rain, bloom, or other native-effects compatibility.

An optional`--native-data-root ... --logical-bytes262144/524288`build invokes
the separate`scene_codec_compat_probe.build_overlay`tool in its own sibling
directory, then uses its host installer to merge materials. Native effect
parameters, pass counts and alpha math remain owned by that tool. The ROI is
compile fixed, so each capacity requires its own project/overlay. Runtime
rejects another capacity; using a maximum ROI to decode uncovered RGB is
forbidden. The source builder hash and overlay manifest are retained. Default
exact correctness/static profiles still disable native effects, even when the
overlay is installed. Enabling effects for compatibility performance requires
the earlier phase's explicit profile integration. An identity baseline uses a
separate build with`--identity-native-overlay`; it cannot reuse an active
carrier decoder on a writer-free scene.

Host preparation commands (no game start):

```powershell
python -B -X utf8 -m unittest discover -s tests -p test_scene_codec_large_probe.py -v
python -B -X utf8 tools/scene_codec_large_probe/build_probe.py --output .runtime/scene-codec-large-OFFLINE/project
# For isolated native execution, add --native-effects-off-data-root <native data>.
```

After explicit phase3 authorization only, the owner-bound host can launch and
resize to1080×1440. Write its resize receipt as`evidence/resize_native.json`,
then run`runner.py --project ... --evidence ...`. The runner never launches a
game and checks that receipt before any native upload. `--correctness-only`
skips all static samples. A fresh evidence directory is required; prior errors
and captures are preserved. Available system commit must remain at least4GiB.

The authorized 2026-11-18 isolated run is saved under
`.runtime/scene-codec-large-native-20261118-r2/evidence/large_codec.results.json`.
Both capacities passed all before/after identity, dependent and source-integrity
checks with zero query or guard errors, including all699072 source pixels for
512KiB. Hidden native geometry failed as expected, restored geometry passed,
and all10wrong-generation oracle checks failed. All8static windows retain the
full raw vectors. This establishes this fixed-clear-weather isolated fixture;
rain and native-effects compatibility remain separate unresolved questions.

The512KiB GetFps means were60.07826/60.07751/60.07751/60.07751 for
copy baseline/writer+copy/restore/dependent. Corresponding mean render
intervals were16.66802/16.66685/16.66659/16.66641ms. A60cap masks headroom;
these windows do not measure uncapped throughput or GPU execution time.
The256KiB restore window had one90.6435ms interval; it is retained without
resampling. No other window had an interval above33.3ms.

The earlier r1 run remains preserved as failed:256KiB correctness passed,
but the native bloom state remained true, and the runner rejected the first
static profile before recording FPS. The r2 startup resource config made all
nine reported native flags false, and persistent copy profiles avoided the
all-custom-off chain reset. The running r2 package predates the source runtime's
copy-profile adjustment; hashed explicit host controls implement its equivalent
1pass profiles in game memory. `host_control_sources.json` records this detail.
