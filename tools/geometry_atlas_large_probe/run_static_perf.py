"""Plan or run static prefix comparisons on the already allocated2MiB dataset.

The plan action never contacts Minecraft. The run action is reserved for the
coordinated performance phase, after other research games have stopped.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
SYSTEM = 'pmanim_geometry_atlas_large_probe'
ALLOCATED_BYTES = 2097152
PAGE_BYTES = 65536


def plan(sample_seconds=25., warmup_seconds=2.):
    if not 20. <= sample_seconds <= 30. or not 2. <= warmup_seconds <= 10.:
        raise ValueError('Use20..30sample seconds and2..10warmup seconds')
    return {'schema': 'geometry_atlas_large_static_perf_v1', 'actual_sampling': False,
        'allocated_bytes_all_cases': ALLOCATED_BYTES, 'allocated_pages_all_cases': 32,
        'page_bytes': PAGE_BYTES, 'screen_size': [2560,1440],
        'sample_seconds': sample_seconds, 'warmup_seconds': warmup_seconds,
        'baseline': 'all32native geometry attachments hidden; pipeline disabled; allocations and anchors retained',
        'resident': 'native visible prefix; writer plus copy/private texture/consumer active; mode3 has no diagnostic gathers',
        'require_other_research_games_stopped': True, 'continuous_uploads': False,
        'cases': [{'active_pages': p, 'active_prefix_bytes': p*PAGE_BYTES,
            'native_visibility': [i < p for i in range(32)], 'pipeline_enabled': p > 0,
            'writer_visible': p > 0, 'diagnostic_enabled': False} for p in (0,16,24,32)]}


def frozen_identity(state):
    return {'seed': state['seed'], 'generation': state['generation'], 'slot_count': state['slot_count'],
        'loaded_bytes': state['loaded_bytes'], 'geometry_build_serial': state['geometry_build_serial'],
        'native_attempt_serial': state['native_attempt_serial'], 'geometry_names': state['geometry_names'],
        'pages': [{key: p[key] for key in ('base','count','name','seed','generation','payload_fingerprint','upload_serial')}
            for p in state['pages']]}


def controls_code(active_pages):
    if active_pages not in (0,16,24,32):
        raise ValueError('Unsupported static prefix')
    return """probe=api.GetSystem(%r,'probe')
if probe.slot_count!=2097152 or len(probe.pages)!=32 or not all(p['loaded'] for p in probe.pages):
    raise RuntimeError('Static comparison requires the existing complete2MiB dataset')
if probe.measurement is not None:
    raise RuntimeError('A previous measurement is still running')
active_pages=%d
native_visibility=[]
for index,page in enumerate(probe.pages):
    visible=index<active_pages
    accepted=page['render'].SetActorBlockGeometryVisible(page['name'],visible)
    native_visibility.append({'page':index,'name':page['name'],'visible':visible,'accepted':bool(accepted)})
    if not accepted:
        raise RuntimeError('Native geometry visibility rejected page%%d'%%index)
probe.geometry_visible=active_pages>0
probe.set_writer_visible(active_pages>0)
probe.set_pipeline_enabled(active_pages>0)
active_bytes=active_pages*65536
if active_pages:
    probe.query(3,salt=37,salt2=91,flip_y=True)
    layout=[active_bytes,2048,8,32]
    query=[0,active_bytes,7,37]
    if not probe.post.SetParameter('pmanim_geometry_atlas_gather','layout',[float(v) for v in layout]):
        raise RuntimeError('Active prefix layout rejected')
    if not probe.post.SetParameter('pmanim_geometry_atlas_gather','query',[float(v) for v in query]):
        raise RuntimeError('Resident passthrough query rejected')
    probe.layout=layout
    probe.query_value=[0,active_bytes,3,37]
else:
    probe.layout[0]=0
    probe.query_value=[0,0,3,37]
_result=json.dumps({'probe':probe.snapshot(),'controls':{'active_pages':active_pages,
    'active_prefix_bytes':active_bytes,'allocated_bytes':probe.slot_count,
    'diagnostic_enabled':False,'pipeline_enabled':active_pages>0,
    'native_visibility':native_visibility,'baseline_has_resident_allocations_and32anchors':True}})
""" % (SYSTEM,active_pages)


class StaticPerf:
    def __init__(self,args):
        self.args=args
        self.output=args.evidence.resolve()
        if self.output.exists():
            raise ValueError('Choose a new performance evidence directory')
        self.output.mkdir(parents=True)
        self.commands=self.output/'commands'
        self.commands.mkdir()
        launch=(args.source_evidence/'launch.json').read_text(encoding='utf-8')
        (self.output/'launch.json').write_text(launch,encoding='utf-8')
        self.serial=0
        self.events=[]
        self.cases=[]
        self.frozen=None

    def call(self,label,code):
        self.serial+=1
        name='%03d_%s'%(self.serial,label)
        path=self.commands/(name+'.py')
        path.write_text(code,encoding='utf-8')
        command=[sys.executable,'-B','-X','utf8',str(HERE/'host.py'),'call',
            '--project',str(self.args.project.resolve()),'--evidence',str(self.output),
            '--label',name,'--code',str(path),'--timeout','120']
        event={'label':name,'mutation_retried':False}
        self.events.append(event)
        with (self.output/(name+'.call.log')).open('x',encoding='utf-8') as log:
            result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=140.)
        event['returncode']=result.returncode
        if result.returncode:
            raise RuntimeError('Host call failed; inspect state before another mutation: '+name)
        state=json.loads((self.output/(name+'.state.json')).read_text(encoding='utf-8'))
        event['state_file']=str(self.output/(name+'.state.json'))
        return state

    def snapshot(self,label):
        return self.call(label,"probe=api.GetSystem(%r,'probe')\n_result=json.dumps(probe.snapshot())\n"%SYSTEM)

    def assert_frozen(self,state):
        current=frozen_identity(state)
        if self.frozen is None:
            self.frozen=current
        elif current!=self.frozen:
            raise ValueError('Resident payload identity changed during the static comparison')

    def run(self,settings):
        initial=self.snapshot('initial')
        if initial['slot_count']!=ALLOCATED_BYTES or initial['loaded_bytes']!=ALLOCATED_BYTES:
            raise ValueError('All2MiB must already be allocated and loaded; this driver never uploads')
        self.assert_frozen(initial)
        for case in settings['cases']:
            pages=case['active_pages']
            controlled=self.call('native_prefix_%02d'%pages,controls_code(pages))
            self.assert_frozen(controlled['probe'])
            controls=controlled['controls']
            if (len(controls['native_visibility'])!=32 or
                    sum(item['visible'] for item in controls['native_visibility'])!=pages or
                    not all(item['accepted'] for item in controls['native_visibility'])):
                raise ValueError('Native visibility receipt is incomplete')
            print(json.dumps({'stage':'sampling','active_pages':pages,'allocated_bytes':ALLOCATED_BYTES,
                'sample_seconds':settings['sample_seconds'],'warmup_seconds':settings['warmup_seconds']}),flush=True)
            code="probe=api.GetSystem(%r,'probe')\nprobe.start_measurement(%r,%r)\n_result=json.dumps(probe.snapshot())\n"%(
                SYSTEM,settings['sample_seconds'],settings['warmup_seconds'])
            self.call('start_%02d'%pages,code)
            deadline=time.monotonic()+settings['sample_seconds']+settings['warmup_seconds']+20.
            while True:
                time.sleep(3.)
                state=self.snapshot('sample_status_%02d'%pages)
                self.assert_frozen(state)
                if not state['measurement_running']:
                    break
                if time.monotonic()>deadline:
                    raise TimeoutError('Measurement did not finish; start was not replayed')
            measured=state['last_measurement']
            if not measured or measured['sample_seconds']<settings['sample_seconds'] or measured['warmup_seconds']<2.:
                raise ValueError('Measurement does not contain the required warmup and complete sample')
            entry={'active_pages':pages,'active_prefix_bytes':pages*PAGE_BYTES,
                'allocated_bytes':ALLOCATED_BYTES,'controls':controls,'measurement':measured,
                'payload_identity_frozen':True}
            self.cases.append(entry)
            print(json.dumps(entry),flush=True)
        final=self.call('quiesce',controls_code(0))
        self.assert_frozen(final['probe'])
        return final


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('plan','run'))
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--source-evidence',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--sample-seconds',type=float,default=25.)
    parser.add_argument('--warmup-seconds',type=float,default=2.)
    args=parser.parse_args()
    settings=plan(args.sample_seconds,args.warmup_seconds)
    if args.action=='plan':
        args.evidence.mkdir(parents=True,exist_ok=True)
        path=args.evidence/'static_perf.plan.json'
        with path.open('x',encoding='utf-8') as output:
            json.dump(settings,output,indent=2)
        print(json.dumps({'actual_sampling':False,'plan':str(path.resolve())}))
        return
    task=StaticPerf(args)
    summary=dict(settings,status='running',actual_sampling=True)
    try:
        summary['final']=task.run(settings)
        summary['status']='passed'
    except (OSError,RuntimeError,ValueError,KeyError,TimeoutError,subprocess.SubprocessError) as error:
        summary.update(status='failed',error='%s: %s'%(type(error).__name__,error),
            needs_state_inspection_before_any_retry=True)
        raise
    finally:
        summary.update(cases=task.cases,events=task.events)
        (task.output/'static_perf.summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
