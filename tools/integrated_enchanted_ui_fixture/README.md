# Native inventory-item enchantment fixture

This isolated fixture uses the stock native `inventory_item_renderer` inside a dedicated JSON UI ScreenNode. It is a **native item-widget test in a custom screen**, not the stock inventory screen. Root coordinates the separate public `OpenInventoryGui` / `PopTopUI` round trip. The helper never launches Minecraft, activates a window, sends desktop input, edits an inventory or writes files from game Python.

`build_fixture.install(project)` augments a fresh generated project containing `behavior_pack/stencil_large`. It adds only a UI definition, one opaque black PNG, the client helper/configuration and `enchanted_ui_fixture_receipt.json`; it preserves existing `_ui_defs.json` entries. No shader or material is replaced. The main compatibility builder should call it only for its optional enchanted-fixture build.

The generated helper is `stencil_large.enchanted_ui_fixture.EnchantedFixture(probe)`:

```python
probe.enchanted_fixture = EnchantedFixture(probe)
probe.enchanted_fixture.open()
# Configure in a later managed call after ScreenNode.Create:
probe.enchanted_fixture.configure('normal_all')
probe.enchanted_fixture.configure('mixed')
probe.enchanted_fixture.configure('off')
probe.enchanted_fixture.snapshot()
probe.enchanted_fixture.destroy()
```

Supported modes are `off`, `normal_all`, `mixed`, and `enchanted_all`. `normal_all` removes the enchantment display flag from every visible item. `mixed` enables it only in the two designated enchanted slots. `enchanted_all` is an extra diagnostic control. Every configuration uses public `asItemRenderer().SetUiItem('minecraft:diamond_sword',0,isEnchanted)` and requires `GetUiItem()` to return the exact item, aux and enchant flag before accepting the state. Requests are not treated as proof that pixels rendered.

Six 88×88 cards have a 72×72 native item renderer inset by eight physical pixels. Source-inside cards are at x=32; source-outside cards are at x=536. Normal, enchanted and empty-control cards start at y=160,264,368 respectively. Thus all cards end at y=456, within/without source ROI `[8,128,512,512]` as declared, away from the Y650 data diagnostic and lower composite shape. Positions and sizes are scaled from fixed 720×1080 physical coordinates to the logical UI size; receipts record both scales and `GetScreenViewInfo()`.

The empty control contains a native item control whose visibility is false. It is accurately a **hidden-renderer empty visual control**, not a claim that a real inventory slot is logically empty. The underlying card remains an exact opaque black reference. This avoids inventing the meaning of `SetUiItem('air')` or a nonexistent clearing API. The primary stock-inventory route can supply real empty-slot evidence separately.

## Temporal visual oracle

For each fixed carrier/data state, capture four fresh WGC frames, retaining native fixture states and capture timestamps:

1. Configure `normal_all`, settle, capture before and after at least 0.5 seconds apart.
2. Configure `mixed`, settle, capture before and after at least 0.5 seconds apart.
3. Pass the four images, project receipt and four fixture states to `verify.verify(...)`.

The oracle uses fixed coordinates and zero tolerance for stable controls. It requires both normal-all frames to be identical in every visible item crop. In mixed mode, designated normal slots must remain identical over time and to the normal-all reference; designated enchanted slots must differ from normal-all and visibly change over time. Every item must have nonblack pixels, card corner patches must remain exact black, and both full empty cards must be black in all four frames. The same checks apply source-inside and source-outside. Animated images are not compared as if their glint phase were identical across separate runs.

`verify.compare_normals(off_image,on_image,receipt,mode='normal_all')` provides an exact stable-control comparison across carrier/data states, including the slots that will later display glint. In `mixed` mode it excludes the animated slots. The overall `all_passed` requires the four actual native getter states; images without states can establish only the separate visual gate. Re-run the four-frame temporal gates for stock/writer-off and unchanged-carrier/data-on states, then run the owner's complete 64KiB data readback. Frame provenance, timing gaps, full payload correctness and pass state remain the owner's responsibility. Do not repeat `configure`/`SetUiItem` between the two observations of a mode, because doing so could restart the animation; use a snapshot-only call instead.

This is a visible-behavior gate, not a byte-perfect oracle for every animated glint texel. A failure is preserved; it must not be repaired by cropping around changed pixels or aligning images by color search.

## Native resource facts and scope

MCP confirms public `SetUiItem`, `GetUiItem`, `asItemRenderer`, `RegisterUI`, `CreateUI`, logical control sizing and `ScreenNode.SetRemove`. Installed NetEase 3.10.0.467018 defines ordinary inventory item controls as `type:custom`, `renderer:inventory_item_renderer` in both vanilla and vanilla_netease inventory JSON.

The installed native `ui.material` contains `ui_item_glint_stencil:ui_item` with stencil reference 1, read mask 240, write mask 15 and stencil replacement. `ui_item_glint:ui_base` uses GLINT and tint defines. Its `ui_inventory_item_glint` specialization ultimately uses SourceColor/One blending, stencil reference 1, read mask 255 and write mask 255. The native `color_texture.fragment` samples the glint texture in two animated layers; the INVENTORY branch outputs glint RGB. These are source facts, not proof that a particular observed custom widget took every one of those branches; the fixture deliberately leaves all native materials untouched.

No native execution is claimed by constructing this package. Actual results must come from the sole lifecycle owner's recorded native screenshots, state receipts and exhaustive data oracle. The fixture does not establish stock inventory-screen compatibility, world held-item rendering, all item classes or arbitrary screen transitions.

## Separate stock-inventory reference

MCP confirms `clientApi.OpenInventoryGui(clientApi.GetMinecraftEnum().InventoryType.NATURE, True)` publicly opens the original inventory screen. `GetTopUI()` / `GetTopUINode()` can record the resulting native screen, and public `PopTopUI()` closes one top UI per frame. Root owns this round trip; this helper does not open or close stock menus. Native screen layout depends on profile and scale, so slot rectangles must be established from the actual top node, rather than copied from the fixed custom-widget coordinates above. A stock menu may cover the Y650 diagnostic; exhaustive data captures should follow its closure with data state preserved.

For a bounded real inventory fixture, use owned-world slots 0/1/2/3 for plain bow, Power I bow, empty, and plain bow. On the server, `CreateItem(playerId).GetPlayerItem(ItemPosType.INVENTORY, slot, True)` returns the full backup including userData or None; `GetSelectSlotId()` records the current selected index. The documented creation call is:

```python
normal = {'itemName':'minecraft:bow', 'count':1, 'auxValue':0, 'enchantData':[]}
enchanted = {'itemName':'minecraft:bow', 'count':1, 'auxValue':0,
             'enchantData':[(serverApi.GetMinecraftEnum().EnchantType.BowDamage,1)]}
item.SpawnItemToPlayerInv(normal, playerId, 0)
item.SpawnItemToPlayerInv(enchanted, playerId, 1)
item.SetInvItemNum(2, 0)
item.SpawnItemToPlayerInv(normal, playerId, 3)
```

Explicit slots avoid stack-merging behavior. Back up each slot before editing and clear it before installation if needed. `GetInvItemEnchantData(slot)` independently returns the enchantment tuples, so the normal result must be empty and the Power I result must contain `(BowDamage,1)`. Restore by clearing each touched slot with `SetInvItemNum(slot,0)` then spawning its nonempty backup into that exact slot; read it back and restore the selection. `GetEntityItem`/`SetEntityItem` are not the player-inventory replacement: their documentation explicitly redirects player inventory creation to `SpawnItemToPlayerInv` and clearing to `SetInvItemNum`.

These are documented recipes and test-layout suggestions, not claims that this helper executed them. Preserve all actual item, screen lifecycle, capture and cleanup receipts in the lifecycle owner's evidence.
