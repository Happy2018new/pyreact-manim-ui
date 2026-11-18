# Paged alpha atlas, 1–2 MiB experiment

This isolated development fixture uploads a single in-memory dataset through
64 KiB block palettes and geometry pages. It reuses the original atlas asset
builder and byte codec without editing their source files. Each page has its
own anchor and actor uniforms. `G4.z` adds the global record base after local
bounds checks. Each palette remains `256 × 256 × 16`, including the 2 MiB case.

Game Python writes no payload files. Host build outputs, PNG captures, command
receipts, and the engine-managed debugging infrastructure are development
evidence. Runtime page fingerprints use `sum_u8_mod2^32`; the host separately
records independently generated page SHA-256 values.

The source atlas is `[8,32]`, 2048 columns, one native pixel per byte. The
diagnostic is `[16,128]`, 2048 columns, one query per native pixel. Every valid
query pixel is compared with an independent integer oracle at zero tolerance.
Every nonquery pixel inside `[0,128,2560,1408)` is also checked against the
sentinel color. The top debug UI and bottom window corners are outside this
guard; no payload pixel is excluded. Dependent addresses use the first sampled
byte. Seven bounded modular doubles avoid large float32 address products.

Build into a fresh directory, launch through `host.py`, and resize before
uploading or setting postprocess parameters. The resize helper uses protected
owner/session routing, explicit DPI awareness, and noactivation. It centers
the full native client area on screen. Resize can reset engine postprocess
parameters, so queries are set again afterward.

```powershell
python -B -X utf8 tools/geometry_atlas_large_probe/build_probe.py --output .runtime/NEW/project
python -B -X utf8 tools/geometry_atlas_large_probe/host.py launch --project .runtime/NEW/project --evidence .runtime/NEW/evidence
python -B -X utf8 tools/geometry_atlas_large_probe/host.py resize --project .runtime/NEW/project --evidence .runtime/NEW/evidence --width 2560 --height 1440 > .runtime/NEW/evidence/resize_2560x1440.json
python -B -X utf8 tools/geometry_atlas_large_probe/run_case.py --project .runtime/NEW/project --evidence .runtime/NEW/evidence
```

The correctness runner calibrates 64 KiB, hides/restores the writer as a negative
control, then grows the same seed/generation prefix to 1, 1.5, and 2 MiB. Each
size receives complete identity and dependent scans. Page content identity,
geometry names, and upload serials are frozen between queries. Failed mutations
are never replayed automatically. Available system commit is checked against a
4 GiB gate before growing and after each capacity. Existing evidence is not
overwritten. `--resume-resident64k` is an explicit recovery path accepting only
an already loaded 64 KiB prefix; it does not submit that page again.

The completed run is under
`.runtime/geometry-atlas-large-20261118-r3/evidence-centered/large_case.summary.json`.
All six 1–2 MiB full scans passed with zero errors. The hidden-writer negative
control failed 65,279 of 65,536 queries. The independent replay is
`independent-audit.json` in that directory. Earlier r1/r2 and initial r3 evidence
preserve the missing runtime SHA-256 API, clipped viewport/debug UI, and wrong
size calibration failures. They are not capacity failures.

The proven capacity is **at least 2 MiB for this device and viewport**, not an
absolute limit. CPU submission timings are sums over individual page calls,
without a GPU completion fence or host IPC/capture waits. Single-generation
capacity evidence does not establish continuous updates or general alpha
compatibility.

`run_static_perf.py plan` only writes a plan and never contacts Minecraft.
Its separate `run` action is for the coordinated performance phase after other
research games stop. All 2 MiB of resources and all 32 anchors remain allocated
in every case. It changes native attachment visibility to 0, 16, 24, or 32
active pages. Baseline hides all native geometries and disables the data chain;
resident cases keep writer, copy, private array, and consumer active in mode 3
without diagnostic gathers. Each case warms for 2 seconds and samples for 25
seconds by default. It records engine FPS and render-event intervals and
freezes payload identity throughout. The driver never uploads data.

```powershell
python -B -X utf8 tools/geometry_atlas_large_probe/run_static_perf.py plan --project .runtime/NEW/project --source-evidence .runtime/NEW/evidence --evidence .runtime/NEW/perf-plan
# Run only during the coordinated performance phase, using another fresh output:
python -B -X utf8 tools/geometry_atlas_large_probe/run_static_perf.py run --project .runtime/NEW/project --source-evidence .runtime/NEW/evidence --evidence .runtime/NEW/perf-run
```

Tests: `python -B -X utf8 -m unittest discover -s tests -p test_geometry_atlas_large_probe.py -v`.
