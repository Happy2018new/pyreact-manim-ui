"""Exercise orchestration without invoking an installed client."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import matrix


class CandidateMatrixTests(unittest.TestCase):
    def test_select_active_includes_earlier_identity(self):
        self.assertEqual(matrix.cases_for(["bloom-control", "dof-active"]),
                         ["dof-identity", "dof-active", "bloom-control"])
        with self.assertRaises(ValueError):
            matrix.cases_for(["dimension", "dimension"])

    def test_case_invocations_include_pack_plan_and_identity_receipt(self):
        base = Path("prepared")
        script, arguments = matrix.case_command(base, "particle-pack-last")
        self.assertEqual(script.name, "particle_pack_order.py")
        self.assertEqual(arguments[-1], base / "particle-pack-last/pack-order-plan.json")
        script, arguments = matrix.case_command(base, "dof-active")
        self.assertEqual(script.parent.name, "native_stencil_post_candidate")
        self.assertEqual(arguments[-1], base / "dof-identity/run-evidence" / matrix.DOF_GATE)

    def test_failed_identity_skips_active_but_runs_bloom(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            calls = []

            def execute_case(_base, case, row):
                calls.append(case)
                row["status"] = "completed"

            with (patch.object(matrix, "require_runtime_child", return_value=base),
                  patch.object(matrix, "verify_plan"),
                  patch.object(matrix, "require_no_active_game"),
                  patch.object(matrix, "execute_case", side_effect=execute_case)):
                result = matrix.execute(base, ["dof-active", "bloom-control"])
            self.assertEqual(result, 1)
            self.assertEqual(calls, ["dof-identity", "bloom-control"])
            (receipt,) = base.glob("matrix-run-*.json")
            self.assertEqual([row["status"] for row in matrix.read_json(receipt)],
                             ["completed", "skipped", "completed"])

    def test_unverified_cleanup_halts_remaining_cases(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            with (patch.object(matrix, "require_runtime_child", return_value=base),
                  patch.object(matrix, "verify_plan"),
                  patch.object(matrix, "require_no_active_game"),
                  patch.object(matrix, "execute_case", side_effect=RuntimeError("unverified stop")) as run):
                result = matrix.execute(base, ["dimension", "particle"])
            self.assertEqual(result, 1)
            run.assert_called_once()
            (receipt,) = base.glob("matrix-run-*.json")
            self.assertEqual(matrix.read_json(receipt)[0]["stop_reason"], "unverified stop")

    def test_status_distinguishes_shadow_control_and_failed_active_dof(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = Path(folder)
            matrix.save_json(evidence / "shadow-candidate-status.json",
                             {"failure": None, "compatibility": False})
            row = {}
            matrix.record_verdict("shadow-255", evidence, row)
            self.assertIs(row["visual_and_data_compatible"], False)

            matrix.save_json(evidence / "dof-active-status.json",
                             {"failure": None, "compatibility_verified": False})
            with self.assertRaisesRegex(RuntimeError, "did not match"):
                matrix.record_verdict("dof-active", evidence, {})

    def test_verify_rejects_modified_project(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            project = base / "dimension/project"
            project.mkdir(parents=True)
            exe = base / "Minecraft.Windows.exe"
            exe.write_bytes(b"test-exe")
            resource = project / "resource.json"
            resource.write_bytes(b"{}")
            plan = {"schema": matrix.SCHEMA, "native_execution_performed": False,
                    "game_exe": str(exe), "game_exe_sha256": matrix.sha256(exe), "tools": {},
                    "cases": {"dimension": {"project": matrix.hashes(project), "related_files": {}}}}
            matrix.save_json(base / matrix.PLAN, plan)
            with patch.object(matrix, "dependency_hashes", return_value={}):
                self.assertEqual(matrix.verify_plan(base, ["dimension"]), plan)
                resource.write_bytes(b"[]")
                with self.assertRaisesRegex(RuntimeError, "Prepared project changed"):
                    matrix.verify_plan(base, ["dimension"])


if __name__ == "__main__":
    unittest.main()
