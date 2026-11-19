# Isolated native post candidates

These are **offline-built, unverified native candidates**, separate from all
preserved original probes. Imports do nothing to Minecraft. The builder only
writes a caller-created fresh project. The runner never launches, attaches,
activates, sends input to, or stops a game: only the existing lifecycle owner
may invoke it against that owner's already-launched session and passive WGC
transport. All game Python commands operate in memory; game runtime file writes
are absent.

The exact integration API is:

```python
# Host build, before the project has ever launched:
project = original_build_probe.build(output, game_exe, 'carrier')
candidate = build_candidate.install(project, game_exe, case)
# case: 'dof-identity', 'dof-active', or 'bloom-control'
```

`build_candidate.validate(project, case)` is read-only and can run after launch.
Every case needs a different fresh generated project and evidence directory.
Installation preserves the old `native_post_startup.json` as a frozen input
record, then writes its own `native_post_candidate.json`; the old original-only
startup validator intentionally does not accept a derived DOF candidate.

The corresponding CLI install/validation forms are:

```powershell
python -B -X utf8 tools/native_stencil_post_candidate/build_candidate.py --project <fresh-project> --game-exe <actual-game-exe> --case dof-identity
python -B -X utf8 tools/native_stencil_post_candidate/build_candidate.py --project <fresh-project> --case dof-identity --validate-only
```

The owner launches that project at 60 FPS with noactivation using its existing
lifecycle helper, and then runs:

```powershell
python -B -X utf8 tools/native_stencil_post_candidate/runner.py --project <identity-project> --evidence <new-identity-evidence> --previous-evidence <current-launch-evidence> --case dof-identity --initialize
python -B -X utf8 tools/native_stencil_post_candidate/runner.py --project <active-project> --evidence <new-active-evidence> --previous-evidence <current-active-launch-evidence> --case dof-active --identity-gate <new-identity-evidence>/dof-identity-status.json --initialize
python -B -X utf8 tools/native_stencil_post_candidate/runner.py --project <bloom-project> --evidence <new-bloom-evidence> --previous-evidence <current-bloom-launch-evidence> --case bloom-control --initialize
```

`--initialize` is implied if the previous evidence contains no completed upload
in `results.json`. It may be omitted to continue an already initialized current
candidate. The previous launch receipt must belong to **that candidate's current
instance**, not the separate identity baseline. Active's `--identity-gate`
refers to the completed baseline from the other instance. Owner/project/PID
bindings remain those of `native_stencil_compat_probe.runner.Experiment`.

## DOF identity and active phases

The native process stays named `depthoffield`. Both legacy and RNGL config
files retain the original parameter values, target sizes, shader pass names,
order and pass arrays. Only the final material name changes, plus permitted
native startup-enable flags. The final material copies its original fields and
changes only the fragment source. Every original shader statement is retained;
the wrapper can be mechanically reversed to byte-exact original source.

The identity variant wraps the single raw `TEXTURE_1` sample without decoding.
The active variant restores only that sample's RGB in fixed physical ROI
`[8,128,512,512]` of the fixed `720x1080` viewport, preserving its alpha. Native
`TEXTURE_0` blur, `TEXTURE_2` depth, `DEPTH_OF_FIELD_*` uniforms and auto-center
focus math are unchanged. `TEXTURE_0` at the final native pass is already blurred;
substituting it for clear scene input would change the effect.

The identity runner captures zero blur, manual near, manual far, auto center,
and a native final return to zero. The acceptance artifact is
`dof-identity-status.json`, with `gate.accepted == true`, `failure == null`, and
`cleanup_failure == null`. The gate independently reopens five native profile
PNGs, requires analytic zero/return RGB and a nonzero fixture-interior response,
checks native enable order and resident identity, then re-decodes all actual
65,536 bytes, dependent queries, restored RGB and **all guards** from three late
diagnostic PNGs. Stored `exact`/`pass` flags are not used as pixel proof.

Active revalidates that complete gate **before initialization makes any SDK or
resize call**. Its native DOF starts disabled. It loads the data and makes the
full carrier visible before enabling native DOF. It captures the same five
profiles and compares their fixed ROI plus eight-pixel guard to actual baseline
PNGs at per-channel tolerance 2, rejecting changed camera/depth origin. It also
performs full late data/restored diagnostics. Its result is
`dof-active-status.json`; `candidate_profile_match` applies only to those tested
profiles. Separate near/far autofocus target poses are explicitly untested.

The static active decoder has no general runtime switch. It is **unsafe to
decode clean source RGB when the carrier is hidden**. Cleanup first requires
the dedicated native disable call and a false readback, then independently
hides carrier and fixture. Failed native disable leaves the carrier visible
for the lifecycle owner. The custom chain is marked unready after disable
because native setters can rebuild/remove dynamic registrations. The owner
closes each candidate instance; this helper does not restore a reusable native
post editing session. Resizing, moving ROI, continuous updates and production
enable switching require another implementation and validation.

## Bloom source positive control

Bloom shaders, native materials, parameters and original passes stay unchanged.
The candidate adds two owned custom materials only. `bloom.resources()` returns
their definitions and GLSL. `bloom.run_bloom_candidate(experiment)` (also `run`)
works with an already initialized, owner-validated Experiment.

The source immediately precedes native `bloom` in ordinary chaining. It emits
black with a fixed `64x64` white patch at `[328,508]`, using patch alpha
`1 -> 0 -> 1` and identical RGB. Six explicit T3 diagnostic captures verify
source RGB and alpha before the native phase. A failed source gate skips all
native response captures. The three native captures disable the diagnostic and
require exactly `[source,bloom]` enabled. Both owned passes are primed and
linked on different render turns.

A native positive needs a coherent signed RGB halo across **all four sides**
outside the three-pixel edge exclusion, stable distant guards and a full A
return. Alpha-zero or alpha-one gain is accepted without claiming which
renderer branch ran. A response confined to the source patch, one local
transient, or colored world movement cannot satisfy the criterion. The result
is `bloom_candidate_status.json`: `source_input_gate_passed` and
`native_positive_response_observed` are separate fields. `compatibility` remains
null because this tests synthetic source-to-native response, not carrier or
real emissive-material compatibility. Zero response stays `native_stage_unproven`.

Engine slot naming is literal here: `TEXTURE_0` is the implicit preceding pass,
`TEXTURE_1` is raw scene, and custom depth is `TEXTURE_2`. The public explicit
`PostPassResultToOtherPass` link is used only at slot **3**; its documented range
is 3–7. No explicit slot-zero connection or UI/DSL texture alias is used.

## Offline verification

```powershell
python -B -m unittest discover -s tools/native_stencil_post_candidate -p 'test_*.py' -v
```

Tests cover both native config routes, original-math preservation, startup
disable safety, source tampering, ambiguous samples, actual diagnostic PNG
corruption and guard-only false positives, native zero return, auto setter
order, active preflight, cleanup, legal T3 links, source gating, signed halos,
motion negatives, state changes and rejected operations. Passing offline tests
does not establish any candidate's native execution or compatibility.
