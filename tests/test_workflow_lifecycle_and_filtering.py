import pytest
import database as db
from fastapi.testclient import TestClient
from app import app
import activity as act
import workflow as wf

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_clean_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_lifecycle.db")
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()
    yield test_db

def test_1_teach_by_doing_not_saved_not_in_my_workflows(monkeypatch):
    # Simulate stopping teach session which synthesizes plan but does not save it
    act.collector.start_recording("test_session_1")
    act.collector.record_event("click", "Notepad", "Untitled - Notepad", {"target": "Text Editor"})
    
    response = client.post("/api/teach/stop")
    assert response.status_code == 200
    w_id = response.json().get("workflow_id")
    assert w_id is None

    # Verify via API GET /api/workflows
    res = client.get("/api/workflows")
    assert res.status_code == 200
    workflows = res.json()["workflows"]
    assert len(workflows) == 0, "Unsaved Teach workflow should NOT appear in My Workflows"

def test_2_teach_by_doing_explicitly_saved_appears_in_my_workflows():
    act.collector.start_recording("test_session_2")
    act.collector.record_event("click", "Notepad", "Untitled - Notepad", {"target": "Text Editor"})
    
    response = client.post("/api/teach/stop")
    plan = response.json().get("plan")
    assert plan is not None

    # User explicitly clicks Save Workflow
    save_res = client.post("/api/workflows/save", json={"plan": plan, "title": "Saved Teach Workflow"})
    assert save_res.status_code == 200
    saved_id = save_res.json().get("workflow_id")
    assert saved_id is not None and saved_id > 0

    # Verify via API GET /api/workflows
    res = client.get("/api/workflows")
    assert res.status_code == 200
    workflows = res.json()["workflows"]
    saved_ids = [w["id"] for w in workflows]
    assert saved_id in saved_ids, "Explicitly saved Teach workflow MUST appear in My Workflows"

def test_3_and_4_run_workflow_updates_execution_count_without_duplicates():
    # Save a workflow first
    w_id = db.save_workflow({
        "name": "Test Workflow Run",
        "description": "Lifecycle test workflow",
        "steps": [{"action_type": "click", "target": "btn"}],
        "is_saved": True,
        "is_demo": False,
        "is_test": False,
        "is_temporary": False,
        "source": "TEACH_BY_DOING",
        "owner_id": "default_user"
    })

    # Initial check
    initial_res = client.get("/api/workflows").json()["workflows"]
    matching_initial = [w for w in initial_res if w["id"] == w_id]
    assert len(matching_initial) == 1
    assert matching_initial[0]["executions_count"] == 0

    # Record first execution
    exec_id1 = db.record_execution(w_id, 1, "MANUAL", "RUNNING")
    db.finish_execution(exec_id1, "COMPLETED", [{"msg": "Executed 1"}])

    run1_res = client.get("/api/workflows").json()["workflows"]
    matching_run1 = [w for w in run1_res if w["id"] == w_id]
    assert len(matching_run1) == 1, "Running workflow must not duplicate card"
    assert matching_run1[0]["executions_count"] == 1

    # Record second execution
    exec_id2 = db.record_execution(w_id, 1, "MANUAL", "RUNNING")
    db.finish_execution(exec_id2, "COMPLETED", [{"msg": "Executed 2"}])

    run2_res = client.get("/api/workflows").json()["workflows"]
    matching_run2 = [w for w in run2_res if w["id"] == w_id]
    assert len(matching_run2) == 1, "Running workflow again must not duplicate card"
    assert matching_run2[0]["executions_count"] == 2

def test_5_chat_workflow_not_saved_not_in_my_workflows():
    # Simulate chat workflow generation without saving
    w_id = wf.create_workflow_from_plan({
        "name": "Open Notepad Chat",
        "description": "Chat workflow test",
        "actions": [{"action_type": "click"}]
    }, is_saved=False, source="CHAT")

    res = client.get("/api/workflows")
    saved_ids = [w["id"] for w in res.json()["workflows"]]
    assert w_id not in saved_ids, "Unsaved Chat workflow must NOT appear in My Workflows"

def test_6_chat_workflow_explicitly_saved_appears_in_my_workflows():
    w_id = wf.create_workflow_from_plan({
        "name": "Open Notepad Chat Saved",
        "description": "Saved Chat workflow test",
        "actions": [{"action_type": "click"}]
    }, is_saved=False, source="CHAT")

    # Explicitly save
    save_res = client.post("/api/workflows/save", json={"workflow_id": w_id})
    assert save_res.status_code == 200

    res = client.get("/api/workflows")
    saved_ids = [w["id"] for w in res.json()["workflows"]]
    assert w_id in saved_ids, "Explicitly saved Chat workflow MUST appear in My Workflows"

def test_7_system_test_or_demo_workflow_not_in_my_workflows():
    # Save a demo workflow and a test workflow
    demo_id = db.save_workflow({
        "name": "Demo Workflow",
        "description": "Demo",
        "steps": [],
        "is_saved": True,
        "is_demo": True,
        "is_test": False,
        "is_temporary": False,
        "source": "DEMO"
    })
    test_id = db.save_workflow({
        "name": "Unit Test Workflow",
        "description": "Test",
        "steps": [],
        "is_saved": True,
        "is_demo": False,
        "is_test": True,
        "is_temporary": False,
        "source": "SYSTEM_TEST"
    })

    # Execute them
    exec_id_d = db.record_execution(demo_id, 1, "MANUAL", "RUNNING")
    db.finish_execution(exec_id_d, "COMPLETED", [])
    exec_id_t = db.record_execution(test_id, 1, "MANUAL", "RUNNING")
    db.finish_execution(exec_id_t, "COMPLETED", [])

    res = client.get("/api/workflows")
    saved_ids = [w["id"] for w in res.json()["workflows"]]
    assert demo_id not in saved_ids, "Demo workflow must NOT appear in My Workflows"
    assert test_id not in saved_ids, "Test workflow must NOT appear in My Workflows"

def test_8_page_refresh_returns_only_user_saved_workflows():
    # Create mix of saved, unsaved, demo, and test workflows
    saved_id = db.save_workflow({
        "name": "Legitimate User Saved Workflow",
        "description": "User saved",
        "steps": [],
        "is_saved": True,
        "is_demo": False,
        "is_test": False,
        "is_temporary": False,
        "source": "MANUAL"
    })
    db.save_workflow({
        "name": "Unsaved Temp Workflow",
        "steps": [],
        "is_saved": False,
        "is_temporary": True
    })

    res = client.get("/api/workflows")
    workflows = res.json()["workflows"]
    assert len(workflows) == 1
    assert workflows[0]["id"] == saved_id
