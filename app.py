"""
WorkFlowOS — AI-Powered Desktop Workflow Automation.
Main application server using FastAPI.
Provides both full REST API endpoints and a modern, responsive web desktop interface.
"""

import os
import sys
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database as db
import automation as auto
import activity as act
import ai
import workflow as wf_engine

from json_utils import make_json_safe

BASE_DIR = Path(__file__).resolve().parent
SANDBOX_DIR = BASE_DIR / "sandbox"
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="WorkFlowOS", description="AI-Powered Desktop Workflow Automation", version="1.0.0")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    endpoint_name = request.url.path
    print(f"\n[API RESPONSE ERROR] endpoint = {endpoint_name}")
    print(f"[API RESPONSE ERROR] status = 500")
    print(f"[API RESPONSE ERROR] content_type = application/json")
    print(f"[API RESPONSE ERROR] exception = {exc}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content=make_json_safe({
            "success": False,
            "status": "FAILED",
            "error": {
                "type": exc.__class__.__name__,
                "message": str(exc)
            },
            "detail": str(exc)
        })
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=make_json_safe({
            "success": False,
            "status": "FAILED",
            "error": {
                "type": "HTTPException",
                "message": str(exc.detail)
            },
            "detail": exc.detail
        })
    )


# ---------------- Request Models ----------------

class ChatPlanRequest(BaseModel):
    prompt: str


class PlanSaveRequest(BaseModel):
    workflow_id: Optional[int] = None
    title: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    goal: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    mode: Optional[str] = "sandbox"


class DiscardRequest(BaseModel):
    workflow_id: Optional[int] = None


class ExecuteRequest(BaseModel):
    workflow_id: Optional[int] = None
    actions: Optional[List[Dict[str, Any]]] = None
    plan: Optional[Dict[str, Any]] = None
    confirmed_medium: bool = True
    confirmed_high: bool = True
    mode: Optional[str] = "REAL"
    ui_mode: Optional[str] = None
    requested_mode: Optional[str] = None
    expected_action_count: Optional[int] = None
    source: Optional[str] = None
    recording_id: Optional[str] = None
    execution_id: Optional[str] = None


class DryRunRequest(BaseModel):
    workflow_id: Optional[int] = None
    plan: Optional[Dict[str, Any]] = None
    mode: Optional[str] = "sandbox"


class EvolutionApplyRequest(BaseModel):
    workflow_id: int
    new_actions: List[Dict[str, Any]]
    change_reason: Optional[str] = "User demonstrated changed workflow behavior"


class RestoreVersionRequest(BaseModel):
    workflow_id: int
    target_version: int


class CorrectionRequest(BaseModel):
    workflow_id: int
    execution_id: Optional[int] = None
    feedback_text: str
    original_action: Dict[str, Any]
    corrected_action: Dict[str, Any]
    remember: bool = True


class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, str]


class DemoTriggerRequest(BaseModel):
    demo_id: str


class RecordEventRequest(BaseModel):
    event_type: str
    app_name: Optional[str] = "desktop"
    window_title: Optional[str] = ""
    details: Optional[Dict[str, Any]] = None
    semantic_action: Optional[str] = None


# ---------------- API Endpoints ----------------

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "WorkFlowOS", "version": "1.0.0"}


@app.get("/api/session-info")
def session_info():
    """Returns Windows session and interactive desktop status."""
    return auto.check_interactive_session()


# 1. Chat to Automation Endpoints
@app.post("/api/chat/plan")
def chat_create_plan(req: ChatPlanRequest):
    """Generate structured workflow plan from natural language goal."""
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Goal prompt cannot be empty")
    plan = ai.parse_chat_goal(req.prompt)
    if not plan or not plan.get("actions"):
        raise HTTPException(status_code=400, detail="Unable to parse a valid workflow plan from your prompt.")
    return {"success": True, "plan": plan}


@app.post("/api/chat/save-and-run")
def chat_save_and_run(req: PlanSaveRequest):
    """Save generated plan and execute it with one-time approval."""
    if not req.plan:
        raise HTTPException(status_code=400, detail="Plan is required")
    wf_id = wf_engine.create_workflow_from_plan(req.plan, is_saved=True, source="CHAT", is_temporary=False)
    mode = req.mode or "sandbox"
    res = wf_engine.execute_workflow(wf_id, confirmed_medium=True, confirmed_high=True, mode=mode)
    return {"workflow_id": wf_id, "execution": res}


# 2. Teach-by-Doing Endpoints
@app.post("/api/teach/start")
def start_teaching(session_name: Optional[str] = "Manual Teaching"):
    rec_id = act.collector.start_recording(session_name)
    return {"recording_id": rec_id, "session_id": rec_id, "status": "recording"}


@app.post("/api/teach/stop")
def stop_teaching():
    events = act.collector.stop_recording()
    rec_id = act.collector.current_recording_id or act.collector.current_session_id or "rec_unknown"

    # Requirement 4: Show Raw Observed Events
    print(f"\n==================================================")
    print(f"RAW EVENTS OBSERVED DURING THIS RECORDING")
    print(f"Recording ID: {rec_id}")
    print(f"Total Events: {len(events)}")
    for idx, ev in enumerate(events, start=1):
        t = ev.get("timestamp", "")
        et = ev.get("event_type", "")
        aw = f"{ev.get('app_name', '')} / {ev.get('window_title', '')}"
        tgt = ev.get("target", "") or ev.get("details", {}).get("target", "")
        src = ev.get("source", "OBSERVED")
        print(f"[EVENT {idx}] timestamp={t} | type={et} | app/window={aw} | target={tgt} | source={src}")
    print(f"==================================================")

    if not events:
        return {"events_count": 0, "plan": None, "evolution": None, "workflow_id": None, "recording_id": rec_id}

    # Synthesize semantic workflow with recording isolation
    plan = ai.synthesize_workflow_from_events(events, recording_id=rec_id)

    # Generate temporary in-memory workflow plan (DO NOT save to database)
    wf_id = None
    if plan:
        plan["id"] = None
        plan["workflow_id"] = None
        plan["recording_id"] = rec_id
        plan["is_saved"] = False
        plan["is_temporary"] = True
    actions_count = len(plan.get("actions", [])) if plan else 0

    print(f"\n[TEACH]")
    print(f"recording_id = {rec_id}")
    print(f"workflow_id = {wf_id}")
    print(f"version = {plan.get('version', 1) if plan else 1}")
    print(f"actions = {actions_count}")


    # Check for Workflow Evolution against existing workflows
    existing = db.get_user_saved_workflows()
    evolution = ai.detect_workflow_evolution(existing, plan.get("actions", []), plan.get("goal"))

    return {
        "workflow_id": None,
        "recording_id": rec_id,
        "events_count": len(events),
        "events": events[:20],
        "plan": plan,
        "evolution": evolution
    }


@app.get("/api/teach/status")
def teach_status():
    return act.collector.get_status()


@app.post("/api/teach/record-event")
def record_event_endpoint(req: RecordEventRequest):
    """Allows programmatic/external injection of desktop events into active recording."""
    ev = act.collector.record_event(
        event_type=req.event_type,
        app_name=req.app_name or "desktop",
        window_title=req.window_title or "",
        details=req.details or {},
        semantic_action=req.semantic_action
    )
    return {"status": "recorded", "event": ev, "events_count": len(act.collector.events_buffer)}


@app.post("/api/teach/simulate-demo")
def simulate_demonstration(req: DemoTriggerRequest):
    """Inject sample demonstration events for testing."""
    events = act.collector.simulate_demonstration(req.demo_id)
    plan = ai.synthesize_workflow_from_events(events)
    wf_id = None
    if plan:
        plan["id"] = None
        plan["workflow_id"] = None
        plan["is_saved"] = False
        plan["is_demo"] = True
        plan["is_temporary"] = True
    actions_count = len(plan.get("actions", [])) if plan else 0

    print(f"\n==================================================")
    print(f"[TEACH DEMO] In-memory preview workflow generated")
    print(f"[TEACH DEMO] Temporary actions = {actions_count}")
    print(f"==================================================")

    existing = db.get_user_saved_workflows()
    evolution = ai.detect_workflow_evolution(existing, plan.get("actions", []), plan.get("goal"))

    return {
        "workflow_id": None,
        "demo_id": req.demo_id,
        "events_count": len(events),
        "events": events,
        "plan": plan,
        "evolution": evolution
    }


# 3. Workflows CRUD & Versioning
@app.get("/api/workflows")
def list_workflows(owner_id: str = "default_user", include_all: bool = False):
    if include_all:
        wfs = db.get_all_workflows()
    else:
        wfs = db.get_user_saved_workflows(owner_id=owner_id)
    return {"workflows": wfs}


@app.get("/api/workflows/{workflow_id}")
def get_workflow(workflow_id: int):
    wf = db.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"workflow": wf}


@app.post("/api/workflows")
@app.post("/api/workflows/save")
def save_workflow(req: PlanSaveRequest):
    user_title = req.title or req.name or (req.plan.get("title") or req.plan.get("name") if req.plan else None)
    if user_title:
        user_title = str(user_title).strip()

    wf_id = req.workflow_id or (req.plan.get("id") or req.plan.get("workflow_id") if req.plan else None)
    
    try:
        if wf_id:
            if req.plan and user_title:
                req.plan["name"] = user_title
                req.plan["title"] = user_title
                req.plan["goal"] = user_title
            db.mark_workflow_as_saved(
                wf_id,
                title=user_title,
                name=user_title,
                description=req.description or (req.plan.get("description") if req.plan else None) or user_title,
                goal=req.goal or (req.plan.get("goal") if req.plan else None) or user_title
            )
            saved_wf = db.get_workflow(wf_id)
            if not saved_wf and req.plan:
                if req.plan.get("actions"):
                    req.plan["is_saved"] = True
                    req.plan["is_temporary"] = False
                    wf_id = wf_engine.create_workflow_from_plan(req.plan, is_saved=True, is_temporary=False)
                    saved_wf = db.get_workflow(wf_id)
        elif req.plan:
            if user_title:
                req.plan["name"] = user_title
                req.plan["title"] = user_title
                req.plan["goal"] = user_title
            req.plan["is_saved"] = True
            req.plan["is_temporary"] = False
            if not req.plan.get("actions"):
                raise HTTPException(status_code=400, detail="Cannot save workflow without actions captured")

            # Check idempotency: if user saved a workflow with exact same title/name already
            existing_saved = db.get_user_saved_workflows()
            match = None
            if user_title:
                for w in existing_saved:
                    if (w.get("name") or w.get("title") or "").strip().lower() == user_title.lower():
                        match = w
                        break
            if match:
                wf_id = match["id"]
                db.mark_workflow_as_saved(
                    wf_id,
                    title=user_title,
                    name=user_title,
                    description=req.description or user_title,
                    goal=req.goal or user_title
                )
                saved_wf = db.get_workflow(wf_id)
            else:
                wf_id = wf_engine.create_workflow_from_plan(req.plan, is_saved=True, is_temporary=False)
                saved_wf = db.get_workflow(wf_id)
        else:
            raise HTTPException(status_code=400, detail="Provide plan or workflow_id to save")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    rec_id = (saved_wf.get("metadata", {}).get("recording_id") if saved_wf else None) or (req.plan.get("recording_id") if req.plan else None) or "R001"
    version = saved_wf.get("version", 1) if saved_wf else 1
    actions_count = len(saved_wf.get("actions", [])) if saved_wf else (len(req.plan.get("actions", [])) if req.plan else 0)
    final_title = (saved_wf.get("title") if saved_wf else None) or (saved_wf.get("name") if saved_wf else None) or user_title or "Untitled Workflow"

    print(f"\n==================================================")
    print(f"[STORAGE] Created/Saved workflow")
    print(f"[STORAGE] workflow_id = {wf_id}")
    print(f"[STORAGE] title = {final_title}")
    print(f"[STORAGE] version = {version}")
    print(f"[STORAGE] actions = {actions_count}")
    print(f"==================================================")

    return {
        "success": True,
        "workflow_id": wf_id,
        "id": wf_id,
        "title": final_title,
        "name": final_title,
        "recording_id": rec_id,
        "version": version,
        "saved": True,
        "action_count": actions_count,
        "message": "Workflow saved successfully"
    }


@app.post("/api/workflows/discard")
def discard_workflow_endpoint(req: DiscardRequest):
    if req.workflow_id:
        db.delete_workflow(req.workflow_id)
    return {"message": "Workflow discarded"}


@app.get("/api/workflows/{workflow_id}/versions")
def get_versions(workflow_id: int):
    versions = db.get_workflow_versions(workflow_id)
    return {"workflow_id": workflow_id, "versions": versions}


@app.post("/api/workflows/restore-version")
def restore_version(req: RestoreVersionRequest):
    res = wf_engine.restore_version(req.workflow_id, req.target_version)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.delete("/api/workflows")
def delete_all_workflows_endpoint(saved_only: bool = True):
    deleted_count = db.delete_all_workflows(saved_only=saved_only)
    return {"message": "All saved workflows deleted successfully", "deleted_count": deleted_count}


@app.delete("/api/workflows/{workflow_id}")
def delete_workflow_endpoint(workflow_id: int):
    success = db.delete_workflow(workflow_id)
    if not success:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"message": f"Workflow {workflow_id} deleted successfully"}


@app.get("/api/workflows/{workflow_id}/history")
def get_workflow_history_route(workflow_id: int):
    history = db.get_workflow_execution_history(workflow_id)
    return {"workflow_id": workflow_id, "history": history}




# 4. Dry Run & Execution
@app.post("/api/workflows/dry-run")
def dry_run(req: DryRunRequest):
    mode = req.mode or "sandbox"
    if req.workflow_id:
        wf = db.get_workflow(req.workflow_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        preview = wf_engine.dry_run_workflow(wf, mode=mode)
    elif req.plan:
        preview = wf_engine.dry_run_workflow(req.plan, mode=mode)
    else:
        raise HTTPException(status_code=400, detail="Provide either workflow_id or plan")
    return {"preview": preview}


def prepare_and_validate_execution(req: ExecuteRequest):
    wf_id = req.workflow_id
    if not wf_id and req.plan:
        wf_id = req.plan.get("id") or req.plan.get("workflow_id")

    executor_mode = (req.mode or "REAL").strip().upper()
    ui_mode = (req.ui_mode or req.mode or "REAL").strip().upper()
    requested_mode = (req.requested_mode or req.mode or "REAL").strip().upper()

    print(f"\n[API] REQUEST execution_id={req.execution_id} workflow_id={wf_id}")
    print(f"[API] Received execution request")
    print(f"[API] Workflow ID = {wf_id} | Execution ID = {req.execution_id}")
    print(f"[MODE] UI = {ui_mode}")
    print(f"[MODE] REQUEST = {requested_mode}")
    print(f"[MODE] EXECUTOR = {executor_mode}")

    # Requirement 4 & 12: Real/Sandbox mode single source of truth verification
    if not (ui_mode == requested_mode == executor_mode):
        error_msg = f"Execution mode mismatch: UI={ui_mode}, REQUEST={requested_mode}, EXECUTOR={executor_mode}"
        print(f"[MODE ERROR] {error_msg}")
        return None, None, {
            "status": "FAILED",
            "mode": executor_mode,
            "workflow_id": wf_id,
            "execution_id": req.execution_id,
            "total_steps": 0,
            "completed_steps": 0,
            "failed_step": 1,
            "verified": False,
            "verification": False,
            "error": error_msg,
            "result": {
                "status": "FAILED",
                "mode": executor_mode,
                "workflow_id": wf_id,
                "execution_id": req.execution_id,
                "success": False,
                "verification": False,
                "error": error_msg
            }
        }

    wf = None
    if wf_id and isinstance(wf_id, int) and wf_id > 0:
        wf = db.get_workflow(wf_id)
        if not wf and not req.plan:
            error_msg = f"Workflow ID {wf_id} could not be loaded from storage. Fallback execution is prohibited."
            print(f"[ERROR] {error_msg}")
            return None, None, {
                "status": "FAILED",
                "mode": executor_mode,
                "workflow_id": wf_id,
                "execution_id": req.execution_id,
                "total_steps": 0,
                "completed_steps": 0,
                "failed_step": 1,
                "verified": False,
                "verification": False,
                "error": error_msg,
                "result": {
                    "status": "FAILED",
                    "mode": executor_mode,
                    "workflow_id": wf_id,
                    "execution_id": req.execution_id,
                    "success": False,
                    "verification": False,
                    "error": error_msg
                }
            }

    if not wf and req.plan:
        wf = req.plan
        wf_id = req.plan.get("id") or req.plan.get("workflow_id")

    if not wf and req.actions:
        wf = {"id": None, "name": "Dynamic Workflow", "actions": req.actions}

    if not wf:
        error_msg = "Missing workflow_id or plan for execution."
        print(f"[ERROR] {error_msg}")
        return None, None, {
            "status": "FAILED",
            "mode": executor_mode,
            "workflow_id": wf_id,
            "execution_id": req.execution_id,
            "total_steps": 0,
            "completed_steps": 0,
            "failed_step": 1,
            "verified": False,
            "verification": False,
            "error": error_msg,
            "result": {
                "status": "FAILED",
                "mode": executor_mode,
                "workflow_id": wf_id,
                "execution_id": req.execution_id,
                "success": False,
                "verification": False,
                "error": error_msg
            }
        }

    actions = wf.get("actions", [])
    if req.actions and not actions:
        actions = req.actions
        wf["actions"] = actions

    rec_id = req.recording_id or (wf.get("metadata", {}).get("recording_id") if wf else None) or "UNKNOWN"
    ver_num = wf.get("version", 1) if wf else 1

    print(f"\n[API] Received execution request")
    print(f"[API] REQUEST execution_id={req.execution_id} workflow_id={wf_id}")
    print(f"[API] Workflow ID = {wf_id}")
    print(f"[API] recording_id = {rec_id}")
    print(f"[API] mode = {executor_mode}")
    print(f"[UI MODE] {ui_mode}")
    print(f"[REQUEST MODE] {requested_mode}")
    print(f"[EXECUTOR MODE] {executor_mode}")

    print(f"[WORKFLOW] Loaded workflow ID = {wf_id}")
    print(f"[WORKFLOW] Action count = {len(actions)}")

    print(f"\n[RUN]")
    print(f"[RUN] Requested Workflow ID = {wf_id}")
    print(f"[RUN] Loaded workflow ID = {wf_id}")
    print(f"[RUN] Recording ID = {rec_id}")
    print(f"[RUN] Action count = {len(actions)}")
    print(f"[RUN] Loaded actions = {len(actions)}")
    print(f"workflow_id = {wf_id}")
    print(f"version = {ver_num}")
    print(f"recording_id = {rec_id}")
    print(f"action_count = {len(actions)}")

    print(f"[EXECUTOR] Selected executor = {executor_mode}")
    print(f"[EXECUTOR] Action count = {len(actions)}")
    print(f"[EXECUTOR] Received actions = {len(actions)}")

    for s_idx, act in enumerate(actions, start=1):
        step_lbl = act.get("label") or act.get("type")
        p_info = act.get("params") or {}
        tgt_val = act.get("target") or p_info.get("app") or p_info.get("path") or p_info.get("file") or p_info.get("target") or step_lbl
        print(f"[RUN] Step {s_idx} = {act.get('type')}")
        print(f"[RUN] Step {s_idx} = {step_lbl} (type: {act.get('type')}, target: {tgt_val})")

    if req.expected_action_count is not None and len(actions) != req.expected_action_count:
        error_msg = f"Action count mismatch: saved has {len(actions)}, expected {req.expected_action_count}"
        print(f"[ERROR] {error_msg}")
        return None, None, {
            "status": "FAILED",
            "mode": executor_mode,
            "workflow_id": wf_id,
            "execution_id": req.execution_id,
            "total_steps": len(actions),
            "completed_steps": 0,
            "failed_step": 1,
            "verified": False,
            "verification": False,
            "error": error_msg,
            "result": {
                "status": "FAILED",
                "mode": executor_mode,
                "workflow_id": wf_id,
                "execution_id": req.execution_id,
                "success": False,
                "verification": False,
                "error": error_msg
            }
        }

    # High-Risk Action & Observed Action Safety Checks
    for s_idx, act in enumerate(actions, start=1):
        act_type = (act.get("type") or act.get("action_type") or "").upper()
        if act_type in ("DELETE_FILE", "DELETE"):
            evidence_ids = act.get("evidence_event_ids") or (act.get("params") or {}).get("evidence_event_ids")
            if not evidence_ids or len(evidence_ids) == 0:
                error_msg = "High-risk action has no valid demonstration evidence."
                print(f"[SECURITY ERROR] Step {s_idx} ({act_type}): {error_msg}")
                return None, None, {
                    "status": "FAILED",
                    "mode": executor_mode,
                    "workflow_id": wf_id,
                    "execution_id": req.execution_id,
                    "total_steps": len(actions),
                    "completed_steps": 0,
                    "failed_step": s_idx,
                    "verified": False,
                    "verification": False,
                    "error": error_msg,
                    "result": {
                        "status": "FAILED",
                        "mode": executor_mode,
                        "workflow_id": wf_id,
                        "execution_id": req.execution_id,
                        "success": False,
                        "verification": False,
                        "error": error_msg
                    }
                }
        elif act_type == "TYPE":
            text_val = (act.get("params") or {}).get("text") or act.get("text") or ""
            evidence_ids = act.get("evidence_event_ids") or (act.get("params") or {}).get("evidence_event_ids")
            if not text_val:
                error_msg = f"TYPE action at step {s_idx} has no text to type."
                print(f"[SECURITY ERROR] {error_msg}")
                return None, None, {
                    "status": "FAILED",
                    "mode": executor_mode,
                    "workflow_id": wf_id,
                    "execution_id": req.execution_id,
                    "total_steps": len(actions),
                    "completed_steps": 0,
                    "failed_step": s_idx,
                    "verified": False,
                    "verification": False,
                    "error": error_msg,
                    "result": {
                        "status": "FAILED",
                        "mode": executor_mode,
                        "workflow_id": wf_id,
                        "execution_id": req.execution_id,
                        "success": False,
                        "verification": False,
                        "error": error_msg
                    }
                }
            if req.source == "teach" and (not evidence_ids or len(evidence_ids) == 0):
                error_msg = f"TYPE action at step {s_idx} has no valid demonstration evidence."
                print(f"[SECURITY ERROR] {error_msg}")
                return None, None, {
                    "status": "FAILED",
                    "mode": executor_mode,
                    "workflow_id": wf_id,
                    "execution_id": req.execution_id,
                    "total_steps": len(actions),
                    "completed_steps": 0,
                    "failed_step": s_idx,
                    "verified": False,
                    "verification": False,
                    "error": error_msg,
                    "result": {
                        "status": "FAILED",
                        "mode": executor_mode,
                        "workflow_id": wf_id,
                        "execution_id": req.execution_id,
                        "success": False,
                        "verification": False,
                        "error": error_msg
                    }
                }

    if len(actions) == 0:
        error_msg = "Saved workflow contains no executable actions."
        print(f"[ERROR] {error_msg}")
        return None, None, {
            "status": "FAILED",
            "mode": executor_mode,
            "workflow_id": wf_id,
            "execution_id": req.execution_id,
            "total_steps": 0,
            "completed_steps": 0,
            "failed_step": 1,
            "verified": False,
            "verification": False,
            "error": error_msg,
            "result": {
                "status": "FAILED",
                "mode": executor_mode,
                "workflow_id": wf_id,
                "execution_id": req.execution_id,
                "success": False,
                "verification": False,
                "error": error_msg
            }
        }

    return wf, actions, None


@app.post("/api/workflows/execute")
def execute_workflow(req: ExecuteRequest):
    wf, actions, error_res = prepare_and_validate_execution(req)
    executor_mode = (req.mode or "REAL").strip().upper()
    wf_id = req.workflow_id or (wf.get("id") if wf else None)

    print(f"\n[API REQUEST] endpoint = /api/workflows/execute")
    print(f"[API REQUEST] workflow_id = {wf_id}")
    print(f"[API REQUEST] execution_id = {req.execution_id}")
    print(f"[API REQUEST] mode = {executor_mode}")

    if error_res:
        print(f"[API RESPONSE] status = FAILED")
        print(f"[API RESPONSE] content_type = application/json")
        print(f"[API RESPONSE] body_type = dict")
        error_res["success"] = False
        return JSONResponse(content=make_json_safe(error_res))

    if req.source == "teach" or executor_mode == "REAL":
        print("\n==================================================")
        print("[TEACH] Permission granted")
        print(f"[TEACH] Workflow ID = {wf_id}")
        print(f"[TEACH] Target Mode = {executor_mode}")
        print(f"[TEACH] Actions = {len(actions)}")
        print("[TEACH] Sending workflow to REAL executor")
        print("==================================================")

    try:
        res = wf_engine.execute_workflow(
            workflow_id=wf_id,
            confirmed_medium=req.confirmed_medium,
            confirmed_high=req.confirmed_high,
            mode=executor_mode,
            actions=actions,
            wf_dict=wf,
            execution_id=req.execution_id
        )
    except Exception as exc:
        print(f"[API RESPONSE] status = FAILED")
        print(f"[API RESPONSE] content_type = application/json")
        print(f"[API RESPONSE] exception = {exc}", file=sys.stderr)
        return JSONResponse(
            status_code=500,
            content=make_json_safe({
                "success": False,
                "status": "FAILED",
                "mode": executor_mode,
                "workflow_id": wf_id,
                "execution_id": req.execution_id,
                "error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc)
                },
                "detail": str(exc)
            })
        )

    status_val = res.get("status", "SUCCESS" if res.get("success") else "FAILED")
    print(f"[API] Returning execution result = {status_val}")
    print(f"[API RESPONSE] status = {status_val}")
    print(f"[API RESPONSE] content_type = application/json")
    print(f"[API RESPONSE] body_type = dict")
    verified_bool = res.get("verification", res.get("success", False))
    success_bool = res.get("success", str(status_val).upper() in ("SUCCESS", "COMPLETED"))

    out_data = {
        "success": success_bool,
        "status": status_val,
        "mode": executor_mode,
        "workflow_id": wf_id,
        "execution_id": res.get("execution_id"),
        "workflow_execution_count": res.get("workflow_execution_count", 1),
        "executions_performed": res.get("executions_performed", 1),
        "workflow_action_count": res.get("workflow_action_count", len(actions)),
        "workflow_internal_iterations": res.get("workflow_internal_iterations", 0),
        "completed_steps": res.get("completed_steps", 0),
        "total_steps": res.get("total_steps", len(actions)),
        "failed_step": res.get("failed_step"),
        "error": res.get("error"),
        "verified": verified_bool,
        "verification": verified_bool,
        "result": res
    }
    return JSONResponse(content=make_json_safe(out_data))


@app.post("/api/workflows/execute-stream")
async def execute_workflow_stream(req: ExecuteRequest):
    import queue
    import threading
    import asyncio

    wf, actions, error_res = prepare_and_validate_execution(req)
    executor_mode = (req.mode or "REAL").strip().upper()
    wf_id = req.workflow_id or (wf.get("id") if wf else None)

    print(f"\n[API REQUEST] endpoint = /api/workflows/execute-stream")
    print(f"[API REQUEST] workflow_id = {wf_id}")
    print(f"[API REQUEST] execution_id = {req.execution_id}")
    print(f"[API REQUEST] mode = {executor_mode}")

    if error_res:
        print(f"[API RESPONSE] status = FAILED")
        print(f"[API RESPONSE] content_type = application/x-ndjson")
        print(f"[API RESPONSE] body_type = stream")
        error_res["success"] = False
        async def err_gen():
            yield json.dumps(make_json_safe({
                "event": "failed",
                "status": "FAILED",
                "success": False,
                "mode": executor_mode,
                "workflow_id": req.workflow_id,
                "execution_id": req.execution_id,
                "completed_steps": 0,
                "total_steps": 0,
                "failed_step": 1,
                "verified": False,
                "verification": False,
                "error": error_res.get("error"),
                "result": error_res.get("result")
            })) + "\n"
        return StreamingResponse(err_gen(), media_type="application/x-ndjson")

    if req.source == "teach" or executor_mode == "REAL":
        print("\n==================================================")
        print("[TEACH] Permission granted")
        print(f"[TEACH] Workflow ID = {wf_id}")
        print(f"[TEACH] Target Mode = {executor_mode}")
        print(f"[TEACH] Actions = {len(actions)}")
        print("[TEACH] Sending workflow to REAL executor")
        print("==================================================")

    ev_queue = queue.Queue()

    def progress_callback(data):
        ev_queue.put(make_json_safe(data))

    def run_worker():
        try:
            res = wf_engine.execute_workflow(
                workflow_id=wf_id,
                confirmed_medium=req.confirmed_medium,
                confirmed_high=req.confirmed_high,
                mode=executor_mode,
                actions=actions,
                wf_dict=wf,
                progress_callback=progress_callback,
                execution_id=req.execution_id
            )
            status_val = res.get("status", "SUCCESS" if res.get("success") else "FAILED")
            print(f"[API RESPONSE] status = {status_val}")
            print(f"[API RESPONSE] content_type = application/x-ndjson")
            print(f"[API RESPONSE] body_type = stream")
            verified_bool = res.get("verification", res.get("success", False))
            success_bool = res.get("success", str(status_val).upper() in ("SUCCESS", "COMPLETED"))
            ev_queue.put(make_json_safe({
                "event": "completed" if success_bool else "failed",
                "status": status_val,
                "success": success_bool,
                "mode": executor_mode,
                "workflow_id": wf_id,
                "execution_id": res.get("execution_id"),
                "workflow_execution_count": res.get("workflow_execution_count", 1),
                "executions_performed": res.get("executions_performed", 1),
                "workflow_action_count": res.get("workflow_action_count", len(actions)),
                "workflow_internal_iterations": res.get("workflow_internal_iterations", 0),
                "completed_steps": res.get("completed_steps", 0),
                "total_steps": res.get("total_steps", len(actions)),
                "failed_step": res.get("failed_step"),
                "error": res.get("error"),
                "verified": verified_bool,
                "verification": verified_bool,
                "result": res
            }))
        except Exception as e:
            print(f"[API RESPONSE] status = FAILED")
            print(f"[API RESPONSE] exception = {e}", file=sys.stderr)
            ev_queue.put(make_json_safe({
                "event": "failed",
                "status": "FAILED",
                "success": False,
                "mode": executor_mode,
                "workflow_id": wf_id,
                "execution_id": req.execution_id,
                "completed_steps": 0,
                "total_steps": len(actions),
                "failed_step": 1,
                "verified": False,
                "verification": False,
                "error": str(e),
                "result": {
                    "status": "FAILED",
                    "mode": executor_mode,
                    "workflow_id": wf_id,
                    "execution_id": req.execution_id,
                    "success": False,
                    "verification": False,
                    "error": str(e)
                }
            }))
        finally:
            ev_queue.put(None)

    worker_thread = threading.Thread(target=run_worker, daemon=True)
    worker_thread.start()

    async def event_generator():
        while True:
            try:
                item = ev_queue.get_nowait()
                if item is None:
                    break
                yield json.dumps(make_json_safe(item)) + "\n"
            except queue.Empty:
                await asyncio.sleep(0.04)

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


# 5. Evolution Engine
@app.post("/api/evolution/apply")
def apply_evolution(req: EvolutionApplyRequest):
    res = wf_engine.evolve_workflow(
        workflow_id=req.workflow_id,
        new_actions=req.new_actions,
        change_reason=req.change_reason or "Demonstrated workflow update"
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


# 6. User Corrections
@app.post("/api/corrections")
def submit_correction(req: CorrectionRequest):
    res = wf_engine.record_user_correction(
        workflow_id=req.workflow_id,
        execution_id=req.execution_id,
        feedback_text=req.feedback_text,
        original_action=req.original_action,
        corrected_action=req.corrected_action,
        remember=req.remember
    )
    return res


# 7. Activity Log
@app.get("/api/activity")
def get_activity():
    events = db.get_recent_activity(50)
    return {"activity": events}


# 8. Settings & Sandbox
@app.get("/api/settings")
def get_settings():
    return {"settings": db.get_all_settings()}


@app.post("/api/settings")
def update_settings(req: SettingsUpdateRequest):
    for k, v in req.settings.items():
        db.set_setting(k, v)
    return {"status": "updated", "settings": db.get_all_settings()}


@app.get("/api/sandbox/status")
def sandbox_status():
    wf_engine.setup_sandbox_environment()
    tree = {}
    if SANDBOX_DIR.exists():
        for root, dirs, files in os.walk(SANDBOX_DIR):
            rel_dir = os.path.relpath(root, str(SANDBOX_DIR))
            if rel_dir == ".":
                rel_dir = "root"
            if ".trash" in rel_dir:
                continue
            tree[rel_dir] = files
    return {"sandbox_path": str(SANDBOX_DIR), "tree": tree}


@app.post("/api/sandbox/reset")
def sandbox_reset():
    if SANDBOX_DIR.exists():
        try:
            shutil.rmtree(SANDBOX_DIR)
        except Exception:
            pass
    info = wf_engine.setup_sandbox_environment()
    return {"message": "Sandbox environment reset to default demo state", "info": info}


# ---------------- Frontend Web Application ----------------

HTML_PAGE = None

# Frontend UI served static files via frontend/ directory




@app.get("/")
def index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>WorkFlowOS API Server</h1>")


@app.get("/styles.css")
def serve_css():
    css_file = FRONTEND_DIR / "styles.css"
    if css_file.exists():
        return FileResponse(css_file, media_type="text/css")
    raise HTTPException(status_code=404, detail="styles.css not found")


@app.get("/app.js")
def serve_js():
    js_file = FRONTEND_DIR / "app.js"
    if js_file.exists():
        return FileResponse(js_file, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="app.js not found")



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"\n=======================================================")
    print(f"  WorkFlowOS – AI-Powered Desktop Workflow Automation")
    print(f"  Local Web Interface running at: http://127.0.0.1:{port}")
    print(f"=======================================================\n")
    uvicorn.run("app:app", host="127.0.0.1", port=port, reload=False)
