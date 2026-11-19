# Isolated native post-process recovery

These host tools implement a fresh retest; the frozen candidate tools and r2
matrix are unchanged. The owner generates a **new carrier project** with
`native_stencil_compat_probe.build_probe.build(...)`, then calls:

```python
build_retest.install(project, game_executable, case)
build_retest.validate(project, case)  # read-only, also safe after launch
```

The installer never launches/attaches/stops a game, contacts an SDK session, or
changes installed client files. It rejects prior startup/candidate/retest builds,
existing launch receipts and project material-list overrides. Every pack file,
the actual installed source inputs and material registration are checked.

The frozen builder put definitions in `materials/native_post_candidate.material`
without registering that filename. The installed `materials/common.json` loads
`materials/postprocess.material`. This retest merges its definitions into that
loaded map and preserves every original carrier entry. The omission is proven
from source; its causal role in the failed native results still needs this run.

| Case | Purpose | Native startup |
| --- | --- | --- |
| `dof-sentinel` | Exact final material route must output RGB `[51,204,102]` throughout the fixed source ROI. | DOF enabled |
| `dof-raw-t1` | Exact final material and original sampler 1 metadata must expose the analytic clear source. | DOF enabled |
| `dof-identity` | Byte-exact native shader copy under the exact native material name; zero/nonzero/auto/zero profiles and all late diagnostics. | DOF enabled |
| `dof-active` | Decode only the raw T1 sample inside the frozen ROI; compare all profiles with the accepted retest identity. | All native effects disabled |
| `bloom-control` | Same frozen synthetic source RGB/alpha A/B/A and native halo gates, with loaded materials and separate registration/prime/link turns. | Bloom enabled |

DOF always keeps process `depthoffield`, final material `depth_sample_with_blur`,
original sampler metadata and both native pass templates, RT sizes and
`shaderPassName` values. Only the exact named material's fragment alias points
at an owned GLSL file. Identity copies native bytes including CRLF unchanged.
The optional constant and raw-T1 controls alter only the final assignment.
The active wrapper preserves all original native math, depth/auto-focus reads
and clear alpha; it does not replace blurred T0 with clear T1.

After the sole lifecycle owner launches a fresh project with the normal owned
host wrapper, it runs one bounded helper against the existing launch receipt:

```powershell
python -B -X utf8 tools/native_stencil_post_retest/runner.py `
  --project <fresh-project> --evidence <fresh-run-evidence> `
  --previous-evidence <owner-launch-evidence> `
  --case dof-identity --initialize
```

Active additionally requires
`--identity-gate <identity-run-evidence>/dof-identity-status.json`.
The gate is checked before Experiment construction and before active SDK
initialization. Old candidate schemas cannot pass. The gate independently
reopens all five native PNGs, validates requested setter receipts, checks passive
capture provenance, fully decodes all late bytes/guards and checks the native
zero return. Active sets the full carrier before native enable and disables
native before hiding the carrier. If disable fails, it preserves carrier
visibility for owner cleanup. Cleanup failure clears success flags.

Bloom creates enabled source and input processes in separate SDK commands,
observes a later render turn after each operation, primes them, then attempts
one legal custom-to-custom `TEXTURE_3` link. It records all request/readback and
link receipts. Setup or source RGB/alpha failure skips native image evaluation.
Even a positive synthetic halo keeps `compatibility=null`; carrier and emissive
material compatibility are outside this control's claim.

The runner never launches or stops an instance and never activates a window.
The lifecycle owner must close each startup variant, including on a rejected
gate or helper failure. Native tests must remain serial, 60 FPS, passive WGC
and noactivation. Use fresh projects/evidence for every attempt.

Offline validation:

```powershell
python -B -X utf8 -m unittest discover -s tools/native_stencil_post_retest -p test_*.py -v
```

The tests cover loaded-map registration, exact native name/templates, CRLF
identity copying, changed dependencies/inventory, full PNG replay and corrupted
data/guards, passive capture receipts, native profile requests, disable ordering,
split-frame Bloom setup, one rejected link, source-gate skipping and halo drift.
No offline test contacts a game.
