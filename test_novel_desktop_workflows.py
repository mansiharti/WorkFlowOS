"""
Automated Test Suite for Novel Desktop Workflows Learned via Teach-by-Doing.
Verifies end-to-end replay, strict identity preservation, real desktop action execution,
and boundary verification across arbitrary desktop task categories.
"""

import unittest
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import database as db
import automation as auto
import ai
import workflow as wf_engine


class TestNovelDesktopWorkflows(unittest.TestCase):

    def setUp(self):
        """Setup clean sandbox and isolated test database."""
        self.test_dir = BASE_DIR / "tests" / "test_sandbox"
        if self.test_dir.exists():
            try:
                shutil.rmtree(self.test_dir)
            except Exception:
                pass
        self.test_dir.mkdir(parents=True, exist_ok=True)
        db.DB_PATH = self.test_dir / "test_workflowos.db"
        db.init_db()
        wf_engine.SANDBOX_DIR = self.test_dir

    def tearDown(self):
        """Cleanup after test."""
        if self.test_dir.exists():
            try:
                shutil.rmtree(self.test_dir)
            except Exception:
                pass

    def test_novel_workflow_replay_folder_and_file(self):
        """
        Verify: Arbitrary novel workflow (folder creation + file creation)
        learned via Teach-by-Doing can be replayed cleanly.
        """
        target_folder = self.test_dir / "NovelProject"
        target_file = target_folder / "notes.txt"

        events = [
            {
                "event_id": "ev_1",
                "timestamp": "2026-10-01T22:00:00",
                "event_type": "DIRECTORY_CREATED",
                "semantic_action": "CREATE_FOLDER",
                "app_name": "explorer.exe",
                "window_title": "File Explorer",
                "details": {"path": str(target_folder), "name": "NovelProject"}
            },
            {
                "event_id": "ev_2",
                "timestamp": "2026-10-01T22:00:05",
                "event_type": "FILE_CREATED",
                "semantic_action": "CREATE_FILE",
                "app_name": "explorer.exe",
                "window_title": "File Explorer",
                "details": {"path": str(target_file), "name": "notes.txt"}
            }
        ]

        # 1. Synthesize learned workflow
        plan = ai.synthesize_workflow_from_events(events, recording_id="rec_novel_001")
        self.assertEqual(len(plan["actions"]), 2)

        # 2. Save workflow to database
        wf_id = wf_engine.create_workflow_from_plan(plan)
        self.assertGreater(wf_id, 0)

        # 3. Replay workflow via execute_workflow
        res1 = wf_engine.execute_workflow(wf_id, mode="real")

        # 4. Verify real execution success and files
        self.assertTrue(res1["success"])
        self.assertEqual(res1["workflow_execution_count"], 1)
        self.assertEqual(res1["workflow_action_count"], 2)
        self.assertTrue(target_folder.exists())
        self.assertTrue(target_file.exists())

        # 5. Replay a SECOND time with new explicit Run request
        res2 = wf_engine.execute_workflow(wf_id, mode="real")

        self.assertTrue(res2["success"])
        self.assertNotEqual(res1["execution_id"], res2["execution_id"])
        self.assertEqual(res2["workflow_execution_count"], 1)

    def test_novel_workflow_replay_file_move_and_rename(self):
        """
        Verify: Novel workflow containing file move and rename operations
        replays and verifies target filesystem changes.
        """
        src_file = self.test_dir / "draft.txt"
        dest_folder = self.test_dir / "Archive"
        renamed_file = dest_folder / "final_draft.txt"

        src_file.write_text("Draft Content", encoding="utf-8")

        events = [
            {
                "event_id": "ev_10",
                "timestamp": "2026-10-01T22:10:00",
                "event_type": "FILE_MOVED",
                "semantic_action": "MOVE",
                "app_name": "explorer.exe",
                "window_title": "File Explorer",
                "details": {
                    "source": str(src_file),
                    "destination": str(dest_folder),
                    "filename": "draft.txt"
                }
            },
            {
                "event_id": "ev_11",
                "timestamp": "2026-10-01T22:10:05",
                "event_type": "FILE_RENAMED",
                "semantic_action": "RENAME",
                "app_name": "explorer.exe",
                "window_title": "File Explorer",
                "details": {
                    "source": str(dest_folder / "draft.txt"),
                    "new_name": "final_draft.txt",
                    "destination": str(renamed_file)
                }
            }
        ]

        plan = ai.synthesize_workflow_from_events(events, recording_id="rec_novel_002")
        wf_id = wf_engine.create_workflow_from_plan(plan)

        res = wf_engine.execute_workflow(wf_id, mode="real")

        self.assertTrue(res["success"])
        self.assertEqual(res["workflow_action_count"], 2)
        self.assertTrue(renamed_file.exists())


if __name__ == "__main__":
    unittest.main()
