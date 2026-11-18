# -*- coding: utf-8 -*-
"""Server-only small, reconstructible real-world scene via documented ModSDK.

Use only in the owned test world. Pass serverApi explicitly on the server side;
this module does not import or initialize either side. Caller chooses a loaded
origin and a fixed camera looking toward +Z. Returned receipts stay in memory.
"""


def block_plan(origin, case='solid'):
    if case not in ('solid', 'water_glass', 'rain', 'glint_emissive'):
        raise ValueError('Unknown native scene case')
    ox, oy, oz = origin
    result = {}
    for x in range(-4, 5):
        for z in range(1, 9):
            result[(ox+x, oy-2, oz+z)] = 'minecraft:stone'
    for x in range(-3, 4):
        for y in range(0, 4):
            result[(ox+x, oy+y, oz+7)] = 'minecraft:stone'
            result[(ox+x, oy+y, oz+4)] = 'minecraft:air'
    # Pool is enclosed so fluid changes do not silently change the fixture.
    for x in range(-3, 4):
        for z in range(1, 7):
            edge = x in (-3, 3) or z in (1, 6)
            result[(ox+x, oy-1, oz+z)] = ('minecraft:glass' if edge else 'minecraft:water') if case == 'water_glass' else 'minecraft:stone'
    if case == 'water_glass':
        for x in range(-2, 3):
            for y in range(0, 3):
                result[(ox+x, oy+y, oz+4)] = 'minecraft:glass'
    for x in (-2, 2):
        result[(ox+x, oy+1, oz+7)] = 'minecraft:glowstone' if case == 'glint_emissive' else 'minecraft:stone'
    return [(pos, {'name': name, 'aux': 0}) for pos, name in sorted(result.items())]


def prepare(server_api, level_id, origin, case='solid', dimension=0, player_id=None):
    factory = server_api.GetEngineCompFactory()
    game = factory.CreateGame(level_id)
    old_rules = game.GetGameRulesInfoServer()
    rule_patch = {'cheat_info': {'daylight_cycle': False, 'weather_cycle': False,
                                 'mob_spawn': False, 'random_tick_speed': 0}}
    rules_ok = game.SetGameRulesInfoServer(rule_patch)
    time = factory.CreateTime(level_id)
    time_ok = time.SetTimeOfDay(6000)
    weather = factory.CreateWeather(level_id)
    weather_calls = [('local', weather.SetDimensionUseLocalWeather(dimension, True)),
                     ('cycle', weather.SetDimensionLocalDoWeatherCycle(dimension, False)),
                     ('rain', weather.SetDimensionLocalRain(dimension, 1.0 if case == 'rain' else 0.0, 12000000)),
                     ('thunder', weather.SetDimensionLocalThunder(dimension, 0.0, 12000000))]
    if not rules_ok or not time_ok or not all(result for name, result in weather_calls):
        raise RuntimeError('Deterministic scene controls rejected: ' + repr(
            {'rules': rules_ok, 'time': time_ok, 'weather': weather_calls}))
    blocks = factory.CreateBlockInfo(level_id)
    edits = []
    for pos, desired in block_plan(origin, case):
        before = blocks.GetBlockNew(pos, dimension)
        if before is None:
            raise RuntimeError('Test scene requires already loaded terrain: ' + str(pos))
        changed = blocks.SetBlockNew(pos, desired, 0, dimension, True, False)
        after = blocks.GetBlockNew(pos, dimension)
        exact = after is not None and after.get('name') == desired['name'] and after.get('aux', 0) == desired['aux']
        edits.append({'pos': pos, 'before': before, 'desired': desired,
                      'api_changed': bool(changed), 'after': after, 'matches': exact})
        if not exact:
            raise RuntimeError('Scene block did not match requested fixture: ' + str(pos))
    item_receipt = None
    if case == 'glint_emissive' and player_id is not None:
        item = factory.CreateItem(player_id)
        enum = server_api.GetMinecraftEnum()
        item_dict = {'itemName': 'minecraft:bow', 'count': 1, 'auxValue': 0,
                     'enchantData': [(enum.EnchantType.BowDamage, 1)]}
        spawned = item.SpawnItemToPlayerInv(item_dict, player_id, 0)
        selected = factory.CreatePlayer(player_id).ChangeSelectSlot(0)
        item_receipt = {'item': item_dict, 'spawned': spawned, 'selected': selected,
                        'meaning': 'Enchantment glint; not proof that native bloom was activated'}
    return {'kind': 'native_scene_receipt_v1', 'case': case, 'origin': origin,
            'dimension': dimension, 'old_rules': old_rules, 'rule_patch': rule_patch,
            'rules_ok': rules_ok, 'time_of_day': 6000, 'time_ok': time_ok,
            'weather_calls': weather_calls, 'edits': edits, 'item': item_receipt,
            'capture_semantics': 'Reconstructed separate runs; rain and glint animation are not atomic references',
            'still_required': ['Record fixed camera transform and confirm ROI overlap',
                               'Preserve same-frame raw/decoded alpha and payload evidence',
                               'Measure non-255 alpha; glass or rain alone may preserve alpha write masks']}
