"""Owner-bound host checks for real scene alpha and native effect compatibility."""
import argparse
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/scene_codec_probe'))
from runner import Experiment, compare, sample_pixels, expected_query


class CompatExperiment(Experiment):
    def capture(self, suffix, code):
        result = super().capture(suffix, code)
        self.result.with_suffix('.progress.json').write_text(json.dumps(
            {'reports':self.reports,'events':self.events},ensure_ascii=False,indent=2),encoding='utf-8')
        return result

    def initialize_world(self):
        camera = self.client('initial_camera', "camera=probe.factory.CreateCamera(probe.level)\n"
                             "_result=json.dumps({'position':camera.GetPosition(),'forward':camera.GetForward(),"
                             "'player':api.GetLocalPlayerId()})")
        origin = [int(camera['position'][0]), int(camera['position'][1])-1, int(camera['position'][2])]
        self.origin, self.player = origin, camera['player']
        self.client('camera_fixed', "camera=probe.factory.CreateCamera(probe.level)\n"
                    "camera.DepartCamera()\naccepted=[camera.SetCameraPos(%r),camera.SetCameraRotation((8.,180.,0.))]\n"
                    "_result=json.dumps({'accepted':accepted,'position':camera.GetPosition(),'forward':camera.GetForward()})" %
                    (tuple((origin[0], origin[1]+1., origin[2])),))
        self.server('clear_mobs', "command=api.GetEngineCompFactory().CreateCommand(api.GetLevelId())\n"
                    "_result=json.dumps({'clear_nonplayers':command.SetCommand('/kill @e[type=!player]')})")
        self.call('load', 'probe.pipeline_ready=False\nif probe.logical_bytes!=65536:\n    probe.load_payload(65536,bits=2)\nprobe.layout[2:]=[296,192]\n'
                  'probe.codec_roi=[296,192,128,683]\nprobe._writer_controls()')
        self.compat_receipt = None

    def ensure_pipeline(self, label):
        state = self.client(label+'_order', "_result=json.dumps({'order':probe.post.GetPostProcessOrder()})")
        if 'scene_codec_decode' not in state['order']:
            self.client(label+'_reinstall', "from geometry_atlas_probe.scene_config import PROCESSES\n"
                        "accepted=[probe.post.AddPostProcess(process,index)for index,process in enumerate(PROCESSES)]\n"
                        "probe.pipeline_installed=True\nprobe.pipeline_ready=False\nprobe.pipeline=PROCESSES[-1]\n"
                        "_result=json.dumps({'added':accepted,'order':probe.post.GetPostProcessOrder()})")
            time.sleep(.5)
            self.call(label+'_reconnect', 'probe.finish_pipeline()')
        if 'scene_codec_compat_consumer_after' in (state['order'] or []):
            return
        receipt = self.client(label+'_compat_install', "from geometry_atlas_probe import compat_runtime_client as compat\n"
                    "import copy\nfrom geometry_atlas_probe.scene_config import PROCESSES\n"
                    "process=copy.deepcopy(next(p for p in PROCESSES if p['name']=='scene_codec_consumer'))\n"
                    "process['name']='scene_codec_compat_consumer_after'\n"
                    "accepted=probe.post.AddPostProcess(process,len(probe.post.GetPostProcessOrder()))\n"
                    "_result=json.dumps({'late_consumer_added':accepted,'chain':compat.install(probe.post,('scene_codec_decode',0))})")
        time.sleep(.5)
        self.client(label+'_compat_connect', "accepted=probe.post.PostPassResultToOtherPass('scene_codec_encode',0,'scene_codec_compat_consumer_after',0,3)\n"
                    "_result=json.dumps({'late_consumer_connected':accepted})")
        self.compat_receipt = receipt

    def prepare_scene(self, name):
        case = 'solid' if name == 'particle' else name
        receipt = self.server(name+'_prepare', "from geometry_atlas_probe import compat_scene_server as scene\n"
                    "_result=json.dumps(scene.prepare(api,api.GetLevelId(),%r,%r,player_id=%r))" %
                    (tuple(self.origin), case, self.player))
        if name == 'particle':
            self.particle = self.client('particle_spawn', "from geometry_atlas_probe import compat_runtime_client as compat\n"
                        "_result=json.dumps(compat.spawn_translucent_particle(api,%r))" %
                        (tuple((self.origin[0], self.origin[1]+1., self.origin[2]+3.)),))
        time.sleep(3.)
        return receipt

    def effect_controls(self, bloom=False, dof=False):
        return "probe.post.SetEnableByName('scene_codec_compat_consumer_after',False)\n"

    def select_effects(self, label, bloom=False, dof=False):
        self.client(label+'_effects', "accepted=[probe.post.SetEnableByName('bloom',%r),probe.post.SetEnableByName('depthoffield',%r)]\n"
                    "_result=json.dumps({'accepted':accepted,'order_after_native_toggle':probe.post.GetPostProcessOrder(),"
                    "'bloom':probe.post.CheckEnabledByName('bloom'),'dof':probe.post.CheckEnabledByName('depthoffield')})" % (bloom,dof))
        time.sleep(1.)
        self.ensure_pipeline(label)

    def late_query(self, suffix, mode):
        name = 'scene_codec_compat_consumer_after'
        code = ("probe.post.SetParameter(%r,'codec',[2.,65536.,%d.,0.])\n"
                "probe.post.SetParameter(%r,'roi',[296.,192.,128.,683.])\n"
                "probe.post.SetParameter(%r,'physical',[720.,1080.,1.,65536.])\n"
                "probe.post.SetEnableByName(%r,True)" % (name,mode+3,name,name,name))
        return self.checked(suffix,code,[expected_query(i,mode,65536,29) for i in range(65536)],native=True,consumer=True)

    def real_cases(self):
        self.initialize_world()
        for name in self.args.cases.split(','):
            self.prepare_scene(name)
            self.select_effects(name+'_off')
            # Native effect images precede diagnostics; all data readers are off.
            disabled = "for process in probe.codec_processes:\n    probe.post.SetEnableByName(process,False)\n"
            _, visible = self.capture(name+'_visible', self.effect_controls()+disabled+'probe.set_native_writer_visible(False)')
            visible['meaning'] = 'Actual scene image; feature visibility must be visually checked, command receipt is separate.'
            self.ensure_pipeline(name+'_after_visible')
            self.call(name+'_codec','probe.set_native_writer_visible(True)\nprobe.configure_codec()')
            grid, distribution = self.capture(name+'_alpha_grid', self.effect_controls()+'probe.diagnostic(1,True)')
            roi = grid.crop((296,192,424,875))
            codes = [p[0] for p in roi.getdata()]
            distribution.update(sample_count=len(codes),histogram=dict(sorted(Counter(codes).items())),
                                off_byte_grid_flags=sum(p[2]>127 for p in roi.getdata()),
                                maximum_displayed_residual=max(p[1] for p in roi.getdata()),
                                precision_limit='Shader residual flags with quantized screenshot; not attachment-format proof')
            blocks, block_report = self.capture(name+'_alpha_blocks','probe.diagnostic(2,False)')
            values = [blocks.getpixel((296+i%128,192+i//128)) for i in range(0,87424,32)]
            block_report.update(blocks=len(values),overflow_blocks=sum(p[1]>127 for p in values),
                                exception_histogram=dict(sorted(Counter(int(p[0]*32/255.+.5)for p in values).items())))
            self.checked(name+'_alpha_sameframe','probe.inspect(20,0,87424)',[(0,0,0)]*87424,native=True)
            # Restore is the last custom source before the original native chain.
            finish = ("probe.configure_codec()\nprobe.post.SetEnableByName('scene_codec_inspect',False)\n"
                      "probe.set_native_writer_visible(True)\n")
            for effect, bloom, dof in (('bloom',True,False),('dof',False,True),('both',True,True)):
                self.select_effects(name+'_'+effect,bloom,dof)
                self.capture(name+'_'+effect,finish+self.effect_controls())
            native = self.client(name+'_native_states', "_result=json.dumps({'states':[(n,probe.post.CheckEnabledByName(n))for n in probe.post.GetPostProcessOrder()],"
                                 "'camera':probe.factory.CreateCamera(probe.level).GetPosition(),'writer':probe.snapshot()})")
            self.late_query(name+'_identity_after_native',0)
            self.late_query(name+'_dependent_after_native',2)
            if name == 'particle':
                self.client('particle_remove', "from geometry_atlas_probe import compat_runtime_client as compat\n"
                            "_result=json.dumps(compat.remove_translucent_particle(api,%r))" % self.particle['particle_id'])
        output={'kind':'real_scene_compat_evidence_v1','reports':self.reports,'events':self.events,
                'compat':self.compat_receipt,'origin':self.origin,'camera_player':self.player}
        self.result.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
        return output

    def execute(self, suffix, code, is_client=True):
        summary = json.loads((self.evidence/'launch.json').read_text(encoding='utf-8'))
        os.environ.update(MCDEV_SESSION_FILE=summary['session_file'], MCDEV_OWNER='manim-scene-codec',
                          MCDEV_ALLOW_USER_FOREGROUND='1')
        sys.path.insert(0, str(ROOT/'.agents/skills/pyreact-debugging/scripts'))
        from _session import load_session
        from _background_policy import require_background_session
        from mcdk import Client, return_value
        session = load_session(live=True)
        if Path(session['project']).resolve() != self.args.project.resolve():
            raise ValueError('Compatibility runtime project mismatch')
        before = require_background_session(session)
        path = self.commands/(self.args.name+'_'+suffix+'.py')
        path.write_text(code, encoding='utf-8')
        with Client(timeout=120.) as client:
            result = return_value(client.call('execute_code', {'code': code, 'is_client': is_client,
                                                               'direct_return': True}))
        if isinstance(result, str):
            result = json.loads(result)
        after = require_background_session(load_session(live=True))
        receipt = {'result': result, 'is_client': is_client,
                   'background_before': before, 'background_after': after}
        (self.evidence/(self.args.name+'_'+suffix+'.execute.json')).write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    def server(self, suffix, code):
        return self.execute(suffix, 'import json\nimport mod.server.extraServerApi as api\n'+code, False)

    def client(self, suffix, code):
        return self.execute(suffix, "import json\nimport mod.client.extraClientApi as api\n"
                            "probe=api.GetSystem('pmanim_geometry_atlas_probe','probe')\n"+code)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--code', type=Path)
    parser.add_argument('--stage', choices=('custom','real_cases'), default='custom')
    parser.add_argument('--settle', type=float, default=1.)
    parser.add_argument('--cases', default='solid,water_glass,rain,glint_emissive,particle')
    parser.add_argument('--server', action='store_true')
    args = parser.parse_args()
    case = CompatExperiment(args)
    if args.stage == 'real_cases':
        result=case.real_cases()
        print(json.dumps({'result':str(case.result),'captures':len(result['reports'])}))
    else:
        result = case.execute('custom', args.code.read_text(encoding='utf-8'), not args.server)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
