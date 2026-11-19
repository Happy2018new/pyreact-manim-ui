# Fixed native world for the existing DOF comparison

This host wrapper composes the unchanged guarded DOF runner. It changes no
shader, material, pass, native math, source ROI, tolerance or existing image
gate. It requires a fresh disposable developer world and its sole lifecycle
owner. Importing it and running `--preflight` perform no game operations.

Build fresh identity and active projects with the existing final
`native_stencil_post_retest/build_retest.py`; there is no new pack builder.
After the owner launches one project, invoke:

```powershell
python -B -X utf8 tools/native_stencil_dof_fixed_world/runner.py `
  --project <fresh-project> --evidence <fresh-run-evidence> `
  --previous-evidence <owner-launch-evidence> `
  --case dof-identity --initialize
```

The separate active invocation uses `--case dof-active` and additionally
`--identity-gate <fixed-identity-run>/dof-identity-status.json`. Before runtime
transport it requires the unchanged image gate, the existing actor-guard gate,
and the new clean `dof-fixed-world-status.json`, bound to the exact wrapper
sources and identity status. Earlier open-world identities cannot pass.

After the unchanged detached camera and actor controls are established, a
17×13×17 block room surrounds the actual camera. At the expected position
`(0,-58,-3)`, its inclusive bounds are `(-8,-62,-11)` to `(8,-50,5)`:

- Every boundary cell is static `minecraft:glowstone`, an opaque emissive
  block with no installed flipbook entry. Every strict interior cell is air.
- The unchanged three- and four-block fixture anchors remain inside the room.
- All **3,757** prior cells are read before the first write; all requested cells
  are read again to establish exact native block identity. `SetBlockNew=False`
  is correctly treated as “unchanged”; complete readback is the acceptance.
- Dimension 0 must use global time. Absolute time is fixed at 6,000 ticks,
  daylight/weather cycling is paused, and dimension-local rain/thunder are
  explicitly zero with their local cycle paused.
- Full room, time and local-weather readbacks run after initialization, before
  profiles, at the zero baseline and after profiles. Later render turns allow
  chunk mesh/light updates to settle before image evidence.

The added active prerequisite occurs immediately after the zero capture and
**before any nonzero setter**: the entire exterior below the debug HUD must be
byte-exact against the accepted identity zero image. Inside the original source
ROI, tolerance 2 allows the already declared RGB codec error. A failed exterior
gate skips active nonzero profiles and follows normal native disable/cleanup.
The original full ROI plus 8px guard comparison still determines compatibility;
the new gate only adds a prerequisite. Identity zero-return must also reproduce
its entire exterior exactly.

After the unchanged native helper disables DOF, independent cleanup restores
every prior room cell, the original clock and only the saved world-rule keys,
and the prior dimension-local weather mode/settings. The existing guard then
restores actor visibility and spawning. Errors are preserved and prevent a
complete receipt. The owner still closes the instance.

Offline commands:

```powershell
python -B -X utf8 tools/native_stencil_dof_fixed_world/runner.py --preflight
python -B -X utf8 -m unittest discover -s tools/native_stencil_dof_fixed_world -p test_*.py -v
```

The tests execute the actual generated server snippets against a fake SDK,
cover full block/environment restoration, stale weather/time rejection,
independent cleanup after a transport failure, and exact exterior gating.
