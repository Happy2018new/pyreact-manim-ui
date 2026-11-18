"""Explicitly run correctness and static performance on an already owned game.

This module never launches Minecraft. Build and all CPU tests are separate.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from PIL import Image
from verify_capture import expected_bytes, payload_identity, verify_files, verify_image

HERE=Path(__file__).resolve().parent
SYSTEM='pmanim_scene_codec_large'


def copy_profile_controls(profile):
    if profile not in ('baseline','writer'):
        raise ValueError('Copy controls require baseline or writer')
    return ("probe.set_native_visible(%r)\n"
        "for name in probe.process_enabled:\n"
        "    enable=name=='scene_large_raw'\n"
        "    if not probe.post.SetEnableByName(name,enable):\n"
        "        raise RuntimeError('Static copy profile rejected '+name)\n"
        "    probe.process_enabled[name]=enable\n"
        "    probe._params(name)\n"
        "probe.profile=%r"%(profile=='writer',profile))


class Experiment:
    def __init__(self,args):
        self.args=args
        self.evidence=args.evidence.resolve()
        self.commands=self.evidence/'large_commands'
        self.commands.mkdir(exist_ok=False)
        self.serial=0
        self.state={}
        self.events=[]
        self.reports=[]
        self.samples=[]
        self.frozen=None
        self.started=time.monotonic()

    def host(self,action,label,code=None):
        path=None
        if code is not None:
            path=self.commands/(label+'.py')
            path.write_text("probe=api.GetSystem(%r,'probe')\n"%SYSTEM+code+
                "\nstate=probe.snapshot()\n"
                "state['actual_post_order']=probe.post.GetPostProcessOrder()\n"
                "state['declared_enabled_processes']=state['enabled_processes']\n"
                "state['actual_post_states']=[(name,bool(probe.post.CheckEnabledByName(name))) for name in state['actual_post_order']]\n"
                "state['enabled_processes']=[name for name,enabled in state['actual_post_states'] if enabled and name in probe.process_enabled]\n"
                "state['custom_pass_count']=len(state['enabled_processes'])\n"
                "_result=json.dumps(state)\n",encoding='utf-8')
        command=[sys.executable,'-B','-X','utf8',str(HERE/'host.py'),action,
            '--project',str(self.args.project.resolve()),'--evidence',str(self.evidence),
            '--label',label,'--timeout','120']
        if path:
            command+=['--code',str(path)]
        event={'action':action,'label':label,'started_seconds':time.monotonic()-self.started,
            'command_sha256':hashlib.sha256(path.read_bytes()).hexdigest() if path else None,
            'automatic_mutation_replay':False}
        self.events.append(event)
        with (self.evidence/(label+'.'+action+'.log')).open('x',encoding='utf-8') as log:
            result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                timeout=140.,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        event['returncode']=result.returncode
        event['finished_seconds']=time.monotonic()-self.started
        if result.returncode:
            raise RuntimeError('Host call failed; inspect state before another mutation: '+label)
        if action=='call':
            self.state=json.loads((self.evidence/(label+'.state.json')).read_text(encoding='utf-8-sig'))
            if self.state.get('error'):
                raise RuntimeError(self.state['error'])
        return label

    def call(self,label,code=''):
        self.serial+=1
        return self.host('call','%03d_%s'%(self.serial,label),code)

    def freeze(self):
        self.frozen=payload_identity(self.state)

    def assert_frozen(self):
        if payload_identity(self.state)!=self.frozen:
            raise ValueError('A query or static measurement changed resident payload identity')

    def assert_active_chain(self):
        expected={'scene_large_'+name for name in ('raw','encode','decode','consumer','integrity')}
        if (not expected.issubset(self.state['actual_post_order']) or
                self.state['native_post_effects_enabled'] or
                set(self.state['enabled_processes'])!=set(self.state['declared_enabled_processes'])):
            raise ValueError('Actual post order/state disagrees with the isolated declared chain')

    def resource_gate(self,label):
        class Status(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('percent',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong)
                for name in ('total_physical','available_physical','commit_limit','available_commit',
                    'total_virtual','available_virtual','extended_virtual')]
        status=Status()
        status.length=ctypes.sizeof(status)
        if not ctypes.WinDLL('kernel32',use_last_error=True).GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        report={name:int(getattr(status,name)) for name,_ in status._fields_}
        report['minimum_available_commit']=4*1024**3
        (self.evidence/(label+'.resources.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
        if report['available_commit']<report['minimum_available_commit']:
            raise RuntimeError('Available system commit below4GiB; no larger geometry will be submitted')

    def load(self,logical):
        self.resource_gate('before_%d'%logical)
        self.frozen=None
        self.call('prepare_%d'%logical,'probe.prepare(%d,seed=54321,generation=1)'%logical)
        deadline=time.monotonic()+30.
        while not self.state['ready']:
            if time.monotonic()>deadline:
                raise TimeoutError('Page actor uniforms did not become ready')
            time.sleep(.25)
            self.call('ready')
        current=[p for p in self.state['pages'] if p['dataset']==self.state['dataset_serial']]
        for page in current:
            self.call('upload_%d_page%02d'%(logical,page['page']),'probe.upload_page(%d)'%page['page'])
            runtime=[p for p in self.state['pages'] if p['dataset']==self.state['dataset_serial'] and p['page']==page['page']][0]
            indices=np.arange(runtime['payload_byte_base'],runtime['payload_byte_base']+runtime['payload_byte_count'],dtype=np.uint64)
            values=expected_bytes(54321,1,indices)
            values[indices>=logical]=0
            report={'dataset':self.state['dataset_serial'],'logical_bytes':logical,'page':page['page'],
                'payload_byte_base':runtime['payload_byte_base'],'payload_byte_count':runtime['payload_byte_count'],
                'record_base':runtime['record_base'],'record_count':runtime['record_count'],
                'sha256':hashlib.sha256(values.tobytes()).hexdigest(),
                'sum_u8_mod2^32':int(values.astype(np.uint64).sum())&0xffffffff,
                'runtime_fingerprint':runtime['payload_fingerprint']}
            if report['sum_u8_mod2^32']!=runtime['payload_fingerprint']['value']:
                raise ValueError('Runtime page fingerprint disagrees with independent host payload')
            (self.evidence/('payload_%d_page%02d.host-oracle.json'%(logical,page['page']))).write_text(json.dumps(report,indent=2),encoding='utf-8')
        self.freeze()
        self.resource_gate('after_%d'%logical)

    def capture(self,label,kind,code=None,expect_pass=True):
        if code:
            self.call(label+'_controls',code)
        time.sleep(self.args.settle)
        state_label=self.call(label+'_settled')
        self.assert_frozen()
        self.assert_active_chain()
        self.host('capture',label)
        receipt=self.evidence/(state_label+'.state.json')
        capture=self.evidence/(label+'.png')
        capture_receipt=json.loads((self.evidence/(label+'.json')).read_text(encoding='utf-8'))
        if (capture_receipt.get('ok') is not True or capture_receipt.get('backend')!='Windows.Graphics.Capture' or
                capture_receipt.get('agent_activation_allowed') is not False or
                capture_receipt['frame_qpc_100ns']<capture_receipt['request_qpc_100ns']):
            raise ValueError('Capture must be fresh passive native Windows.Graphics.Capture')
        output=self.evidence/(label+'.verify.json')
        report=verify_files(receipt,capture,kind,output)
        item={'label':label,'kind':kind,'expected_pass':expect_pass,'receipt':str(receipt),
            'capture':str(capture),'verification':str(output),'passed':report['passed'],
            'failed_query_pixels':report['failed_query_pixels'],'failed_guard_pixels':report['failed_guard_pixels'],
            'checked_native_query_pixels':report['checked_native_query_pixels']}
        self.reports.append(item)
        print(json.dumps(item),flush=True)
        if (report['passed']!=expect_pass or report['failed_guard_pixels'] or
                (not expect_pass and report['failed_query_pixels']<report['checked_native_query_pixels']*.9)):
            raise ValueError('Unexpected complete native pixel result '+label)
        if expect_pass and kind in ('identity','dependent'):
            wrong=dict(self.state,generation=self.state['generation']+1)
            wrong['pages']=[dict(p,generation=p['generation']+1) for p in self.state['pages']]
            with Image.open(capture) as image:
                control=verify_image(wrong,image,kind)
            control['oracle_control']='different_generation_same_native_capture'
            (self.evidence/(label+'.wrong-generation.verify.json')).write_text(json.dumps(control,indent=2),encoding='utf-8')
            if control['passed']:
                raise ValueError('Wrong generation oracle unexpectedly passed')

    def measure(self,logical,profile):
        if profile in ('baseline','writer'):
            # Keep raw enabled throughout this control turn. Native builds may
            # reset all dynamic registrations after the last custom pass stops.
            controls=copy_profile_controls(profile)
        else:
            controls="probe.set_profile(%r)"%profile
        self.call('%d_%s_controls'%(logical,profile),controls)
        self.assert_frozen()
        self.assert_active_chain()
        expected=['scene_large_raw'] if profile in ('baseline','writer') else ['scene_large_raw','scene_large_encode','scene_large_decode']
        if profile=='dependent':
            expected.append('scene_large_consumer')
        if set(self.state['enabled_processes'])!=set(expected) or self.state['native_post_effects_enabled']:
            raise ValueError('Static pass set does not match the isolated declared profile')
        current=[p for p in self.state['pages'] if p['dataset']==self.state['dataset_serial']]
        expected_visible=0 if profile=='baseline' else len(current)
        if sum(p['native_visible'] for p in self.state['pages'])!=expected_visible:
            raise ValueError('Native attachment visibility disagrees with the static profile')
        allocation={'payload_bytes_all_datasets':self.state['allocated_payload_bytes_all_datasets'],
            'records_all_datasets':self.state['allocated_records_all_datasets'],
            'anchor_count':len(self.state['pages'])}
        self.call('%d_%s_start'%(logical,profile),'probe.start_static_measurement(%r,2.)'%self.args.seconds)
        deadline=time.monotonic()+self.args.seconds+22.
        while True:
            time.sleep(3.)
            self.call('%d_%s_status'%(logical,profile))
            self.assert_frozen()
            self.assert_active_chain()
            if not self.state['measurement_running']:
                break
            if time.monotonic()>deadline:
                raise TimeoutError('Measurement did not finish; start was not replayed')
        measured=self.state['last_measurement']
        if (not measured or measured['sample_seconds']<self.args.seconds or measured['warmup_seconds']!=2. or
                measured['pass_count']!=len(expected)):
            raise ValueError('Static measurement window/pass count mismatch')
        reported_profile={'baseline':'copy_baseline','writer':'writer_copy'}.get(profile,profile)
        entry={'logical_bytes':logical,'profile':reported_profile,'runtime_profile':profile,'custom_pass_count':len(expected),
            'native_effects_enabled':False,'same_allocations_for_all_profiles_of_this_dataset':allocation,
            'baseline_native_attachments_hidden':profile=='baseline','measurement':measured,
            'frozen_payload_identity':True,'continuous_updates':False,'fps_cap':60}
        self.samples.append(entry)
        print(json.dumps({'logical_bytes':logical,'profile':reported_profile,'fps':measured['fps'],
            'interval_ms':measured['interval_ms']}),flush=True)

    def run(self):
        resize=json.loads((self.evidence/'resize_native.json').read_text(encoding='utf-8'))
        if resize.get('result',resize).get('actualClient')!=[1080,1440]:
            raise ValueError('A successful owned1080x1440resize receipt is required before native submission')
        metadata=json.loads((self.args.project/'probe_resources.json').read_text(encoding='utf-8'))
        fixed=metadata.get('fixed_logical_bytes')
        capacities=self.args.bytes or ([fixed] if fixed else [262144,524288])
        if fixed and capacities!=[fixed]:
            raise ValueError('Requested capacities disagree with the compile-fixed native overlay ROI')
        for position,logical in enumerate(capacities):
            self.load(logical)
            if not self.state['pipeline_installed']:
                self.call('install','probe.install_pipeline()')
                time.sleep(.3)
                self.call('connect','probe.finish_pipeline()')
            else:
                self.call('configure_%d'%logical,"probe.set_profile('restore')")
            if self.state['native_post_effects_enabled']:
                raise ValueError('Native effects must actually be disabled before correctness or FPS checks')
            self.assert_active_chain()
            if position==0:
                for kind in ('calibration','coordinates','screeninfo'):
                    self.capture('native_'+kind,kind,"probe.set_profile(%r)"%kind)
            for kind in ('identity','dependent','integrity'):
                self.capture('%d_before_%s'%(logical,kind),kind,"probe.set_profile(%r)"%kind)
            self.capture('%d_hidden'%logical,'identity',"probe.set_profile('identity')\nprobe.set_native_visible(False)",False)
            self.capture('%d_restored_identity'%logical,'identity',"probe.set_profile('identity')")
            if not self.args.correctness_only:
                for profile in ('baseline','writer','restore','dependent'):
                    self.measure(logical,profile)
            for kind in ('identity','dependent','integrity'):
                self.capture('%d_after_%s'%(logical,kind),kind,"probe.set_profile(%r)"%kind)
        self.call('quiesce','probe.quiesce()')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=25.)
    parser.add_argument('--settle',type=float,default=.3)
    parser.add_argument('--correctness-only',action='store_true')
    parser.add_argument('--bytes',type=int,nargs='+',choices=(262144,524288))
    args=parser.parse_args()
    if not 20.<=args.seconds<=25. or not .1<=args.settle<=2.:
        parser.error('Use20..25sample seconds and0.1..2settle seconds')
    task=Experiment(args)
    result={'schema':'scene_codec_large_experiment_v1','status':'running','runtime_file_writes':False,
        'continuous_updates':False,'formal_fps_requested':not args.correctness_only,'formal_fps_measured':False,
        'isolation_condition':'fixed clear weather; native config and reported flags disabled; copy baseline1/writer copy1/restore3/dependent4',
        'rain_compatibility_claimed':False,'bloom_compatibility_claimed':False}
    try:
        task.run()
        result['status']='passed'
    except (OSError,RuntimeError,ValueError,KeyError,TimeoutError,subprocess.SubprocessError) as error:
        result.update(status='failed',error='%s: %s'%(type(error).__name__,error),automatic_mutation_replayed=False)
        raise
    finally:
        result.update(reports=task.reports,samples=task.samples,events=task.events,final_state=task.state,
            elapsed_host_seconds=time.monotonic()-task.started,formal_fps_measured=bool(task.samples))
        with (task.evidence/'large_codec.results.json').open('x',encoding='utf-8') as output:
            json.dump(result,output,indent=2)


if __name__=='__main__':
    main()
