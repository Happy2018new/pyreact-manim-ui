# Native rain and transparent geometry probe

This separate package freezes the current scene codec builder/runtime, uses
the same fixed k2 blend shader/material for all controls, and only calls the
documented geometry transparency API. It does not write game payload files,
upload private textures, perform continuous updates, or change earlier probes.

The first candidate calls EnableActorBlockGeometryTransparent(name,True), then
SetActorBlockGeometryTransparency(name,1.0), keeping the same resident payload
geometry. API success is not proof of render ordering. Native resources suggest
that this switch may select another material and vertex shader; disappearing
geometry or changed encoded RGB is a recorded candidate failure.

The known-color control covers every 6-bit Q symbol times every original
red byte (16384 records), comparing original RGB, blended RGB, restored RGB,
and same-frame alpha restoration exactly with host integer arithmetic. The
64KiB payload has salt29, source ROI [296,192,128,683], 87424 source pixels,
and32 zero padding bytes. Full identity/dependent queries cover all65536 bytes.

Phases are clear default, clear transparent, rain default, rain transparent,
then rain restored default. The runner supports three or five loops per rain phase. Per loop the
native diagnostics save actual observed Q+raw alpha from the same source sample,
block exception count/overflow+same-frame decoded alpha error, identity, and
dependent. All source/query pixels are checked; every nonquery pixel in native
guard [0,128,720,1064) must be black opaque. No payload region is excluded.

Dynamic rain frames are separate observations, not paired atomic RGB references.
Rain original RGB restoration cannot be proven from an unknown original color;
the known-color control and payload/alpha integrity have distinct scope. The
64 KiB runner records whether correctness supports expanding to a separate
512 KiB performance run. It neither samples FPS nor launches MC.

The offline native config copies all engine passes/parameters/order and changes
only enable flags to false. Actual getters/order are checked at startup and in
every receipt. User foreground opt-in preserves noactivation and grants no
agent desktop input. All capture is passive Windows Graphics Capture.

The authorized 2026-11-18 runs are preserved in
`.runtime/rain-geometry-native-20261118-r1/evidence` (amount1.0, five loops per
rain phase) and `rain-geometry-native-20261118-r2/evidence` (amount0.5, three).
Both candidates passed all clear-weather64KiB identity/dependent and87424pixel
raw-Q/alpha/block checks. Both failed every rain identity/dependent capture.
The r2 transparent bad-Q counts were152/647/108, with166/682/114non255alpha
pixels; every bad Q was at a non255alpha pixel from the same source sample.
The three r2 block diagnostics had at most2/3/4exceptions, zero overflow and
zero decoded-alpha error, while payload captures still failed. Overflow alone
does not explain the native rain payload failures. Default rain before and
after each transparent phase also failed. Dynamic frames are not paired
comparisons, so differences between these error counts are not an effect size.

The known-color domain fixture was invalid in r1. Encoded captures equaled the
original background for default, transparent and returned-default alike. The
captures did not expose the writer blend despite background-first attachment.
Those failures are preserved; r2 skips the fixture and makes no original-RGB
restoration accuracy claim. The clear-weather raw-Q checks still independently
prove the payload symbols, in addition to full identity/dependent readback.

R1 also preserves a terminal quiesce error after all81captures:the last enabled
custom pass reset the chain, then a setter for a removed pass failed. A separate
read-only state confirmed all three attachments hidden and custom/native enabled
lists empty. R2 re-reads membership before every cleanup setter, completed all
45captures and quiesced normally. Native shaders/materials are byte-identical
across both packages. R1 has a separately documented metadata-only manifest hash
discrepancy; r2's generated manifest checks all files correctly. Both owned games
exited normally and sessions are stopped, with no active MC remaining. Neither
candidate progressed to512KiB or FPS sampling. These two API amounts did not
solve this fixture; no render queue change is proven.
