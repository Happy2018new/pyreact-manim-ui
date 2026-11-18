# Bounded two-bit, arbitrary 64-byte stencil bridge

This extends the one-bit fixture with two independent geometry bitplanes and three late FrameAni draws. It remains a small research probe. No 512 KiB capacity, frame-time, throughput, continuous-update, cross-device, or reserved-stencil-bit result is established.

The host passes three actual arrays of 64 integer bytes: a boundary array and two SHA-512 digests transmitted as complete byte lists. The receiver shader contains no payload seed. The encoder splits each byte into four little-endian two-bit symbols, giving 256 records. Two memory-resident compact8 geometry pages receive those symbols, independently writing stencil bits 64 and 128. An opaque, allzero-value geometry page clears only mask 192. The payload pages write neither RGBA nor depth.

Three native sequence material routes draw the source ROI after weather:

| Layer | Material route | Operation |
| --- | --- | --- |
| 13 | `sequence` | Black source, RGB SourceAlpha/OneMinusSrcAlpha with source alpha 192/255; preserve destination alpha |
| 14 | `point_sequence` | Stencil Equal on bit64; additive red64/255, RGB One/One; preserve alpha |
| 15 | `point_sequence_add` | Stencil Equal on bit128; additive red128/255, RGB One/One; preserve alpha |

For a byte-valued scene color C and two-bit symbol q, the red result is `round(C*63/255)+64*q`. Green and blue contain `round(C*63/255)`. All intermediate results fit UNORM8. The post consumer obtains q by dividing the red byte by64, packs four symbols per logical byte, and performs identity or dependent indexing. A first post pass copies final RGBA; the next pass reads T0 (that copy) or T1 (the original final scene). Restoration removes red's two upper bits and multiplies all three lower values by255/63.

The source is 128×128 pixels at `[96,192]` in a native720×1080 client. Each of the 16×16 records occupies8×8 pixels. The diagnostic reader checks every source pixel or every pixel of its720×256 output. Repeated query pixels do not increase logical capacity beyond64B.

The first native attempt in `.runtime/weather-stencil-packed64-native-20261119-r1/evidence/` failed the varied-color opaque fixture gate. Only a lower strip of its varied-height opaque geometry was visible:14,720 of16,384 RGB source samples differed from the intended fixture, while all guards passed. This failure is retained and independently audited. Its cause is unresolved; it is not evidence that a known full-color fixture or the original planned restoration test passed.

Root authorized a continuation in the same still-running instance, saved separately under `evidence/followup/`. The continuation hides that page and creates the allzero-value clear geometry shape already used by the one-bit probe, with its RGB blend coefficient0. It verifies the independent bit64, bit128, both, and zero routes before arbitrary input. All three64B arrays then pass identity/dependent queries in T0 and T1. Hiding the two payload pages rejects181,440 of184,320 query-output pixels, and showing them again restores the positive result.

Sunny restoration uses the actual natural scene rather than the failed fixture. The entire16,384 sampled RGBA source pixels before and after the encoded/restored captures are identical. Against that stable source, restored RGB has maximum error2 in each channel and no pixel exceeds2. This is a finite before/after identity gate; it does not supply an oracle for changing rain color.

Two arbitrary wet arrays pass T0/T1 identity/dependent queries and full-source symbol checks. Four same-source RGB/alpha pair captures contain634,353,619,580 alpha bytes below255, respectively, with zero payload-symbol errors. These are intermediate texture-alpha observations. They do not establish byte-for-byte preservation of the original pre-writer alpha or general rainy scene restoration.

All nine native post effects are off. The client has a60 FPS cap, but no frame-time sample or actual performance claim was collected. The game runtime writes no files. Evidence, resource builds, commands and PNGs are host-side development artifacts. Both owned sessions have stopped, and cleanup receipts retain normal-stop timeouts and subsequent owner-bound force stops.

Stencil bits are shared native state. Native entity-outline masks include bit64; UI masks include64 and128. No public allocation guarantee was found. At two bits per source pixel,512KiB would require2,097,152 source pixels and roughly4.19million payload quads across the two geometry bitplanes, before the clear geometry. That arithmetic fits the2560×1600 screen budget but does not establish rendering feasibility or60FPS.

The finite native procedure is intentionally two stages: `packed_runner.py` retains the initial fixture gate and `packed_followup.py` is the recorded same-instance continuation. The followup does not launch Minecraft. Do not treat it as permission for additional instances or dimensions.
