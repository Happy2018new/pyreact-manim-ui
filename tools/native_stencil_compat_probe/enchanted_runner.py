"""Finite native enchanted-item UI observations; visual failures retain later cases."""
import hashlib
import json
from pathlib import Path
import time

from runner import HERE, module


verify = module('native_compat_enchanted_oracle', HERE.parent/'integrated_enchanted_ui_fixture/verify.py')
DELAYS = {'normal': .37, 'mixed': .83}


def run(experiment):
    """Use the existing owned Experiment. This function neither launches nor stops it."""
    receipt_path = experiment.args.project/'enchanted_ui_fixture_receipt.json'
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    if (receipt['physical'] != [720,1080] or receipt['data_diagnostic_y'] != 650
            or any(slot['rect'][1]+slot['rect'][3] > 650 for slot in receipt['slots'])):
        raise RuntimeError('Enchanted fixture must leave all cards above the full data output')
    status = {'schema':'native_enchanted_compatibility_run_v1', 'variant':experiment.variant,
        'failure':None,'operational_failure':None,'visual_failures':[], 'groups':[],
        'normal_comparisons':[], 'cleanup':{}, 'complete':False,
        'receipt':str(receipt_path),'receipt_sha256':hashlib.sha256(receipt_bytes).hexdigest(),
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'verifier_sha256':hashlib.sha256((HERE.parent/'integrated_enchanted_ui_fixture/verify.py').read_bytes()).hexdigest(),
        'fixture_material_override':False,'stock_inventory_screen':False,
        'requested_nonperiodic_delays':dict(DELAYS)}
    output = experiment.evidence/'enchanted-status.json'

    def save():
        output.write_text(json.dumps(status,indent=2),encoding='utf-8')
        experiment.save()

    def fixture_snapshot(label):
        return experiment.call(label,expression='probe.enchanted_fixture.snapshot()')

    def capture(label,configuration):
        before = time.monotonic()
        report = experiment.raw_capture(label,configuration)
        snapshot = fixture_snapshot(label+'_fixture_state')
        return {'label':label,'capture_file':report['capture_file'],
            'capture_receipt':report['capture_receipt'],'fixture_state':snapshot,
            'started_monotonic':before,'completed_monotonic':time.monotonic()}

    def visual_failure(label,result,key):
        if result.get(key) is not True:
            status['visual_failures'].append(label)

    pending = None
    try:
        experiment.call('enchanted_open',
            'from stencil_large.enchanted_ui_fixture import EnchantedFixture\n'
            'probe.enchanted_fixture=EnchantedFixture(probe)\nprobe.enchanted_fixture.open()')
        time.sleep(.7)
        configurations = ('off',) if experiment.variant == 'stock' else ('off','all')
        for configuration in configurations:
            prefix = 'enchanted_'+experiment.variant+'_'+configuration
            item = {'configuration':configuration,'frames':[], 'payload_captures':[],
                    'normal_control_data_comparisons':[]}
            status['groups'].append(item)
            experiment.extra['enchanted'].append(item)
            save()
            for ui_mode, name, delay in (('normal_all','normal',DELAYS['normal']),
                                        ('mixed','mixed',DELAYS['mixed'])):
                experiment.call(prefix+'_'+name+'_configure',
                                'probe.enchanted_fixture.configure(%r)' % ui_mode)
                first = capture(prefix+'_'+name+'_before',configuration)
                item['frames'].append(first)
                save()
                time.sleep(delay)
                second = capture(prefix+'_'+name+'_after',configuration)
                item['frames'].append(second)
                item[name+'_actual_start_gap_seconds'] = second['started_monotonic']-first['started_monotonic']
                item[name+'_actual_frame_gap_100ns'] = (
                    second['capture_receipt']['frame_qpc_100ns']-first['capture_receipt']['frame_qpc_100ns'])
                save()
            frames = item['frames']
            result = verify.verify(*(frame['capture_file'] for frame in frames),receipt,
                                   states=[frame['fixture_state'] for frame in frames])
            item['oracle'] = result
            visual_failure(prefix,result,'all_passed')
            save()
            print(json.dumps({'enchanted':prefix,'visual_pass':result['all_visual_gates_passed'],
                              'state_pass':result['all_state_gates_passed'],
                              'empty_errors':result['empty_control_wrong_pixels'],
                              'border_errors':result['border_wrong_pixels']}),flush=True)
            if experiment.variant == 'carrier':
                # Keep mixed widgets visible. The exhaustive carrier oracle is
                # independent and may stop on an actual data correctness failure.
                for mode in (1,3):
                    report = experiment.capture(prefix+'_mixed_payload_m%d' % mode,mode,
                                                configuration='all',output_y=650)
                    state = fixture_snapshot(prefix+'_mixed_payload_m%d_state' % mode)
                    check = verify.compare_normals(frames[2]['capture_file'],report['capture_file'],receipt,mode='mixed')
                    item['payload_captures'].append({'label':report['label'],'mode':mode,
                        'fixture_state':state,'exact':report['exact'],'capture_file':report['capture_file']})
                    item['normal_control_data_comparisons'].append(check)
                    visual_failure(prefix+'_payload_m%d_normal_controls' % mode,check,'all_exact')
                    save()
        if len(status['groups']) == 2:
            off, active = status['groups']
            for index, ui_mode in ((0,'normal_all'),(2,'mixed'),(3,'mixed')):
                comparison = verify.compare_normals(off['frames'][index]['capture_file'],
                    active['frames'][index]['capture_file'],receipt,mode=ui_mode)
                label = 'enchanted_off_vs_all_'+('normal_before','normal_after','mixed_before','mixed_after')[index]
                status['normal_comparisons'].append({'label':label,'result':comparison})
                visual_failure(label,comparison,'all_exact')
                save()
        status['complete'] = True
        if status['visual_failures']:
            status['failure'] = 'Native enchanted UI visual gates failed: '+', '.join(status['visual_failures'])
    except Exception as error:
        pending = error
        status['operational_failure'] = repr(error)
        status['failure'] = repr(error)
    finally:
        for label, code in (('enchanted_cleanup_off',
                            "if hasattr(probe,'enchanted_fixture'): probe.enchanted_fixture.configure('off')"),
                           ('enchanted_cleanup_destroy',
                            "if hasattr(probe,'enchanted_fixture'): probe.enchanted_fixture.destroy()")):
            try:
                experiment.call(label,code)
                status['cleanup'][label] = True
            except Exception as error:
                status['cleanup'][label] = repr(error)
                status['failure'] = status['failure'] or 'Enchanted fixture cleanup failed: '+repr(error)
        status['all_visual_groups_passed'] = (status['complete'] and not status['visual_failures'])
        status['last_state'] = experiment.state
        save()
    if pending is not None:
        raise pending
    return status
