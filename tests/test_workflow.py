"""
Automated Test Suite for WorkFlowOS.
Uses standard Python unittest (zero external dependencies required).
Validates Database, Automation Engine, AI Intent Parsing, Teach-by-Doing Synthesis,
Workflow Evolution Engine, Version Rollback, and User Corrections.
"""

import os
import shutil
import unittest
from pathlib import Path

# Add project root to path
import sys
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import database as db
import automation as auto
import ai
import workflow as wf_engine
import activity as act

TEST_SANDBOX = BASE_DIR / "tests" / "test_sandbox"


class TestWorkFlowOS(unittest.TestCase):

    def setUp(self):
        """Setup clean sandbox and isolated test database before each test."""
        if TEST_SANDBOX.exists():
            try:
                shutil.rmtree(TEST_SANDBOX)
            except Exception:
                pass
        TEST_SANDBOX.mkdir(parents=True, exist_ok=True)
        # Point database to isolated test DB
        db.DB_PATH = TEST_SANDBOX / "test_workflowos.db"
        db.init_db()

    def tearDown(self):
        """Cleanup after each test."""
        if TEST_SANDBOX.exists():
            try:
                shutil.rmtree(TEST_SANDBOX)
            except Exception:
                pass

    def test_database_initialization(self):
        """Verify SQLite database and required tables are initialized."""
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row["name"] for row in cursor.fetchall()]
        conn.close()

        self.assertIn("workflows", tables)
        self.assertIn("workflow_versions", tables)
        self.assertIn("workflow_actions", tables)
        self.assertIn("activity_events", tables)
        self.assertIn("executions", tables)
        self.assertIn("feedback", tables)
        self.assertIn("settings", tables)

    def test_automation_safe_file_operations(self):
        """Verify safe local file operations (create folder, rename, move, search)."""
        # 1. Create folder
        res_create = auto.execute_action(
            {"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "test_folder"}},
            dry_run=False,
            base_sandbox=TEST_SANDBOX
        )
        self.assertTrue(res_create.success)
        self.assertTrue((TEST_SANDBOX / "test_folder").is_dir())

        # Create dummy file inside test_folder
        test_file = TEST_SANDBOX / "test_folder" / "sample.txt"
        test_file.write_text("Hello WorkFlowOS test content", encoding="utf-8")

        # 2. Read file
        res_read = auto.execute_action(
            {"type": auto.ACTION_READ_FILE, "params": {"file": "test_folder/sample.txt"}},
            dry_run=False,
            base_sandbox=TEST_SANDBOX
        )
        self.assertTrue(res_read.success)
        self.assertIn("Hello WorkFlowOS", str(res_read.data))

        # 3. Rename file
        res_rename = auto.execute_action(
            {"type": auto.ACTION_RENAME_FILE, "params": {"source": "test_folder/sample.txt", "new_name": "renamed.txt"}},
            dry_run=False,
            base_sandbox=TEST_SANDBOX
        )
        self.assertTrue(res_rename.success)
        self.assertTrue((TEST_SANDBOX / "test_folder" / "renamed.txt").exists())

        # 4. Move file
        res_move = auto.execute_action(
            {"type": auto.ACTION_MOVE_FILE, "params": {"source": "test_folder/renamed.txt", "destination": "moved_dir"}},
            dry_run=False,
            base_sandbox=TEST_SANDBOX
        )
        self.assertTrue(res_move.success)
        self.assertTrue((TEST_SANDBOX / "moved_dir" / "renamed.txt").exists())

        # 5. Search files
        res_search = auto.execute_action(
            {"type": auto.ACTION_SEARCH_FILES, "params": {"folder": "moved_dir", "query": "*.txt"}},
            dry_run=False,
            base_sandbox=TEST_SANDBOX
        )
        self.assertTrue(res_search.success)
        self.assertEqual(len(res_search.data), 1)

    def test_dry_run_does_not_modify_disk(self):
        """Verify dry run simulation previews steps without altering disk."""
        plan = {
            "name": "Dry Run Test",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "should_not_exist"}}
            ]
        }
        preview = wf_engine.dry_run_workflow(plan)
        self.assertTrue(preview["dry_run"])
        self.assertEqual(len(preview["steps"]), 1)
        self.assertTrue(preview["steps"][0]["simulated"])
        self.assertFalse((TEST_SANDBOX / "should_not_exist").exists())

    def test_ai_chat_parser_demo2(self):
        """Verify AI parser handles Demo 2 (Placement folder creation and move)."""
        prompt = "Create a folder called Placement and move all PDF files containing placement-related documents into it."
        plan = ai.parse_chat_goal(prompt)

        self.assertEqual(plan["name"], "Organize Placement Documents")
        self.assertGreaterEqual(plan["confidence"], 0.75)
        self.assertEqual(plan["risk"], "LOW")
        action_types = [a["type"] for a in plan["actions"]]
        self.assertIn(auto.ACTION_CREATE_FOLDER, action_types)
        self.assertIn(auto.ACTION_MOVE_FILE, action_types)

    def test_teach_event_synthesis_demo1(self):
        """Verify Teach-by-Doing event synthesis converts raw demonstration into workflow."""
        collector = act.ActivityCollector(sandbox_dir=TEST_SANDBOX)
        events = collector.simulate_demonstration("demo1_file_org")
        self.assertGreaterEqual(len(events), 4)

        plan = ai.synthesize_workflow_from_events(events)
        self.assertTrue("Placement" in plan["name"] or "Organize" in plan["name"])
        self.assertGreaterEqual(len(plan["actions"]), 3)
        self.assertGreater(plan["confidence"], 0.70)

    def test_workflow_evolution_detection_demo3(self):
        """
        CORE FEATURE TEST — Workflow Evolution Engine
        1. Teach initial workflow: Downloads -> Rename -> Placement (v1)
        2. Demonstrate mutated behavior: Downloads -> Classify -> Rename -> College/Placement
        3. Verify system detects evolution, displays diff, and saves v2 while keeping v1.
        """
        # 1. Save original workflow v1
        v1_plan = {
            "name": "Organize Placement Documents",
            "goal": "Move placement-related documents to the Placement folder",
            "trigger": "New document appears in Downloads",
            "actions": [
                {"type": auto.ACTION_OPEN_FOLDER, "label": "Open Downloads", "params": {"path": "Downloads"}, "risk": "LOW"},
                {"type": auto.ACTION_RENAME_FILE, "label": "Rename offer letter", "params": {"source": "Downloads/offer.pdf", "new_name": "Placement_Offer.pdf"}, "risk": "LOW"},
                {"type": auto.ACTION_MOVE_FILE, "label": "Move to Placement", "params": {"source": "Downloads/Placement_Offer.pdf", "destination": "Placement"}, "risk": "LOW"}
            ],
            "confidence": 0.90,
            "risk": "LOW",
            "version": 1
        }
        wf_id = wf_engine.create_workflow_from_plan(v1_plan)

        # 2. Simulate new evolved demonstration
        collector = act.ActivityCollector(sandbox_dir=TEST_SANDBOX)
        new_events = collector.simulate_demonstration("demo3_evolution")
        evolved_plan = ai.synthesize_workflow_from_events(new_events)

        # 3. Detect evolution
        existing_wfs = db.get_all_workflows()
        evolution = ai.detect_workflow_evolution(existing_wfs, evolved_plan["actions"], evolved_plan["goal"])

        self.assertIsNotNone(evolution)
        self.assertEqual(evolution["workflow_id"], wf_id)
        self.assertEqual(evolution["proposed_version"], 2)
        self.assertIn("Placement", evolution["old_workflow_display"])
        self.assertIn("College/Placement", evolution["new_workflow_display"])

        # 4. Accept and apply evolution (bump to version 2)
        evolve_res = wf_engine.evolve_workflow(
            workflow_id=wf_id,
            new_actions=evolved_plan["actions"],
            change_reason=evolution["change_summary"]
        )
        self.assertTrue(evolve_res["success"])
        self.assertEqual(evolve_res["new_version"], 2)

        # Verify both v1 and v2 exist in database
        versions = db.get_workflow_versions(wf_id)
        version_numbers = [v["version"] for v in versions]
        self.assertIn(1, version_numbers)
        self.assertIn(2, version_numbers)

        # Verify active version in workflows table is 2
        active_wf = db.get_workflow(wf_id)
        self.assertEqual(active_wf["version"], 2)

        # 5. Rollback test: Restore Version 1
        restore_res = wf_engine.restore_version(wf_id, 1)
        self.assertTrue(restore_res["success"])
        self.assertEqual(restore_res["active_version"], 1)
        restored_wf = db.get_workflow(wf_id)
        self.assertEqual(restored_wf["version"], 1)

    def test_user_correction_memory_demo4(self):
        """
        Demo 4 test — User Correction Memory
        User flags wrong destination folder, system stores feedback and remembers correction.
        """
        plan = {
            "name": "Sort Resumes",
            "goal": "Sort candidate resumes",
            "actions": [
                {"type": auto.ACTION_MOVE_FILE, "label": "Move resume to Other", "params": {"source": "Downloads/resume.pdf", "destination": "Other"}, "risk": "LOW"}
            ],
            "version": 1
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)

        # User correction: resume.pdf should go to Placement instead of Other
        correction = wf_engine.record_user_correction(
            workflow_id=wf_id,
            execution_id=None,
            feedback_text="resume.pdf should go to Placement, not Other",
            original_action={"type": auto.ACTION_MOVE_FILE, "params": {"destination": "Other"}},
            corrected_action={"type": auto.ACTION_MOVE_FILE, "label": "Move to Placement", "params": {"destination": "Placement"}, "risk": "LOW"},
            remember=True
        )

        self.assertTrue(correction["success"])
        self.assertTrue(correction["remembered"])

        # Check updated workflow has evolved with the corrected destination
        wf = db.get_workflow(wf_id)
        destinations = [a.get("params", {}).get("destination") for a in wf.get("actions", [])]
        self.assertIn("Placement", destinations)

    def test_execution_risk_enforcement(self):
        """Verify Risk System: high risk requires explicit confirmation."""
        plan = {
            "name": "High Risk File Deletion",
            "actions": [
                {"type": auto.ACTION_DELETE_FILE, "params": {"file": "Downloads/temp.txt"}, "risk": "HIGH"}
            ],
            "version": 1
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)

        # Unconfirmed high risk should block execution
        res_blocked = wf_engine.execute_workflow(wf_id, confirmed_medium=True, confirmed_high=False)
        self.assertFalse(res_blocked["success"])
        self.assertTrue(res_blocked.get("blocked"))
        self.assertEqual(res_blocked.get("risk_level"), "HIGH")

    def test_real_file_organization_lifecycle(self):
        """Verify full execution lifecycle with real files in the sandbox."""
        # 1. Setup sample files in sandbox
        downloads = TEST_SANDBOX / "Downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        sample_file = downloads / "campus_offer.pdf"
        sample_file.write_text("Official offer for placement 2026", encoding="utf-8")

        # 2. Define workflow
        plan = {
            "name": "End to End Placement File Move",
            "goal": "Organize placement offer file into Placement folder",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "Placement"}, "risk": "LOW"},
                {"type": auto.ACTION_RENAME_FILE, "params": {"source": "Downloads/campus_offer.pdf", "new_name": "Placement_2026_Offer.pdf"}, "risk": "LOW"},
                {"type": auto.ACTION_MOVE_FILE, "params": {"source": "Downloads/Placement_2026_Offer.pdf", "destination": "Placement"}, "risk": "LOW"}
            ],
            "version": 1
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)

        # 3. Dry run test first
        dry = wf_engine.dry_run_workflow(plan)
        self.assertTrue(dry["dry_run"])
        self.assertEqual(len(dry["steps"]), 3)

        # 4. Real Execution
        # Temporarily redirect SANDBOX_DIR in workflow engine for test isolation
        orig_sandbox = wf_engine.SANDBOX_DIR
        wf_engine.SANDBOX_DIR = TEST_SANDBOX
        try:
            exec_res = wf_engine.execute_workflow(wf_id, confirmed_medium=True, confirmed_high=True)
            self.assertTrue(exec_res["success"])
            self.assertEqual(exec_res["status"], "COMPLETED")

            # Verify file physically exists at destination
            dest_file = TEST_SANDBOX / "Placement" / "Placement_2026_Offer.pdf"
            self.assertTrue(dest_file.exists())
            self.assertEqual(dest_file.read_text(encoding="utf-8"), "Official offer for placement 2026")
        finally:
            wf_engine.SANDBOX_DIR = orig_sandbox

    def test_real_desktop_mode_harmless_actions(self):
        """
        Requirement 20: Test Real Desktop Mode with harmless tasks:
        Task 1: Create a test folder on the desktop.
        Task 2: Create a test file.
        Task 3: Move test file to test folder.
        Verify without permission nothing happens, after ALLOW & RUN executes complete workflow.
        """
        test_folder_name = f"WorkflowOS_Harmless_TestFolder_{os.getpid()}"
        test_file_name = f"WorkflowOS_Harmless_TestFile_{os.getpid()}.txt"
        desktop_dir = auto.get_user_desktop()

        # Ensure clean state on desktop
        target_folder = desktop_dir / test_folder_name
        target_file = desktop_dir / test_file_name
        if target_folder.exists():
            shutil.rmtree(target_folder, ignore_errors=True)
        if target_file.exists():
            target_file.unlink(missing_ok=True)

        plan = {
            "name": "Desktop Harmless Verification",
            "goal": "Create test folder, create test file, and move file to folder on desktop",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "label": "Create test folder", "params": {"path": f"Desktop/{test_folder_name}"}, "risk": "LOW"},
                {"type": auto.ACTION_CREATE_FILE, "label": "Create test file", "params": {"path": f"Desktop/{test_file_name}", "content": "Harmless test verified"}, "risk": "LOW"},
                {"type": auto.ACTION_MOVE_FILE, "label": "Move file into folder", "params": {"source": f"Desktop/{test_file_name}", "destination": f"Desktop/{test_folder_name}"}, "risk": "LOW"}
            ],
            "version": 1
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)

        try:
            # 1. Without permission: Only preview / dry run, NOTHING happens on disk!
            preview = wf_engine.dry_run_workflow(plan, mode="real")
            self.assertTrue(preview["dry_run"])
            self.assertEqual(len(preview["steps"]), 3)
            self.assertFalse(target_folder.exists(), "Without permission, folder MUST NOT be created")
            self.assertFalse(target_file.exists(), "Without permission, file MUST NOT be created")

            # 2. After user gives ONE-TIME approval: entire workflow executes
            exec_res = wf_engine.execute_workflow(wf_id, confirmed_medium=True, confirmed_high=True, mode="real")
            self.assertTrue(exec_res["success"], f"Execution should succeed: {exec_res.get('error')}")
            self.assertEqual(exec_res["status"], "COMPLETED")
            self.assertEqual(len(exec_res["logs"]), 3)

            # Verify folder and moved file exist on Desktop
            final_file = target_folder / test_file_name
            self.assertTrue(target_folder.exists(), "Target folder should exist after ALLOW & RUN")
            self.assertTrue(final_file.exists(), "Target file should be inside folder after ALLOW & RUN")
            self.assertEqual(final_file.read_text(encoding="utf-8"), "Harmless test verified")

        finally:
            # Cleanup desktop test artifacts
            if target_folder.exists():
                shutil.rmtree(target_folder, ignore_errors=True)
            if target_file.exists():
                target_file.unlink(missing_ok=True)

    def test_one_time_approval_all_steps_execute(self):
        """
        Verify Requirement 3 & 19:
        One click on [ALLOW & RUN] executes all 4 steps without stopping or prompting.
        """
        plan = {
            "name": "One Time Approval Multi-Step Workflow",
            "goal": "Execute multiple operations with a single approval",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "label": "Step 1: Create Dir", "params": {"path": "multi_step"}, "risk": "LOW"},
                {"type": auto.ACTION_CREATE_FILE, "label": "Step 2: Create File A", "params": {"path": "multi_step/a.txt", "content": "A"}, "risk": "LOW"},
                {"type": auto.ACTION_CREATE_FILE, "label": "Step 3: Create File B", "params": {"path": "multi_step/b.txt", "content": "B"}, "risk": "LOW"},
                {"type": auto.ACTION_RENAME_FILE, "label": "Step 4: Rename File A", "params": {"source": "multi_step/a.txt", "new_name": "renamed_a.txt"}, "risk": "LOW"}
            ],
            "version": 1
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)

        orig_sandbox = wf_engine.SANDBOX_DIR
        wf_engine.SANDBOX_DIR = TEST_SANDBOX
        try:
            exec_res = wf_engine.execute_workflow(wf_id, confirmed_medium=True, confirmed_high=True, mode="sandbox")
            self.assertTrue(exec_res["success"])
            self.assertEqual(len(exec_res["logs"]), 4)
            # All 4 steps executed in one run
            for log in exec_res["logs"]:
                self.assertTrue(log["success"])

            self.assertTrue((TEST_SANDBOX / "multi_step" / "renamed_a.txt").exists())
            self.assertTrue((TEST_SANDBOX / "multi_step" / "b.txt").exists())
        finally:
            wf_engine.SANDBOX_DIR = orig_sandbox

    def test_mandatory_test1_open_notepad_real(self):
        """Mandatory Test 1: Open Notepad on my computer in REAL mode."""
        goal = "Open Notepad on my computer."
        plan = ai.parse_chat_goal(goal)
        self.assertEqual(plan["actions"][0]["type"], auto.ACTION_OPEN_APP)
        self.assertEqual(plan["actions"][0]["params"]["app"], "notepad")

        exec_res = wf_engine.execute_real_workflow(plan)
        self.assertTrue(exec_res["success"], f"Execution should succeed: {exec_res.get('error')}")
        self.assertEqual(exec_res["status"], "COMPLETED")
        self.assertEqual(len(exec_res["logs"]), 1)
        self.assertIn("OPEN_APPLICATION", exec_res["logs"][0]["message"])
        self.assertIn("SUCCESS", exec_res["logs"][0]["message"])

    def test_mandatory_test2_open_notepad_and_type_real(self):
        """Mandatory Test 2: Open Notepad and type Hello from WorkFlowOS with ONE approval."""
        goal = "Open Notepad and type Hello from WorkFlowOS."
        plan = ai.parse_chat_goal(goal)
        self.assertEqual(len(plan["actions"]), 2)
        self.assertEqual(plan["actions"][0]["type"], auto.ACTION_OPEN_APP)
        self.assertEqual(plan["actions"][1]["type"], auto.ACTION_TYPE)

        # Executes all approved actions sequentially without asking permission between steps
        exec_res = wf_engine.execute_real_workflow(plan)
        self.assertTrue(exec_res["success"], f"Execution should succeed: {exec_res.get('error')}")
        self.assertEqual(exec_res["status"], "COMPLETED")
        self.assertEqual(len(exec_res["logs"]), 2)
        self.assertTrue(exec_res["logs"][0]["success"])
        self.assertTrue(exec_res["logs"][1]["success"])

    def test_mandatory_test3_desktop_file_move_verification(self):
        """Mandatory Test 3: Real harmless file operation on Windows Desktop with verification."""
        desktop_dir = auto.get_user_desktop()
        test_file = desktop_dir / "WorkflowOS_Test.txt"
        test_file.write_text("WorkFlowOS Test 3 file content", encoding="utf-8")
        self.assertTrue(test_file.exists())

        folder_name = "WorkflowOS_Test"
        target_folder = desktop_dir / folder_name

        try:
            goal = "Create a folder called WorkflowOS_Test on my Desktop and move WorkflowOS_Test.txt into it."
            plan = ai.parse_chat_goal(goal)
            self.assertEqual(len(plan["actions"]), 2)
            self.assertEqual(plan["actions"][0]["type"], auto.ACTION_CREATE_FOLDER)
            self.assertEqual(plan["actions"][1]["type"], auto.ACTION_MOVE_FILE)

            exec_res = wf_engine.execute_real_workflow(plan)
            self.assertTrue(exec_res["success"], f"Execution failed: {exec_res.get('error')}")
            self.assertEqual(exec_res["status"], "COMPLETED")

            # Verify destination file physically exists on Windows Desktop
            destination_file = target_folder / "WorkflowOS_Test.txt"
            if not destination_file.exists():
                destination_file = target_folder / "workflowos_test.txt"
            self.assertTrue(destination_file.exists(), f"Destination file must exist at {destination_file}")
            self.assertEqual(destination_file.read_text(encoding="utf-8"), "WorkFlowOS Test 3 file content")
        finally:
            if target_folder.exists():
                shutil.rmtree(target_folder, ignore_errors=True)
            if test_file.exists():
                test_file.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
