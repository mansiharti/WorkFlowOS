"""
Automated unit tests for Workflow Title Persistence and My Workflows Display.
Verifies that:
1. User-provided title ("My Calculator Test") is persisted in database and returned via API.
2. Action description ("Click: UI Element") never overwrites workflow title.
3. Page refresh / reloading from database retains exact user title.
4. Editing workflow title updates database and UI without creating duplicate workflow records.
5. Multiple workflows retain distinct user-provided titles.
6. Saving existing workflow updates record idempotently without duplicate row creation.
"""

import pytest
from fastapi.testclient import TestClient
from app import app
import database as db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    db.init_db()
    yield

def test_1_save_workflow_persists_exact_user_title():
    # 1. Start teaching session
    res = client.post("/api/teach/start?session_name=TitleTestSession")
    assert res.status_code == 200
    rec_id = res.json()["recording_id"]

    # 2. Record click action event
    client.post("/api/teach/record-event", json={
        "recording_id": rec_id,
        "event_type": "UI_CLICK",
        "app_name": "calc.exe",
        "window_title": "Calculator",
        "details": {"target": "UI Element"},
        "source": "USER_INPUT"
    })

    # 3. Stop teaching
    res_stop = client.post("/api/teach/stop")
    assert res_stop.status_code == 200
    plan = res_stop.json()["plan"]
    assert res_stop.json()["workflow_id"] is None

    # 4. Save workflow with custom title "My Calculator Test"
    custom_title = "My Calculator Test"
    res_save = client.post("/api/workflows/save", json={
        "title": custom_title,
        "name": custom_title,
        "plan": plan
    })
    assert res_save.status_code == 200
    save_data = res_save.json()
    assert save_data["success"] is True
    assert save_data["title"] == custom_title
    wf_id = save_data["workflow_id"]
    assert wf_id is not None and wf_id > 0

    # 5. Fetch saved workflows from database
    res_list = client.get("/api/workflows")
    assert res_list.status_code == 200
    wfs = res_list.json()["workflows"]
    matching = [w for w in wfs if w["id"] == wf_id or w.get("workflow_id") == wf_id]
    assert len(matching) == 1
    assert matching[0]["title"] == custom_title
    assert matching[0]["name"] == custom_title
    assert matching[0]["title"] != "Click: UI Element"

def test_2_refresh_and_app_restart_retains_title():
    # Save a workflow directly to DB via save endpoint
    res_save = client.post("/api/workflows/save", json={
        "title": "Persistent Test Workflow",
        "plan": {
            "name": "Persistent Test Workflow",
            "goal": "Persistent Test Workflow Goal",
            "actions": [{"type": "CLICK", "label": "Click: UI Element", "params": {"target": "Button"}}]
        }
    })
    assert res_save.status_code == 200
    wf_id = res_save.json()["workflow_id"]

    # Simulate app restart / page refresh by querying DB directly
    db_wf = db.get_workflow(wf_id)
    assert db_wf is not None
    assert db_wf["title"] == "Persistent Test Workflow"
    assert db_wf["name"] == "Persistent Test Workflow"

    # Query API endpoint
    res_get = client.get(f"/api/workflows/{wf_id}")
    assert res_get.status_code == 200
    wf_data = res_get.json()["workflow"]
    assert wf_data["title"] == "Persistent Test Workflow"

def test_3_edit_workflow_title_updates_db_and_api():
    # Save initial workflow
    res_save = client.post("/api/workflows/save", json={
        "title": "My Calculator Test",
        "plan": {
            "name": "My Calculator Test",
            "goal": "Calculator Task",
            "actions": [{"type": "CLICK", "label": "Click: UI Element", "params": {"target": "Calc"}}]
        }
    })
    wf_id = res_save.json()["workflow_id"]

    # Edit workflow title to "Calculator Addition Workflow"
    res_edit = client.post("/api/workflows/save", json={
        "workflow_id": wf_id,
        "title": "Calculator Addition Workflow",
        "name": "Calculator Addition Workflow"
    })
    assert res_edit.status_code == 200
    assert res_edit.json()["title"] == "Calculator Addition Workflow"

    # Verify DB update
    db_wf = db.get_workflow(wf_id)
    assert db_wf["name"] == "Calculator Addition Workflow"
    assert db_wf["title"] == "Calculator Addition Workflow"

def test_4_multiple_workflows_retain_distinct_titles():
    # Create Workflow A
    r_a = client.post("/api/workflows/save", json={
        "title": "My Calculator Test",
        "plan": {"actions": [{"type": "CLICK", "label": "Click: UI Element", "params": {}}]}
    })
    wf_a_id = r_a.json()["workflow_id"]

    # Create Workflow B
    r_b = client.post("/api/workflows/save", json={
        "title": "Browser Search Test",
        "plan": {"actions": [{"type": "CLICK", "label": "Click: UI Element", "params": {}}]}
    })
    wf_b_id = r_b.json()["workflow_id"]

    # Create Workflow C
    r_c = client.post("/api/workflows/save", json={
        "title": "File Organization Test",
        "plan": {"actions": [{"type": "CLICK", "label": "Click: UI Element", "params": {}}]}
    })
    wf_c_id = r_c.json()["workflow_id"]

    # Retrieve all saved workflows
    res = client.get("/api/workflows")
    wfs = {w["id"]: w["title"] for w in res.json()["workflows"]}

    assert wfs[wf_a_id] == "My Calculator Test"
    assert wfs[wf_b_id] == "Browser Search Test"
    assert wfs[wf_c_id] == "File Organization Test"

def test_5_saving_existing_workflow_prevents_duplicate_records():
    # Save initial
    r1 = client.post("/api/workflows/save", json={
        "title": "Idempotent Title Test",
        "plan": {"actions": [{"type": "CLICK", "label": "Click: UI Element", "params": {}}]}
    })
    wf_id = r1.json()["workflow_id"]

    count_before = len(client.get("/api/workflows").json()["workflows"])

    # Re-save same workflow ID with updated title
    r2 = client.post("/api/workflows/save", json={
        "workflow_id": wf_id,
        "title": "Idempotent Title Test Updated"
    })
    assert r2.json()["workflow_id"] == wf_id

    count_after = len(client.get("/api/workflows").json()["workflows"])
    assert count_after == count_before
