import pytest
import database as db
from fastapi.testclient import TestClient
from app import app
import workflow as wf_engine

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_clean_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_idempotency.db")
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()
    yield test_db

def test_single_click_idempotent_execution_id():
    # Save a test workflow
    wf_id = db.save_workflow({
        "name": "Idempotency Test Workflow",
        "description": "Test single execution per execution_id",
        "actions": [{"type": "CLICK", "target": "button"}],
        "is_saved": True
    })

    exec_id = "E_IDEMPOTENT_001"

    # First execution request
    res1 = client.post("/api/workflows/execute", json={
        "workflow_id": wf_id,
        "execution_id": exec_id,
        "mode": "sandbox",
        "confirmed_medium": True,
        "confirmed_high": True
    })
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["execution_id"] == exec_id
    assert data1["status"] in ("SUCCESS", "COMPLETED")

    # Duplicate execution request with SAME execution_id
    res2 = client.post("/api/workflows/execute", json={
        "workflow_id": wf_id,
        "execution_id": exec_id,
        "mode": "sandbox",
        "confirmed_medium": True,
        "confirmed_high": True
    })
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["execution_id"] == exec_id
    # Must return the existing execution state without starting a second execution
    assert data2["workflow_execution_count"] == 1 or data2.get("result", {}).get("workflow_execution_count") == 1

def test_action_executes_exactly_once_per_workflow_run():
    wf_id = db.save_workflow({
        "name": "Single Action Run Test",
        "description": "Test single action execution",
        "actions": [{"type": "CLICK", "target": "button1"}, {"type": "CLICK", "target": "button2"}],
        "is_saved": True
    })

    exec_id = "E_ACTION_ONCE_001"
    res = client.post("/api/workflows/execute", json={
        "workflow_id": wf_id,
        "execution_id": exec_id,
        "mode": "sandbox",
        "confirmed_medium": True,
        "confirmed_high": True
    })
    assert res.status_code == 200
    data = res.json()
    assert data["total_steps"] == 2
    assert data["completed_steps"] == 2
