"""Owner-run menu, viewport and dimension transitions for the 64 KiB probe."""
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image


BASE_VIEW = [720, 1080]
BASE_ROI = [8, 128, 512, 512]
OUTPUT_Y = 650
HERE = Path(__file__).resolve().parent
FROZEN = ('identity', 'active_pages', 'native_page_names', 'native_attempt_count', 'effects')


def state(experiment, label):
    code = "actors=[(a['entity'],probe.factory.CreatePos(a['entity']).GetPos()) for a in probe.actors]"
    return experiment.call(label, code,
        "{'native_size':list(probe.game.GetScreenSize()),'menu':api.GetTopUI(),"
        "'dimension':probe.game.GetCurrentDimension(),'camera':probe.camera.GetPosition(),"
        "'actors':actors,'order':probe.post.GetPostProcessOrder(),'probe':probe.snapshot()}")


def diagnostics(experiment, prefix):
    return [experiment.capture(prefix+'_m%d' % mode, mode, output_y=OUTPUT_Y)['exact']
            for mode in (1, 3)]


def screenshot(experiment, label, check_payload=False, expected_bytes=None):
    experiment.invoke([sys.executable, '-B', '-X', 'utf8', str(HERE/'host.py'),
                       'capture', '--project', str(experiment.args.project.resolve()),
                       '--evidence', str(experiment.evidence), '--label', label], label+'_capture')
    receipt = json.loads((experiment.evidence/(label+'.json')).read_text(encoding='utf-8'))
    if (not receipt['ok'] or receipt['backend'] != 'Windows.Graphics.Capture'
            or [receipt['width'], receipt['height']] != experiment.viewport
            or receipt['frame_qpc_100ns'] < receipt['request_qpc_100ns']
            or receipt.get('agent_activation_allowed') is not False
            or not all(receipt.get(key, {}).get('window_noactivate')
                       for key in ('background_before', 'background_after'))):
        raise RuntimeError('Fresh passive screenshot required for '+label)
    path = experiment.evidence/(label+'.png')
    row = {'label': label, 'image': str(path)}
    if check_payload:
        from runner import integrated
        with Image.open(path) as frame:
            expected = experiment.payload if expected_bytes is None else expected_bytes
            check = integrated.verify_module.verify(frame.convert('RGB'),1,expected,
                experiment.viewport,experiment.roi,output_y=OUTPUT_Y)
        row.update(exact=check['exact'], data_errors=check['data_error_pixels'],
                   guard_errors=check['guard_error_pixels'])
    return row


def menu(experiment, label, action):
    before = state(experiment,label+'_before')
    experiment.call(label+'_open',action)
    time.sleep(.7)
    opened = state(experiment,label+'_opened')
    if opened['menu'] == before['menu']:
        raise RuntimeError('Native UI stack did not change for '+label)
    try:
        frame = screenshot(experiment,label+'_visible')
    finally:
        result = experiment.call(label+'_pop','popped=api.PopTopUI()',"{'accepted':popped}")
        if not result['accepted']:
            raise RuntimeError('Native PopTopUI rejected for '+label)
    time.sleep(.7)
    returned = state(experiment,label+'_returned')
    if returned['menu'] != before['menu']:
        raise RuntimeError('Top native UI did not return for '+label)
    raw = screenshot(experiment,label+'_without_rebind',True)
    return {'before':before,'opened':opened,'image':frame,'returned':returned,'unattended':raw,
            'same_allocations':all(before['probe'][k]==returned['probe'][k] for k in FROZEN),
            'after_standard_controls':diagnostics(experiment,label+'_checked')}


def stock_inventory(experiment):
    player = experiment.call('stock_inventory_player',expression='api.GetLocalPlayerId()')
    prefix = (
        "player=%r\nfac=api.GetEngineCompFactory()\nitems=fac.CreateItem(player)\n"
        "slots=api.GetMinecraftEnum().ItemPosType.INVENTORY\n"
        "power=api.GetMinecraftEnum().EnchantType.BowDamage\n" % player)
    backup=experiment.server('stock_inventory_backup',prefix+
        "_result=json.dumps([items.GetPlayerItem(slots,i,True) for i in range(4)])")
    try:
        code = prefix + (
            "base={'itemName':'minecraft:bow','count':1,'auxValue':0}\n"
            "wanted=[dict(base,enchantData=[]),dict(base,enchantData=[(power,1)]),None,dict(base,enchantData=[])]\n"
            "for i,item in enumerate(wanted):\n"
            "    if items.GetPlayerItem(slots,i,True): items.SetInvItemNum(i,0)\n"
            "    if item and not items.SpawnItemToPlayerInv(item,player,i): raise RuntimeError('Cannot seed owned inventory slot')\n"
            "vals=[items.GetPlayerItem(slots,i,True) for i in range(4)]\n"
            "ench=[items.GetInvItemEnchantData(i) for i in range(4)]\n"
            "_result=json.dumps({'items':vals,'enchant':ench,'power':power})")
        seeded=experiment.server('stock_inventory_seeded',code)
        if (not seeded['enchant'][1] or seeded['enchant'][1][0]!=[seeded['power'],1]
                or seeded['enchant'][0] or seeded['enchant'][3]
                or seeded['items'][2]):
            raise RuntimeError('Native inventory slot contents differ from declared controls')
        action = 'api.OpenInventoryGui(api.GetMinecraftEnum().InventoryType.NATURE,True)'
        seen = []
        for cfg in ('off','all'):
            label='stock_inventory_'+cfg
            experiment.call(label+'_configuration',"probe.configure(%r)\nprobe.inspect(0)"%cfg)
            at_start=state(experiment,label+'_initial')
            experiment.call(label+'_open',action)
            time.sleep(.8)
            try:
                now=state(experiment,label+'_native_screen')
                if now['menu']==at_start['menu']:
                    raise RuntimeError('Stock inventory did not open')
                first=screenshot(experiment,label+'_phase1')
                time.sleep(.35)
                second=screenshot(experiment,label+'_phase2')
                seen.append({'configuration':cfg,'state':now,'phase1':first,'phase2':second})
            finally:
                ui=state(experiment,label+'_before_close')
                if ui['menu']!=at_start['menu']:
                    experiment.call(label+'_close','popped=api.PopTopUI()',"{'accepted':popped}")
                    time.sleep(.6)
        _arm(experiment,'stock_inventory_return_arm')
        return {'seeded':seeded,'captures':seen,'return':diagnostics(experiment,'stock_inventory_returned')}
    finally:
        code=prefix+(
            "before=%r\n"
            "for i,item in enumerate(before):\n"
            "    if items.GetPlayerItem(slots,i,True): items.SetInvItemNum(i,0)\n"
            "    if item and not items.SpawnItemToPlayerInv(item,player,i): raise RuntimeError('Cannot restore owned inventory slot')\n"
            "after=[items.GetPlayerItem(slots,i,True) for i in range(4)]\n"
            "_result=json.dumps({'before':before,'after':after,'exact':before==after})" % backup)
        receipt=experiment.server('stock_inventory_restored',code)
        if not receipt['exact']:
            raise RuntimeError('Owned inventory restoration differs from the pre-test snapshot')


def relocate(experiment, label, viewport, roi):
    if viewport != experiment.viewport:
        experiment.invoke([sys.executable,'-B','-X','utf8',str(HERE/'host.py'),'resize',
            '--project',str(experiment.args.project.resolve()),'--evidence',str(experiment.evidence),
            '--width',str(viewport[0]),'--height',str(viewport[1])],label+'_resize')
        time.sleep(.4)
    code = "probe.configure('off')\nprobe.viewport=%r\nprobe.roi=%r\nprobe._effects_ready()\nprobe.configure('all')"%(viewport,roi)
    experiment.call(label+'_update_layout',code)
    experiment.viewport,experiment.roi = list(viewport),list(roi)
    return {'state':state(experiment,label+'_state'),'exact':diagnostics(experiment,label)}


def _source(report, roi):
    x,y,w,h = roi
    with Image.open(report['capture_file']) as frame:
        return np.array(frame.convert('RGB').crop((x,y,x+w,y+h)),dtype=np.int16)


def residual_reader(experiment):
    # Leave every geometry hidden, including the ROI clear rectangle. Playing
    # only the matched late stencil readers tests the next frame for stale bits.
    setup = ("probe.configure('off')\nprobe.inspect(1,restore_enabled=False)\n"
             "if not probe.post.SetParameter('stencil_integrated_consumer','output',[0.,650.,720.,0.]): "
             "raise RuntimeError('No residual diagnostic location')\n"
             "if not all(c.Play() for c in probe.controls): raise RuntimeError('No late stencil reader')")
    experiment.call('residual_reader_only_arm',setup)
    time.sleep(.65)
    try:
        return screenshot(experiment,'residual_after_off',True,bytes(len(experiment.payload)))
    finally:
        experiment.call('residual_reader_only_stop',"probe.configure('off')")


def toggle_and_resize(experiment):
    first = state(experiment,'transitions_before')
    experiment.call('known_reference_start','probe.configure_known_fixture(True,True)')
    try:
        rows = [experiment.raw_capture('toggle_'+label, cfg)
                for label,cfg in [('before','off'),('active','all'),('after','off')]]
        before,active,after = [_source(row,experiment.roi) for row in rows]
        comparison = {
            'source_pixels':before.shape[0]*before.shape[1],
            'after_off_rgb_changes':int(np.any(before!=after,axis=2).sum()),
            'active_error_above_2':int(np.any(np.abs(before-active)>2,axis=2).sum())}
        if comparison['after_off_rgb_changes'] or comparison['active_error_above_2']:
            raise RuntimeError('Known RGB toggle comparison failed: '+repr(comparison))
    finally:
        experiment.call('known_reference_stop','probe.configure_known_fixture(False)')
    results = {'screen_recovery':comparison,'residual_reader':residual_reader(experiment),
               'reopened':diagnostics(experiment,'toggle_reopened')}
    try:
        results['move'] = relocate(experiment,'data_moved',BASE_VIEW,[48,160,512,512])
        results['resize'] = relocate(experiment,'viewport_resized',[1120,1080],[48,160,1024,256])
    finally:
        results['return'] = relocate(experiment,'viewport_original',BASE_VIEW,BASE_ROI)
    results['same_allocations'] = all(results[key]['state']['probe'][name]==first['probe'][name]
                                     for key in ('move','resize','return') for name in FROZEN)
    return results


def _arm(experiment, name):
    experiment.call(name,
        "probe.configure('all')\nprobe.inspect(1)\n"
        "if not probe.post.SetParameter('stencil_integrated_consumer','output',[0.,650.,720.,0.]): "
        "raise RuntimeError('No resident diagnostic location')")


def transit(experiment, label, target, position, player_id):
    code = "dim=api.GetEngineCompFactory().CreateDimension(%r)\nok=dim.ChangePlayerDimension(%d,%r)\n_result=json.dumps({'accepted':ok})"%(
        player_id,target,tuple(position))
    receipt = experiment.server(label+'_request',code)
    if not receipt['accepted']:
        raise RuntimeError('Owned dimension request rejected')
    for attempt in range(12):
        time.sleep(.65)
        item = state(experiment,label+'_poll_%02d'%attempt)
        if item['dimension']==target:
            time.sleep(.75)
            return {'state':item,'unattended':screenshot(experiment,label+'_without_rebind',True)}
    raise RuntimeError('Owned client dimension did not settle to %d'%target)


def dimension(experiment):
    first = state(experiment,'dimension_start')
    if first['dimension']!=0:
        raise RuntimeError('Expected Overworld')
    player_id = experiment.call('dimension_player',expression='api.GetLocalPlayerId()')
    location = experiment.server('dimension_position',
        'p=api.GetEngineCompFactory().CreatePos(%r)\n_result=json.dumps(p.GetPos())'%player_id)
    if location is None:
        raise RuntimeError('Owned player position unavailable')
    _arm(experiment,'dimension_arm')
    output = {'before':first,'player_position':location,
              'initial_unattended':screenshot(experiment,'dimension_before_exact',True)}
    if not output['initial_unattended']['exact']:
        raise RuntimeError('World transition requires a positive payload read before transit')
    try:
        output['nether'] = transit(experiment,'dimension_nether',1,[0,70,0],player_id)
    finally:
        output['overworld'] = transit(experiment,'dimension_overworld',0,location,player_id)
    output['survived_without_rebind'] = all(output[k]['unattended']['exact'] for k in ('nether','overworld'))
    return output


def run(experiment, *, include_dimension=True):
    if (experiment.variant != 'carrier' or experiment.viewport != BASE_VIEW
            or experiment.roi != BASE_ROI or len(experiment.payload)!=65536):
        raise ValueError('The live 720x1080 carrier with a 64 KiB allocation is required')
    results = {}
    checks = [
        ('inventory',lambda: menu(experiment,'native_inventory',
            'api.OpenInventoryGui(api.GetMinecraftEnum().InventoryType.NATURE,True)')),
        ('pause',lambda: menu(experiment,'native_pause','api.OpenPauseGui(True)')),
        ('stock_glint',lambda: stock_inventory(experiment)),
        ('toggle_and_resize',lambda: toggle_and_resize(experiment))]
    if include_dimension:
        checks.append(('dimension',lambda: dimension(experiment)))
    for name,check in checks:
        try:
            _arm(experiment,'arm_'+name)
            results[name] = {'result':check(),'error':None}
        except (RuntimeError,ValueError,OSError,KeyError) as error:
            results[name] = {'error':repr(error)}
        finally:
            (experiment.evidence/'lifecycle-results.json').write_text(
                json.dumps(results,indent=2)+'\n',encoding='utf-8')
    return results
