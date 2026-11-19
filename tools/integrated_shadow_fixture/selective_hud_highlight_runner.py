"""Bounded native highlight retry with F1 off and separate bottom HUD parts hidden."""
import hashlib
import importlib.util
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
SOURCE=HERE/'attached_highlight_runner.py'
_SPEC=importlib.util.spec_from_file_location('frozen_attached_selective_hud_highlight',SOURCE)
attached=importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(attached)


def run(experiment):
    """Show native HUD only for this retry; restore known hidden harness state."""
    path=experiment.evidence/'selective-hud-highlight-status.json'
    if path.exists():
        raise RuntimeError('HUD-visible highlighter requires fresh evidence')
    source_hash=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    status={'schema':'native_highlight_selective_hud_retry_v1','failure':None,
            'attached_source':str(SOURCE),'attached_source_sha256_before':source_hash,
            'only_setup_change':'nativeHUD and crosshair visible; ordinary slotbar/experience, health and armor widgets hidden by public APIs',
            'reason':'HUD-visible native and carrier-active highlight positives passed, but bottom HUD occluded4074 mode1guard pixels',
            'forced_camera_rotation_refresh':False,'oracle_relaxation':False,
            'known_harness_final_hud_hidden':True,'game_lifecycle_operations':False}
    try:
        experiment.call('native_highlight_selective_hud',
            'api.HideHudGUI(False)\napi.HideCrossHairGUI(False)\napi.HideSlotBarGui(True)\n'
            "if not api.HideHealthGui(True): raise RuntimeError('Health widget hide rejected')\n"
            "if not api.HideArmorGui(True): raise RuntimeError('Armor widget hide rejected')")
        result=attached.run(experiment)
        status['attached_pass']=result.get('pass') is True and result.get('failure') is None
        status['attached_status_file']=str(experiment.evidence/'attached-highlight-status.json')
    except Exception as error:
        status['failure']=repr(error)
        raise
    finally:
        try:
            experiment.call('native_highlight_selective_hud_restore_hidden',
                'api.HideSlotBarGui(False)\napi.HideHealthGui(False)\napi.HideArmorGui(False)\n'
                'api.HideCrossHairGUI(True)\napi.HideHudGUI(True)')
            status['known_harness_hud_restore_requested']=True
        except Exception as error:
            status['known_harness_hud_restore_requested']=False
            status['hud_restore_failure']=repr(error)
            status['failure']=status['failure'] or 'Known harness HUD restoration failed'
        after=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        status['attached_source_sha256_after']=after
        status['frozen_attached_source_unchanged']=after==source_hash
        if after!=source_hash:
            status['failure']=status['failure'] or 'Frozen attached highlighter source changed'
        status['pass']=status.get('attached_pass') is True and status['failure'] is None
        path.write_text(json.dumps(status,indent=2),encoding='utf-8')
        experiment.save()
    return status
