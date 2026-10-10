"""
Comprehensive Tests for Teach by Doing ALLOW & RUN Execution Pipeline:
- Verification of real Windows execution when ALLOW & RUN is triggered.
- Verification that mode="REAL" strictly invokes execute_real_workflow.
- Verification of required debug logs ([TEACH] Permission granted, [TEACH] Target Mode = REAL, etc.).
- Verification of structured execution contract:
  {
      "status": "SUCCESS" | "FAILED",
      "mode": "REAL",
      "workflow_id": ...,
      "completed_steps": ...,
      "total_steps": ...,
      "failed_step": ...,
      "error": ...,
      "verification": True/False
  }
- Verification that failure propagates (no false success).
- Verification of execute-stream live events.
"""

import os
import sys
import unittest
import io
from pathlib import Path
from contextlib import redirect_stdout
from fastapi.testclient import TestClient

import app
import database as db
import workflow as wf_engine


class TestTeachAllowAndRun(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.desktop_dir = Path.home() / "Desktop"

    def test_teach_allow_and_run_real_execution(self):
        """
        Test that Teach by Doing ALLOW & RUN triggers real Windows desktop execution,
        logs the exact required debug messages, verifies desktop changes, and returns
        the structured contract with status = 'SUCCESS'.
        """
        test_folder = self.desktop_dir / "WorkflowOS_TeachTest_Folder"
        test_file = test_folder / "taught_output.txt"

        # Cleanup if existed
        if test_file.exists():
            test_file.unlink()
        if test_folder.exists():
            test_folder.rmdir()

        # Simulate a learned workflow produced by Teach by Doing
        taught_plan = {
            "name": "Teach by Doing Directory and File Workflow",
            "goal": "Create test directory and write verification file on Desktop",
            "confidence": 0.96,
            "actions": [
                {
                    "type": "CREATE_FOLDER",
                    "label": f"Create directory: {test_folder.name}",
                    "params": {"path": str(test_folder)},
                    "risk": "LOW"
                },
                {
                    "type": "CREATE_FILE",
                    "label": f"Create file: {test_file.name}",
                    "params": {"path": str(test_file), "content": "Verified Real Teach By Doing Execution"},
                    "risk": "LOW"
                }
            ]
        }

        # 1. Save workflow
        save_res = self.client.post("/api/workflows", json={"plan": taught_plan, "mode": "REAL"})
        self.assertEqual(save_res.status_code, 200)
        wf_id = save_res.json()["workflow_id"]
        self.assertGreater(wf_id, 0)

        # 2. Click ALLOW & RUN
        f = io.StringIO()
        with redirect_stdout(f):
            exec_res = self.client.post("/api/workflows/execute", json={
                "workflow_id": wf_id,
                "mode": "REAL",
                "actions": taught_plan["actions"],
                "source": "teach",
                "confirmed_medium": True,
                "confirmed_high": True
            })
        out = f.getvalue()

        self.assertEqual(exec_res.status_code, 200)
        data = exec_res.json()

        # Contract checks
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["mode"], "REAL")
        self.assertEqual(data["workflow_id"], wf_id)
        self.assertEqual(data["completed_steps"], 2)
        self.assertEqual(data["total_steps"], 2)
        self.assertIsNone(data["failed_step"])
        self.assertIsNone(data["error"])
        self.assertTrue(data["verification"])

        # Check required debug logs
        self.assertIn("[TEACH] Permission granted", out)
        self.assertIn(f"[TEACH] Workflow ID = {wf_id}", out)
        self.assertIn("[TEACH] Target Mode = REAL", out)
        self.assertIn("[TEACH] Actions = 2", out)
        self.assertIn("[TEACH] Sending workflow to REAL executor", out)
        self.assertIn("[REAL] Starting workflow execution", out)
        self.assertIn("[REAL] Step 1/2", out)
        self.assertIn("[REAL] Step 2/2", out)
        self.assertIn("[REAL] Verification = SUCCESS", out)
        self.assertIn("[REAL] Workflow verification = SUCCESS", out)

        # Verify real desktop changes
        self.assertTrue(test_folder.exists(), "Target folder should exist on real desktop")
        self.assertTrue(test_file.exists(), "Target file should exist on real desktop")
        self.assertEqual(test_file.read_text(encoding="utf-8"), "Verified Real Teach By Doing Execution")

        # Cleanup
        if test_file.exists():
            test_file.unlink()
        if test_folder.exists():
            test_folder.rmdir()

    def test_teach_allow_and_run_failure_propagation(self):
        """
        Verify that if any step in the learned workflow fails verification,
        the system returns status = 'FAILED', failure propagates, and no false success occurs.
        """
        non_existent_src = self.desktop_dir / "NonExistent_Fake_File_9999.txt"
        target_dest = self.desktop_dir / "SomeDestFolder"

        failing_plan = {
            "name": "Failing Learned Move Workflow",
            "goal": "Move non-existent file",
            "actions": [
                {
                    "type": "MOVE_FILE",
                    "label": "Move missing file",
                    "params": {"source": str(non_existent_src), "destination": str(target_dest)},
                    "risk": "LOW"
                }
            ]
        }

        save_res = self.client.post("/api/workflows", json={"plan": failing_plan, "mode": "REAL"})
        wf_id = save_res.json()["workflow_id"]

        f = io.StringIO()
        with redirect_stdout(f):
            exec_res = self.client.post("/api/workflows/execute", json={
                "workflow_id": wf_id,
                "mode": "REAL",
                "actions": failing_plan["actions"],
                "source": "teach",
                "confirmed_medium": True,
                "confirmed_high": True
            })
        out = f.getvalue()

        self.assertEqual(exec_res.status_code, 200)
        data = exec_res.json()

        # Failure contract checks
        self.assertEqual(data["status"], "FAILED")
        self.assertFalse(data["verification"])
        self.assertEqual(data["completed_steps"], 0)
        self.assertEqual(data["total_steps"], 1)
        self.assertIsNotNone(data["failed_step"])
        self.assertIsNotNone(data["error"])

        self.assertIn("[REAL] Verification = FAILED", out)
        self.assertIn("[REAL] Workflow verification = FAILED", out)

    def test_streaming_execution_events(self):
        """
        Test the live execution streaming endpoint (/api/workflows/execute-stream),
        ensuring real-time step_executing, step_verified, and completion events are yielded.
        """
        test_folder = self.desktop_dir / "WorkflowOS_StreamTest_Dir"
        if test_folder.exists():
            test_folder.rmdir()

        stream_plan = {
            "name": "Streaming Test Workflow",
            "goal": "Stream folder creation",
            "actions": [
                {
                    "type": "CREATE_FOLDER",
                    "label": f"Create directory: {test_folder.name}",
                    "params": {"path": str(test_folder)},
                    "risk": "LOW"
                }
            ]
        }

        save_res = self.client.post("/api/workflows", json={"plan": stream_plan, "mode": "REAL"})
        wf_id = save_res.json()["workflow_id"]

        with self.client.stream("POST", "/api/workflows/execute-stream", json={
            "workflow_id": wf_id,
            "mode": "REAL",
            "actions": stream_plan["actions"],
            "source": "teach"
        }) as response:
            self.assertEqual(response.status_code, 200)
            events = []
            for line in response.iter_lines():
                if line.strip():
                    import json
                    ev = json.loads(line)
                    events.append(ev)

        event_types = [e.get("event") for e in events]
        self.assertIn("start", event_types)
        self.assertIn("step_executing", event_types)
        self.assertIn("step_verified", event_types)
        self.assertIn("completed", event_types)

        self.assertTrue(test_folder.exists())
        test_folder.rmdir()


if __name__ == "__main__":
    unittest.main()
