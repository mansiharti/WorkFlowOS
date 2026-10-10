"""
Unit tests for Global JSON Serialization and API Response Integrity in WorkFlowOS.
"""

import json
from datetime import datetime
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app import app
import database as db
import workflow as wf_engine
from json_utils import make_json_safe
from automation import ExecutionResult

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_clean_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_json_serialization.db")
    monkeypatch.setattr(db, "DB_PATH", test_db)
    db.init_db()
    yield test_db


def test_successful_workflow_response_is_valid_json():
    """1. Successful workflow response is valid JSON."""
    wf_id = db.save_workflow({
        "name": "JSON Success Test",
        "description": "Test workflow",
        "actions": [{"type": "OPEN_APPLICATION", "params": {"app": "Notepad"}}],
        "is_saved": True
    })

    res = client.post("/api/workflows/execute", json={
        "workflow_id": wf_id,
        "mode": "SANDBOX",
        "confirmed_medium": True,
        "confirmed_high": True
    })

    assert res.status_code == 200
    assert "application/json" in res.headers["content-type"]
    
    # Must parse without SyntaxError
    data = res.json()
    assert isinstance(data, dict)
    assert data.get("status") in ("SUCCESS", "COMPLETED")
    assert data.get("success") is True
    assert data.get("workflow_id") == wf_id
    assert "execution_id" in data
    assert "result" in data


def test_failed_workflow_response_is_valid_json():
    """2. Failed workflow response is valid JSON."""
    # Workflow with empty actions or failed validation
    wf_id = db.save_workflow({
        "name": "JSON Failure Test",
        "description": "Empty workflow",
        "actions": [],
        "is_saved": True
    })

    res = client.post("/api/workflows/execute", json={
        "workflow_id": wf_id,
        "mode": "SANDBOX",
        "confirmed_medium": True,
        "confirmed_high": True
    })

    assert res.status_code == 200
    assert "application/json" in res.headers["content-type"]

    data = res.json()
    assert isinstance(data, dict)
    assert data.get("status") == "FAILED"
    assert data.get("success") is False
    assert "error" in data


def test_missing_workflow_id_returns_valid_json():
    """3. Missing workflow_id returns valid JSON."""
    res = client.post("/api/workflows/execute", json={
        "workflow_id": 0,
        "mode": "SANDBOX",
        "confirmed_medium": True,
        "confirmed_high": True
    })

    assert res.status_code == 200
    assert "application/json" in res.headers["content-type"]

    data = res.json()
    assert isinstance(data, dict)
    assert "Missing workflow" in str(data.get("error"))


def test_execution_exception_returns_valid_json(monkeypatch):
    """4. Execution exception returns valid JSON via global exception handler."""
    def raise_err(*args, **kwargs):
        raise RuntimeError("Simulated internal backend engine failure")

    monkeypatch.setattr(wf_engine, "execute_workflow", raise_err)

    wf_id = db.save_workflow({
        "name": "Exception Test",
        "actions": [{"type": "OPEN_APPLICATION", "params": {"app": "Notepad"}}],
        "is_saved": True
    })

    res = client.post("/api/workflows/execute", json={
        "workflow_id": wf_id,
        "mode": "SANDBOX"
    })

    # Exception caught by global exception handler
    assert res.status_code == 500
    assert "application/json" in res.headers["content-type"]

    data = res.json()
    assert isinstance(data, dict)
    assert data.get("status") == "FAILED"
    assert data.get("success") is False
    assert "Simulated internal backend engine failure" in str(data.get("error"))


def test_multiple_action_results_serialize_correctly():
    """5. Multiple action results serialize correctly."""
    wf_id = db.save_workflow({
        "name": "Multi Action Test",
        "actions": [
            {"type": "OPEN_APPLICATION", "params": {"app": "Notepad"}},
            {"type": "CREATE_FOLDER", "params": {"path": "SandboxFolder"}},
            {"type": "CREATE_FILE", "params": {"path": "SandboxFolder/test.txt", "content": "hello"}}
        ],
        "is_saved": True
    })

    res = client.post("/api/workflows/execute", json={
        "workflow_id": wf_id,
        "mode": "SANDBOX",
        "confirmed_medium": True,
        "confirmed_high": True
    })

    assert res.status_code == 200
    data = res.json()
    assert data.get("total_steps") == 3
    assert len(data.get("result", {}).get("logs", [])) == 3

    # Re-serialize with json.dumps to verify 100% valid JSON
    serialized = json.dumps(data)
    assert isinstance(serialized, str)


def test_datetime_and_pathlib_values_serialize_correctly():
    """6 & 7. datetime and pathlib values serialize correctly via make_json_safe."""
    now = datetime.now()
    p = Path("C:/Users/hp/Desktop/test_file.txt")

    raw_data = {
        "timestamp": now,
        "file_path": p,
        "nested": {
            "created_at": now,
            "target": p
        }
    }

    safe_data = make_json_safe(raw_data)
    assert safe_data["timestamp"] == now.isoformat()
    assert safe_data["file_path"] == str(p)
    assert safe_data["nested"]["created_at"] == now.isoformat()
    assert safe_data["nested"]["target"] == str(p)

    # Must dump without TypeError
    dumped = json.dumps(safe_data)
    assert isinstance(dumped, str)


def test_custom_objects_and_execution_result_serialize_correctly():
    """8. Custom objects like ExecutionResult serialize cleanly."""
    exec_res = ExecutionResult(
        success=True,
        message="Created folder",
        data={"path": Path("sandbox/Folder1")},
        stage_logs=["Stage 1: Verified"]
    )

    safe_res = make_json_safe(exec_res)
    assert isinstance(safe_res, dict)
    assert safe_res["success"] is True
    assert safe_res["data"]["path"] == str(Path("sandbox/Folder1"))

    dumped = json.dumps(safe_res)
    assert isinstance(dumped, str)


def test_server_debug_logs_do_not_appear_inside_http_json_body():
    """10. Server debug logs do not appear inside the HTTP JSON body."""
    wf_id = db.save_workflow({
        "name": "Log Separation Test",
        "actions": [{"type": "OPEN_APPLICATION", "params": {"app": "Notepad"}}],
        "is_saved": True
    })

    res = client.post("/api/workflows/execute", json={
        "workflow_id": wf_id,
        "mode": "SANDBOX",
        "confirmed_medium": True,
        "confirmed_high": True
    })

    raw_text = res.text.strip()
    
    # Must be valid JSON from first character '{' to last character '}'
    assert raw_text.startswith("{")
    assert raw_text.endswith("}")
    
    # Debug logs like [TEACH] or [EXECUTOR] must NOT precede or succeed JSON in the response
    data = json.loads(raw_text)
    assert isinstance(data, dict)
