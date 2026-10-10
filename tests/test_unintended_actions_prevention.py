"""
Unit and Integration Tests for Prevention of Unintended Actions and Strict Recording Isolation:
1. File replacement during save (create -> delete -> create) without user input does NOT produce DELETE_FILE.
2. User-demonstrated delete (Delete key / UI click) produces evidenced DELETE_FILE.
3. Synthesis rejects un-evidenced DELETE_FILE.
4. All synthesized actions have valid evidence_event_ids.
5. Real executor refuses execution of high-risk actions lacking valid evidence.
6. Recording session isolation (unique recording_id, no event leakage).
7. Strict ALLOW & RUN logging contract.
"""

import io
import time
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

import app
import database as db
from activity import ActivityCollector, FileActivityHandler
from ai import synthesize_workflow_from_events
from automation import execute_real_action, ExecutionResult


class TestUnintendedActionsPrevention(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.collector = ActivityCollector()

    def test_background_file_deletion_is_dropped_without_user_demonstration(self):
        """Rule 1 & 6: File replacement/atomic write by OS without user delete action is dropped."""
        handler = FileActivityHandler(self.collector)
        mock_event = MagicMock()
        mock_event.src_path = str(Path.home() / "Downloads" / "hello I am fine here.txt")
        mock_event.is_directory = False

        # No Delete key pressed or Delete button clicked
        self.collector.last_user_delete_key_time = 0.0
        self.collector.last_user_delete_click_time = 0.0
        self.collector.is_recording = True
        self.collector.current_recording_id = "rec_test_123"
        self.collector.events_buffer = []

        handler.on_deleted(mock_event)

        # Buffer must NOT have received any DELETE_FILE / DELETE event
        delete_events = [e for e in self.collector.events_buffer if e.get("semantic_action") == "DELETE"]
        self.assertEqual(len(delete_events), 0, "Background file deletion must NOT be recorded as user delete")

    def test_user_delete_key_enables_evidenced_delete(self):
        """Rule 5: User explicitly pressing Delete records user input and permits subsequent file delete."""
        self.collector.is_recording = True
        self.collector.current_recording_id = "rec_test_delete"
        self.collector.events_buffer = []

        # Simulate user pressing Delete key
        mock_key = MagicMock()
        from pynput import keyboard
        self.collector._on_key_press(keyboard.Key.delete)

        # Verify USER_INPUT delete was captured
        user_events = [e for e in self.collector.events_buffer if e.get("semantic_action") == "DELETE" and e.get("source") == "USER_INPUT"]
        self.assertEqual(len(user_events), 1)
        self.assertTrue(time.time() - self.collector.last_user_delete_key_time < 1.0)

        # Now simulate OS delete event within 3 seconds
        handler = FileActivityHandler(self.collector)
        mock_event = MagicMock()
        mock_event.src_path = str(Path.home() / "Downloads" / "test_file_to_remove.txt")
        mock_event.is_directory = False
        handler.on_deleted(mock_event)

        # Both user intent keypress and file delete are captured
        fs_events = [e for e in self.collector.events_buffer if e.get("event_type") == "FILE_DELETED"]
        self.assertEqual(len(fs_events), 1)
        self.assertEqual(fs_events[0].get("semantic_action"), "DELETE")

    def test_synthesis_rejects_unevidenced_delete_file(self):
        """Rule 1 & 6: synthesize_workflow_from_events strictly rejects DELETE_FILE if no user input demonstrated it."""
        mock_events = [
            {
                "event_id": "rec_001_ev_1",
                "recording_id": "rec_001",
                "timestamp": time.time(),
                "event_type": "FILE_CREATED",
                "semantic_action": "CREATE",
                "source": "FILESYSTEM",
                "details": {"file_name": "hello I am fine here.txt", "path": "C:\\Users\\hp\\Downloads\\hello I am fine here.txt"}
            },
            {
                "event_id": "rec_001_ev_2",
                "recording_id": "rec_001",
                "timestamp": time.time() + 0.05,
                "event_type": "FILE_DELETED",
                "semantic_action": "DELETE",
                "source": "FILESYSTEM",
                "details": {"file_name": "hello I am fine here.txt", "path": "C:\\Users\\hp\\Downloads\\hello I am fine here.txt"}
            },
            {
                "event_id": "rec_001_ev_3",
                "recording_id": "rec_001",
                "timestamp": time.time() + 0.1,
                "event_type": "FILE_CREATED",
                "semantic_action": "CREATE",
                "source": "FILESYSTEM",
                "details": {"file_name": "hello I am fine here.txt", "path": "C:\\Users\\hp\\Downloads\\hello I am fine here.txt"}
            }
        ]

        plan = synthesize_workflow_from_events(mock_events, recording_id="rec_001")
        actions = plan.get("actions", [])
        action_types = [a.get("type") for a in actions]

        self.assertNotIn("ACTION_DELETE_FILE", action_types, "ACTION_DELETE_FILE must NOT be generated without user delete demonstration")

    def test_all_synthesized_actions_have_evidence_event_ids(self):
        """Rule 5: Every generated action must have evidence_event_ids linking to observed events."""
        mock_events = [
            {
                "event_id": "rec_002_ev_1",
                "recording_id": "rec_002",
                "timestamp": time.time(),
                "event_type": "APP_LAUNCH",
                "semantic_action": "LAUNCH_APP",
                "source": "USER_INPUT",
                "details": {"app_name": "Notepad"}
            },
            {
                "event_id": "rec_002_ev_2",
                "recording_id": "rec_002",
                "timestamp": time.time() + 1.0,
                "event_type": "FILE_CREATED",
                "semantic_action": "CREATE",
                "source": "FILESYSTEM",
                "details": {"file_name": "notes.txt", "path": "C:\\Users\\hp\\Downloads\\notes.txt"}
            }
        ]

        plan = synthesize_workflow_from_events(mock_events, recording_id="rec_002")
        for a in plan.get("actions", []):
            evidence = a.get("evidence_event_ids", [])
            self.assertTrue(isinstance(evidence, list), "evidence_event_ids must be a list")
            self.assertGreater(len(evidence), 0, f"Action {a.get('type')} has no evidence_event_ids")

    def test_executor_refuses_unevidenced_delete_file(self):
        """Rule 9: Executor must refuse to execute DELETE_FILE if evidence_event_ids is missing or empty."""
        unapproved_action = {
            "type": "DELETE_FILE",
            "action_type": "DELETE_FILE",
            "target": "C:\\Users\\hp\\Downloads\\unauthorized.txt",
            "evidence_event_ids": []
        }

        res = execute_real_action(unapproved_action)
        self.assertFalse(res.success)
        self.assertIn("High-risk action has no valid demonstration evidence.", res.message)

    def test_recording_session_isolation(self):
        """Rule 2 & 7: Start recording creates a new recording_id and clears events from previous sessions."""
        res1 = self.client.post("/api/teach/start")
        self.assertEqual(res1.status_code, 200)
        rec_id_1 = res1.json()["recording_id"]
        self.assertTrue(rec_id_1.startswith("rec_"))

        # Add event to recording 1
        import activity as act
        act.collector.record_event("KEY_PRESS", "Notepad", "Notepad", {"key": "a"}, semantic_action="TYPE", source="USER_INPUT")
        stop1 = self.client.post("/api/teach/stop")
        self.assertEqual(stop1.status_code, 200)

        # Start recording 2
        res2 = self.client.post("/api/teach/start")
        self.assertEqual(res2.status_code, 200)
        rec_id_2 = res2.json()["recording_id"]
        self.assertNotEqual(rec_id_1, rec_id_2)

        # Events in recording 2 must not contain events from recording 1
        for ev in act.collector.events_buffer:
            self.assertEqual(ev.get("recording_id"), rec_id_2)

        self.client.post("/api/teach/stop")

    def test_allow_and_run_step_logging_contract(self):
        """Rule 8: When ALLOW & RUN runs, log Workflow ID, Recording ID, Action count, and each Step N."""
        test_plan = {
            "name": "Strict Log Test Workflow",
            "goal": "Test workflow execution logging contract",
            "recording_id": "rec_test_log_contract",
            "actions": [
                {
                    "type": "CREATE_FILE",
                    "action_type": "CREATE_FILE",
                    "label": "Create File",
                    "target": str(Path.home() / "Desktop" / "test_strict_log.txt"),
                    "evidence_event_ids": ["rec_ev_1"]
                }
            ]
        }

        save_res = self.client.post("/api/workflows", json={"plan": test_plan, "mode": "REAL"})
        self.assertEqual(save_res.status_code, 200)
        wf_id = save_res.json()["workflow_id"]

        f = io.StringIO()
        with redirect_stdout(f):
            exec_res = self.client.post("/api/workflows/execute", json={
                "workflow_id": wf_id,
                "recording_id": "rec_test_log_contract",
                "ui_mode": "REAL",
                "requested_mode": "REAL",
                "mode": "REAL",
                "source": "teach"
            })
        out = f.getvalue()

        # Check required log lines from specification
        self.assertIn(f"[RUN] Requested Workflow ID = {wf_id}", out)
        self.assertIn(f"[RUN] Loaded workflow ID = {wf_id}", out)
        self.assertIn("[RUN] Recording ID = rec_test_log_contract", out)
        self.assertIn("[RUN] Action count = 1", out)
        self.assertIn("[RUN] Step 1 = CREATE_FILE", out)

        # Clean up created file if on desktop
        test_file = Path.home() / "Desktop" / "test_strict_log.txt"
        if test_file.exists():
            test_file.unlink()

    def test_create_file_never_injects_default_workflowos_string(self):
        """Root Cause Fix: Creating a file without explicit content creates an empty file, NEVER 'Created by WorkFlowOS'."""
        target_path = Path.home() / "Desktop" / "test_no_default_text.txt"
        if target_path.exists():
            target_path.unlink()

        action = {
            "type": "CREATE_FILE",
            "action_type": "CREATE_FILE",
            "params": {"path": str(target_path)}
        }
        res = execute_real_action(action)
        self.assertTrue(res.success)
        self.assertTrue(target_path.exists())

        content = target_path.read_text(encoding="utf-8")
        self.assertEqual(content, "", "File created without explicit content must be empty")
        self.assertNotIn("Created by WorkFlowOS", content)

        if target_path.exists():
            target_path.unlink()

    def test_type_action_requires_exact_observed_text_and_evidence(self):
        """Rule: TYPE action must contain exact observed text, recording_id, and evidence_event_ids."""
        observed_events = [
            {
                "event_id": "rec_type_1_ev_1",
                "recording_id": "rec_type_1",
                "timestamp": time.time(),
                "event_type": "TEXT_INPUT",
                "semantic_action": "TYPE",
                "source": "USER_INPUT",
                "app_name": "Notepad",
                "window_title": "Untitled - Notepad",
                "details": {"text": "hello I am typing my actual notes here", "target": "Untitled - Notepad"}
            }
        ]

        plan = synthesize_workflow_from_events(observed_events, recording_id="rec_type_1")
        actions = plan.get("actions", [])
        type_actions = [a for a in actions if a.get("type") == "TYPE"]

        self.assertEqual(len(type_actions), 1)
        type_act = type_actions[0]
        self.assertEqual(type_act["params"]["text"], "hello I am typing my actual notes here")
        self.assertEqual(type_act.get("recording_id"), "rec_type_1")
        self.assertEqual(type_act.get("evidence_event_ids"), ["rec_type_1_ev_1"])
        self.assertNotIn("Created by WorkFlowOS", type_act["params"]["text"])

    def test_executor_refuses_empty_or_unevidenced_type_action(self):
        """Rule: TYPE action without text or without demonstration evidence is rejected."""
        empty_type_action = {
            "type": "TYPE",
            "action_type": "TYPE",
            "params": {"text": ""},
            "evidence_event_ids": ["ev_1"]
        }
        res_empty = execute_real_action(empty_type_action)
        self.assertFalse(res_empty.success)
        self.assertIn("TYPE action has no text to type", res_empty.message)

        # In teach workflow execution, unevidenced TYPE is rejected by prepare_and_validate_execution
        unevidenced_plan = {
            "name": "Unevidenced Type Workflow",
            "goal": "Test unevidenced type rejection",
            "recording_id": "rec_no_ev",
            "actions": [
                {
                    "type": "TYPE",
                    "action_type": "TYPE",
                    "label": "Type without evidence",
                    "params": {"text": "Injected text"},
                    "evidence_event_ids": []
                }
            ]
        }
        save_res = self.client.post("/api/workflows", json={"plan": unevidenced_plan, "mode": "REAL"})
        wf_id = save_res.json()["workflow_id"]

        exec_res = self.client.post("/api/workflows/execute", json={
            "workflow_id": wf_id,
            "recording_id": "rec_no_ev",
            "ui_mode": "REAL",
            "requested_mode": "REAL",
            "mode": "REAL",
            "source": "teach"
        })
        self.assertEqual(exec_res.json().get("status"), "FAILED")
        self.assertIn("has no valid demonstration evidence", exec_res.json().get("error", ""))


if __name__ == "__main__":
    unittest.main()
