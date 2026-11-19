# Matched DOF scene guard

This owner-invoked host wrapper leaves every frozen builder, shader, pass,
kernel and image gate unchanged. Generate two fresh carrier projects with the
final `native_stencil_post_retest/build_retest.py`, cases `dof-identity` and
`dof-active`, and launch each serially with the normal sole-owner host wrapper.

Use this runner instead of the previous retest runner:

```powershell
python -B -X utf8 tools/native_stencil_dof_guard_retest/runner.py `
  --project <fresh-identity-project> --evidence <fresh-identity-run> `
  --previous-evidence <owner-launch-evidence> --case dof-identity --initialize
```

The matched active invocation adds
`--identity-gate <fresh-identity-run>/dof-identity-status.json` and uses
`--case dof-active`. Before any runtime transport, it requires both the original
strict image gate and the adjacent new `dof-guard-status.json`: same wrapper
source SHA/policy, acknowledged scene controls, clean restoration and a hash of
the accepted identity status. Old uncontrolled identities cannot pass.

Before original camera preparation creates any client fixture, the wrapper:

1. Reads only the disposable world's `cheat_info.mob_spawn`, preserves it, sets
   that key false and verifies its readback.
2. Enumerates server nonplayers using `GetEngineActor()` and excludes other
   dimensions. Public documentation explicitly excludes players from this list.
3. Saves each currently loaded current-dimension actor's `GetNotRenderAtAll()` flag, hides that
   actor with `SetNotRenderAtAll(True)`, and reads the flag on a later call.
4. Runs the unchanged original detached-camera preparation and then explicitly
   hides the local player using `Game.SetRenderLocalPlayer(False)`.

The analytic fixture and carrier use independently created client SFX, so they
are outside the earlier server actor enumeration. The wrapper never uses
render-distance culling, kills entities, changes the viewport/ROI/tolerance,
or masks any post-observed pixel. It preserves the existing 8px guard and all
five profile comparisons, native auto-focus/depth math and late diagnostics.

After the unchanged DOF helper disables native and hides its own fixture, the
wrapper independently restores local player rendering to the fresh session's
visible default, restores every saved ordinary actor flag, and restores only
the saved world spawning key. Cleanup also runs after partial setup or later
initialization failure. Local-player rendering has no documented getter; its
setter receipt and the rendered PNGs are the evidence, and no actor getter is
misrepresented as readback of that separate Game flag.

Every check reopens the documented client entity inventory. Genuinely absent
handles are recorded separately from exact owned-fixture IDs; a loaded new
ordinary actor or changed identifier/dimension fails preparation. Cleanup
restores only still-loaded original ordinary actors, never a fixture that has
reused an old handle. It records missing/replaced IDs instead of treating an
unloaded actor's false getter or rejected setter as a scene mismatch.

`dof-guard-status.json` records every control/readback/restore and binds the
identity status. A restore failure prevents a complete matched-fixture gate.
This is a bounded fixture for fresh disposable developer worlds; the lifecycle
owner still closes each instance. Importing the wrapper does not contact a game.

```powershell
python -B -X utf8 -m unittest discover -s tools/native_stencil_dof_guard_retest -p test_*.py -v
```
