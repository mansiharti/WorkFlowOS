"""
Database manager for WorkFlowOS.
Handles SQLite operations for workflows, versioning, actions, activity logs, executions, and user corrections.
"""

import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "workflowos.db"


def _ensure_tables_exist(conn: sqlite3.Connection):
    cursor = conn.cursor()
    # Workflows main table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workflows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            goal TEXT NOT NULL,
            trigger TEXT,
            confidence REAL DEFAULT 0.85,
            risk TEXT DEFAULT 'LOW',
            version INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            executions_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            metadata_json TEXT,
            owner_id TEXT DEFAULT 'default_user',
            source TEXT DEFAULT 'MANUAL',
            is_saved INTEGER DEFAULT 0,
            is_demo INTEGER DEFAULT 0,
            is_test INTEGER DEFAULT 0,
            is_temporary INTEGER DEFAULT 0
        )
    """)

    # Ensure metadata columns exist if database pre-existed
    new_cols = [
        ("owner_id", "TEXT DEFAULT 'default_user'"),
        ("source", "TEXT DEFAULT 'MANUAL'"),
        ("is_saved", "INTEGER DEFAULT 0"),
        ("is_demo", "INTEGER DEFAULT 0"),
        ("is_test", "INTEGER DEFAULT 0"),
        ("is_temporary", "INTEGER DEFAULT 0")
    ]
    for col_name, col_type in new_cols:
        try:
            cursor.execute(f"ALTER TABLE workflows ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass

    # Workflow versions history
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workflow_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            actions_json TEXT NOT NULL,
            conditions_json TEXT,
            apps_json TEXT,
            confidence REAL,
            risk TEXT,
            change_reason TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
        )
    """)

    # Workflow individual actions for active version
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workflow_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            step_order INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            params_json TEXT NOT NULL,
            semantic_label TEXT,
            risk_level TEXT DEFAULT 'LOW',
            FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
        )
    """)

    # Activity collector events
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            app_name TEXT,
            window_title TEXT,
            details_json TEXT,
            semantic_action TEXT
        )
    """)

    # Workflow execution audit log
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            trigger_type TEXT DEFAULT 'MANUAL',
            status TEXT DEFAULT 'PENDING',
            start_time TEXT NOT NULL,
            end_time TEXT,
            log_json TEXT,
            error_message TEXT,
            execution_key TEXT,
            FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
        )
    """)

    try:
        cursor.execute("ALTER TABLE executions ADD COLUMN execution_key TEXT")
    except Exception:
        pass

    # User corrections and feedback memory
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workflow_id INTEGER NOT NULL,
            execution_id INTEGER,
            user_feedback TEXT,
            original_action_json TEXT,
            corrected_action_json TEXT,
            remembered INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
        )
    """)

    # App Settings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    default_settings = {
        "gemini_api_key": "",
        "require_medium_approval": "true",
        "require_high_approval": "true",
        "recording_enabled": "false",
        "sandbox_path": str(BASE_DIR / "sandbox"),
        "confidence_threshold": "0.75"
    }

    for k, v in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    conn.commit()


def get_db_connection() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='workflows'")
    if not cursor.fetchone():
        cursor.close()
        _ensure_tables_exist(conn)
    return conn


def purge_unsaved_temporary_workflows() -> int:
    """Delete any temporary or unsaved workflows from SQLite database on startup."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM workflows WHERE is_saved = 0 OR is_temporary = 1 OR is_demo = 1 OR is_test = 1")
    rows = cursor.fetchall()
    count = len(rows)
    for r in rows:
        wf_id = r["id"]
        cursor.execute("DELETE FROM workflow_actions WHERE workflow_id = ?", (wf_id,))
        cursor.execute("DELETE FROM workflow_versions WHERE workflow_id = ?", (wf_id,))
        cursor.execute("DELETE FROM executions WHERE workflow_id = ?", (wf_id,))
        cursor.execute("DELETE FROM feedback WHERE workflow_id = ?", (wf_id,))
        cursor.execute("DELETE FROM workflows WHERE id = ?", (wf_id,))
    conn.commit()
    conn.close()
    return count


def init_db():
    """Initialize database tables and purge unsaved temporary workflow artifacts."""
    conn = get_db_connection()
    conn.close()
    purge_unsaved_temporary_workflows()


# ---------------- Workflow Database CRUD ----------------

def save_workflow(workflow_data: Dict[str, Any]) -> int:
    """Save a new workflow and its initial version."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    actions = workflow_data.get("actions", [])
    version = workflow_data.get("version", 1)

    meta = dict(workflow_data.get("metadata", {}))
    if workflow_data.get("recording_id"):
        meta["recording_id"] = workflow_data["recording_id"]

    owner_id = workflow_data.get("owner_id") or workflow_data.get("owner") or workflow_data.get("user_id") or "default_user"
    source = workflow_data.get("source", "MANUAL")
    is_saved = 1 if workflow_data.get("is_saved", False) else 0
    is_demo = 1 if workflow_data.get("is_demo", False) else 0
    is_test = 1 if workflow_data.get("is_test", False) else 0
    is_temporary = 1 if workflow_data.get("is_temporary", False) else 0

    cursor.execute("""
        INSERT INTO workflows (
            name, description, goal, trigger, confidence, risk, version,
            created_at, last_used_at, executions_count, success_count, fail_count,
            is_active, metadata_json, owner_id, source, is_saved, is_demo, is_test, is_temporary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 1, ?, ?, ?, ?, ?, ?, ?)
    """, (
        workflow_data.get("name", "Untitled Workflow"),
        workflow_data.get("description", ""),
        workflow_data.get("goal", ""),
        workflow_data.get("trigger", "Manual User Trigger"),
        workflow_data.get("confidence", 0.85),
        workflow_data.get("risk", "LOW"),
        version,
        now,
        now,
        json.dumps(meta),
        owner_id,
        source,
        is_saved,
        is_demo,
        is_test,
        is_temporary
    ))

    workflow_id = cursor.lastrowid

    # Save initial version in workflow_versions
    cursor.execute("""
        INSERT INTO workflow_versions (
            workflow_id, version, actions_json, conditions_json, apps_json,
            confidence, risk, change_reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        workflow_id,
        version,
        json.dumps(actions),
        json.dumps(workflow_data.get("conditions", [])),
        json.dumps(workflow_data.get("application_names", [])),
        workflow_data.get("confidence", 0.85),
        workflow_data.get("risk", "LOW"),
        workflow_data.get("change_reason", "Initial creation"),
        now
    ))

    # Save individual actions
    for idx, act in enumerate(actions, start=1):
        act_type = act.get("type", "UNKNOWN")
        params = dict(act.get("params", {}))
        for k, v in act.items():
            if k not in ("type", "label", "risk", "params"):
                params[k] = v
        label = act.get("label", act.get("semantic_action", act_type))
        act_risk = act.get("risk", "LOW")

        cursor.execute("""
            INSERT INTO workflow_actions (
                workflow_id, version, step_order, action_type, params_json, semantic_label, risk_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            workflow_id,
            version,
            idx,
            act_type,
            json.dumps(params),
            label,
            act_risk
        ))

    conn.commit()
    conn.close()
    return workflow_id


def mark_workflow_as_saved(
    workflow_id: int,
    owner_id: Optional[str] = None,
    name: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    goal: Optional[str] = None
) -> bool:
    """Mark an existing workflow as explicitly saved by the user and update title/name."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    user_title = title or name
    query = "UPDATE workflows SET is_saved = 1, is_temporary = 0, is_demo = 0, is_test = 0"
    params = []
    
    if user_title:
        query += ", name = ?, goal = ?"
        params.extend([user_title, goal or user_title])
    elif goal:
        query += ", goal = ?"
        params.append(goal)
    if description:
        query += ", description = ?"
        params.append(description)
    if owner_id:
        query += ", owner_id = ?"
        params.append(owner_id)
        
    query += " WHERE id = ?"
    params.append(workflow_id)
    
    cursor.execute(query, params)
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def get_user_saved_workflows(owner_id: str = "default_user") -> List[Dict[str, Any]]:
    """Retrieve only workflows explicitly saved by the specified user."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM workflows
        WHERE is_active = 1
          AND is_saved = 1
          AND (is_demo IS NULL OR is_demo = 0)
          AND (is_test IS NULL OR is_test = 0)
          AND (is_temporary IS NULL OR is_temporary = 0)
          AND (owner_id = ? OR owner_id IS NULL OR owner_id = 'default_user')
        ORDER BY id DESC
    """, (owner_id,))
    rows = cursor.fetchall()

    results = []
    for row in rows:
        wf = dict(row)
        wf_id = wf["id"]
        v = wf["version"]

        cursor.execute("""
            SELECT step_order, action_type, params_json, semantic_label, risk_level
            FROM workflow_actions
            WHERE workflow_id = ? AND version = ?
            ORDER BY step_order ASC
        """, (wf_id, v))

        actions = []
        for a_row in cursor.fetchall():
            actions.append({
                "step": a_row["step_order"],
                "type": a_row["action_type"],
                "params": json.loads(a_row["params_json"]),
                "label": a_row["semantic_label"],
                "risk": a_row["risk_level"]
            })

        wf["actions"] = actions
        wf["title"] = wf.get("name") or wf.get("goal") or "Untitled Workflow"
        wf["workflow_id"] = wf_id
        if wf.get("metadata_json"):
            wf["metadata"] = json.loads(wf["metadata_json"])
        results.append(wf)

    conn.close()
    return results


def delete_workflow(workflow_id: int) -> bool:
    """Delete a workflow and all associated actions, versions, executions, and feedback."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM workflow_actions WHERE workflow_id = ?", (workflow_id,))
    cursor.execute("DELETE FROM workflow_versions WHERE workflow_id = ?", (workflow_id,))
    cursor.execute("DELETE FROM executions WHERE workflow_id = ?", (workflow_id,))
    cursor.execute("DELETE FROM feedback WHERE workflow_id = ?", (workflow_id,))
    cursor.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def delete_all_workflows(saved_only: bool = False) -> int:
    """Delete workflows and all associated actions, versions, executions, and feedback."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if saved_only:
        cursor.execute("SELECT id FROM workflows WHERE is_saved = 1")
        wf_ids = [row["id"] for row in cursor.fetchall()]
        for wf_id in wf_ids:
            delete_workflow(wf_id)
        deleted_count = len(wf_ids)
    else:
        cursor.execute("DELETE FROM workflow_actions")
        cursor.execute("DELETE FROM workflow_versions")
        cursor.execute("DELETE FROM executions")
        cursor.execute("DELETE FROM feedback")
        cursor.execute("DELETE FROM workflows")
        deleted_count = cursor.rowcount
        conn.commit()
    conn.close()
    return deleted_count


def get_all_workflows(include_inactive: bool = False, saved_only: bool = False, owner_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all workflows with their current version actions."""
    if saved_only:
        return get_user_saved_workflows(owner_id=owner_id or "default_user")

    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM workflows" if include_inactive else "SELECT * FROM workflows WHERE is_active = 1"
    query += " ORDER BY id DESC"
    cursor.execute(query)
    rows = cursor.fetchall()

    results = []
    for row in rows:
        wf = dict(row)
        wf_id = wf["id"]
        v = wf["version"]

        # Get actions for this version
        cursor.execute("""
            SELECT step_order, action_type, params_json, semantic_label, risk_level
            FROM workflow_actions
            WHERE workflow_id = ? AND version = ?
            ORDER BY step_order ASC
        """, (wf_id, v))

        actions = []
        for a_row in cursor.fetchall():
            actions.append({
                "step": a_row["step_order"],
                "type": a_row["action_type"],
                "params": json.loads(a_row["params_json"]),
                "label": a_row["semantic_label"],
                "risk": a_row["risk_level"]
            })

        wf["actions"] = actions
        wf["title"] = wf.get("name") or wf.get("goal") or "Untitled Workflow"
        wf["workflow_id"] = wf_id
        if wf.get("metadata_json"):
            wf["metadata"] = json.loads(wf["metadata_json"])
        results.append(wf)

    conn.close()
    return results


def get_workflow(workflow_id: int) -> Optional[Dict[str, Any]]:
    """Get a workflow by ID including its active actions."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    wf = dict(row)
    v = wf["version"]

    cursor.execute("""
        SELECT step_order, action_type, params_json, semantic_label, risk_level
        FROM workflow_actions
        WHERE workflow_id = ? AND version = ?
        ORDER BY step_order ASC
    """, (workflow_id, v))

    actions = []
    for a_row in cursor.fetchall():
        actions.append({
            "step": a_row["step_order"],
            "type": a_row["action_type"],
            "params": json.loads(a_row["params_json"]),
            "label": a_row["semantic_label"],
            "risk": a_row["risk_level"]
        })

    wf["actions"] = actions
    wf["title"] = wf.get("name") or wf.get("goal") or "Untitled Workflow"
    wf["workflow_id"] = workflow_id
    if wf.get("metadata_json"):
        wf["metadata"] = json.loads(wf["metadata_json"])
    conn.close()
    return wf


def get_workflow_versions(workflow_id: int) -> List[Dict[str, Any]]:
    """Get all past and current versions of a workflow."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM workflow_versions
        WHERE workflow_id = ?
        ORDER BY version DESC
    """, (workflow_id,))
    rows = cursor.fetchall()

    versions = []
    for r in rows:
        v = dict(r)
        v["actions"] = json.loads(v["actions_json"]) if v.get("actions_json") else []
        v["conditions"] = json.loads(v["conditions_json"]) if v.get("conditions_json") else []
        v["apps"] = json.loads(v["apps_json"]) if v.get("apps_json") else []
        versions.append(v)

    conn.close()
    return versions


def save_workflow_version(
    workflow_id: int,
    new_version: int,
    actions: List[Dict[str, Any]],
    confidence: float,
    risk: str,
    change_reason: str,
    conditions: Optional[List[str]] = None,
    apps: Optional[List[str]] = None
) -> None:
    """Save an evolved version of a workflow, set it active in the workflow table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    # Insert into workflow_versions
    cursor.execute("""
        INSERT INTO workflow_versions (
            workflow_id, version, actions_json, conditions_json, apps_json,
            confidence, risk, change_reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        workflow_id,
        new_version,
        json.dumps(actions),
        json.dumps(conditions or []),
        json.dumps(apps or []),
        confidence,
        risk,
        change_reason,
        now
    ))

    # Insert actions for the new version
    for idx, act in enumerate(actions, start=1):
        act_type = act.get("type", "UNKNOWN")
        params = act.get("params", {k: v for k, v in act.items() if k not in ("type", "label", "risk")})
        label = act.get("label", act.get("semantic_action", act_type))
        act_risk = act.get("risk", "LOW")

        cursor.execute("""
            INSERT INTO workflow_actions (
                workflow_id, version, step_order, action_type, params_json, semantic_label, risk_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            workflow_id,
            new_version,
            idx,
            act_type,
            json.dumps(params),
            label,
            act_risk
        ))

    # Update main workflow active version and risk/confidence
    cursor.execute("""
        UPDATE workflows
        SET version = ?, confidence = ?, risk = ?, last_used_at = ?
        WHERE id = ?
    """, (new_version, confidence, risk, now, workflow_id))

    conn.commit()
    conn.close()


def restore_workflow_version(workflow_id: int, target_version: int) -> bool:
    """Restore an older version to be the active version."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM workflow_versions
        WHERE workflow_id = ? AND version = ?
    """, (workflow_id, target_version))
    target = cursor.fetchone()
    if not target:
        conn.close()
        return False

    target_dict = dict(target)
    now = datetime.now().isoformat()

    cursor.execute("""
        UPDATE workflows
        SET version = ?, confidence = ?, risk = ?, last_used_at = ?
        WHERE id = ?
    """, (target_version, target_dict["confidence"], target_dict["risk"], now, workflow_id))

    conn.commit()
    conn.close()
    return True


def record_execution(
    workflow_id: int,
    version: int,
    trigger_type: str = "MANUAL",
    status: str = "RUNNING",
    execution_key: Optional[str] = None
) -> int:
    """Create a new execution record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute("""
        INSERT INTO executions (
            workflow_id, version, trigger_type, status, start_time, log_json, execution_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (workflow_id, version, trigger_type, status, now, json.dumps([]), execution_key))

    exec_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return exec_id


def finish_execution(
    execution_id: int,
    status: str,
    logs: List[Dict[str, Any]],
    error_message: Optional[str] = None
) -> None:
    """Update execution completion status and logs."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute("""
        UPDATE executions
        SET status = ?, end_time = ?, log_json = ?, error_message = ?
        WHERE id = ?
    """, (str(status), now, json.dumps(logs), error_message, execution_id))

    # Update workflow execution counts
    cursor.execute("SELECT workflow_id FROM executions WHERE id = ?", (execution_id,))
    row = cursor.fetchone()
    if row:
        wf_id = row["workflow_id"]
        status_upper = str(status).upper()
        is_success = 1 if status_upper in ("COMPLETED", "SUCCESS") else 0
        is_fail = 1 if status_upper == "FAILED" else 0

        cursor.execute("""
            UPDATE workflows
            SET executions_count = executions_count + 1,
                success_count = success_count + ?,
                fail_count = fail_count + ?,
                last_used_at = ?
            WHERE id = ?
        """, (is_success, is_fail, now, wf_id))

    conn.commit()
    conn.close()


def get_execution_by_key(execution_key: str) -> Optional[Dict[str, Any]]:
    """Retrieve execution record by unique execution_key."""
    if not execution_key:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM executions WHERE execution_key = ? ORDER BY id DESC LIMIT 1", (execution_key,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    res = dict(row)
    if res.get("log_json"):
        try:
            res["logs"] = json.loads(res["log_json"])
        except Exception:
            res["logs"] = []
    return res


def get_workflow_execution_history(workflow_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve execution history audit log for a workflow."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM executions
        WHERE workflow_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (workflow_id, limit))
    rows = cursor.fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("log_json"):
            try:
                d["logs"] = json.loads(d["log_json"])
            except Exception:
                d["logs"] = []
        results.append(d)
    conn.close()
    return results



def save_user_correction(
    workflow_id: int,
    execution_id: Optional[int],
    feedback_text: str,
    original_action: Dict[str, Any],
    corrected_action: Dict[str, Any],
    remember: bool = True
) -> int:
    """Store user correction and update feedback memory."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute("""
        INSERT INTO feedback (
            workflow_id, execution_id, user_feedback,
            original_action_json, corrected_action_json, remembered, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        workflow_id,
        execution_id,
        feedback_text,
        json.dumps(original_action),
        json.dumps(corrected_action),
        1 if remember else 0,
        now
    ))
    feedback_id = cursor.lastrowid

    # If remember is requested, attach to workflow metadata
    if remember:
        cursor.execute("SELECT metadata_json FROM workflows WHERE id = ?", (workflow_id,))
        wf_row = cursor.fetchone()
        metadata = json.loads(wf_row["metadata_json"]) if (wf_row and wf_row["metadata_json"]) else {}
        corrections = metadata.get("user_corrections", [])
        corrections.append({
            "feedback": feedback_text,
            "original": original_action,
            "corrected": corrected_action,
            "date": now
        })
        metadata["user_corrections"] = corrections
        cursor.execute("UPDATE workflows SET metadata_json = ? WHERE id = ?", (json.dumps(metadata), workflow_id))

    conn.commit()
    conn.close()
    return feedback_id


def log_activity_event(
    session_id: str,
    event_type: str,
    app_name: str,
    window_title: str,
    details: Dict[str, Any],
    semantic_action: Optional[str] = None
) -> int:
    """Log an event into activity_events."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute("""
        INSERT INTO activity_events (
            session_id, timestamp, event_type, app_name, window_title, details_json, semantic_action
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id,
        now,
        event_type,
        app_name,
        window_title,
        json.dumps(details),
        semantic_action or event_type
    ))

    event_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return event_id


def get_recent_activity(limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent activity events."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM activity_events
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()

    results = []
    for r in rows:
        d = dict(r)
        d["details"] = json.loads(d["details_json"]) if d.get("details_json") else {}
        results.append(d)

    conn.close()
    return results


def get_setting(key: str, default: str = "") -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, value))
    conn.commit()
    conn.close()


def get_all_settings() -> Dict[str, str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


# Auto-initialize database on import
init_db()
