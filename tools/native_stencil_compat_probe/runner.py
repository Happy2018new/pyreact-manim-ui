"""Finite stock/carrier native compatibility orchestration; one owned instance."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OWNER = 'manim-native-stencil-compat'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


integrated = module('native_compat_integrated_host_runner', HERE.parent/'weather_stencil_integrated_probe/runner.py')
integrated.HERE = HERE
integrated.bulk.HERE = HERE
integrated.bulk.OWNER = OWNER
integrated.bulk.order.HERE = HERE
integrated.bulk.order.OWNER = OWNER


class Experiment(integrated.Experiment):
    def __init__(self, args):
        super().__init__(args)
        self.variant = json.loads((args.project/'probe_resources.json').read_text(encoding='utf-8'))['native_compatibility']['variant']
        self.extra = {'variant': self.variant, 'frameani': [], 'shadow': [], 'enchanted': []}

    def save(self):
        super().save()
        if hasattr(self, 'extra'):
            (self.evidence/'compat-extra.json').write_text(json.dumps(self.extra, indent=2), encoding='utf-8')

    def initialize(self):
        self.invoke([sys.executable,'-B','-X','utf8',str(HERE/'host.py'),'resize',
                     '--project',str(self.args.project),'--evidence',str(self.evidence),
                     '--width','720','--height','1080'], 'resize')
        self.prepare_camera()
        self.weather('prepare_clear', False, True)
        self.viewport, self.roi = [720,1080], [8,128,512,512]
        self.payload = integrated.verify_module.payload_bytes(65536)
        if self.variant == 'carrier':
            self.load(65536)
        else:
            self.call('stock_viewport_only', 'probe.viewport=[720,1080]\nprobe.roi=[8,128,512,512]')
        self.call('install_pipeline', 'probe.install_pipeline()')
        time.sleep(.7)
        self.call('finish_pipeline', 'probe.finish_pipeline()')
        return self.call('fixed_camera_ready')

    def prepare_camera(self):
        """Split detached-camera requests and anchor creation across render turns."""
        initial=self.call('camera_setup_initial',expression=
            "{'origin':probe.origin,'anchor':probe.anchor,'clear_actor':probe.clear_actor is not None,"
            "'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward(),'frame':probe.render_event}")
        if initial['origin'] is not None:
            if initial['anchor'] is None or not initial['clear_actor']:
                raise RuntimeError('Partially prepared camera must not be silently reused')
            return self.call('initial_prepare_existing','api.HideCrossHairGUI(True)\nprobe.prepare()')

        def ready(value):
            vectors=(value.get('position'),value.get('forward'))
            return (all(isinstance(vector,(tuple,list)) and len(vector)==3
                        and all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in vector)
                        for vector in vectors) and sum(x*x for x in vectors[1])>0.)
        for turn in range(20):
            value=self.call('camera_attached_ready_%02d'%turn,expression=
                "{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward(),'frame':probe.render_event}")
            if ready(value) and value['frame']>initial['frame']:
                break
            time.sleep(.25)
        else:
            raise RuntimeError('Native attached camera did not settle')
        requested=self.call('camera_request_fixed',
            "position=probe.camera.GetPosition()\n"
            "probe.origin=(int(position[0]),int(position[1])-1,int(position[2]))\n"
            "probe.camera.DepartCamera()\n"
            "if not (probe.camera.SetCameraPos((probe.origin[0],probe.origin[1]+1.,probe.origin[2])) and probe.camera.SetCameraRotation((8.,180.,0.))): raise RuntimeError('Fixed camera rejected')")
        for turn in range(20):
            value=self.call('camera_detached_ready_%02d'%turn,expression=
                "{'position':probe.camera.GetPosition(),'forward':probe.camera.GetForward(),'frame':probe.render_event}")
            if ready(value) and value['frame']>requested['render_event']:
                break
            time.sleep(.25)
        else:
            raise RuntimeError('Detached camera did not settle after its public request')
        return self.call('camera_create_delayed_anchor',
            "position=%r\nforward=%r\n" % (tuple(value['position']),tuple(value['forward']))+
            "probe.anchor=tuple(position[i]+forward[i]*3. for i in range(3))\n"
            "api.HideHudGUI(True)\napi.HideCrossHairGUI(True)\nprobe.native_hud_hidden=True\n"
            "probe.clear_actor=probe._new_actor('clear',0)")

    def raw_capture(self, label, configuration='off'):
        return self.capture(label, 0, configuration=configuration, verify_pixels=False, expected=False)

    def frameani(self, route, enabled, label):
        return self.call(label,
            "probe.ordinary_frameani.set_route(%r,%r)" % (route,enabled),
            expression='probe.ordinary_frameani.snapshot()')

    def data_checks(self, prefix):
        if self.variant != 'carrier':
            return []
        return [self.capture(prefix+'_m%d' % mode, mode, output_y=650) for mode in (1,3)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--initialize-only', action='store_true')
    args = parser.parse_args()
    args.project, args.evidence = args.project.resolve(), args.evidence.resolve()
    experiment = Experiment(args)
    failure = None
    try:
        experiment.initialize()
        experiment.raw_capture('initial_scene')
        experiment.data_checks('initial_payload')
    except Exception as error:
        failure = repr(error)
        raise
    finally:
        experiment.save()
        (args.evidence/'initialize-status.json').write_text(json.dumps({'failure':failure,
            'variant':experiment.variant,'last_state':experiment.state,
            'owned_game_retained':True,'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
