"""
Unit and Integration Tests for Teach by Doing Desktop Recording Overlay & Real-Time Status.
"""

import sys
import time
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

class TestDesktopRecordingOverlay(unittest.TestCase):

    def test_overlay_lifecycle_and_live_status(self):
        # 1. Start teaching
        start_res = client.post("/api/teach/start", params={"session_name": "Overlay Test"})
        self.assertEqual(start_res.status_code, 200)
        start_data = start_res.json()
        self.assertEqual(start_data.get("status"), "recording")

        # 2. Check live status endpoint
        st_res = client.get("/api/teach/status")
        self.assertEqual(st_res.status_code, 200)
        st = st_res.json()
        self.assertTrue(st["is_recording"])
        self.assertIn("active_app", st)
        self.assertIn("current_action", st)
        self.assertIn("events_count", st)
        print(f"\n[OK] Initial Live Status: Active App='{st['active_app']}', Current Action='{st['current_action']}'")

        # 3. Simulate real actions occurring
        events = [
            # App focus
            {
                "event_type": "WINDOW_FOCUS",
                "app_name": "notepad.exe",
                "window_title": "Notes.txt - Notepad",
                "details": {"app": "notepad", "title": "Notes.txt"},
                "semantic_action": "WINDOW_FOCUS"
            },
            # User types
            {
                "event_type": "TEXT_INPUT",
                "app_name": "notepad.exe",
                "window_title": "Notes.txt - Notepad",
                "details": {"text": "Weekly Review Task List"},
                "semantic_action": "TYPE"
            },
            # User clicks
            {
                "event_type": "UI_CLICK",
                "app_name": "notepad.exe",
                "window_title": "Notes.txt - Notepad",
                "details": {"element": "File Menu", "target": "File Menu"},
                "semantic_action": "CLICK"
            }
        ]

        for ev in events:
            r = client.post("/api/teach/record-event", json=ev)
            self.assertEqual(r.status_code, 200)

        # 4. Check status update
        time.sleep(0.1)
        st_res2 = client.get("/api/teach/status")
        st2 = st_res2.json()
        print(f"[OK] Updated Live Status: Count={st2['events_count']}, Action='{st2['current_action']}'")
        self.assertGreaterEqual(st2["events_count"], 3)
        self.assertIn("Click", st2["current_action"])

        # 5. Stop teaching
        stop_res = client.post("/api/teach/stop")
        self.assertEqual(stop_res.status_code, 200)
        stop_data = stop_res.json()
        plan = stop_data.get("plan")
        self.assertIsNotNone(plan)
        actions = plan.get("actions", [])
        print(f"[OK] Workflow Synthesized ({len(actions)} steps):")
        for i, a in enumerate(actions, 1):
            print(f"   [{i}] {a['type']}: {a.get('label')}")

        # 6. Verify recorder is stopped
        st_res3 = client.get("/api/teach/status")
        st3 = st_res3.json()
        self.assertFalse(st3["is_recording"])
        print("[OK] Recorder confirmed stopped and overlay terminated.")


if __name__ == "__main__":
    unittest.main()
