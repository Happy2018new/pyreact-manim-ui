"""Diagnose native Chinese fill precision using an isolated, windowless Camera.

Run this script in the pinned reference environment once per --scene/--dtype
combination. f2 is unmodified ManimGL; f4 temporarily changes only the shared
fill framebuffer's color texture precision and is NOT a canonical reference.
No installed source, ordinary reference frames or game resources are edited.
"""
import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from pyreact_manim.reference.exporter import _reference_environment


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dtype',choices=['f2','f4'],required=True)
    parser.add_argument('--scene',choices=['direct','change','math'],required=True)
    parser.add_argument('--order',choices=['endpoint','forward','reverse'],default='endpoint')
    parser.add_argument('--output',type=Path,default=ROOT/'.runtime/native-fill-diagnosis',
                        help='Experiment-only output root; canonical .runtime/reference is rejected')
    args=parser.parse_args()
    environment=_reference_environment()
    from manimlib import Text,Transform
    from manimlib.mobject.svg.text_mobject import register_font
    from manimlib.camera.camera import Camera
    from manimlib.config import manim_config
    from manimlib.shader_wrapper import VShaderWrapper

    output_root=args.output.resolve()
    canonical=(ROOT/'.runtime/reference').resolve()
    if output_root==canonical or canonical in output_root.parents:
        parser.error('Use a separate diagnostic output directory; canonical reference output is protected')
    output=output_root/('%s-%s-%s'%(args.scene,args.dtype,args.order))
    output.mkdir(parents=True,exist_ok=True)
    previous_cache=manim_config.directories.cache
    previous_resolution=manim_config.camera.resolution
    manim_config.directories.cache=str(output_root/'manim-cache')
    Path(manim_config.directories.cache).mkdir(parents=True,exist_ok=True)
    manim_config.camera.resolution=(1280,720)
    original_factory=VShaderWrapper.__dict__['get_fill_canvas']
    original_callable=VShaderWrapper.get_fill_canvas
    if args.dtype=='f4':
        @lru_cache
        def patched_factory(context):
            framebuffer,quad,depth=original_callable(context)
            texture=context.texture(framebuffer.size,components=4,dtype='f4')
            return context.framebuffer(texture),quad,depth
        VShaderWrapper.get_fill_canvas=staticmethod(patched_factory)
    camera=None
    try:
        with register_font(ROOT/'tools/reference/fonts/PyreactManimSong-Regular.ttf'):
            source=Text('数学' if args.scene=='math' else '中文',font='Pyreact Manim Song',font_size=48).set_height(3)
            before=[len(m.get_points()) for m in source.family_members_with_points()]
            animation=None
            if args.scene!='direct':
                target=Text('中文' if args.scene=='math' else '变换',font='Pyreact Manim Song',font_size=48).set_height(3)
                animation=Transform(source,target,run_time=2)
                animation.begin()
            endpoint=1.0 if args.scene=='math' else 0.0
            order=[endpoint]
            if args.order=='forward':
                order=[0.0,0.25,0.5,0.75,1.0]
            elif args.order=='reverse':
                order=[1.0,0.75,0.5,0.25,0.0]
            order += [endpoint,endpoint]
            camera=Camera(resolution=(1280,720),frame_config={'frame_shape':(128/9,8)})
            frames=[]
            for index,alpha in enumerate(order):
                if animation:
                    animation.interpolate(alpha)
                camera.capture(source)
                image=camera.get_image()
                filename='%02d-%03d.png'%(index,round(alpha*100))
                image.save(output/filename)
                paths=[]
                for member in source.family_members_with_points():
                    points=member.get_points()
                    paths.append({'point_count':len(points),'normal':member.get_unit_normal().tolist(),
                                  'skip_markers':int(sum(np.array_equal(points[i],points[i+1]) for i in range(0,len(points)-2,2))),
                                  'points_sha256':hashlib.sha256(points.tobytes()).hexdigest()})
                frames.append({'index':index,'alpha':alpha,'file':filename,'paths':paths,
                               'png_sha256':hashlib.sha256((output/filename).read_bytes()).hexdigest()})
            fbo=VShaderWrapper.get_fill_canvas(camera.ctx)[0]
            values=np.frombuffer(fbo.read(components=4,dtype='f4',alignment=1),dtype=np.float32).reshape(fbo.height,fbo.width,4)
            # Small deterministic summaries of native fill alpha, not a replacement render.
            alpha=values[:,:,3]
            unique,counts=np.unique(alpha,return_counts=True)
            residual=sorted(((float(value),int(count)) for value,count in zip(unique,counts)
                             if 0 < abs(value) < 0.2),key=lambda item:item[1],reverse=True)[:20]
            result={'experiment':{'scene':args.scene,'dtype':args.dtype,'order':args.order},
                    'reference_kind':'unmodified_native_manimgl' if args.dtype=='f2' else 'modified_native_fill_precision_diagnostic',
                    'precision_patch':'none' if args.dtype=='f2' else 'in-memory fill canvas color attachment f2 -> f4; original native shader programs and geometry retained',
                    'standalone_context':True,'canonical_reference_modified':False,
                    'installed_source_modified':False,
                    'upstream':environment['upstream'],'input_point_counts_before_transform':before,
                    'fill_texture_dtype':fbo.color_attachments[0].dtype,
                    'fill_canvas_size':list(fbo.size),'fill_alpha_frequent_small_nonzero_values':residual,
                    'frames':frames}
            (output/'report.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
            print(args.scene,args.dtype,args.order,'points',before,'->',[m['point_count'] for m in frames[-1]['paths']],
                  'residual',residual[:5],flush=True)
    finally:
        VShaderWrapper.get_fill_canvas=original_factory
        manim_config.directories.cache=previous_cache
        manim_config.camera.resolution=previous_resolution
        if camera:
            camera.ctx.release()


if __name__=='__main__':
    main()
