# Sequential Bloom source control

This is a bounded, development-only synthetic Bloom witness. It uses ordinary
preceding-pass `TEXTURE_0` chaining and never calls
`PostPassResultToOtherPass`. It does not use a native Bloom runtime setter.
Importing the builder or runner does not launch, attach to, stop, or initialize
a game. Build and test work is offline; the existing lifecycle owner alone runs
the two fresh packages, one at a time.

The earlier T3 candidate and its recovery both stopped before any screenshots
because the public texture-link call returned false. The recovery established
loaded owned material definitions, correct order, enables and parameters across
render turns, but that did not resolve the link. This folder preserves those
experiments and avoids their explicit texture-link requirement.

## Two independent startup phases

`source-control` sets every native effect's startup flag to false in both native
configuration variants. It registers the procedural source followed by a
terminal observer. The observer samples ordinary `TEXTURE_0` and displays either
source RGB or source alpha as RGB. The source keeps a 64 by 64 white patch on
black RGB while patch alpha follows `1 → 0 → 1`; background alpha stays one.
Six captures must match the complete declared RGB and alpha images, including
the return, with identical source RGB across the sequence.

The owner closes that session before launching the separate `native` package.
This package enables only original native Bloom at startup. It registers the
same source directly before Bloom and never registers the observer. Three
captures use the same alpha sequence. The frozen halo evaluator requires a
consistent signed change in all RGB channels on four sides outside the patch,
stable distant guards and full A-return. A three-pixel exclusion around the
source edge prevents source-edge filtering alone from becoming a halo witness.
The native final image can contain original world color, so its base RGB is not
compared with the procedural source.

Only startup enable flags differ from the installed native configuration. The
original native order, parameters, pass arrays, materials and shaders remain
unchanged. Owned materials are merged into the loaded
`materials/postprocess.material` map. Owned shader aliases follow installed
native form `shaders/<filename>`, with physical files under `shaders/glsl/`.

## Interfaces

Build a fresh carrier project with the existing
`native_stencil_compat_probe/build_probe.py` first. Then install one phase:

```python
build.install(project, game_exe, phase)  # phase is source-control or native
build.validate(project, phase=None)     # read-only, regenerates expected outputs
```

The builder's CLI accepts `--project`, `--game-exe`, `--phase`, and
`--validate-only`. Each phase needs its own fresh project. The receipt is
`native_bloom_sequential_build.json`. Validation checks exact pack inventory,
regenerated material/shader/config/manifest outputs, frozen carrier files,
native inputs, loaded registration lists, control files and dependency hashes.

The runtime entrypoints consume an already owned Experiment:

```python
runner.initialize(experiment, phase)
runner.run(experiment, phase, source_gate=None)
runner.verify_source_gate(path, expected_fixture)
```

Initialization prepares only the camera, weather and viewport. It does not
upload a payload or install the integrated copy/restore/consumer chain. The
capacity tested is zero bytes; this is a pure synthetic control. The runner
registers custom processes in separate commands with render-turn checks, keeps
complete order/enable/parameter observations, and restores prior custom flags
and fixture configuration in its final cleanup. The lifecycle owner must still
close each startup variant.

The runtime CLI accepts:

```text
--project <fresh-phase-project>
--evidence <new-evidence-directory>
--previous-evidence <current-owner-launch-evidence>
--phase source-control|native
--source-gate <source-control-evidence/bloom_sequential_status.json>
```

`--source-gate` is required for `native`. Before constructing or initializing
the native Experiment, the CLI validates the source build and shared fixture
identity, reopens all six actual source PNGs, verifies hashes, sequence, states,
parameters, the raw passive capture sidecars, restored configuration/fixture
state, and fully re-decodes the expected RGB/alpha images. A hash-bound minimal
assigned-session snapshot is reopened together with the assigned session record
to bind the source PID to its owner and project. The native client path, native
input records and owned-resource hash must match the source package. Gate
failure stops native work. The status output is
`bloom_sequential_status.json`.

## Scope of a result

The source proof crosses sessions. Matching source material, shader, pass,
parameters and layout establishes replicated inputs; it does not directly
observe the pre-Bloom attachment in the native session. A positive native halo
is required to establish a synthetic native response in that session. A missing
halo remains `native_stage_unproven`, and compatibility is always `null`.

Neither source proof nor a positive halo establishes carrier coexistence, real
emissive-material behavior, renderer branch identity, capacity or performance.
The owner must preserve noactivation/passive-capture requirements and the
existing 60 FPS session policy. This folder adds no lifecycle control.

## Offline verification

```text
python -B -m unittest discover -s tools/native_stencil_bloom_sequential_retest -p "test_*.py" -v
```

Tests use temporary pack fixtures, fake Experiments and actual synthetic PNGs.
They never invoke a game host or runtime tool. Coverage includes both startup
plans, exact resource and native-source preservation, tampered output/receipt
and added-file rejection, ordinary T0 RGB/alpha proof, re-decoding a modified PNG
even when its reported hash is updated, capture/parameter/cleanup provenance,
assigned-session and raw-sidecar tampering, mismatched-client rejection before
transport, no-response uncertainty and cleanup. The current suite contains 24
passing offline tests; it does not establish native execution.
