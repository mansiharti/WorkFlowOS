"""
Automated Test Suite for WorkFlowOS Trustworthy Completion & Live Progress.
Validates:
1. Live progress state transitions: QUEUED -> RUNNING -> VERIFYING -> SUCCESS/FAILED
2. Trustworthy completion criteria:
   - Complete learned workflow executed (completed == total > 0)
   - Every required action verified (verified == total)
   - Final expected state verified (post-condition checks pass)
   - Mode and Workflow ID match requested execution
3. Immediate failure status if any step or final state check fails.
4. Prevention of false positive SUCCESS status.
"""

import os
import shutil
import unittest
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import database as db
import automation as auto
import workflow as wf_engine

TEST_SANDBOX = BASE_DIR / "tests" / "test_sandbox_trustworthy"


class TestTrustworthyCompletion(unittest.TestCase):

    def setUp(self):
        if TEST_SANDBOX.exists():
            try:
                shutil.rmtree(TEST_SANDBOX)
            except Exception:
                pass
        TEST_SANDBOX.mkdir(parents=True, exist_ok=True)
        db.DB_PATH = TEST_SANDBOX / "test_workflowos.db"
        db.init_db()
        wf_engine.setup_sandbox_environment()

    def tearDown(self):
        if TEST_SANDBOX.exists():
            try:
                shutil.rmtree(TEST_SANDBOX)
            except Exception:
                pass

    def test_live_progress_events_emitted(self):
        """Verify stream events (start, step_executing, step_verified, verifying_final_state, completed) are emitted in correct order."""
        events = []
        def callback(data):
            events.append(data)

        actions = [
            {"type": auto.ACTION_CREATE_FOLDER, "label": "Create Test Folder", "params": {"path": "live_test_folder"}},
            {"type": auto.ACTION_CREATE_FILE, "label": "Create Test File", "params": {"file": "live_test_folder/note.txt", "content": "Hello"}}
        ]
        plan = {
            "name": "Live Progress Workflow",
            "goal": "Test live progress events",
            "actions": actions
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)

        res = wf_engine.execute_workflow(
            workflow_id=wf_id,
            mode="sandbox",
            progress_callback=callback
        )

        event_types = [e["event"] for e in events]
        self.assertEqual(event_types[0], "start")
        self.assertIn("step_executing", event_types)
        self.assertIn("step_verified", event_types)
        self.assertIn("verifying_final_state", event_types)
        self.assertIn(event_types[-1], ("completed", "failed"))

        self.assertTrue(res["verification"])
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["completed_actions"], 2)
        self.assertEqual(res["verified_actions"], 2)
        self.assertEqual(res["final_verification_status"], "VERIFIED ✓")

    def test_final_state_verification_failure_marks_workflow_failed(self):
        """If a post-condition file is missing during final verification, status must be FAILED."""
        actions = [
            {"type": auto.ACTION_CREATE_FILE, "label": "Create Ghost File", "params": {"file": "ghost_test.txt", "content": "Test"}}
        ]
        plan = {
            "name": "Ghost File Workflow",
            "goal": "Test final state verification failure",
            "actions": actions
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)

        def callback(data):
            # Remove target file during verification event so post-condition fails
            if data.get("event") == "verifying_final_state":
                created = auto.resolve_sandbox_path("ghost_test.txt", base_sandbox=wf_engine.SANDBOX_DIR, must_exist=False)
                if created.exists():
                    os.remove(created)

        res = wf_engine.execute_workflow(
            workflow_id=wf_id,
            mode="sandbox",
            progress_callback=callback
        )

        self.assertFalse(res["verification"])
        self.assertEqual(res["status"], "FAILED")
        self.assertIn("Final State Verification", str(res.get("failed_step")))
        self.assertEqual(res["final_verification_status"], "FAILED ✕")

    def test_incomplete_actions_marked_failed(self):
        """If an action fails midway, overall status MUST be FAILED and failed_step recorded."""
        actions = [
            {"type": auto.ACTION_CREATE_FOLDER, "label": "Step 1 Create Folder", "params": {"path": "valid_folder"}},
            {"type": auto.ACTION_READ_FILE, "label": "Step 2 Read Missing File", "params": {"file": "nonexistent_file_99.txt"}}
        ]
        plan = {
            "name": "Failing Workflow",
            "goal": "Test step failure",
            "actions": actions
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)

        res = wf_engine.execute_workflow(
            workflow_id=wf_id,
            mode="sandbox"
        )

        self.assertFalse(res["verification"])
        self.assertEqual(res["status"], "FAILED")
        self.assertEqual(res["completed_actions"], 1)
        self.assertEqual(res["total_actions"], 2)
        self.assertIn("Step 2", res["failed_step"])

    def test_empty_actions_workflow_marked_failed(self):
        """A workflow with 0 actions can never be SUCCESS."""
        err_res = wf_engine.execute_workflow(
            workflow_id=0,
            mode="sandbox",
            actions=[]
        )
        self.assertFalse(err_res["verification"])
        self.assertEqual(err_res["status"], "FAILED")

    def test_mode_in_result_matches_requested_mode(self):
        """Result contract mode must strictly match requested mode."""
        plan = {
            "name": "Mode Test",
            "goal": "Test mode verification",
            "actions": [{"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "mode_dir"}}]
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)

        res_sandbox = wf_engine.execute_workflow(workflow_id=wf_id, mode="sandbox")
        self.assertEqual(res_sandbox["mode"], "SANDBOX")


if __name__ == "__main__":
    unittest.main()
