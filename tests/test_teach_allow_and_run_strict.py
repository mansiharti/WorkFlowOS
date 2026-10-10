"""
Comprehensive Strict Architectural Verification Suite for Teach-by-Doing ALLOW & RUN:
1. End-to-end boundary logging verification:
   [API] Received execution request
   [WORKFLOW] Loaded workflow ID = ...
   [WORKFLOW] Action count = ...
   [RUN] Loaded workflow ID = ...
   [RUN] Loaded actions = ...
   [EXECUTOR] Selected executor = ...
   [EXECUTOR] Action count = ...
   [EXECUTOR] Received actions = ...
   [REAL] Starting execution
   [REAL] Step X/N ...
   [REAL] Verification ...
   [REAL] Final verification ...
   [API] Returning execution result = SUCCESS / FAILED
2. Action preservation (action count == N, no collapsing to single CREATE_FILE).
3. Prohibition of demo / fallback workflows (non-existent workflow ID strictly returns FAILED).
4. Single source of truth for execution mode (UI, REQUEST, EXECUTOR mode mismatch fails with "Execution mode mismatch").
5. Strict verification on Windows desktop (real state checked, failure propagated).
6. Contract conformance:
   {
       "status": "SUCCESS" | "FAILED",
       "mode": "REAL",
       "workflow_id": ...,
       "total_steps": N,
       "completed_steps": ...,
       "failed_step": ...,
       "verified": True / False
   }
"""

import io
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from fastapi.testclient import TestClient

import app
import database as db


class TestTeachAllowAndRunStrictArchitecture(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.desktop_dir = Path.home() / "Desktop"

    def test_mode_mismatch_fails_loudly(self):
        """Requirement 4: If UI mode and Request/Executor mode differ, fail loudly with Execution mode mismatch."""
        f = io.StringIO()
        with redirect_stdout(f):
            res = self.client.post("/api/workflows/execute", json={
                "workflow_id": 99999,
                "ui_mode": "SANDBOX",
                "requested_mode": "REAL",
                "mode": "REAL",
                "source": "teach"
            })
        out = f.getvalue()
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "FAILED")
        self.assertFalse(data["verified"])
        self.assertIn("Execution mode mismatch", data["error"])
        self.assertIn("[MODE ERROR] Execution mode mismatch: UI=SANDBOX, REQUEST=REAL, EXECUTOR=REAL", out)

    def test_unloaded_workflow_fails_loudly_without_fallback(self):
        """Requirement 3: Missing workflow in storage MUST return FAILED, never fall back to demo/chat/file."""
        f = io.StringIO()
        with redirect_stdout(f):
            res = self.client.post("/api/workflows/execute", json={
                "workflow_id": 888888,
                "ui_mode": "REAL",
                "requested_mode": "REAL",
                "mode": "REAL",
                "source": "teach"
            })
        out = f.getvalue()
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "FAILED")
        self.assertFalse(data["verified"])
        self.assertIn("could not be loaded from storage", data["error"])
        self.assertIn("Fallback execution is prohibited", data["error"])

    def test_action_count_mismatch_fails_loudly(self):
        """Requirement 2: If expected_action_count differs from loaded actions, fail loudly."""
        # Create a saved workflow with 2 actions
        test_folder = self.desktop_dir / "WorkflowOS_CountTest_Dir"
        plan = {
            "name": "Action Count Test",
            "goal": "Test action count preservation",
            "actions": [
                {
                    "type": "CREATE_FOLDER",
                    "label": f"Create directory: {test_folder.name}",
                    "params": {"path": str(test_folder)},
                    "risk": "LOW"
                },
                {
                    "type": "CREATE_FILE",
                    "label": "Create dummy.txt",
                    "params": {"path": str(test_folder / "dummy.txt"), "content": "test"},
                    "risk": "LOW"
                }
            ]
        }
        save_res = self.client.post("/api/workflows", json={"plan": plan, "mode": "REAL"})
        wf_id = save_res.json()["workflow_id"]

        f = io.StringIO()
        with redirect_stdout(f):
            res = self.client.post("/api/workflows/execute", json={
                "workflow_id": wf_id,
                "ui_mode": "REAL",
                "requested_mode": "REAL",
                "mode": "REAL",
                "expected_action_count": 5,  # Deliberate mismatch
                "source": "teach"
            })
        out = f.getvalue()
        data = res.json()
        self.assertEqual(data["status"], "FAILED")
        self.assertFalse(data["verified"])
        self.assertIn("Action count mismatch", data["error"])
        self.assertIn("[ERROR] Action count mismatch: saved has 2, expected 5", out)

    def test_full_pipeline_with_exact_boundary_logs_and_verification(self):
        """
        Requirements 1, 2, 5, 6, 7, 8, 11:
        - Teach workflow saved with unique ID
        - Exact boundary logs emitted at every boundary
        - Action sequence preserved (N steps)
        - Real Windows desktop modified and verified
        - Success returned ONLY because desktop state verified
        """
        test_dir = self.desktop_dir / "WorkflowOS_PipelineTest_Dir"
        test_file = test_dir / "pipeline_report.txt"

        # Cleanup if existed
        if test_file.exists():
            test_file.unlink()
        if test_dir.exists():
            test_dir.rmdir()

        # Simulate recording stop endpoint saving workflow
        # Let's save a multi-action workflow directly to db
        actions = [
            {
                "type": "CREATE_FOLDER",
                "label": f"Create directory: {test_dir.name}",
                "params": {"path": str(test_dir)},
                "risk": "LOW"
            },
            {
                "type": "CREATE_FILE",
                "label": f"Create file: {test_file.name}",
                "params": {"path": str(test_file), "content": "Strict Architecture Verified"},
                "risk": "LOW"
            }
        ]
        wf_id = db.save_workflow({
            "name": "Strict Pipeline Workflow",
            "goal": "Execute multi-action taught workflow on real desktop",
            "trigger": "User Demonstration",
            "actions": actions,
            "variables": []
        })

        f = io.StringIO()
        with redirect_stdout(f):
            res = self.client.post("/api/workflows/execute", json={
                "workflow_id": wf_id,
                "ui_mode": "REAL",
                "requested_mode": "REAL",
                "mode": "REAL",
                "expected_action_count": 2,
                "source": "teach",
                "confirmed_medium": True,
                "confirmed_high": True
            })
        out = f.getvalue()

        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Validate structured contract
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["mode"], "REAL")
        self.assertEqual(data["workflow_id"], wf_id)
        self.assertEqual(data["total_steps"], 2)
        self.assertEqual(data["completed_steps"], 2)
        self.assertIsNone(data["failed_step"])
        self.assertTrue(data["verified"])

        # Boundary Logging checks
        self.assertIn("[API] Received execution request", out)
        self.assertIn(f"[API] Workflow ID = {wf_id}", out)
        self.assertIn(f"[WORKFLOW] Loaded workflow ID = {wf_id}", out)
        self.assertIn("[WORKFLOW] Action count = 2", out)
        self.assertIn(f"[RUN] Loaded workflow ID = {wf_id}", out)
        self.assertIn("[RUN] Loaded actions = 2", out)
        self.assertIn("[EXECUTOR] Selected executor = REAL", out)
        self.assertIn("[EXECUTOR] Action count = 2", out)
        self.assertIn("[EXECUTOR] Received actions = 2", out)
        self.assertIn("[REAL] Starting execution", out)
        self.assertIn("[REAL] Step 1/2 ...", out)
        self.assertIn("[REAL] Step 2/2 ...", out)
        self.assertIn("[REAL] Verification ...", out)
        self.assertIn("[REAL] Final verification ...", out)
        self.assertIn("[API] Returning execution result = SUCCESS", out)

        # Real desktop verification
        self.assertTrue(test_dir.exists())
        self.assertTrue(test_file.exists())
        self.assertEqual(test_file.read_text(encoding="utf-8"), "Strict Architecture Verified")

        # Cleanup
        if test_file.exists():
            test_file.unlink()
        if test_dir.exists():
            test_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
