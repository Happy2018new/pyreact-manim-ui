"""Run the isolated particle candidate with a real additional stock SFX pack."""
import argparse
from pathlib import Path
import shutil
import sys
import time

from PIL import Image

from matrix import TOOLS, load_module, read_json, save_json, sha256

PARTICLE = TOOLS / "native_stencil_particle_candidate"
PACK = TOOLS / "native_stencil_pack_order_fixture"
CANARY_POSITION = (632, 160)


def verify_canary_images(reports, verify, evidence):
    observed = {}
    for row in reports:
        path = Path(row["capture_file"]).resolve(strict=True)
        if path.parent != evidence or path.suffix.lower() != ".png":
            raise ValueError("Use the owned case's native PNGs.")
        if path.name in observed:
            raise ValueError("Duplicate capture in pack-order receipt.")
        with Image.open(path) as frame:
            result = verify(frame, CANARY_POSITION)
        observed[path.name] = {"sha256": sha256(path), **result}
    return observed


def run(experiment, plan, packs, check_pixels, particle_run):
    status = {"failure": None, "pack_order": None, "candidate_pass": False, "canary": {}, "pass": False}
    evidence = experiment.evidence
    canary_created = False
    capture_start = None
    try:
        relation = {"first": "before", "last": "after"}[plan["plan"]["input_position"]]
        status["pack_order"] = packs.deployed_order(
            experiment.session, experiment.args.project, plan["fixture"],
            "manim-native-stencil-compat", expected_relation=relation)
        if status["pack_order"]["material_conflict_present"] is not True:
            raise RuntimeError("Test pack does not override the stock SFX asset.")
        experiment.initialize()
        canary_created = True
        experiment.call("particle_pack_canary_open",
            "registered=api.RegisterUI('pmanim_pack_order_canary','canary',"
            "'pmanim_pack_order_fixture.runtime.PackOrderCanary','pmanim_pack_order_canary.main')\n"
            "if not registered: raise RuntimeError('Pack canary registration failed')\n"
            "probe.pack_order_canary=api.CreateUI('pmanim_pack_order_canary','canary',{'isHud':1})\n"
            "if probe.pack_order_canary is None: raise RuntimeError('Pack canary creation failed')")
        time.sleep(0.7)
        experiment.call("particle_pack_canary_show",
                        "probe.pack_order_canary.configure(True,(720,1080),%r)" % (CANARY_POSITION,))
        capture_start = len(experiment.reports)
        experiment.raw_capture("particle_pack_canary_initial")
        result = particle_run(experiment)
        status["candidate_pass"] = result["pass"] is True
    except Exception as error:
        status["failure"] = repr(error)
        raise
    finally:
        if capture_start is not None:
            try:
                status["canary"] = verify_canary_images(
                    experiment.reports[capture_start:], check_pixels, evidence)
                status["pass"] = (status["candidate_pass"] and len(status["canary"]) > 1
                                  and all(row["exact"] for row in status["canary"].values()))
            except (OSError, ValueError) as error:
                status["canary_verification_failure"] = repr(error)
        if canary_created:
            try:
                experiment.call("particle_pack_canary_remove",
                    "canary=getattr(probe,'pack_order_canary',None)\n"
                    "if canary is not None: canary.SetRemove()")
            except Exception as error:
                status["cleanup_failure"] = repr(error)
                status["pass"] = False
        save_json(evidence / "particle-pack-order-status.json", status)
        experiment.save()
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("project", "evidence", "previous-evidence", "plan"):
        parser.add_argument("--" + option, type=Path, required=True)
    args = parser.parse_args()
    args.project, args.evidence, args.previous_evidence = (
        path.resolve() for path in (args.project, args.evidence, args.previous_evidence))
    plan = read_json(args.plan)
    if not plan:
        parser.error("Missing prepared pack-order plan.")
    args.evidence.mkdir()
    shutil.copyfile(args.previous_evidence / "launch.json", args.evidence / "launch.json")
    sys.path.insert(0, str(PARTICLE))
    candidate = load_module("particle_matrix_native_runner", PARTICLE / "runner.py")
    packs = load_module("particle_matrix_order_checker", PACK / "build_fixture.py")
    pixels = load_module("particle_matrix_canary_checker", PACK / "verify.py")
    experiment = candidate.ParticleExperiment(args)
    result = run(experiment, plan, packs, pixels.verify, candidate.run)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
