# Resource-pack order fixtures

Both variants add unique textures, a plain JSON UI canary and a unique ordinary
FrameAni effect. The default `benign` variant overrides no stock asset. The
explicit `stock_sfx_conflict` variant also supplies `materials/sfx.material`,
copied byte for byte from the selected installed game. Each variant has a
different deterministic resource/behavior UUID pair. The source installation
is never written. The behavior pack contains a minimal `modMain.py` loader
binding; its client init imports the ScreenNode class, and creates no systems,
events, UI or effects. The server side never imports the client runtime. Only the lifecycle owner
may include the addon, launch the finite cases and explicitly create the UI.

`build_fixture.install(output, variant='benign', game_exe=None)` returns pack
roots, variant, UUIDs, effect/UI names and source hashes. It requires a fresh
output under this repository's `.runtime`. The conflict variant requires the
actual installed game executable; its receipt records the native material
source, SHA256 and exact-copy assertion.

Fixture version 1.0.1 includes the required loader entry. The earlier 1.0.0
passive package had no `modMain.py`; a native run accepted RegisterUI but failed
CreateUI with `ImportError: No module named pmanim_pack_order_fixture.runtime`.
Keep that evidence and generate fresh 1.0.1 addons and projects for both order
cases. Do not edit a deployed pack or inject import paths into a live session.
`config_plan(project, fixture, position='first'|'last')` reads the existing
`.mcdev.json` and returns byte-exact `before_base64`/`after_base64`, readable
text and SHA256 hashes without writing. The before bytes preserve a UTF-8 BOM
and original line endings. Decode the base64 fields to apply or restore.
The owner applies each plan only to a fresh offline project before launch and
restores the original bytes if reusing that project. The input list position
is not an engine priority assertion.

After launch, `deployed_order(session_file, project, fixture, expected_owner,
expected_relation=None)` reads only the assigned world's
`world_resource_packs.json`, checks each UUID occurs once and verifies all
deployed benign RP file hashes. `expected_relation='before'|'after'` compares
indices with the project's resource UUID. Run both input positions and require
the actual deployed relation to reverse. Do not label first/last as high/low
priority from the list alone. The benign variant has no conflicts and therefore
does not establish conflict precedence. For the conflict variant, record native
FrameAni visuals and carrier payload together to determine effective behavior.

Build the explicit conflict pack offline:

```python
from pathlib import Path
from tools.native_stencil_pack_order_fixture import build_fixture as packs

fixture = packs.install(
    Path('.runtime/order-conflict/extra'),
    variant='stock_sfx_conflict',
    game_exe=Path('D:/MCStudioDownload/game/MinecraftPE_Netease/3.10.0.467018/Minecraft.Windows.exe'))
plan = packs.config_plan(fresh_carrier_project, fixture, position='first')
# The lifecycle owner writes base64.b64decode(plan['after_base64']) before launch.
# Repeat with a separate fresh carrier project and position='last'.
```

Use one external variant per project; their canary asset names are intentionally
identical while UUIDs and source receipts differ. For each order, the owner
records `deployed_order`, exact UI canary pixels, ordinary four-route
off/on/off witnesses and carrier payload output. Check the fixed OFF background
against stock before interpreting cross-pack ON differences. Payload decoding
failure is an observation for this conflict experiment; preserve its capture
and error instead of aborting before the ordinary FrameAni controls.

If ordinary FrameAni matches stock and payload fails, behavior is consistent
with stock SFX definitions winning. If ordinary FrameAni disappears while the
carrier payload remains exact, behavior is consistent with carrier SFX
definitions winning. Mixed route behavior must be reported per route instead
of forcing either conclusion. Include actual UUID order, hashes and both kinds
of visible evidence in the receipt. Do not repair the carrier before this pair.

Explicit client setup, using the API names in the install receipt:

```python
api.RegisterUI('pmanim_pack_order_canary', 'canary',
               'pmanim_pack_order_fixture.runtime.PackOrderCanary',
               'pmanim_pack_order_canary.main')
canary = api.CreateUI('pmanim_pack_order_canary', 'canary', {'isHud': 1})
# Wait for Create; use a fixed location outside the source and data output.
canary.configure(True, (720, 1080), (632, 160))
```

`verify.verify(image, position=(632,160))` checks 1,344 interior pixels exactly.
Create the ordinary effect at the same recorded world position in every case:
`effects/pmanim_pack_order/ordinary.json`. It uses stock non-point normal blend,
depth testing, the unique red texture and white mix color. Its expected native
world geometry/UV must be checked with the dedicated ordinary FrameAni fixture;
the UI canary independently proves the extra pack's assets loaded even when
the global carrier shader makes ordinary FrameAni disappear.

The compact matrix is stock/carrier with native data hidden, then carrier with
data active; repeat for both actual deployed pack relations. If the ordinary
effect already fails when carrier data is hidden, the failure is caused by the
global resource overlay. Data activation is a separate variable. A correct
canary is not evidence that stock FrameAni materials remain compatible. Keep
the first native failure before attempting a routing fix. No game operations
occur when importing or building these files.
