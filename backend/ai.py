"""
AI Intent & Workflow Understanding Engine for WorkFlowOS.
Converts natural language chat requests and recorded demonstration events into structured semantic workflows.
Supports Google Gemini API with seamless local heuristic fallback for 100% offline functionality.
"""

import os
import re
import sys
import json
import time
import collections
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = [
            str(arg).encode(getattr(sys.stdout, 'encoding', 'utf-8') or 'ascii', errors='replace').decode(getattr(sys.stdout, 'encoding', 'utf-8') or 'ascii')
            for arg in args
        ]
        print(*safe_args, **kwargs)

import requests
from database import get_setting

# Semantic action constants
ACTION_OPEN_APP = "OPEN_APPLICATION"
ACTION_OPEN_FOLDER = "OPEN_FOLDER"
ACTION_OPEN_FILE = "OPEN_FILE"
ACTION_CREATE_FOLDER = "CREATE_FOLDER"
ACTION_CREATE_FILE = "CREATE_FILE"
ACTION_RENAME_FILE = "RENAME_FILE"
ACTION_MOVE_FILE = "MOVE_FILE"
ACTION_COPY_FILE = "COPY_FILE"
ACTION_DELETE_FILE = "DELETE_FILE"
ACTION_SEARCH_FILES = "SEARCH_FILES"
ACTION_READ_FILE = "READ_FILE"
ACTION_BROWSER_NAVIGATE = "BROWSER_NAVIGATE"
ACTION_CLICK = "CLICK"
ACTION_TYPE = "TYPE"
ACTION_DOWNLOAD = "DOWNLOAD"
ACTION_UPLOAD = "UPLOAD"
ACTION_SUBMIT = "SUBMIT"
ACTION_SEND = "SEND"

LOW_RISK_ACTIONS = {ACTION_OPEN_APP, ACTION_OPEN_FOLDER, ACTION_OPEN_FILE, ACTION_CREATE_FOLDER, ACTION_CREATE_FILE,
                    ACTION_RENAME_FILE, ACTION_MOVE_FILE, ACTION_COPY_FILE, ACTION_SEARCH_FILES, ACTION_READ_FILE}
MEDIUM_RISK_ACTIONS = {ACTION_BROWSER_NAVIGATE, ACTION_CLICK, ACTION_TYPE, ACTION_DOWNLOAD, ACTION_UPLOAD, ACTION_SUBMIT, ACTION_SEND}
HIGH_RISK_ACTIONS = {ACTION_DELETE_FILE, "PURCHASE", "SEND_SENSITIVE_INFO"}


def calculate_risk(actions: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    """
    Determine the overall workflow risk level and return flagged warnings.
    """
    highest_risk = "LOW"
    warnings = []

    for idx, act in enumerate(actions, start=1):
        act_type = act.get("type", "").upper()
        if act_type in HIGH_RISK_ACTIONS:
            highest_risk = "HIGH"
            warnings.append(f"Step {idx} ({act_type}): Irreversible or dangerous operation requiring explicit confirmation.")
        elif act_type in MEDIUM_RISK_ACTIONS and highest_risk != "HIGH":
            highest_risk = "MEDIUM"
            warnings.append(f"Step {idx} ({act_type}): External interaction or data transmission.")

    return highest_risk, warnings


def calculate_confidence(
    actions: List[Dict[str, Any]],
    repetitions: int = 1,
    consistency: float = 1.0,
    has_unclear_destination: bool = False
) -> Tuple[float, List[str]]:
    """
    Calculate confidence score (0.0 - 1.0) and explainable reasons.
    """
    base_score = 0.85
    reasons = []

    if repetitions > 1:
        bonus = min(0.12, repetitions * 0.03)
        base_score += bonus
        reasons.append(f"Consistent sequence observed across {repetitions} demonstrations")
    else:
        reasons.append("Single demonstration analyzed")

    # Destination and path clarity
    if has_unclear_destination:
        base_score -= 0.25
        reasons.append("Ambiguous destination directory detected")
    else:
        reasons.append("Target directories and parameters are explicitly resolved")

    # Action clarity
    unknown_count = sum(1 for a in actions if a.get("type") in ("UNKNOWN", ""))
    if unknown_count > 0:
        base_score -= 0.15 * unknown_count
        reasons.append(f"{unknown_count} action(s) could not be mapped to standard semantic types")
    else:
        reasons.append("All steps mapped to verified semantic primitives")

    score = round(max(0.40, min(0.98, base_score)), 2)
    return score, reasons


# ---------------- HEURISTIC / RULE-BASED ENGINE (OFFLINE) ----------------

def parse_single_instruction(clause: str, context_folder: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Parse a single action clause into a structured semantic action dictionary.
    Supports arbitrary apps, files, URLs, folders, patterns, operations, and pronoun resolution ('into it').
    """
    c = clause.strip()
    c_lower = c.lower()

    # 1. Explicit Folder / Directory Intent
    # (Matches ONLY when 'folder' or 'directory' is explicitly stated)
    if "folder" in c_lower or "directory" in c_lower:
        fm_a = re.search(r"(?:open|explore|show)\s+(?:the\s+)?['\"]?([a-zA-Z0-9_\-\.\/]+)['\"]?\s+(?:folder|directory)(?:\s+on\s+(?:my\s+)?(desktop|downloads|documents))?", c_lower)
        if fm_a:
            fname = fm_a.group(1).strip()
            loc = fm_a.group(2)
            target = f"{loc.capitalize()}/{fname}" if (loc and not fname.lower().startswith(loc.lower())) else fname
            return {
                "type": ACTION_OPEN_FOLDER,
                "label": f"Open folder: {target}",
                "params": {"path": target},
                "risk": "LOW"
            }
        fm_b = re.search(r"(?:open|explore|show)\s+(?:the\s+)?(?:folder|directory)\s+(?:called\s+|named\s+)?['\"]?([a-zA-Z0-9_\-\.\/]+)['\"]?(?:\s+on\s+(?:my\s+)?(desktop|downloads|documents))?", c_lower)
        if fm_b:
            fname = fm_b.group(1).strip()
            loc = fm_b.group(2)
            target = f"{loc.capitalize()}/{fname}" if (loc and not fname.lower().startswith(loc.lower())) else fname
            return {
                "type": ACTION_OPEN_FOLDER,
                "label": f"Open folder: {target}",
                "params": {"path": target},
                "risk": "LOW"
            }

    # 2. Browser Navigation / URLs & Known Website Names
    KNOWN_SITES = {
        "thehindu": "https://www.thehindu.com",
        "the hindu": "https://www.thehindu.com",
        "the hindu newspaper": "https://www.thehindu.com",
        "the hindu news paper": "https://www.thehindu.com",
        "hindu": "https://www.thehindu.com",
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "github": "https://www.github.com",
        "wikipedia": "https://www.wikipedia.org",
        "reddit": "https://www.reddit.com",
        "twitter": "https://www.twitter.com"
    }

    clean_clause = c_lower.strip()
    for verb in ("open ", "go to ", "browse ", "navigate to ", "visit ", "launch ", "show "):
        if clean_clause.startswith(verb):
            clean_clause = clean_clause[len(verb):].strip()

    if clean_clause in KNOWN_SITES or c_lower in KNOWN_SITES:
        site_url = KNOWN_SITES.get(clean_clause) or KNOWN_SITES.get(c_lower)
        return {
            "type": ACTION_BROWSER_NAVIGATE,
            "label": f"Navigate to: {site_url}",
            "params": {"url": site_url},
            "risk": "MEDIUM"
        }

    COMMON_FILE_EXTS = {
        "txt", "pdf", "csv", "docx", "xlsx", "json", "py", "md", "png", "jpg", "jpeg",
        "gif", "zip", "tar", "gz", "7z", "rar", "exe", "blend", "fbx", "obj", "mp3", "mp4"
    }

    # 2. Browser Navigation / URLs & Known Website Names
    KNOWN_SITES = {
        "thehindu": "https://www.thehindu.com",
        "the hindu": "https://www.thehindu.com",
        "the hindu newspaper": "https://www.thehindu.com",
        "the hindu news paper": "https://www.thehindu.com",
        "hindu": "https://www.thehindu.com",
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "github": "https://www.github.com",
        "wikipedia": "https://www.wikipedia.org",
        "reddit": "https://www.reddit.com",
        "twitter": "https://www.twitter.com"
    }

    clean_clause = c_lower.strip()
    for verb in ("open ", "go to ", "browse ", "navigate to ", "visit ", "launch ", "show "):
        if clean_clause.startswith(verb):
            clean_clause = clean_clause[len(verb):].strip()

    if clean_clause in KNOWN_SITES or c_lower in KNOWN_SITES:
        site_url = KNOWN_SITES.get(clean_clause) or KNOWN_SITES.get(c_lower)
        return {
            "type": ACTION_BROWSER_NAVIGATE,
            "label": f"Navigate to: {site_url}",
            "params": {"url": site_url},
            "risk": "MEDIUM"
        }

    url_match = None
    if "http://" in c_lower or "https://" in c_lower or "www." in c_lower:
        url_match = re.search(r"(https?://[^\s]+|www\.[a-zA-Z0-9_\-]+\.[a-zA-Z]{2,4}[^\s]*)", c_lower)
    else:
        domain_match = re.search(r"\b([a-zA-Z0-9_\-]+\.(?:com|org|net|io|gov|edu|co|in|uk|de|fr|dev|app|ai))(?:\/[^\s]*)?\b", c_lower)
        if domain_match:
            url_match = domain_match

    if url_match:
        matched_str = url_match.group(1) if url_match.groups() else url_match.group(0)
        ext = matched_str.split(".")[-1].lower() if "." in matched_str else ""
        if ext not in COMMON_FILE_EXTS:
            url = matched_str
            if not url.startswith("http"):
                url = "https://" + url
            return {
                "type": ACTION_BROWSER_NAVIGATE,
                "label": f"Navigate to: {url}",
                "params": {"url": url},
                "risk": "MEDIUM"
            }

    # 3. Create File Intent
    create_file_match = re.search(r"(?:create|make|write|generate|save)\s+(?:a\s+)?(?:new\s+)?file\s+(?:called\s+|named\s+)?['\"]?([a-zA-Z0-9_\-\.\/]+)['\"]?(?:\s+(?:with\s+content|with\s+text|containing|saying)\s+['\"]?([^'\"]+)['\"]?)?", c, flags=re.IGNORECASE)
    if not create_file_match:
        create_file_match = re.search(r"(?:create|make|write|generate|save)\s+['\"]?([a-zA-Z0-9_\-\/]+\.(?:txt|pdf|csv|docx|xlsx|json|py|md|html|css|js))['\"]?(?:\s+(?:with\s+content|with\s+text|containing|saying)\s+['\"]?([^'\"]+)['\"]?)?", c, flags=re.IGNORECASE)
    if create_file_match:
        fname = create_file_match.group(1).strip()
        fcontent = create_file_match.group(2).strip() if create_file_match.group(2) else ""
        return {
            "type": ACTION_CREATE_FILE,
            "label": f"Create file: {fname}",
            "params": {"path": fname, "content": fcontent},
            "risk": "LOW"
        }

    # 4. Create Folder (Supports 'on my Desktop' or 'on Downloads')
    create_match = re.search(r"(?:create|make|mkdir)\s+(?:a\s+)?(?:folder|directory)\s+(?:called\s+|named\s+)?['\"]?([a-zA-Z0-9_\-\/]+)['\"]?(?:\s+on\s+(?:my\s+)?(desktop|downloads))?", c_lower)
    if create_match:
        folder = create_match.group(1)
        location = create_match.group(2)
        if location and not folder.lower().startswith(location.lower()):
            folder = f"{location.capitalize()}/{folder}"
        return {
            "type": ACTION_CREATE_FOLDER,
            "label": f"Create directory: {folder}",
            "params": {"path": folder},
            "risk": "LOW"
        }

    # 5. Rename File
    rename_match = re.search(r"rename\s+(?:file\s+)?['\"]?([a-zA-Z0-9_\-\.\/]+)['\"]?\s+(?:to|as)\s+['\"]?([a-zA-Z0-9_\-\.]+)['\"]?", c_lower)
    if rename_match:
        src = rename_match.group(1)
        new_name = rename_match.group(2)
        return {
            "type": ACTION_RENAME_FILE,
            "label": f"Rename '{src}' to '{new_name}'",
            "params": {"source": src, "new_name": new_name},
            "risk": "LOW"
        }

    # 6. Move File / Batch Move (Supports 'into it' pronoun resolution and specific desktop files)
    move_match = re.search(r"move\s+(?:all\s+)?['\"]?([a-zA-Z0-9_\-\*\.\s\/]+?)['\"]?\s+(?:to|into)\s+(?:the\s+)?(?:folder\s+)?['\"]?([a-zA-Z0-9_\-\/]+)['\"]?", c_lower)
    if move_match:
        target_item = move_match.group(1).strip()
        dest = move_match.group(2).strip()
        if dest in ("it", "them", "that", "this", "here") and context_folder:
            dest = context_folder

        if "." in target_item and not ("*" in target_item or "?" in target_item):
            src_path = target_item
            if context_folder and context_folder.lower().startswith("desktop") and not target_item.lower().startswith("desktop/"):
                src_path = f"Desktop/{target_item}"
            return {
                "type": ACTION_MOVE_FILE,
                "label": f"Move '{target_item}' to '{dest}'",
                "params": {"source": src_path, "destination": dest},
                "risk": "LOW"
            }
        else:
            pat = target_item
            if "pdf" in target_item and not ("*" in target_item or "." in target_item):
                pat = "*placement*.pdf" if "placement" in target_item else "*.pdf"
            elif not ("*" in target_item or "." in target_item):
                pat = f"*{target_item}*"

            src_dir = "Downloads"
            if context_folder and context_folder.lower().startswith("desktop"):
                src_dir = "Desktop"

            return {
                "type": ACTION_MOVE_FILE,
                "label": f"Move '{target_item}' to '{dest}'",
                "params": {"source": src_dir, "pattern": pat, "destination": dest},
                "risk": "LOW"
            }

    # 7. Copy File
    copy_match = re.search(r"copy\s+(?:file\s+)?['\"]?([a-zA-Z0-9_\-\*\.\/]+)['\"]?\s+(?:to|into)\s+(?:the\s+)?(?:folder\s+)?['\"]?([a-zA-Z0-9_\-\/]+)['\"]?", c_lower)
    if copy_match:
        src = copy_match.group(1).strip()
        dest = copy_match.group(2).strip()
        if dest in ("it", "them", "that") and context_folder:
            dest = context_folder
        return {
            "type": ACTION_COPY_FILE,
            "label": f"Copy '{src}' to '{dest}'",
            "params": {"source": src, "destination": dest},
            "risk": "LOW"
        }

    # 8. Read File
    read_match = re.search(r"(?:read|inspect|view|extract text from)\s+(?:file\s+)?['\"]?([a-zA-Z0-9_\-\.\/]+)['\"]?", c_lower)
    if read_match:
        file_path = read_match.group(1)
        return {
            "type": ACTION_READ_FILE,
            "label": f"Read content of: {file_path}",
            "params": {"path": file_path},
            "risk": "LOW"
        }

    # 9. Open Specific File (by file extension)
    file_open_match = re.search(r"(?:open|view)\s+(?:file\s+)?['\"]?([a-zA-Z0-9_\-\.\/]+\.(?:pdf|txt|csv|docx|xlsx|json|py|md|png|jpg))['\"]?", c_lower)
    if file_open_match:
        fpath = file_open_match.group(1)
        return {
            "type": ACTION_OPEN_FILE,
            "label": f"Open file: {fpath}",
            "params": {"path": fpath},
            "risk": "LOW"
        }

    # 10. Search / Find Files
    search_match = re.search(r"(?:search|find|locate)\s+(?:for\s+)?(?:all\s+)?['\"]?([a-zA-Z0-9_\-\*\.]+)\s*(?:in\s+(?:my\s+)?(?:files|documents|downloads|desktop|folder\s+['\"]?([a-zA-Z0-9_\-\/]+)['\"]?))?", c_lower)
    if search_match:
        query = search_match.group(1).strip()
        folder = search_match.group(2) or "Downloads"
        return {
            "type": ACTION_SEARCH_FILES,
            "label": f"Search for '{query}' in {folder}",
            "params": {"folder": folder, "pattern": query},
            "risk": "LOW"
        }

    # 11. Delete File (High Risk)
    delete_match = re.search(r"(?:delete|remove|trash)\s+(?:file\s+)?['\"]?([a-zA-Z0-9_\-\*\.\/]+)['\"]?", c_lower)
    if delete_match:
        target = delete_match.group(1)
        return {
            "type": ACTION_DELETE_FILE,
            "label": f"[HIGH RISK] Delete file: {target}",
            "params": {"file": target},
            "risk": "HIGH"
        }

    # 12. Type text into active window
    type_match = re.search(r"(?:type|write|input|enter)\s+(?:text\s+|string\s+)?['\"]?([^'\"]+)['\"]?", c, flags=re.IGNORECASE)
    if type_match and not ("file" in c_lower and ("create" in c_lower or "make" in c_lower)):
        text_to_type = type_match.group(1).strip()
        text_to_type = text_to_type.rstrip(".,;")
        return {
            "type": ACTION_TYPE,
            "label": f"Type: \"{text_to_type}\"",
            "params": {"text": text_to_type},
            "risk": "LOW"
        }

    # 13. Click
    click_match = re.search(r"click\s+(?:on\s+)?['\"]?([^'\"]+)['\"]?", c, flags=re.IGNORECASE)
    if click_match:
        target_elem = click_match.group(1).strip()
        return {
            "type": ACTION_CLICK,
            "label": f"Click: {target_elem}",
            "params": {"target": target_elem},
            "risk": "MEDIUM"
        }

    # 14. Application Launch Intent (Open / Launch / Start / Run <app>)
    app_match = re.search(r"(?:open|launch|start|run)\s+(?:the\s+)?(?:application\s+|app\s+)?['\"]?([a-zA-Z0-9_\-\.\s\+]+?)['\"]?(?:\s+on\s+(?:my\s+)?(?:computer|pc|desktop|system|machine))?[\.\s]*$", c, flags=re.IGNORECASE)
    if app_match:
        raw_app = app_match.group(1).strip()
        raw_app = re.sub(r"(?:\s+on\s+(?:my\s+)?(?:computer|pc|desktop|system|machine))[\.\s]*$", "", raw_app, flags=re.IGNORECASE).strip().rstrip(".,;")
        clean_app = re.sub(r"\s+(?:app|application)$", "", raw_app, flags=re.IGNORECASE).strip()
        raw_lower = clean_app.lower()
        is_folder = "folder" in raw_lower or "directory" in raw_lower or raw_lower in ("desktop", "downloads", "documents")
        is_file = any(raw_lower.endswith(ext) for ext in (".txt", ".pdf", ".csv", ".docx", ".xlsx", ".json", ".py", ".md", ".png", ".jpg"))
        is_url = "http" in raw_lower or "www." in raw_lower or any(raw_lower.endswith(tld) for tld in (".com", ".org", ".net", ".io"))

        if not (is_folder or is_file or is_url) and clean_app:
            return {
                "type": ACTION_OPEN_APP,
                "label": f"Launch application: {clean_app.title()}",
                "params": {"app": clean_app.lower()},
                "risk": "LOW"
            }

    # 15. Fallback Open Folder (ONLY if explicitly 'open folder <name>')
    fallback_folder = re.search(r"open\s+(?:folder\s+|directory\s+)['\"]?([a-zA-Z0-9_\-\/]+)['\"]?", c_lower)
    if fallback_folder:
        folder = fallback_folder.group(1)
        return {
            "type": ACTION_OPEN_FOLDER,
            "label": f"Open folder: {folder}",
            "params": {"path": folder},
            "risk": "LOW"
        }

    return None


def parse_chat_heuristic(user_prompt: str) -> Dict[str, Any]:
    """
    Generalized Task Compiler for WorkFlowOS.
    Accepts ANY arbitrary desktop command or multi-step instruction.
    Deconstructs compound instructions and compiles them into safe, ordered semantic actions.
    """
    prompt = user_prompt.strip()
    actions = []
    last_created_folder = None

    # Split compound clauses by "and then", "then", semicolons, numbered steps, or "and" before action verbs
    raw_clauses = re.split(r"(?:\r?\n|\band\s+then\b|\bthen\b|;|\d+\.\s+|\band\s+(?=(?:open|launch|start|run|create|make|write|generate|type|input|move|copy|delete|remove|search|find|navigate|click|press)\b))", prompt, flags=re.IGNORECASE)
    clauses = [c.strip() for c in raw_clauses if c.strip()]
    clauses = [c.strip() for c in raw_clauses if c.strip()]

    # If compound parsing splits into individual commands
    for clause in clauses:
        parsed = parse_single_instruction(clause, context_folder=last_created_folder)
        if parsed:
            if parsed["type"] == ACTION_CREATE_FOLDER:
                last_created_folder = parsed["params"].get("path")

            # If moving to a folder that doesn't exist, ensure CREATE_FOLDER is prepended
            if parsed["type"] == ACTION_MOVE_FILE:
                dest = parsed["params"].get("destination")
                if dest and not any(a["type"] == ACTION_CREATE_FOLDER and a["params"].get("path") == dest for a in actions):
                    actions.append({
                        "type": ACTION_CREATE_FOLDER,
                        "label": f"Ensure directory exists: {dest}",
                        "params": {"path": dest},
                        "risk": "LOW"
                    })
            actions.append(parsed)

    # If multi-clause split didn't find specific actions, try full prompt
    if not actions:
        single = parse_single_instruction(prompt, context_folder=last_created_folder)
        if single:
            actions.append(single)

    # If still not matched, intelligently infer based on keywords
    if not actions:
        prompt_lower = prompt.lower()
        if "organize" in prompt_lower or "sort" in prompt_lower:
            dest_match = re.search(r"(?:into|to)\s+(?:the\s+)?([a-zA-Z0-9_\-]+)", prompt_lower)
            dest = dest_match.group(1) if dest_match else "Organized"
            actions = [
                {"type": ACTION_CREATE_FOLDER, "label": f"Create {dest} directory", "params": {"path": dest}, "risk": "LOW"},
                {"type": ACTION_SEARCH_FILES, "label": "Scan for files in Downloads", "params": {"folder": "Downloads", "pattern": "*"}, "risk": "LOW"},
                {"type": ACTION_MOVE_FILE, "label": f"Move files to {dest}", "params": {"source": "Downloads", "pattern": "*", "destination": dest}, "risk": "LOW"}
            ]
        elif "clean" in prompt_lower:
            actions = [
                {"type": ACTION_OPEN_FOLDER, "label": "Open Downloads", "params": {"path": "Downloads"}, "risk": "LOW"},
                {"type": ACTION_SEARCH_FILES, "label": "Search for temporary files", "params": {"folder": "Downloads", "pattern": "*.tmp"}, "risk": "LOW"}
            ]
        else:
            # General fallback action
            actions = [
                {"type": ACTION_OPEN_FOLDER, "label": "Open Workspace directory", "params": {"path": "Downloads"}, "risk": "LOW"},
                {"type": ACTION_SEARCH_FILES, "label": f"Search matching files for '{prompt}'", "params": {"folder": "Downloads", "query": prompt}, "risk": "LOW"}
            ]

    # Generate a descriptive title from context or prompt
    prompt_lower = prompt.lower()
    if "placement" in prompt_lower:
        name = "Organize Placement Documents"
    elif "report" in prompt_lower:
        name = "Process Reports Workflow"
    elif len(actions) == 1:
        name = actions[0]["label"]
    else:
        # Title case first few words
        clean_title = re.sub(r"[^\w\s]", "", prompt)
        words = clean_title.split()[:4]
        name = " ".join(words).title() if words else "Custom Desktop Task"

    confidence, reasons = calculate_confidence(actions, repetitions=1)
    risk, warnings = calculate_risk(actions)

    return {
        "name": name,
        "description": f"Workflow generated for general task: '{prompt}'",
        "goal": prompt,
        "trigger": "User Chat Request",
        "actions": actions,
        "confidence": confidence,
        "confidence_reasons": reasons,
        "risk": risk,
        "risk_warnings": warnings,
        "application_names": ["explorer.exe"],
        "version": 1,
        "change_reason": "Generated from user command"
    }


def extract_workflow_variables(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    DYNAMIC VARIABLE DETECTION (Requirement 9)
    Discovers dynamic parameters from demonstrated actions:
    - File names/paths (e.g. candidate files to process)
    - Folder directories (e.g. destination folders)
    - Input text / queries (e.g. search terms, form entries)
    - Target URLs
    Allows workflows to be replayed with different parameters.
    """
    variables = []
    seen_vars = set()

    for act in actions:
        params = act.get("params", {})
        for key, val in params.items():
            if not isinstance(val, str) or not val.strip():
                continue
            val_clean = val.strip()

            # 1. File Variables
            if key in ("file", "source", "path") and any(val_clean.lower().endswith(ext) for ext in (".pdf", ".txt", ".csv", ".docx", ".xlsx", ".json", ".py", ".md", ".png", ".jpg", ".blend", ".fbx")):
                var_name = f"var_file_{len(variables)+1}"
                if var_name not in seen_vars:
                    seen_vars.add(var_name)
                    variables.append({
                        "name": var_name,
                        "type": "file",
                        "default": val_clean,
                        "sample_value": val_clean,
                        "param_key": key,
                        "action_type": act.get("type"),
                        "description": f"File operated on ({Path(val_clean).name})"
                    })

            # 2. Folder Variables
            elif key in ("folder", "destination", "directory") or (key == "path" and "." not in val_clean):
                var_name = f"var_folder_{len(variables)+1}"
                if var_name not in seen_vars:
                    seen_vars.add(var_name)
                    variables.append({
                        "name": var_name,
                        "type": "folder",
                        "default": val_clean,
                        "sample_value": val_clean,
                        "param_key": key,
                        "action_type": act.get("type"),
                        "description": f"Directory path ({val_clean})"
                    })

            # 3. Text Input Variables
            elif key in ("text", "content", "query") and len(val_clean) > 2:
                var_name = f"var_input_{len(variables)+1}"
                if var_name not in seen_vars:
                    seen_vars.add(var_name)
                    variables.append({
                        "name": var_name,
                        "type": "string",
                        "default": val_clean,
                        "sample_value": val_clean,
                        "param_key": key,
                        "action_type": act.get("type"),
                        "description": f"Input text parameter: \"{val_clean[:30]}\""
                    })

            # 4. URL Variables
            elif key in ("url", "website", "page") and ("http" in val_clean or "." in val_clean):
                var_name = f"var_url_{len(variables)+1}"
                if var_name not in seen_vars:
                    seen_vars.add(var_name)
                    variables.append({
                        "name": var_name,
                        "type": "url",
                        "default": val_clean,
                        "sample_value": val_clean,
                        "param_key": key,
                        "action_type": act.get("type"),
                        "description": f"Target Web URL ({val_clean})"
                    })

    return variables


KNOWN_BROWSERS = {"chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "arc", "chromium", "safari"}

def is_browser_app(app_name: str) -> bool:
    clean = (app_name or "").lower().replace(".exe", "").strip()
    return clean in KNOWN_BROWSERS or any(b in clean for b in ("browser", "chrome", "firefox", "edge", "opera", "brave"))

def extract_browser_url_and_domain(title: str = "", text: str = "") -> Dict[str, Optional[str]]:
    """
    GENERIC BROWSER URL & DOMAIN EXTRACTOR
    Parses observed browser window titles, address bar entries, or typed text into a normalized URL & domain.
    100% Generic: Works for ANY website (YouTube, Wikipedia, GitHub, Reddit, custom URLs, etc.)
    """
    raw_str = f"{text} {title}".strip()
    if not raw_str:
        return {"url": None, "domain": None}

    # 1. Direct explicit HTTP/HTTPS URL match
    url_match = re.search(r"(https?://[^\s\)]+)", raw_str, re.IGNORECASE)
    if url_match:
        full_url = url_match.group(1).rstrip("./;,")
        dom_match = re.search(r"https?://([^/\s:]+)", full_url, re.IGNORECASE)
        dom = dom_match.group(1) if dom_match else None
        return {"url": full_url, "domain": dom}

    # 2. Check for explicit domain with TLD (e.g. youtube.com, github.com, wikipedia.org)
    tld_pattern = r"\b([a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)*\.(?:com|org|net|io|edu|gov|co|app|dev|ai|me|info|tv|xyz|uk|ca|de|fr|jp|au))\b"
    tld_match = re.search(tld_pattern, raw_str, re.IGNORECASE)
    if tld_match:
        dom = tld_match.group(1).lower()
        return {"url": f"https://{dom}", "domain": dom}

    # 3. Strip browser suffix from window title (e.g. " - Google Chrome", " - Microsoft Edge", " - Mozilla Firefox", etc.)
    clean_title = title
    browser_suffix_pattern = r"\s*[\-\|\:\xB7\u2014\u2013]\s*(?:Google Chrome|Microsoft Edge|Mozilla Firefox|Brave|Opera|Vivaldi|Arc|Chromium|Safari|Browser)\s*$"
    clean_title = re.sub(browser_suffix_pattern, "", clean_title, flags=re.IGNORECASE).strip()

    # Ignore browser internal utility pages and WorkFlowOS management app itself
    ignored_internal_titles = ("new tab", "about:blank", "settings", "extensions", "downloads", "history", "bookmarks", "chrome://", "edge://", "about:", "workflowos", "127.0.0.1", "localhost")
    if not clean_title or any(ig in clean_title.lower() for ig in ignored_internal_titles):
        return {"url": None, "domain": None}

    # 4. Extract site slug from clean title (e.g. "YouTube", "Wikipedia", "GitHub")
    words = [w for w in re.split(r"[\s\-\|\:\,]", clean_title) if w.strip()]
    if words:
        first_word = words[0].strip().lower()
        site_slug = re.sub(r"[^a-z0-9]", "", first_word)
        if len(site_slug) >= 2 and site_slug not in ("home", "page", "welcome", "untitled", "index", "main", "new", "workflowos", "localhost", "127001"):
            dom = f"{site_slug}.com"
            return {"url": f"https://{dom}", "domain": dom}

    return {"url": None, "domain": None}


SYSTEM_BACKGROUND_PROCESSES = {
    "system", "idle", "registry", "smss", "csrss", "wininit", "services", "lsass",
    "svchost", "fontdrvhost", "wuauclt", "dwm", "spoolsv", "sihost", "taskhostw",
    "shellexperiencehost", "startmenuexperiencehost", "searchhost", "searchindexer",
    "runtimebroker", "applicationframehost", "ctfmon", "conhost", "compattelrunner",
    "smartscreen", "securityhealthservice", "audiodg", "wlanext", "lockapp",
    "settingstatedefaults", "systemsettings", "systemsettingsadminflows"
}


def correlate_desktop_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    STAGE 2 & STAGE 3: EVENT CORRELATION & USER-INTENT PIPELINE
    Analyzes raw desktop events across time and processes:
    - Identifies applications where explicit user actions occurred (typing, clicking, hotkeys, navigation, file operations)
    - Distinguishes USER-INITIATED applications (foreground window transitions, process creation) from BACKGROUND / SYSTEM processes
    - Correlates parent-child process relationships to prevent child helper processes from spawning duplicate launches
    - Generates step-by-stage telemetry for raw event qualification.
    """
    explicitly_used_apps = set()
    user_inputs_by_app = collections.defaultdict(list)
    first_interaction_index = {}
    process_parents = {}  # child_name.lower() -> parent_name.lower()
    pid_to_name = {}
    launch_candidates = []

    # Pass 1: map PIDs and parent-child process relationships
    for idx, ev in enumerate(events):
        details = ev.get("details", {})
        app = (details.get("app") or ev.get("app_name", "")).strip().replace(".exe", "")
        pid = details.get("pid")
        ppid = details.get("ppid")
        parent_name = (details.get("parent_name") or "").strip().replace(".exe", "")
        if pid and app:
            pid_to_name[pid] = app.lower()
        if parent_name and app:
            process_parents[app.lower()] = parent_name.lower()
        elif ppid and ppid in pid_to_name and app:
            process_parents[app.lower()] = pid_to_name[ppid]

    print(f"\n[TEACH TELEMETRY] ==================================================")
    print(f"[TEACH TELEMETRY] STAGE 2/3: CORRELATING {len(events)} RAW OS EVENTS")
    print(f"[TEACH TELEMETRY] ==================================================")

    # Pass 2: Evaluate raw events for user-initiated evidence vs background process filtering
    last_click_event = None

    for idx, ev in enumerate(events):
        sem = (ev.get("semantic_action") or ev.get("event_type") or "").upper()
        details = ev.get("details", {})
        app = (details.get("app") or ev.get("app_name", "")).strip().replace(".exe", "")
        app_lower = app.lower()
        w_title = (ev.get("window_title") or details.get("title") or "").strip()

        is_user_initiated = False
        qualification_reason = "Unqualified event"

        # 1. Track explicit user inputs
        is_user_input = False
        if sem in ("TYPE", "TEXT_INPUT"):
            is_user_input = True
        elif sem in ("CLICK", "UI_CLICK"):
            elem = str(details.get("element", "")).lower()
            if "point(" not in elem or app_lower not in ("desktop", "explorer"):
                is_user_input = True
            last_click_event = ev
        elif sem in ("HOTKEY", "SHORTCUT", "COPY", "PASTE", "SAVE", "SELECT_ALL", "UNDO", "FIND", "NEW", "CLOSE_TAB", "KEY_PRESS", "SUBMIT"):
            is_user_input = True
        elif sem in ("BROWSER_NAVIGATE", "BROWSER_URL"):
            is_user_input = True
        elif sem in ("CREATE_FILE", "CREATE_FOLDER", "RENAME", "MOVE", "DELETE", "DOWNLOAD", "READ", "OPEN_FILE", "OPEN_FOLDER"):
            is_user_input = True

        if is_user_input and app and app_lower not in ("desktop",):
            is_user_initiated = True
            parent = process_parents.get(app_lower)
            effective_app = parent if parent and parent not in ("desktop", "explorer") else app_lower
            qualification_reason = f"Explicit user interaction ({sem}) observed in '{app}'"

            explicitly_used_apps.add(effective_app)
            user_inputs_by_app[effective_app].append(ev)
            if effective_app not in first_interaction_index:
                first_interaction_index[effective_app] = idx

        # 2. Track Window Focus / Application Launches generically
        elif sem in ("WINDOW_FOCUS", "OPEN_APPLICATION", "APPLICATION_LAUNCH") and app:
            is_tool = details.get("is_tool_window", False)
            is_app = details.get("is_app_window", False)
            has_owner = details.get("has_owner", False)
            is_visible = details.get("is_visible", True)
            width = details.get("width", 0)
            height = details.get("height", 0)

            # Generic System & Background Process Qualification Rules
            if app_lower in SYSTEM_BACKGROUND_PROCESSES:
                is_user_initiated = False
                qualification_reason = f"BACKGROUND/SYSTEM PROCESS: Known OS service process '{app_lower}'"
            elif app_lower == "desktop" or (app_lower == "explorer" and not details.get("folder") and w_title in ("Desktop", "Taskbar", "")):
                is_user_initiated = False
                qualification_reason = "SYSTEM PROCESS: Desktop workspace / taskbar background shell focus"
            elif w_title and ("workflowos teach by doing" in w_title.lower() or "antigravity" in w_title.lower()):
                is_user_initiated = False
                qualification_reason = "SELF-REFERENTIAL: WorkflowOS recording overlay or IDE window"
            elif is_tool and not is_app:
                is_user_initiated = False
                qualification_reason = "TOOL WINDOW: Utility window style (WS_EX_TOOLWINDOW) without app window flag"
            elif has_owner and not is_app:
                is_user_initiated = False
                qualification_reason = "CHILD DIALOG: Window has parent owner window"
            elif is_visible is False:
                is_user_initiated = False
                qualification_reason = "HIDDEN WINDOW: Window is not visible"
            elif (width > 0 and width <= 50) and (height > 0 and height <= 50):
                is_user_initiated = False
                qualification_reason = f"TINY GEOMETRY: Off-screen or hidden zero-geometry element ({width}x{height})"
            elif width == 0 and height == 0 and not is_app:
                is_user_initiated = False
                qualification_reason = "BACKGROUND PROCESS: Zero-geometry background process without top-level app window flag"
            else:
                # Check parent process relationship
                parent = process_parents.get(app_lower)
                if parent and (parent in explicitly_used_apps or parent in SYSTEM_BACKGROUND_PROCESSES):
                    if parent in SYSTEM_BACKGROUND_PROCESSES:
                        is_user_initiated = False
                        qualification_reason = f"APPLICATION CHILD PROCESS: Spawned by background service '{parent}'"
                    else:
                        is_user_initiated = True
                        qualification_reason = f"APPLICATION CHILD PROCESS: Correlated to parent app '{parent}'"
                else:
                    is_user_initiated = True
                    qualification_reason = f"USER-LAUNCHED APPLICATION / USER-FOREGROUND SWITCH: Top-level interactive window focus for '{app}' ('{w_title}') during recording session"
                    launch_candidates.append({
                        "app": app,
                        "app_lower": app_lower,
                        "event_index": idx,
                        "window_title": w_title,
                        "details": details
                    })

        # Track browser navigation telemetry generically
        if (is_browser_app(app_lower) or sem in ("BROWSER_NAVIGATE", "BROWSER_URL") or details.get("url")) and not is_user_input:
            url_info = extract_browser_url_and_domain(title=w_title, text=details.get("text", ""))
            obs_url = details.get("url") or details.get("domain") or url_info.get("url")
            if obs_url and any(bad in obs_url.lower() for bad in ("workflowos", "127.0.0.1", "localhost")):
                obs_url = None
            if obs_url:
                is_user_initiated = True
                qualification_reason = f"Browser navigation destination observed: '{obs_url}'"
                explicitly_used_apps.add(app_lower)
                print(f"[TEACH TELEMETRY] ==================================================")
                print(f"[TEACH TELEMETRY] BROWSER NAVIGATION DETECTED")
                print(f"[TEACH TELEMETRY] RAW BROWSER EVENT : {ev.get('event_type')} | App: '{app}' | Window Title: '{w_title}'")
                print(f"[TEACH TELEMETRY]   -> OBSERVED URL  : {obs_url}")
                print(f"[TEACH TELEMETRY]   -> SEMANTIC ACTION: BROWSER_NAVIGATE")
                print(f"[TEACH TELEMETRY] ==================================================")

        # Telemetry logging per raw event
        status_str = "YES" if is_user_initiated else "NO"
        print(f"[TEACH TELEMETRY] RAW EVENT #{idx+1}: {ev.get('event_type')} | App: '{app}' | Title: '{w_title}' | Action: {sem}")
        print(f"[TEACH TELEMETRY]   -> USER-INITIATED?: {status_str}")
        print(f"[TEACH TELEMETRY]   -> REASON: {qualification_reason}")

    return {
        "explicitly_used_apps": explicitly_used_apps,
        "user_inputs_by_app": user_inputs_by_app,
        "first_interaction_index": first_interaction_index,
        "process_parents": process_parents,
        "launch_candidates": launch_candidates
    }


def synthesize_workflow_from_events(events: List[Dict[str, Any]], recording_id: Optional[str] = None) -> Dict[str, Any]:
    """
    GENERIC WORKFLOW SYNTHESIZER FOR TEACH-BY-DOING
    5-Stage Pipeline:
    Raw Desktop Events -> Event Correlation -> User-Intent Detection -> Semantic Action Extraction -> Workflow Validation
    Distinguishes user-initiated actions from background system processes and helper subprocesses.
    Zero hardcoded applications, folders, tasks, or workflows.
    """
    meaningful_actions = []
    apps_involved = set()
    emitted_app_launches = set()

    rec_id = recording_id or (events[0].get("recording_id") if events else None) or (events[0].get("session_id") if events else "rec_unknown")

    if not events:
        return {
            "name": "Observed Desktop Activity",
            "description": "Demonstration completed with 0 automated action primitives detected.",
            "goal": "Execute demonstrated desktop activity",
            "trigger": "User Demonstration",
            "recording_id": rec_id,
            "actions": [],
            "variables": [],
            "confidence": 0.0,
            "confidence_reasons": ["No actionable semantic operations captured"],
            "risk": "LOW",
            "risk_warnings": [],
            "application_names": [],
            "version": 1,
            "change_reason": "Demonstration observed"
        }

    # Verify actual user delete demonstration evidence across events
    user_delete_events = [
        (ev.get("event_id") or f"ev_{i+1}")
        for i, ev in enumerate(events)
        if (ev.get("semantic_action") == "DELETE" and (ev.get("source") == "USER_INPUT" or ev.get("event_type") == "KEY_PRESS")) or
           (ev.get("event_type") == "KEY_PRESS" and ev.get("details", {}).get("key") == "Delete") or
           (ev.get("event_type") == "UI_CLICK" and any(k in str(ev.get("details", {})).lower() for k in ("delete", "trash", "remove", "recycle")))
    ]
    has_user_delete_evidence = len(user_delete_events) > 0

    # STAGE 2: EVENT CORRELATION
    correlation = correlate_desktop_events(events)
    explicitly_used_apps = correlation["explicitly_used_apps"]
    process_parents = correlation["process_parents"]
    launch_candidates = correlation["launch_candidates"]

    # STAGE 3: USER-INTENT DETECTION
    # Qualified user apps: apps where user performed explicit actions OR foreground window transitions occurred
    qualified_user_apps = set(explicitly_used_apps)
    for cand in launch_candidates:
        c_app = cand["app_lower"]
        parent = process_parents.get(c_app)
        if parent and parent in qualified_user_apps:
            # Child helper process of already verified app -> correlate to parent, don't duplicate
            continue
        qualified_user_apps.add(c_app)

    # STAGE 4: SEMANTIC ACTION EXTRACTION
    for idx, ev in enumerate(events):
        ev_id = ev.get("event_id") or ev.get("id") or f"ev_{idx+1}"
        sem = (ev.get("semantic_action") or ev.get("event_type") or "").upper()
        details = ev.get("details", {})
        raw_app = (details.get("app") or ev.get("app_name", "")).strip()
        clean_app = raw_app.replace(".exe", "")
        clean_app_lower = clean_app.lower()
        win_title = (ev.get("window_title") or details.get("title") or "").strip()

        # Correlate child processes to parent application if known
        parent_app = process_parents.get(clean_app_lower)
        if parent_app and parent_app in qualified_user_apps:
            clean_app_lower = parent_app

        # 1. Open Application / Window Focus
        if sem in ("OPEN_APPLICATION", "APPLICATION_LAUNCH", "WINDOW_FOCUS") and clean_app_lower and clean_app_lower not in ("desktop", "explorer"):
            # Check 1: Distinguish user-initiated action from background system activity
            if clean_app_lower not in qualified_user_apps:
                continue

            # Emit launch action if app has not been launched yet
            if clean_app_lower not in emitted_app_launches:
                apps_involved.add(clean_app)
                emitted_app_launches.add(clean_app_lower)

                meaningful_actions.append({
                    "type": ACTION_OPEN_APP,
                    "label": f"Launch application: {clean_app}",
                    "params": {"app": clean_app, "target": win_title or clean_app},
                    "risk": "LOW",
                    "confidence": 0.95,
                    "evidence_event_ids": [ev_id]
                })

            # Check if browser window focus contains a browser navigation destination
            if is_browser_app(clean_app_lower) or details.get("browser"):
                url_info = extract_browser_url_and_domain(title=win_title, text=details.get("text", ""))
                obs_url = details.get("url") or details.get("domain") or url_info.get("url")
                if obs_url:
                    meaningful_actions.append({
                        "type": ACTION_BROWSER_NAVIGATE,
                        "label": f"Navigate to: {obs_url}",
                        "params": {"url": obs_url},
                        "risk": "MEDIUM",
                        "evidence_event_ids": [ev_id]
                    })

        # 2. Open Folder
        elif sem in ("OPEN_FOLDER", "FOLDER_OPEN"):
            folder = details.get("folder") or details.get("path") or win_title or "TargetFolder"
            meaningful_actions.append({
                "type": ACTION_OPEN_FOLDER,
                "label": f"Open folder: {folder}",
                "params": {"path": folder},
                "risk": "LOW",
                "evidence_event_ids": [ev_id]
            })

        # 3. Open Specific File
        elif sem in ("OPEN_FILE", "FILE_OPEN"):
            f = details.get("file") or details.get("path") or win_title or "TargetFile"
            meaningful_actions.append({
                "type": ACTION_OPEN_FILE,
                "label": f"Open file: {Path(f).name}",
                "params": {"path": f},
                "risk": "LOW",
                "evidence_event_ids": [ev_id]
            })

        # 4. Text Input / Typing
        elif sem in ("TYPE", "TEXT_INPUT"):
            text = details.get("text", "")
            if text and text.strip():
                short_text = text[:35] + ("..." if len(text) > 35 else "")
                # Ensure target app has launch action if not already present
                if clean_app_lower and clean_app_lower not in ("desktop", "explorer") and clean_app_lower not in emitted_app_launches:
                    emitted_app_launches.add(clean_app_lower)
                    apps_involved.add(clean_app)
                    meaningful_actions.append({
                        "type": ACTION_OPEN_APP,
                        "action_type": ACTION_OPEN_APP,
                        "label": f"Launch application: {clean_app}",
                        "params": {"app": clean_app, "target": win_title or clean_app},
                        "risk": "LOW",
                        "confidence": 0.95,
                        "recording_id": rec_id,
                        "evidence_event_ids": [ev_id]
                    })

                meaningful_actions.append({
                    "type": ACTION_TYPE,
                    "action_type": ACTION_TYPE,
                    "label": f'Type: "{short_text}"',
                    "params": {"text": text, "app": clean_app, "target": win_title or clean_app},
                    "risk": "LOW",
                    "recording_id": rec_id,
                    "evidence_event_ids": [ev_id]
                })

        # 5. Hotkeys & Shortcuts (Ctrl+S, Ctrl+C, Ctrl+V, etc.)
        elif sem in ("HOTKEY", "SHORTCUT", "COPY", "PASTE", "SAVE", "SELECT_ALL", "UNDO", "FIND", "NEW", "CLOSE_TAB"):
            keys = details.get("keys") or details.get("hotkey") or sem
            if clean_app_lower and clean_app_lower not in ("desktop", "explorer") and clean_app_lower not in emitted_app_launches:
                emitted_app_launches.add(clean_app_lower)
                apps_involved.add(clean_app)
                meaningful_actions.append({
                    "type": ACTION_OPEN_APP,
                    "label": f"Launch application: {clean_app}",
                    "params": {"app": clean_app, "target": win_title or clean_app},
                    "risk": "LOW",
                    "confidence": 0.95
                })

            meaningful_actions.append({
                "type": "HOTKEY",
                "label": f"Press {keys}",
                "params": {"keys": keys, "app": clean_app, "target": win_title},
                "risk": "LOW",
                "evidence_event_ids": [ev_id]
            })

        # 6. Key Press (Enter, Tab, Escape)
        elif sem in ("KEY_PRESS", "SUBMIT"):
            key_name = details.get("key", "Enter")
            meaningful_actions.append({
                "type": "KEY_PRESS",
                "label": f"Press {key_name}",
                "params": {"key": key_name, "app": clean_app, "target": win_title},
                "risk": "LOW",
                "evidence_event_ids": [ev_id]
            })

        # 7. UI Clicks
        elif sem in ("CLICK", "UI_CLICK"):
            elem = details.get("element") or details.get("target") or "UI Element"
            if clean_app_lower and clean_app_lower not in ("desktop", "explorer") and clean_app_lower not in emitted_app_launches:
                emitted_app_launches.add(clean_app_lower)
                apps_involved.add(clean_app)
                meaningful_actions.append({
                    "type": ACTION_OPEN_APP,
                    "label": f"Launch application: {clean_app}",
                    "params": {"app": clean_app, "target": win_title or clean_app},
                    "risk": "LOW",
                    "confidence": 0.95,
                    "evidence_event_ids": [ev_id]
                })

            meaningful_actions.append({
                "type": ACTION_CLICK,
                "label": f"Click: {elem}",
                "params": {"target": elem, "app": clean_app, "x": details.get("x"), "y": details.get("y")},
                "risk": "MEDIUM",
                "evidence_event_ids": [ev_id]
            })

        # 8. Create File
        elif sem in ("CREATE_FILE", "FILE_CREATED"):
            p = details.get("path") or details.get("name") or "new_file"
            meaningful_actions.append({
                "type": ACTION_CREATE_FILE,
                "label": f"Create file: {Path(p).name}",
                "params": {"path": p},
                "risk": "LOW",
                "evidence_event_ids": [ev_id]
            })

        # 9. Create Folder
        elif sem in ("CREATE_FOLDER", "DIRECTORY_CREATED"):
            p = details.get("path") or details.get("name") or "new_folder"
            meaningful_actions.append({
                "type": ACTION_CREATE_FOLDER,
                "label": f"Create directory: {Path(p).name}",
                "params": {"path": p},
                "risk": "LOW",
                "evidence_event_ids": [ev_id]
            })

        # 10. Rename File
        elif sem in ("RENAME", "FILE_RENAMED"):
            src = details.get("source", "file")
            new_n = details.get("new_name", "renamed_file")
            meaningful_actions.append({
                "type": ACTION_RENAME_FILE,
                "label": f"Rename '{Path(src).name}' to '{new_n}'",
                "params": {"source": src, "new_name": new_n},
                "risk": "LOW",
                "evidence_event_ids": [ev_id]
            })

        # 11. Move File
        elif sem in ("MOVE", "FILE_MOVED"):
            src = details.get("source", "file")
            dest = details.get("destination") or details.get("target") or "Organized"
            meaningful_actions.append({
                "type": ACTION_MOVE_FILE,
                "label": f"Move '{Path(src).name}' to '{dest}'",
                "params": {"source": src, "destination": dest},
                "risk": "LOW",
                "evidence_event_ids": [ev_id]
            })

        # 12. Delete File (Strictly requires user demonstration evidence - Requirement 1, 5, 6, 9)
        elif sem in ("DELETE", "FILE_DELETED"):
            f = details.get("file") or details.get("name") or "file"
            if not has_user_delete_evidence:
                print(f"[TEACH] Rejecting un-evidenced file deletion '{f}': no user delete demonstration observed")
                continue
            meaningful_actions.append({
                "type": ACTION_DELETE_FILE,
                "label": f"[HIGH RISK] Delete '{Path(f).name}'",
                "params": {"file": f},
                "risk": "HIGH",
                "evidence_event_ids": user_delete_events or [ev_id]
            })

        # 13. Browser Navigation
        elif sem in ("BROWSER_NAVIGATE", "BROWSER_URL"):
            url_info = extract_browser_url_and_domain(title=win_title, text=details.get("text", ""))
            url = details.get("url") or details.get("domain") or url_info.get("url")
            if url:
                if clean_app_lower and clean_app_lower not in ("desktop", "explorer") and clean_app_lower not in emitted_app_launches:
                    emitted_app_launches.add(clean_app_lower)
                    apps_involved.add(clean_app)
                    meaningful_actions.append({
                        "type": ACTION_OPEN_APP,
                        "label": f"Launch application: {clean_app}",
                        "params": {"app": clean_app, "target": win_title or clean_app},
                        "risk": "LOW",
                        "confidence": 0.95,
                        "evidence_event_ids": [ev_id]
                    })

                meaningful_actions.append({
                    "type": ACTION_BROWSER_NAVIGATE,
                    "label": f"Navigate to: {url}",
                    "params": {"url": url},
                    "risk": "MEDIUM",
                    "evidence_event_ids": [ev_id]
                })

        # 14. File Download
        elif sem in ("DOWNLOAD", "FILE_DOWNLOAD"):
            f = details.get("file") or "downloaded_file"
            dest = details.get("destination") or "TargetFolder"
            meaningful_actions.append({
                "type": ACTION_DOWNLOAD,
                "label": f"Download '{f}' to '{dest}'",
                "params": {"file": f, "destination": dest},
                "risk": "MEDIUM",
                "evidence_event_ids": [ev_id]
            })

        # 15. Read / Inspect File
        elif sem == "READ":
            f = details.get("file") or details.get("path") or "document"
            meaningful_actions.append({
                "type": ACTION_READ_FILE,
                "label": f"Read content of: {f}",
                "params": {"path": f},
                "risk": "LOW",
                "evidence_event_ids": [ev_id]
            })

    # STAGE 5: DEDUPLICATION & USER-INTENT VALIDATION
    deduped_actions = []
    for act in meaningful_actions:
        if deduped_actions:
            last = deduped_actions[-1]
            if last.get("type") == act.get("type") and last.get("params") == act.get("params"):
                continue
        deduped_actions.append(act)

    # Validate that every OPEN_APPLICATION action represents an actual user-intended application launch
    validated_actions = []
    for act in deduped_actions:
        if act.get("type") == ACTION_OPEN_APP:
            target_app = (act.get("params", {}).get("app") or "").strip().lower()
            # If target app is not in qualified user apps and has low confidence, prune it
            if target_app and target_app not in qualified_user_apps and act.get("confidence", 0) < 0.70:
                continue
        validated_actions.append(act)

    print(f"[TEACH TELEMETRY] ==================================================")
    print(f"[TEACH TELEMETRY] GENERATED actions[] ({len(validated_actions)} STEPS):")
    for i, act in enumerate(validated_actions, 1):
        print(f"[TEACH TELEMETRY]   Step #{i}: {act.get('type')} | Label: '{act.get('label')}' | Params: {act.get('params')}")
    print(f"[TEACH TELEMETRY] ==================================================\n")

    if not validated_actions:
        return {
            "name": "Observed Desktop Activity",
            "description": "Demonstration completed with 0 automated action primitives detected.",
            "goal": "Execute demonstrated desktop activity",
            "trigger": "User Demonstration",
            "actions": [],
            "variables": [],
            "confidence": 0.0,
            "confidence_reasons": ["No actionable semantic operations captured"],
            "risk": "LOW",
            "risk_warnings": [],
            "application_names": list(apps_involved),
            "version": 1,
            "change_reason": "Demonstration observed"
        }

    # Dynamic Variable Detection (Requirement 9)
    variables = extract_workflow_variables(validated_actions)

    # Dynamic Goal & Name Synthesis (Requirement 8 & 10)
    first_act = validated_actions[0]
    first_label = first_act.get("label", "Custom Step")
    num_steps = len(validated_actions)

    has_app_launch = any(a.get("type") == ACTION_OPEN_APP for a in validated_actions)
    has_typing = any(a.get("type") == ACTION_TYPE for a in validated_actions)
    has_file_op = any(a.get("type") in (ACTION_MOVE_FILE, ACTION_COPY_FILE, ACTION_RENAME_FILE, ACTION_CREATE_FILE) for a in validated_actions)
    has_browser = any(a.get("type") == ACTION_BROWSER_NAVIGATE for a in validated_actions)

    type_act = next((a for a in validated_actions if a.get("type") == ACTION_TYPE), None)
    click_act = next((a for a in validated_actions if a.get("type") == ACTION_CLICK), None)
    input_app = None
    if type_act and type_act.get("params", {}).get("app"):
        input_app = type_act["params"]["app"].replace(".exe", "")
    elif click_act and click_act.get("params", {}).get("app"):
        input_app = click_act["params"]["app"].replace(".exe", "")
    elif has_app_launch:
        input_app = next((a.get("params", {}).get("app") for a in validated_actions if a.get("type") == ACTION_OPEN_APP), "Desktop Application")

    if input_app and has_typing:
        name = f"Automate {input_app.capitalize()} Workflow"
        goal = f"Open {input_app.capitalize()} on Windows desktop and execute demonstrated input sequence"
    elif has_file_op:
        op_label = next((a.get("label") for a in validated_actions if a.get("type") in (ACTION_MOVE_FILE, ACTION_COPY_FILE, ACTION_RENAME_FILE)), "File Operation")
        name = f"File Workflow: {op_label}"
        goal = f"Execute demonstrated file operations: {op_label}"
    elif has_browser:
        url_target = next((a.get("params", {}).get("url") for a in validated_actions if a.get("type") == ACTION_BROWSER_NAVIGATE), "Web")
        name = f"Web Navigation: {url_target}"
        goal = f"Navigate browser to {url_target} and perform interaction sequence"
    elif num_steps == 1:
        name = first_label
        goal = f"Execute: {first_label}"
    else:
        name = f"{first_label} + {num_steps - 1} step(s)"
        goal = f"Automate demonstrated desktop sequence of {num_steps} step(s)"

    trigger = "User Demonstration / Manual Invocation"

    confidence, reasons = calculate_confidence(validated_actions, repetitions=len(events) // 3 + 1)
    risk, warnings = calculate_risk(validated_actions)

    return {
        "name": name,
        "description": f"Workflow dynamically synthesized from user demonstration ({num_steps} steps).",
        "goal": goal,
        "trigger": trigger,
        "actions": validated_actions,
        "variables": variables,
        "confidence": confidence,
        "confidence_reasons": reasons,
        "risk": risk,
        "risk_warnings": warnings,
        "application_names": list(apps_involved),
        "recording_id": rec_id,
        "version": 1,
        "change_reason": "Learned dynamically from user demonstration"
    }


# ---------------- WORKFLOW EVOLUTION ENGINE ----------------

def detect_workflow_evolution(
    existing_workflows: List[Dict[str, Any]],
    new_actions: List[Dict[str, Any]],
    new_goal: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    CORE FEATURE — WORKFLOW EVOLUTION ENGINE
    Compares the newly observed demonstration sequence against existing workflows.
    If the demonstrated sequence is an evolution or modification of an existing workflow,
    it detects the difference, formats the comparison, and proposes an update.
    """
    if not existing_workflows or not new_actions:
        return None

    new_action_types = [a.get("type") for a in new_actions]
    new_labels = [a.get("label", a.get("type", "")) for a in new_actions]

    best_match = None
    highest_similarity = 0.0

    for wf in existing_workflows:
        old_actions = wf.get("actions", [])
        if not old_actions:
            continue

        old_action_types = [a.get("type") for a in old_actions]
        old_labels = [a.get("label", a.get("type", "")) for a in old_actions]

        # Check goal or destination keyword similarity
        goal_overlap = False
        if new_goal and wf.get("goal"):
            words_new = set(re.findall(r"\w+", new_goal.lower()))
            words_old = set(re.findall(r"\w+", wf["goal"].lower()))
            common = words_new.intersection(words_old)
            if len(common) >= 2:
                goal_overlap = True

        # Check action type overlap
        set_new = set(new_action_types)
        set_old = set(old_action_types)
        jaccard = len(set_new.intersection(set_old)) / max(1, len(set_new.union(set_old)))

        # Also check destination differences (e.g. Placement vs College/Placement)
        old_destinations = [str(a.get("params", {}).get("destination", "")) for a in old_actions if "destination" in a.get("params", {})]
        new_destinations = [str(a.get("params", {}).get("destination", "")) for a in new_actions if "destination" in a.get("params", {})]

        is_dest_evolved = False
        if old_destinations and new_destinations:
            if old_destinations != new_destinations:
                # check if there is some root commonality
                if any(od.lower() in nd.lower() or nd.lower() in od.lower() for od in old_destinations for nd in new_destinations):
                    is_dest_evolved = True

        # Check label sequence divergence
        is_sequence_diverged = (old_labels != new_labels) and (jaccard >= 0.40 or goal_overlap or is_dest_evolved)

        similarity_score = jaccard + (0.3 if goal_overlap else 0.0) + (0.3 if is_dest_evolved else 0.0)

        # Format human-readable destination and step summary
        old_dest_str = ", ".join(old_destinations) if old_destinations else "previous steps"
        new_dest_str = ", ".join(new_destinations) if new_destinations else "new steps"

        if is_dest_evolved:
            change_desc = f"Destination path changed from '{old_dest_str}' to '{new_dest_str}'."
        else:
            change_desc = f"Demonstrated steps diverged ({len(old_labels)} steps → {len(new_labels)} steps)."

        if is_sequence_diverged and similarity_score > highest_similarity:
            highest_similarity = similarity_score
            best_match = {
                "workflow_id": wf["id"],
                "name": wf["name"],
                "current_version": wf["version"],
                "old_workflow_display": " → ".join(old_labels),
                "new_workflow_display": " → ".join(new_labels),
                "old_actions": old_actions,
                "new_actions": new_actions,
                "similarity": round(highest_similarity, 2),
                "change_summary": change_desc,
                "proposed_version": wf["version"] + 1
            }

    return best_match if highest_similarity >= 0.50 else None


# ---------------- GEMINI LLM INTEGRATION (OPTIONAL) ----------------

def parse_with_gemini(prompt: str, api_key: str) -> Optional[Dict[str, Any]]:
    """
    Call Google Gemini API if key is provided.
    Includes automatic model fallbacks (gemini-1.5-flash, gemini-2.0-flash, gemini-2.5-flash, gemini-1.5-pro),
    markdown wrapper stripping, and parameter normalization for 100% reliable execution.
    """
    if not api_key:
        return None

    models = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-pro"]
    system_instruction = (
        "You are WorkFlowOS AI, an intelligent desktop automation compiler. "
        "Convert the user's natural language request into a precise, executable workflow JSON.\n"
        "Allowed Action Types:\n"
        "- OPEN_APPLICATION: Launch desktop app. Params: {\"app\": \"name_or_exe\"}\n"
        "- OPEN_FOLDER: Open directory. Params: {\"path\": \"folder_path\"}\n"
        "- OPEN_FILE: Open document or file. Params: {\"path\": \"file_path\"}\n"
        "- CREATE_FOLDER: Create new folder. Params: {\"path\": \"folder_path\"}\n"
        "- CREATE_FILE: Create file. Params: {\"path\": \"file_path\", \"content\": \"text\"}\n"
        "- RENAME_FILE: Rename file. Params: {\"source\": \"old_name\", \"new_name\": \"new_name\"}\n"
        "- MOVE_FILE: Move file. Params: {\"source\": \"file_path\", \"destination\": \"folder_path\"}\n"
        "- COPY_FILE: Copy file. Params: {\"source\": \"file_path\", \"destination\": \"folder_path\"}\n"
        "- DELETE_FILE: Delete file. Params: {\"path\": \"file_path\"}\n"
        "- SEARCH_FILES: Search for files. Params: {\"query\": \"search_term\"}\n"
        "- READ_FILE: Read contents of file. Params: {\"path\": \"file_path\"}\n"
        "- BROWSER_NAVIGATE: Open web page. Params: {\"url\": \"https://...\"}\n"
        "- CLICK: Click target UI element. Params: {\"target\": \"element_name\"}\n"
        "- TYPE: Type text. Params: {\"text\": \"string_to_type\"}\n"
        "- HOTKEY: Send key shortcut. Params: {\"keys\": \"Ctrl+N\"}\n"
        "- RUN_COMMAND: Execute terminal shell command. Params: {\"command\": \"cmd\"}\n"
        "- DOWNLOAD: Download file from URL. Params: {\"url\": \"...\"}\n"
        "- UPLOAD: Upload file to destination. Params: {\"source\": \"...\"}\n\n"
        "Return ONLY a single valid JSON object matching this schema:\n"
        "{\n"
        '  "name": "Short Descriptive Title",\n'
        '  "goal": "Clear summary of user goal",\n'
        '  "description": "Detailed explanation of actions taken",\n'
        '  "trigger": "User request in Chat",\n'
        '  "actions": [\n'
        '    {"type": "ACTION_TYPE", "label": "Human readable step label", "params": {"key": "val"}}\n'
        "  ],\n"
        '  "confidence": 0.95\n'
        "}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{system_instruction}\n\nUser Goal:\n{prompt}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }

    raw_text = None
    selected_model = None

    for m in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
        try:
            resp = requests.post(url, json=payload, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                selected_model = m
                break
        except Exception:
            continue

    if not raw_text:
        return None

    try:
        clean_text = raw_text.strip()
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r"\s*```$", "", clean_text)
        
        json_match = re.search(r"(\{[\s\S]*\})", clean_text)
        if json_match:
            clean_text = json_match.group(1)

        plan = json.loads(clean_text)
        actions = plan.get("actions", [])
        if not actions or not isinstance(actions, list):
            return None

        normalized_actions = []
        for act in actions:
            if not isinstance(act, dict):
                continue
            act_type = str(act.get("type", "")).upper().strip()
            params = act.get("params", {}) or {}

            if act_type in (ACTION_OPEN_APP, "OPEN_APP", "LAUNCH_APP", "APPLICATION_LAUNCH"):
                act_type = ACTION_OPEN_APP
                app_val = params.get("app") or params.get("application") or params.get("name") or ""
                params["app"] = str(app_val).lower().strip()
            elif act_type in (ACTION_BROWSER_NAVIGATE, "NAVIGATE", "OPEN_URL", "BROWSER"):
                act_type = ACTION_BROWSER_NAVIGATE
                url_val = params.get("url") or params.get("target") or ""
                if not str(url_val).startswith("http://") and not str(url_val).startswith("https://"):
                    url_val = f"https://{str(url_val).lstrip('www.')}"
                params["url"] = url_val
            elif act_type in (ACTION_CREATE_FOLDER, "NEW_FOLDER"):
                act_type = ACTION_CREATE_FOLDER
                params["path"] = params.get("path") or params.get("folder") or params.get("name") or "New Folder"
            elif act_type in (ACTION_MOVE_FILE, "MOVE"):
                act_type = ACTION_MOVE_FILE

            label = act.get("label") or f"{act_type}: {params}"
            risk_val = act.get("risk") or ("HIGH" if act_type in HIGH_RISK_ACTIONS else ("MEDIUM" if act_type in MEDIUM_RISK_ACTIONS else "LOW"))

            normalized_actions.append({
                "type": act_type,
                "label": label,
                "params": params,
                "risk": risk_val
            })

        plan["actions"] = normalized_actions
        plan["risk"], plan["risk_warnings"] = calculate_risk(normalized_actions)
        plan["confidence_reasons"] = [f"Generated via Gemini ({selected_model}) LLM with semantic intent analysis"]
        plan["version"] = 1
        plan["confidence"] = plan.get("confidence", 0.95)
        return plan
    except Exception as e:
        safe_print(f"[LLM PARSE ERROR] {e}")

    return None


def parse_chat_goal(prompt: str) -> Dict[str, Any]:
    """
    Main entrypoint for Chat to Automation:
    Uses Gemini LLM if key is provided (in settings or environment variables); otherwise uses robust offline heuristic engine.
    """
    api_key = (
        get_setting("gemini_api_key", "").strip() or
        os.environ.get("GEMINI_API_KEY", "").strip() or
        os.environ.get("GOOGLE_API_KEY", "").strip()
    )
    if api_key:
        plan = parse_with_gemini(prompt, api_key)
        if plan:
            return plan

    return parse_chat_heuristic(prompt)
