# Isolated native shadow read-mask diagnostic candidates

This host-side research tool adds a copy of the installed native
`data/resource_packs/vanilla/materials/shadows.material` to a fresh compatibility
carrier project under the repository's ignored `.runtime/` directory. It is
diagnostic tooling, not a production resource change. It never writes installed
resources or changes native shader code. No native result is implied by an
offline installation or a successful public setter.

Only `/materials/shadow_overlay/stencilReadMask` changes:

| Mask | Meaning | Transport bits still included in the read mask |
| --- | --- | --- |
| `255` / `0xFF` | Byte-exact original control | 64 and 128 |
| `191` / `0xBF` | Exclude bit 64 | 128 |
| `63` / `0x3F` | Exclude both transport bits | Neither |

The installer scopes the numeric token to `shadow_overlay`, splices that token
without JSON reformatting, and proves the original prefix and suffix are exact.
Restoring this one token must reproduce every original byte and the entire
parsed object. `shadow_front`, `shadow_back`, all stencil writes, the overlay
reference, blend state, shader paths, and all other fields remain unchanged.
Each generated diagnostic project gets separate manifest identities. Every
other packaged carrier file is hashed before and after; later validation rejects
drift anywhere in the package. The original native bytes are backed up as a
host-only project file beside the receipt, outside either game pack.

For client `3.10.0.467018`, the installed original SHA-256 is
`544df1859920f38bb7da554e81f30fd45fbca6047fd1db556c5a78d47c4f41b5`.
The expected candidate hashes are
`12c39391f7843f5f4afe0d970d416c4336dcc36018bae555dc0bd92e10362f18`
for 191 and
`7a0b41075ae3b34d3d4c64712f47cc83c6e0971f9d36a55336dbbc3a80f740fc`
for 63. The actual installed source is authenticated again before an owner-run
experiment; these constants are explanatory receipts, not replacement sources.

## Offline preparation

Use a separate fresh project for each mask, with the same unchanged carrier
builder and the same other diagnostic composition, if any. Do this before the
first launch, while that project is offline. Local launch-receipt checks do not
discover every possible external session; lifecycle ownership remains with the
caller.

```python
from pathlib import Path
from tools.native_stencil_compat_probe import build_probe
from tools.native_stencil_shadow_candidate import build_candidate

exe = Path('D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe')
for mask in (255, 191, 63):
    project = build_probe.build(
        Path('.runtime/my-shadow-mask-matrix') / ('mask%d' % mask) / 'project',
        exe, 'carrier', include_enchanted=True)
    build_candidate.install(project, exe, mask)
```

The callable contract is `build_candidate.install(project, game_exe, mask)`.
For an existing freshly generated project, the equivalent CLI is:

```powershell
python -B -X utf8 tools/native_stencil_shadow_candidate/build_candidate.py `
  --project <fresh-project> --game-exe <installed-executable> --mask 191
```

Read-only package validation is available as
`build_candidate.validate(project, mask)` or the same CLI with
`--validate-only` and no `--game-exe`. Installation refuses an existing candidate,
an existing shadow override, known local launch receipts, unrelated included
packs, enabled hot reload, or a stock/non-carrier project. It never overwrites a
previous experiment.

## Explicit owner-run capture

The lifecycle owner launches and later cleans each isolated project using the
existing protected native compatibility host. This folder does not launch,
activate, stop, resize through desktop input, or manage options. `runner.py`
performs ordinary compatibility initialization on the already-ready assigned
session, so a separate initialization step is unnecessary.

```powershell
python -B -X utf8 tools/native_stencil_shadow_candidate/runner.py `
  --project <fresh-project> --evidence <fresh-run-evidence> `
  --previous-evidence <launch-evidence> --mask 191
```

The runner requires owner `manim-native-stencil-compat` and the exact assigned
project/session. It preserves an immutable session snapshot. It reuses the
frozen compatibility initializer and hovering-caster shadow helper, with no
packaged runtime edit. The native-only off/on/off positive control, carrier
off/on/off, actual 65,536-byte input, full identity mode 1, raw-source mode 3,
and all output guards stay intact. At least 4 GiB of available system commit is
checked by the inherited loader before each native geometry build. Every
diagnostic PNG must simultaneously preserve the shadow above Y650. The owner
must still execute normal cleanup after every result, including an expected
negative control.

The runner adds a descriptive `00/01/10/11` analysis with an explicit
**bit128:bit64** convention. Every screen sample's symbol comes from the actual
uploaded input file, using least-significant two-bit pairs first. The native
baseline determines the descriptive shadow samples; active candidate pixels
never select samples. Each class requires at least 24 native shadow pixels.
Acceptance continues to check the **entire predeclared geometric receiver,
body, and floor-control regions**, not only those shadow samples. Results also
report ROI-outside changes and same-PNG class differences.

`shadow-candidate-status.json` separates recording completion from compatibility:

- `operational_complete:true`, `compatibility:false`, exit code 0 means a full,
  valid diagnostic negative was captured and its floor/caster cleanup passed.
- `operational_complete:true`, `compatibility:true`, exit code 0 means all four
  classes, all geometric regions, complete data, and all guards passed for this
  particular isolated candidate.
- A setup, positive-control, class-coverage, source-drift, or cleanup failure
  produces a failed operation and a nonzero exit code. Its evidence is retained.

The original 255 variant is expected to test reproducibility of the historical
conflict, not to be silently treated as a passing compatibility result. An
expected compatibility exception from the predecessor is preserved as an
observation; unrelated exceptions remain failures.

## Saved-evidence comparative validation

Run this after the owner has captured all three separate transcripts:

```powershell
python -B -X utf8 tools/native_stencil_shadow_candidate/compare_matrix.py `
  --evidence-255 <run255> --evidence-191 <run191> --evidence-63 <run63> `
  --output <fresh-matrix-result.json>
```

This is read-only with respect to projects and evidence and writes only the
fresh output file. It reopens the actual input, all eight PNGs, original capture
receipts, assigned-session snapshot, and the frozen package. It independently
replays the exhaustive pixel checks instead of trusting saved pass fields.
Native-only controls must also match the original 255 variant within two RGB
levels across every geometric region, with identical declared geometry,
actual input, camera and caster pose. Engine entity IDs may differ across
sessions. Distinct geometry or changing ordinary native shadows prevents a
cross-candidate compatibility attribution.

The matrix exits 0 for a complete comparative experiment even if a candidate
remains incompatible. `original_control_conflict_reproduced` requires an actual
shadow difference in the original case while its complete data still passes.
`observed_compatible_candidates` reports observed per-case coexistence;
`qualified_mask_repair_candidates` stays empty unless the original negative
control is reproduced and all comparative controls pass. Neither field is a
production-fix validation or a claim that an engine material resolver binding
was queried.

The synthetic Equal/ref1 truth table in the build receipt is separate from
native acceptance. Assuming `stencil = 1 | symbol << 6`, masks 255/191/63 accept
`[00]`, `[00,01]`, and all four classes respectively. Historical native 255
captures instead retained `00/10` and changed `01/11`. That difference is why
the experiment measures each class and does not assume both transport bits
exist at the native overlay's execution point or hardcode mask 191's outcome.

## Offline checks

```powershell
python -B -X utf8 -m unittest discover -s tools/native_stencil_shadow_candidate -p test_candidate.py -v
```

Tests cover exact byte preservation, field ambiguity and source drift,
diagnostic isolation and tamper rejection, the static-model/native-result
distinction, all four class coverage, bit64-selective shadow loss, changes
outside descriptive shadow samples, exhaustive data/guard mutations, replay of
saved matrix pixels, and rejection of repair attribution without the original
negative control. These are offline generated images and files; no game process
or ModSDK runtime is called.
