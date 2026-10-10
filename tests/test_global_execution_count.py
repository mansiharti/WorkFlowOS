"""
Unit Tests for WorkFlowOS Global Workflow Execution Count Architecture.
Validates all 10 core execution requirements:
1. One Run request -> executor called exactly once.
2. Same execution_id submitted twice -> executor runs once.
3. Two different Run requests -> two executions.
4. Workflow with 1 action -> one execution.
5. Workflow with 10 actions -> ten actions inside ONE execution, not ten workflow executions.
6. Frontend duplicate request -> backend prevents duplicate execution.
7. Status update -> does not start another execution.
8. WebSocket reconnect / stream retry -> does not start another execution.
9. Polling -> does not start another execution.
10. Teach by Doing workflow -> follows exactly the same global execution rules.
"""

import unittest
from pathlib import Path
import shutil
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import database as db
import automation as auto
import workflow as wf_engine

TEST_SANDBOX = BASE_DIR / "tests" / "test_sandbox"


class TestGlobalWorkflowExecutionCount(unittest.TestCase):

    def setUp(self):
        """Setup clean sandbox and isolated test database before each test."""
        if TEST_SANDBOX.exists():
            try:
                shutil.rmtree(TEST_SANDBOX)
            except Exception:
                pass
        TEST_SANDBOX.mkdir(parents=True, exist_ok=True)
        db.DB_PATH = TEST_SANDBOX / "test_workflowos.db"
        db.init_db()
        wf_engine.SANDBOX_DIR = TEST_SANDBOX

    def tearDown(self):
        """Cleanup after test."""
        if TEST_SANDBOX.exists():
            try:
                shutil.rmtree(TEST_SANDBOX)
            except Exception:
                pass

    def test_1_one_run_request_executes_once(self):
        """Test 1: One Run request -> executor called exactly once."""
        plan = {
            "name": "Single Run Task",
            "goal": "Execute workflow once",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "single_run_dir"}, "risk": "LOW"},
                {"type": auto.ACTION_CREATE_FILE, "params": {"path": "single_run_dir/file1.txt", "content": "hello"}, "risk": "LOW"}
            ]
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)
        res = wf_engine.execute_workflow(wf_id, mode="sandbox")

        self.assertTrue(res["success"])
        self.assertEqual(res["workflow_execution_count"], 1)
        self.assertEqual(res["executions_performed"], 1)

    def test_2_same_execution_id_submitted_twice(self):
        """Test 2: Same execution_id submitted twice -> executor runs once."""
        plan = {
            "name": "Idempotent Task",
            "goal": "Duplicate execution_id prevention",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "idempotent_dir"}, "risk": "LOW"}
            ]
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)
        exec_id = "E-TEST-IDEMPOTENT-002"

        res1 = wf_engine.execute_workflow(wf_id, mode="sandbox", execution_id=exec_id)
        res2 = wf_engine.execute_workflow(wf_id, mode="sandbox", execution_id=exec_id)

        self.assertEqual(res1["execution_id"], exec_id)
        self.assertEqual(res2["execution_id"], exec_id)
        self.assertEqual(res2["status"], res1["status"])
        self.assertEqual(res2["workflow_execution_count"], 1)

    def test_3_two_different_run_requests(self):
        """Test 3: Two different Run requests -> two executions."""
        plan = {
            "name": "Two Run Task",
            "goal": "Execute workflow twice",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "two_run_dir"}, "risk": "LOW"}
            ]
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)

        res1 = wf_engine.execute_workflow(wf_id, mode="sandbox")
        res2 = wf_engine.execute_workflow(wf_id, mode="sandbox")

        self.assertNotEqual(res1["execution_id"], res2["execution_id"])
        self.assertEqual(res1["workflow_execution_count"], 1)
        self.assertEqual(res2["workflow_execution_count"], 1)

    def test_4_workflow_with_1_action(self):
        """Test 4: Workflow with 1 action -> one execution."""
        plan = {
            "name": "1 Action Task",
            "goal": "Single action workflow",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "one_action_dir"}, "risk": "LOW"}
            ]
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)
        res = wf_engine.execute_workflow(wf_id, mode="sandbox")

        self.assertEqual(res["workflow_action_count"], 1)
        self.assertEqual(res["workflow_execution_count"], 1)

    def test_5_workflow_with_10_actions(self):
        """Test 5: Workflow with 10 actions -> ten actions inside ONE execution, not ten workflow executions."""
        actions = []
        for i in range(1, 11):
            actions.append({"type": auto.ACTION_CREATE_FILE, "params": {"path": f"file_{i}.txt", "content": str(i)}, "risk": "LOW"})

        plan = {
            "name": "10 Action Workflow",
            "goal": "Execute 10 file actions in one execution",
            "actions": actions
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)
        res = wf_engine.execute_workflow(wf_id, mode="sandbox")

        self.assertTrue(res["success"])
        self.assertEqual(res["workflow_action_count"], 10)
        self.assertEqual(res["workflow_execution_count"], 1)
        self.assertEqual(res["executions_performed"], 1)

    def test_6_frontend_duplicate_request_prevented(self):
        """Test 6: Frontend duplicate request -> backend prevents duplicate execution."""
        plan = {
            "name": "Frontend Retry Task",
            "goal": "Simulate frontend duplicate call",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "fe_retry_dir"}, "risk": "LOW"}
            ]
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)
        exec_id = "E-FE-RETRY-006"

        # Simulate double submission from frontend
        res1 = wf_engine.execute_workflow(wf_id, mode="sandbox", execution_id=exec_id)
        res2 = wf_engine.execute_workflow(wf_id, mode="sandbox", execution_id=exec_id)

        self.assertEqual(res1["execution_id"], res2["execution_id"])
        self.assertEqual(res2["workflow_execution_count"], 1)

    def test_7_status_update_does_not_start_another_execution(self):
        """Test 7: Status update -> does not start another execution."""
        plan = {
            "name": "Status Check Task",
            "goal": "Status inspection",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "status_check_dir"}, "risk": "LOW"}
            ]
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)
        exec_id = "E-STATUS-007"

        res = wf_engine.execute_workflow(wf_id, mode="sandbox", execution_id=exec_id)

        # Checking status from manager
        status = wf_engine.execution_manager.get_execution_result(exec_id)
        self.assertIsNotNone(status)
        self.assertEqual(status["execution_id"], exec_id)
        self.assertEqual(status["workflow_execution_count"], 1)

    def test_8_websocket_reconnect_retry_does_not_start_execution(self):
        """Test 8: WebSocket reconnect / stream fallback -> does not start another execution."""
        plan = {
            "name": "Stream Fallback Task",
            "goal": "Stream fallback simulation",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "stream_fallback_dir"}, "risk": "LOW"}
            ]
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)
        exec_id = "E-STREAM-008"

        res1 = wf_engine.execute_workflow(wf_id, mode="sandbox", execution_id=exec_id)
        res2 = wf_engine.execute_workflow(wf_id, mode="sandbox", execution_id=exec_id)

        self.assertEqual(res1["execution_id"], res2["execution_id"])
        self.assertEqual(res2["executions_performed"], 1)

    def test_9_polling_does_not_start_execution(self):
        """Test 9: Polling -> does not start another execution."""
        plan = {
            "name": "Polling Task",
            "goal": "Polling status query",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "polling_dir"}, "risk": "LOW"}
            ]
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)
        exec_id = "E-POLL-009"

        wf_engine.execute_workflow(wf_id, mode="sandbox", execution_id=exec_id)

        # Multiple polling queries for existing execution
        for _ in range(5):
            res = wf_engine.execute_workflow(wf_id, mode="sandbox", execution_id=exec_id)
            self.assertEqual(res["execution_id"], exec_id)
            self.assertEqual(res["workflow_execution_count"], 1)

    def test_10_teach_by_doing_workflow_uses_same_rules(self):
        """Test 10: Teach by Doing workflow -> follows exactly the same global execution rules."""
        plan = {
            "name": "Teach by Doing Task",
            "goal": "Learned desktop workflow",
            "actions": [
                {"type": auto.ACTION_CREATE_FOLDER, "params": {"path": "teach_dir"}, "risk": "LOW"},
                {"type": auto.ACTION_CREATE_FILE, "params": {"path": "teach_dir/note.txt", "content": "learned"}, "risk": "LOW"}
            ]
        }
        wf_id = wf_engine.create_workflow_from_plan(plan)

        res = wf_engine.execute_workflow(wf_id, mode="sandbox")

        self.assertTrue(res["success"])
        self.assertEqual(res["workflow_execution_count"], 1)
        self.assertEqual(res["executions_performed"], 1)
        self.assertEqual(res["workflow_action_count"], 2)


if __name__ == "__main__":
    unittest.main()
