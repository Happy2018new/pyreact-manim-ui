This bounded Bloom witness reuses the already verified native `known_fixture`
SFX overwrite draw. It introduces no post source, observer, texture link, native
runtime setter, carrier upload, or native shader/math override. Import is inert.
The lifecycle owner alone launches, stops, and selects sessions.

Build two fresh projects under `.runtime`:

```powershell
python -B -X utf8 tools/native_stencil_bloom_world_witness/witness.py build --output <source-project> --game-exe <Minecraft.Windows.exe> --phase source-control
python -B -X utf8 tools/native_stencil_bloom_world_witness/witness.py build --output <native-project> --game-exe <Minecraft.Windows.exe> --phase native
```

After the owner launches the source project, run:

```powershell
python -B -X utf8 tools/native_stencil_bloom_world_witness/witness.py run --project <source-project> --evidence <fresh-source-evidence> --previous-evidence <source-launch-evidence> --phase source-control
```

Continue only if `bloom-world-status.json` reports `source_rgb_observed`, then
have the owner close that session and launch the native project. Run:

```powershell
python -B -X utf8 tools/native_stencil_bloom_world_witness/witness.py run --project <native-project> --evidence <fresh-native-evidence> --previous-evidence <native-launch-evidence> --phase native --source-gate <source-evidence>/bloom-world-status.json
```

Source control has all native effects disabled at startup; native has only
original Bloom enabled. Both use the identical native SFX fragment: full-screen
black with a fixed white `[328,508,64,64]` patch. Only patch alpha is declared to
change `1,0,1` through the existing known-fixture mode. Source RGB is verified
from three actual PNGs. New source alpha is not independently sampled; this
limitation is explicit in the receipt.

The predeclared analysis rectangle `[128,256,464,568]` excludes debug text while
retaining the patch, four-sided halo ring, and separated distant guard. The
unchanged existing Bloom response verifier requires coherent signed RGB halo
on all four sides, stable distant guards, and A return. A positive response is
only a native halo witness: it does not prove carrier coexistence, lossless
scene restoration, renderer branch, 512 KiB capacity, or performance.
