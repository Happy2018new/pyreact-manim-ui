"""Prepare or execute the serial 64 KiB stencil compatibility candidate matrix."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ROOT = TOOLS.parent
COMPAT = TOOLS / "native_stencil_compat_probe"
PLAN = "matrix-plan.json"
SCHEMA = "native_stencil_candidate_matrix_v1"

CASES = (
    "dimension", "particle", "particle-pack-first", "particle-pack-last",
    "shadow-255", "shadow-191", "shadow-63",
    "dof-identity", "dof-active", "bloom-control",
)
DIRECTORIES = {
    "dimension": "native_stencil_dimension_candidate",
    "particle": "native_stencil_particle_candidate",
    "shadow": "native_stencil_shadow_candidate",
    "post": "native_stencil_post_candidate",
}
DOF_GATE = "dof-identity-status.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    imported = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(imported)
    return imported


def read_json(path):
    return path.exists() and json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(base):
    return {path.relative_to(base).as_posix(): sha256(path)
            for path in sorted(base.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts}


def dependency_hashes(cases):
    sources = {HERE, COMPAT, *(TOOLS / DIRECTORIES[family(case)] for case in cases)}
    return {f"{source.name}/{relative}": digest
            for source in sorted(sources) for relative, digest in hashes(source).items()
            if not Path(relative).name.startswith("test_")}


def family(case):
    prefix = case.split("-", 1)[0]
    return prefix if prefix in ("dimension", "particle", "shadow") else "post"


def cases_for(items):
    if len(set(items)) != len(items) or set(items) - set(CASES):
        raise ValueError("Choose distinct matrix cases.")
    chosen = set(items)
    if "dof-active" in chosen:
        chosen.add("dof-identity")
    return [case for case in CASES if case in chosen]


def require_runtime_child(path):
    path = Path(path).resolve()
    if (ROOT / ".runtime").resolve() not in path.parents:
        raise ValueError("Use a child of the repository .runtime directory.")
    return path


def prepare(base, game_exe, names):
    base = require_runtime_child(base)
    if base.exists():
        raise FileExistsError(f"Keep previous evidence and choose a fresh directory: {base}")
    game_exe = Path(game_exe).resolve(strict=True)
    if not game_exe.is_file() or game_exe.name.lower() != "minecraft.windows.exe":
        raise ValueError("Pass the installed Minecraft.Windows.exe.")
    base.mkdir(parents=True)
    builder = load_module("matrix_carrier_builder", COMPAT / "build_probe.py")
    packs = load_module("matrix_pack_order_builder",
                        TOOLS / "native_stencil_pack_order_fixture/build_fixture.py")
    cases = cases_for(names)
    receipts = {}
    for case in cases:
        directory = base / case
        project = directory / "project"
        directory.mkdir()
        builder.build(project, game_exe, "carrier")
        role = family(case)
        installer = load_module("matrix_" + role + "_builder",
                                TOOLS / DIRECTORIES[role] / "build_candidate.py")
        if role == "dimension":
            installer.install(project)
        elif role == "particle":
            installer.install(project, game_exe)
        elif role == "shadow":
            installer.install(project, game_exe, int(case.split("-")[1]))
        else:
            installer.install(project, game_exe, case)
        off_project = []
        if case.startswith("particle-pack-"):
            position = case.rsplit("-", 1)[1]
            extra = directory / "extra_addon"
            fixture = packs.install(extra, "stock_sfx_conflict", game_exe)
            changes = packs.config_plan(project, fixture, position)
            (project / ".mcdev.json").write_bytes(base64.b64decode(changes["after_base64"], validate=True))
            pack_plan = directory / "pack-order-plan.json"
            save_json(pack_plan, {"fixture": fixture, "plan": changes})
            off_project = [pack_plan, *(extra / path for path in hashes(extra))]
        receipts[case] = {
            "project": hashes(project),
            "related_files": {path.relative_to(directory).as_posix(): sha256(path)
                              for path in off_project},
        }
    plan = {"schema": SCHEMA, "native_execution_performed": False,
            "payload_bytes": 65536, "viewport": [720, 1080], "fps_cap": 60,
            "game_exe": str(game_exe), "game_exe_sha256": sha256(game_exe),
            "tools": dependency_hashes(cases), "cases": receipts}
    save_json(base / PLAN, plan)
    return base / PLAN


def verify_plan(base, cases):
    plan = read_json(base / PLAN)
    if not plan or plan.get("schema") != SCHEMA or plan.get("native_execution_performed") is not False:
        raise ValueError("A prepared candidate matrix is required.")
    executable = Path(plan["game_exe"])
    if sha256(executable) != plan["game_exe_sha256"]:
        raise RuntimeError("Installed executable changed after preparation.")
    if dependency_hashes(plan["cases"]) != plan["tools"]:
        raise RuntimeError("Candidate or orchestration source changed after preparation.")
    for case in cases:
        record = plan["cases"].get(case)
        if not record:
            raise RuntimeError(f"Case {case} was not prepared.")
        directory = base / case
        if hashes(directory / "project") != record["project"]:
            raise RuntimeError(f"Prepared project changed: {case}")
        related = {}
        if case.startswith("particle-pack-"):
            related["pack-order-plan.json"] = sha256(directory / "pack-order-plan.json")
            related.update({f"extra_addon/{relative}": digest
                            for relative, digest in hashes(directory / "extra_addon").items()})
        if related != record["related_files"]:
            raise RuntimeError(f"Prepared pack-order input changed: {case}")
    return plan


def run_command(script, arguments, log, timeout):
    command = [sys.executable, "-B", "-X", "utf8", str(script), *map(str, arguments)]
    with log.open("x", encoding="utf-8") as output:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,
                                stderr=subprocess.STDOUT, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"returncode": result.returncode, "log": str(log)}


def paths(directory):
    return tuple(directory / name for name in ("project", "launch-evidence", "run-evidence", "cleanup-evidence"))


def case_command(base, case):
    directory = base / case
    project, launch, evidence, _ = paths(directory)
    script = TOOLS / DIRECTORIES[family(case)] / "runner.py"
    arguments = ["--project", project, "--evidence", evidence, "--previous-evidence", launch]
    if case.startswith("particle-pack-"):
        script = HERE / "particle_pack_order.py"
        arguments += ["--plan", directory / "pack-order-plan.json"]
    elif case.startswith("shadow-"):
        arguments += ["--mask", case.split("-")[1]]
    elif family(case) == "post":
        arguments += ["--case", case, "--initialize"]
        if case == "dof-active":
            arguments += ["--identity-gate", paths(base / "dof-identity")[2] / DOF_GATE]
    return script, arguments


def identity_accepted(base):
    identity = read_json(paths(base / "dof-identity")[2] / DOF_GATE)
    return (isinstance(identity, dict) and identity.get("gate", {}).get("accepted") is True
            and not identity.get("failure") and not identity.get("cleanup_failure"))


def verify_host_tools():
    startup = load_module("matrix_startup_validation", TOOLS / "start_dev.py")
    startup.background_arguments(ROOT / "background-tools.local.json")
    helper = (ROOT.parent / "better-building-editor/tools/data/snow-passive-startup-r12-v6"
              / "inputs/capture/native_wgc_capture.exe")
    if not helper.is_file():
        raise FileNotFoundError(f"Passive WGC capture helper unavailable: {helper}")


def require_no_active_game():
    msaa = load_module("matrix_active_game_check", COMPAT / "msaa.py")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                             msaa.EMPTY_GAME_CHECK], check=True, capture_output=True, text=True,
                            timeout=25, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.stdout.strip() != "0":
        raise RuntimeError("An active Minecraft client exists. The serial matrix did not launch a case.")


def clean_case(case, directory):
    project, launch, _, cleanup = paths(directory)
    receipt = read_json(launch / "launch.json")
    if not receipt or not receipt.get("session_file"):
        raise RuntimeError(f"No owned launch receipt for {case}. Check managed sessions before continuing.")
    result = run_command(COMPAT / "cleanup.py",
                         ["--project", project, "--previous-evidence", launch, "--evidence", cleanup],
                         directory / "matrix-cleanup.log", 180)
    check = read_json(cleanup / "cleanup.json")
    if (result["returncode"] != 0 or not check or check.get("active_game_count") != 0
            or check.get("owned_pids_absent") is not True or check.get("session_state") != "stopped"):
        raise RuntimeError(f"Owner cleanup was not verified for {case}. Read {result['log']}.")
    return result


def read_case_result(case, evidence):
    names = {
        "dimension": "dimension-candidate-status.json",
        "particle": "particle-candidate-status.json",
        "particle-pack-first": "particle-pack-order-status.json",
        "particle-pack-last": "particle-pack-order-status.json",
        "bloom-control": "bloom_candidate_status.json",
    }
    name = names.get(case)
    if name is None:
        name = "shadow-candidate-status.json" if case.startswith("shadow-") else case + "-status.json"
    path = evidence / name
    result = read_json(path)
    if not isinstance(result, dict):
        raise RuntimeError(f"No candidate status saved at {path}.")
    return path, result


def record_verdict(case, evidence, row):
    path, result = read_case_result(case, evidence)
    row["evidence"] = str(path)
    if result.get("failure") or result.get("cleanup_failure"):
        raise RuntimeError(result.get("failure") or result["cleanup_failure"])
    if case.startswith("shadow-"):
        row["visual_and_data_compatible"] = result["compatibility"]
    elif case == "bloom-control":
        row["native_bloom_observed"] = result["native_positive_response_observed"]
        row["bloom_source_witness_passed"] = result["source_input_gate_passed"]
        if not row["bloom_source_witness_passed"]:
            raise RuntimeError("Bloom source witness failed.")
    elif case == "dof-identity" and result.get("gate", {}).get("accepted") is not True:
        raise RuntimeError("DOF identity reference failed.")
    elif case == "dof-active" and result.get("compatibility_verified") is not True:
        raise RuntimeError("Active DOF did not match the native reference.")


def execute_case(base, case, row):
    directory = base / case
    project, launch, evidence, _ = paths(directory)
    try:
        row["launch"] = run_command(COMPAT / "host.py",
                                    ["launch", "--project", project, "--evidence", launch],
                                    directory / "matrix-launch.log", 240)
        if row["launch"]["returncode"]:
            raise RuntimeError("Owned case launch failed.")
        script, arguments = case_command(base, case)
        row["run"] = run_command(script, arguments, directory / "matrix-run.log", 1500)
        if row["run"]["returncode"]:
            raise RuntimeError("Candidate runner returned a failure.")
        record_verdict(case, evidence, row)
        row["status"] = "completed"
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        row.update(status="failed", failure=str(error))
    finally:
        row["cleanup"] = clean_case(case, directory)


def compare_shadow_cases(base, rows):
    masks = (255, 191, 63)
    cases = {f"shadow-{mask}" for mask in masks}
    if not cases.issubset({row["case"] for row in rows}):
        return
    completed = {row["case"] for row in rows if row["status"] == "completed"}
    if not cases.issubset(completed):
        rows.append({"case": "shadow-comparison", "status": "skipped",
                     "failure": "All three captures and their native controls are required."})
        return
    output = base / "shadow-comparison.json"
    arguments = [item for mask in masks
                 for item in (f"--evidence-{mask}", paths(base / f"shadow-{mask}")[2])]
    row = {"case": "shadow-comparison", "status": "failed"}
    rows.append(row)
    try:
        row["run"] = run_command(TOOLS / DIRECTORIES["shadow"] / "compare_matrix.py",
                                 [*arguments, "--output", output], base / "shadow-comparison.log", 180)
        row["evidence"] = str(output)
        if row["run"]["returncode"] == 0 and output.is_file():
            row["status"] = "completed"
    except (OSError, subprocess.SubprocessError) as error:
        row["failure"] = str(error)


def execute(base, names):
    base = require_runtime_child(base)
    cases = cases_for(names)
    verify_plan(base, cases)
    for case in cases:
        directory = base / case
        _, launch, evidence, cleanup = paths(directory)
        if any(p.exists() for p in (launch, evidence, cleanup)) or any(directory.glob("matrix-*.log")):
            raise FileExistsError(f"Keep existing evidence and prepare a fresh matrix: {directory}")
    receipt_path = base / ("matrix-run-" + str(time.time_ns()) + ".json")
    rows = []
    for case in cases:
        row = {"case": case, "status": "starting", "run": None, "cleanup": None}
        rows.append(row)
        save_json(receipt_path, rows)
        if case == "dof-active":
            try:
                accepted = identity_accepted(base)
            except (OSError, ValueError) as error:
                accepted = False
                row["identity_receipt_error"] = str(error)
            if not accepted:
                row.update(status="skipped", failure="Native DOF identity gate did not pass.")
                save_json(receipt_path, rows)
                continue
        try:
            require_no_active_game()
            print(f"{case}: running owned native case", flush=True)
            execute_case(base, case, row)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            row.update(status="stopped", stop_reason=str(error))
            save_json(receipt_path, rows)
            break
        save_json(receipt_path, rows)
    compare_shadow_cases(base, rows)
    save_json(receipt_path, rows)
    print(receipt_path)
    finished = {row["case"] for row in rows if row["status"] == "completed"}
    return 0 if set(cases).issubset(finished) and all(row["status"] == "completed" for row in rows) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("prepare", "verify", "run"):
        command = actions.add_parser(name)
        command.add_argument("--base", type=Path, required=True)
        command.add_argument("--cases", nargs="+", choices=CASES)
        if name == "prepare":
            command.add_argument("--game-exe", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        print(prepare(args.base, args.game_exe, args.cases or CASES))
        return 0
    base = require_runtime_child(args.base)
    stored = read_json(base / PLAN)
    if not stored:
        parser.error(f"No prepared matrix at {base / PLAN}")
    chosen = args.cases or list(stored["cases"])
    verify_host_tools()
    if args.action == "verify":
        verify_plan(base, cases_for(chosen))
        print(f"Verified {len(cases_for(chosen))} offline projects and background tools.")
        return 0
    return execute(base, chosen)


if __name__ == "__main__":
    raise SystemExit(main())
