import pytest
import database as db
from fastapi.testclient import TestClient
from app import app
import activity as act
import workflow as wf_engine

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_clean_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_wf_id_integrity.db")
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()
    yield test_db

def test_missing_or_zero_workflow_id_fails_early():
    # Attempting to execute with workflow_id = 0 or None must fail early
    res = client.post("/api/workflows/execute", json={
        "workflow_id": 0,
        "mode": "REAL",
        "confirmed_medium": True,
        "confirmed_high": True
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "FAILED"
    assert data["workflow_id"] == 0 or data["workflow_id"] is None
    assert "Missing workflow_id" in data["error"]

def test_save_workflow_returns_complete_storage_metadata():
    # Create a plan and save it
    w_id = wf_engine.create_workflow_from_plan({
        "name": "Metadata Test Workflow",
        "description": "Testing save metadata return",
        "actions": [{"action_type": "click", "target": "button"}]
    }, is_saved=False, is_temporary=True)

    save_res = client.post("/api/workflows/save", json={"workflow_id": w_id})
    assert save_res.status_code == 200
    data = save_res.json()
    assert data["workflow_id"] == w_id
    assert data["saved"] is True
    assert data["version"] >= 1
    assert data["action_count"] == 1
    assert "recording_id" in data

def test_empty_actions_workflow_fails_early():
    # Save a workflow with 0 actions
    wf_id = db.save_workflow({
        "name": "Empty Actions Workflow",
        "description": "Empty",
        "steps": [],
        "is_saved": True
    })

    res = client.post("/api/workflows/execute", json={
        "workflow_id": wf_id,
        "mode": "REAL",
        "confirmed_medium": True,
        "confirmed_high": True
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "FAILED"
    assert "contains no executable actions" in data["error"] or "has 0 actions" in data["error"]

def test_teach_by_doing_allow_and_run_saves_and_executes_real_id():
    # Simulate stopping teach session
    act.collector.start_recording("test_session_integrity")
    act.collector.record_event("click", "Notepad", "Untitled - Notepad", {"target": "Text Area"})
    
    stop_res = client.post("/api/teach/stop")
    assert stop_res.status_code == 200
    plan = stop_res.json().get("plan")
    assert stop_res.json().get("workflow_id") is None

    # Explicit Save
    save_res = client.post("/api/workflows/save", json={"plan": plan, "title": "Integrity Test Workflow"})
    assert save_res.status_code == 200
    w_id = save_res.json().get("workflow_id")
    assert w_id is not None and w_id > 0

    # Execute workflow using real w_id
    exec_res = client.post("/api/workflows/execute", json={
        "workflow_id": w_id,
        "source": "teach",
        "mode": "REAL",
        "confirmed_medium": True,
        "confirmed_high": True
    })
    assert exec_res.status_code == 200
    exec_data = exec_res.json()
    assert exec_data["workflow_id"] == w_id
    assert exec_data["workflow_id"] != 0
