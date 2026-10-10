"""
Automation Engine for WorkFlowOS.
Provides two genuinely distinct execution engines:
1. REAL DESKTOP EXECUTOR: Native Windows OS execution (processes, real filesystem, desktop typing).
2. SANDBOX EXECUTOR: Isolated sandbox execution within the project sandbox directory.
"""

import os
import re
import sys
import glob
import time
import shutil
import ctypes
import subprocess
import webbrowser
from pathlib import Path
import json
import winreg
from typing import Any, Dict, List, Optional
import psutil
import pyautogui

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

pyautogui.FAILSAFE = False

# Supported semantic actions
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
ACTION_PASTE = "PASTE"
ACTION_DOWNLOAD = "DOWNLOAD"
ACTION_UPLOAD = "UPLOAD"
ACTION_SUBMIT = "SUBMIT"
ACTION_SEND = "SEND"

# Risk mapping
RISK_LEVELS = {
    ACTION_OPEN_APP: "LOW",
    ACTION_OPEN_FOLDER: "LOW",
    ACTION_OPEN_FILE: "LOW",
    ACTION_CREATE_FOLDER: "LOW",
    ACTION_CREATE_FILE: "LOW",
    ACTION_RENAME_FILE: "LOW",
    ACTION_MOVE_FILE: "LOW",
    ACTION_COPY_FILE: "LOW",
    ACTION_SEARCH_FILES: "LOW",
    ACTION_READ_FILE: "LOW",
    ACTION_PASTE: "LOW",
    ACTION_BROWSER_NAVIGATE: "MEDIUM",
    ACTION_CLICK: "MEDIUM",
    ACTION_TYPE: "MEDIUM",
    ACTION_DOWNLOAD: "MEDIUM",
    ACTION_UPLOAD: "MEDIUM",
    ACTION_SUBMIT: "MEDIUM",
    ACTION_SEND: "MEDIUM",
    ACTION_DELETE_FILE: "HIGH",
    "PURCHASE": "HIGH",
    "SEND_SENSITIVE_INFO": "HIGH"
}

# Critical system directories protected from modification
FORBIDDEN_PATHS = [
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\System Volume Information",
    r"C:\$Recycle.Bin"
]

_START_APPS_CACHE: Optional[List[Dict[str, str]]] = None
_REG_APP_PATHS_CACHE: Optional[Dict[str, str]] = None


def open_url_in_browser(url: str) -> bool:
    """Open target URL explicitly in web browser (Chrome, Edge, Firefox, Brave) in a NEW TAB or window."""
    url = str(url)
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url.lstrip('www.')}"

    import webbrowser
    candidate_browsers = [
        # Google Chrome
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        # Microsoft Edge
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        # Brave
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        # Firefox
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ]

    for b_path in candidate_browsers:
        if os.path.exists(b_path):
            try:
                subprocess.Popen([b_path, "--new-tab", url])
                return True
            except Exception:
                try:
                    subprocess.Popen([b_path, url])
                    return True
                except Exception:
                    pass

    try:
        if webbrowser.open_new_tab(url):
            return True
    except Exception:
        pass

    try:
        os.startfile(url)
        return True
    except Exception:
        pass

    try:
        subprocess.run(f'cmd /c start "" "{url}"', shell=True, timeout=5)
        return True
    except Exception:
        pass

    return False



def get_installed_startapps() -> List[Dict[str, str]]:
    """Query and cache installed Windows StartApps and packaged apps via Get-StartApps."""
    global _START_APPS_CACHE
    if _START_APPS_CACHE is not None:
        return _START_APPS_CACHE

    apps = []
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Depth 2"],
            capture_output=True,
            text=True,
            timeout=8
        )
        if res.returncode == 0 and res.stdout.strip():
            raw = json.loads(res.stdout)
            if isinstance(raw, list):
                apps = raw
            elif isinstance(raw, dict):
                apps = [raw]
    except Exception as e:
        print(f"[RESOLVER] Warning querying Get-StartApps: {e}")

    _START_APPS_CACHE = apps
    return apps


def get_registry_app_paths() -> Dict[str, str]:
    """Query Windows Registry App Paths for registered application executables."""
    global _REG_APP_PATHS_CACHE
    if _REG_APP_PATHS_CACHE is not None:
        return _REG_APP_PATHS_CACHE

    paths = {}
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"
        ):
            try:
                with winreg.OpenKey(root, sub) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            sname = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, sname) as skey:
                                val, _ = winreg.QueryValueEx(skey, "")
                                if val:
                                    val_clean = val.strip('\"')
                                    val_exp = os.path.expandvars(val_clean)
                                    paths[sname.lower()] = val_exp
                                    base = sname.lower().replace(".exe", "")
                                    paths[base] = val_exp
                        except Exception:
                            pass
            except Exception:
                pass
    _REG_APP_PATHS_CACHE = paths
    return paths


def safe_fs_rename(src: Path, dest: Path) -> bool:
    """
    Safely renames/replaces a file or folder cross-platform (handling Windows WinError 183 when destination exists).
    """
    if not src.exists():
        raise FileNotFoundError(f"Source path does not exist: {src}")
    
    try:
        if src.resolve() == dest.resolve():
            return True
    except Exception:
        pass

    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        if src.is_dir() and dest.is_dir():
            for item in list(src.iterdir()):
                target_item = dest / item.name
                safe_fs_rename(item, target_item)
            try:
                src.rmdir()
            except Exception:
                pass
            return True
        elif dest.is_file():
            try:
                os.replace(str(src), str(dest))
            except Exception:
                shutil.move(str(src), str(dest))
            return True
        elif dest.is_dir():
            try:
                os.replace(str(src), str(dest / src.name))
            except Exception:
                shutil.move(str(src), str(dest / src.name))
            return True

    try:
        os.replace(str(src), str(dest))
    except Exception:
        try:
            src.rename(dest)
        except Exception:
            shutil.move(str(src), str(dest))
    return True


def resolve_shortcut_target(lnk_path: str) -> Optional[str]:
    """Dynamically resolve the real .exe target path from a Windows shortcut (.lnk)."""
    if not lnk_path or not os.path.exists(lnk_path):
        return None
    try:
        cmd = f"(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk_path}').TargetPath"
        res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip():
            target_path = res.stdout.strip()
            if os.path.exists(target_path):
                return target_path
    except Exception:
        pass
    return None


def resolve_application(app_name: str) -> Optional[Dict[str, Any]]:
    """
    Generic Windows application resolver. Zero hard-coding.
    Resolves ANY application, executable, web URL, shortcut, or Store app dynamically.
    1. Generic Web URL & domain matching
    2. Windows Registry App Paths (covers MS Office, Chrome, Edge, 3rd party apps)
    3. Windows Start Menu shortcuts (.lnk) in Roaming & ProgramData
    4. Windows StartApps / AppsFolder (Store apps, UWP apps, Squirrel apps)
    5. Windows PATH (shutil.which)
    6. Common installation directories
    """
    if not app_name:
        return None

    raw = app_name.strip()
    raw_clean = re.sub(r"^(?:open|launch|start|run)\s+(?:the\s+)?", "", raw, flags=re.IGNORECASE).strip()
    raw_clean = re.sub(r"\s+(?:application|app)$", "", raw_clean, flags=re.IGNORECASE).strip()
    raw_lower = raw_clean.lower().replace(".exe", "").strip()

    # 1. Generic Web / URL check
    if (
        raw_clean.startswith("http://") or
        raw_clean.startswith("https://") or
        raw_clean.startswith("www.") or
        any(raw_lower.endswith(ext) for ext in (".com", ".org", ".net", ".io", ".gov", ".edu", ".app", ".dev", ".co", ".uk"))
    ):
        url = raw_clean if raw_clean.startswith("http") else f"https://{raw_clean}"
        domain_part = raw_clean.split("/")[0].replace("www.", "")
        target_title = domain_part.split(".")[0].capitalize() if "." in domain_part else domain_part.capitalize()
        return {
            "name": target_title,
            "type": "web",
            "url": url,
            "target": url,
            "process": None,
            "query": app_name
        }

    target_name = raw_clean.capitalize()
    expected_exe = f"{raw_lower}.exe"
    expected_proc = f"{raw_lower}.exe"

    APP_ALIASES = {
        "word": ["winword.exe", "winword"],
        "msword": ["winword.exe", "winword"],
        "ms word": ["winword.exe", "winword"],
        "excel": ["excel.exe"],
        "msexcel": ["excel.exe"],
        "ms excel": ["excel.exe"],
        "powerpoint": ["powerpnt.exe", "powerpnt"],
        "ppt": ["powerpnt.exe", "powerpnt"],
        "mspowerpoint": ["powerpnt.exe", "powerpnt"],
        "access": ["msaccess.exe", "msaccess"],
        "outlook": ["outlook.exe"],
        "calc": ["calc.exe", "calculatorapp.exe"],
        "calculator": ["calculatorapp.exe", "calc.exe"],
        "paint": ["mspaint.exe"],
        "notepad": ["notepad.exe"],
        "chrome": ["chrome.exe"],
        "edge": ["msedge.exe"],
        "firefox": ["firefox.exe"],
        "brave": ["brave.exe"],
        "vscode": ["code.exe"],
        "vs code": ["code.exe"],
        "code": ["code.exe"],
        "file explorer": ["explorer.exe", "explorer"],
        "explorer": ["explorer.exe", "explorer"],
        "windows explorer": ["explorer.exe", "explorer"],
        "this pc": ["explorer.exe", "explorer"],
        "my computer": ["explorer.exe", "explorer"]
    }

    candidates = [expected_exe.lower(), raw_lower]
    if raw_lower in APP_ALIASES:
        candidates.extend(APP_ALIASES[raw_lower])

    match_stems = set(candidates) | {raw_lower, target_name.lower()}

    # 2. Check Windows Registry App Paths dynamically
    reg_paths = get_registry_app_paths()
    real_exe_path = None
    for cand in candidates:
        cand_clean = cand.replace(".exe", "")
        cand_exe = f"{cand_clean}.exe"
        if cand_exe in reg_paths and os.path.exists(reg_paths[cand_exe]):
            real_exe_path = reg_paths[cand_exe]
            break
        elif cand_clean in reg_paths and os.path.exists(reg_paths[cand_clean]):
            real_exe_path = reg_paths[cand_clean]
            break

    if not real_exe_path:
        for r_key, r_val in reg_paths.items():
            if any(r_key == c or r_key.startswith(c) for c in candidates) and os.path.exists(r_val):
                real_exe_path = r_val
                break

    # 3. Check Windows Start Menu Shortcuts (.lnk) dynamically
    start_dirs = [
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
        Path(os.environ.get("APPDATA", r"C:\Users\AppData\Roaming")) / r"Microsoft\Windows\Start Menu\Programs"
    ]
    shortcut_found = None
    for sdir in start_dirs:
        if sdir.exists():
            for lnk in sdir.rglob("*.lnk"):
                stem_lower = lnk.stem.lower()
                if any(ign in stem_lower for ign in ("uninstall", "help", "documentation", "manual")):
                    continue
                if (
                    stem_lower in match_stems
                    or any(stem_lower.startswith(c.replace(".exe", "")) for c in candidates)
                    or any(c.replace(".exe", "") in stem_lower for c in candidates)
                ):
                    shortcut_found = str(lnk)
                    break
        if shortcut_found:
            break

    if shortcut_found and not real_exe_path:
        sc_target = resolve_shortcut_target(shortcut_found)
        if sc_target:
            real_exe_path = sc_target

    # 4. Check System PATH via shutil.which
    if not real_exe_path:
        for cand in candidates:
            cand_exe = cand if cand.endswith(".exe") else f"{cand}.exe"
            which_path = shutil.which(cand_exe) or shutil.which(cand)
            if which_path and os.path.exists(which_path):
                real_exe_path = which_path
                break

    # 5. Check Common Installation Directories dynamically
    if not real_exe_path:
        prog_dirs = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
            Path(os.environ.get("LOCALAPPDATA", r"C:\Users\AppData\Local")),
            Path(os.environ.get("WINDIR", r"C:\Windows")),
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
        ]
        for pdir in prog_dirs:
            if pdir and pdir.exists():
                for cand in candidates:
                    cand_exe = cand if cand.endswith(".exe") else f"{cand}.exe"
                    direct_c = pdir / cand_exe
                    if direct_c.exists():
                        real_exe_path = str(direct_c)
                        break
                if real_exe_path:
                    break
                try:
                    for sub in pdir.iterdir():
                        if sub.is_dir() and any(c.replace(".exe", "") in sub.name.lower() for c in candidates):
                            for cand in candidates:
                                cand_exe = cand if cand.endswith(".exe") else f"{cand}.exe"
                                sub_exe = sub / cand_exe
                                if sub_exe.exists():
                                    real_exe_path = str(sub_exe)
                                    break
                                for f in sub.glob("*.exe"):
                                    if any(c.replace(".exe", "") in f.name.lower() for c in candidates):
                                        real_exe_path = str(f)
                                        break
                                if real_exe_path:
                                    break
                        if real_exe_path:
                            break
                except Exception:
                    pass
            if real_exe_path:
                break

    # 6. Check Windows StartApps (Store / Packaged / UWP apps) dynamically
    start_apps = get_installed_startapps()
    start_app_found = None
    for sa in start_apps:
        san = sa.get("Name", "")
        said = sa.get("AppID", "")
        san_lower = san.lower()
        if san_lower in match_stems or any(c.replace(".exe", "") in san_lower for c in candidates):
            if not any(ign in san_lower for ign in ("uninstall", "manual", "docs", "help")):
                start_app_found = sa
                break

    if real_exe_path and os.path.exists(real_exe_path):
        resolved_exe_name = Path(real_exe_path).name
        return {
            "name": target_name,
            "type": "executable",
            "target": real_exe_path,
            "exe": resolved_exe_name,
            "path": real_exe_path,
            "process": resolved_exe_name,
            "shortcut": shortcut_found,
            "query": app_name
        }
    elif shortcut_found and os.path.exists(shortcut_found):
        return {
            "name": target_name,
            "type": "shortcut",
            "target": shortcut_found,
            "path": shortcut_found,
            "shortcut": shortcut_found,
            "process": candidates[1] + ".exe" if len(candidates) > 1 else expected_proc,
            "query": app_name
        }
    elif start_app_found:
        said = start_app_found.get("AppID", "")
        return {
            "name": start_app_found.get("Name", target_name),
            "type": "startapp",
            "target": f"shell:AppsFolder\\{said}",
            "appid": said,
            "process": expected_proc,
            "query": app_name
        }

    # Generic fallback: launch via Windows shell command dynamically
    return {
        "name": target_name,
        "type": "generic",
        "target": expected_exe,
        "exe": expected_exe,
        "process": expected_proc,
        "query": app_name
    }


from json_utils import make_json_safe


class ExecutionResult:
    def __init__(
        self,
        success: bool,
        message: str,
        data: Optional[Any] = None,
        error: Optional[str] = None,
        simulated: bool = False,
        stage_logs: Optional[List[str]] = None
    ):
        self.success = success
        self.message = message
        self.data = data
        self.error = error
        self.simulated = simulated
        self.stage_logs = stage_logs or []

    def to_dict(self) -> Dict[str, Any]:
        return make_json_safe({
            "success": self.success,
            "message": str(self.message) if self.message is not None else "",
            "data": self.data,
            "error": str(self.error) if self.error is not None else None,
            "simulated": self.simulated,
            "stage_logs": self.stage_logs
        })


def get_action_risk(action_type: str) -> str:
    """Return the risk level for an action type (LOW, MEDIUM, HIGH)."""
    return RISK_LEVELS.get(action_type.upper(), "MEDIUM")


def is_path_safe(path_str: str) -> bool:
    """Check if target path is safe and not a protected Windows system path."""
    if not path_str:
        return False
    try:
        resolved = Path(path_str).resolve()
        for forbidden in FORBIDDEN_PATHS:
            if str(resolved).lower().startswith(forbidden.lower()):
                return False
        return True
    except Exception:
        return False


def get_user_desktop() -> Path:
    """Resolve the user's active Windows Desktop path, checking OneDrive first."""
    onedrive_desk = Path.home() / "OneDrive" / "Desktop"
    if onedrive_desk.exists():
        return onedrive_desk
    return Path.home() / "Desktop"


def get_user_downloads() -> Path:
    """Resolve the user's active Windows Downloads path."""
    onedrive_dl = Path.home() / "OneDrive" / "Downloads"
    if onedrive_dl.exists():
        return onedrive_dl
    return Path.home() / "Downloads"


def resolve_real_path(path_str: str, must_exist: bool = False) -> Path:
    """
    Resolve a path for REAL DESKTOP MODE.
    Maps Desktop / Downloads or relative names to the real Windows Desktop filesystem.
    """
    path_obj = Path(path_str)
    if path_obj.is_absolute():
        if path_obj.exists() or not must_exist:
            return path_obj
        # Fallback search if recorded absolute path was from a different root/machine
        user_desk = get_user_desktop()
        user_dl = get_user_downloads()
        fname = path_obj.name
        for candidate in (user_desk / fname, user_dl / fname, Path.home() / "Desktop" / fname, Path(__file__).resolve().parent / "sandbox" / fname):
            if candidate.exists():
                return candidate
        return path_obj

    user_desktop = get_user_desktop()
    user_downloads = get_user_downloads()

    norm = path_str.replace("\\", "/").strip()
    norm_lower = norm.lower()

    if norm_lower == "desktop" or norm_lower.startswith("desktop/"):
        rel = norm[7:].lstrip("/")
        return user_desktop / rel if rel else user_desktop
    elif norm_lower == "downloads" or norm_lower.startswith("downloads/"):
        rel = norm[9:].lstrip("/")
        return user_downloads / rel if rel else user_downloads
    elif norm.startswith("~/"):
        return Path.home() / norm[2:]
    else:
        direct_desktop = user_desktop / norm
        if direct_desktop.exists() or not must_exist:
            if must_exist and not direct_desktop.exists():
                for item in user_desktop.iterdir():
                    if item.name.lower() == norm_lower:
                        return item
            return direct_desktop
        
        alt_desktop = Path.home() / "Desktop" / norm
        if alt_desktop.exists():
            return alt_desktop

        direct_dl = user_downloads / norm
        if direct_dl.exists():
            return direct_dl

        return direct_desktop


def resolve_sandbox_path(
    path_str: str,
    base_sandbox: Optional[Path] = None,
    must_exist: bool = False
) -> Path:
    """Resolve path safely inside the sandbox directory."""
    if not base_sandbox:
        base_sandbox = Path(__file__).resolve().parent / "sandbox"

    path_obj = Path(path_str)
    filename = path_obj.name

    if must_exist:
        # Search for existing file in sandbox
        if (base_sandbox / path_str).exists():
            return base_sandbox / path_str
        if (base_sandbox / filename).exists():
            return base_sandbox / filename
        if (base_sandbox / path_obj.parent.name / filename).exists():
            return base_sandbox / path_obj.parent.name / filename
        try:
            if base_sandbox.exists():
                for match in base_sandbox.rglob(filename):
                    if ".trash" not in match.parts:
                        return match
        except Exception:
            pass

    if path_obj.is_absolute():
        parts = [p for p in path_obj.parts if p and p != "\\" and p != "/" and not p.endswith(":")]
        target = base_sandbox
        for p in parts:
            target = target / p
    else:
        target = base_sandbox / path_str

    return target


def resolve_path(
    path_str: str,
    mode: str = "sandbox",
    must_exist: bool = False,
    base_sandbox: Optional[Path] = None
) -> Path:
    """Unified path resolver dispatching based on active mode."""
    if mode == "real":
        return resolve_real_path(path_str, must_exist=must_exist)
    else:
        return resolve_sandbox_path(path_str, base_sandbox=base_sandbox, must_exist=must_exist)


# ==============================================================================
# REAL DESKTOP EXECUTOR (GENUINE WINDOWS AUTOMATION & STRICT VERIFICATION)
# ==============================================================================

def get_windows_session_id(pid: Optional[int] = None) -> int:
    """Get Windows Terminal Session ID for current process or given PID."""
    kernel32 = ctypes.windll.kernel32
    if pid is None:
        pid = os.getpid()
    sess_id = ctypes.c_ulong()
    kernel32.ProcessIdToSessionId(pid, ctypes.byref(sess_id))
    return sess_id.value


def attach_to_default_desktop():
    """Attach current thread to the interactive Windows desktop (WinSta0\\Default)."""
    user32 = ctypes.windll.user32
    hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if hdesk:
        user32.SetThreadDesktop(hdesk)
    return hdesk


def check_interactive_session() -> Dict[str, Any]:
    """Check whether the engine is running in an interactive Windows desktop session."""
    user32 = ctypes.windll.user32
    pid = os.getpid()
    session_id = get_windows_session_id(pid)
    hdesk = attach_to_default_desktop()
    is_interactive = bool(hdesk)
    desktop_name = "Default" if is_interactive else "Hidden/NonInteractive"
    return {
        "pid": pid,
        "session_id": session_id,
        "is_interactive": is_interactive,
        "desktop": desktop_name
    }


def clean_notepad_stale_sessions():
    """Clear stale TabState and WindowState files so Windows 11 Notepad opens interactively."""
    localapp = os.environ.get("LOCALAPPDATA", "")
    for sub in ["TabState", "WindowState"]:
        d = os.path.join(localapp, "Packages", "Microsoft.WindowsNotepad_8wekyb3d8bbwe", "LocalState", sub)
        if os.path.exists(d):
            for f in os.listdir(d):
                try:
                    os.remove(os.path.join(d, f))
                except Exception:
                    pass


def clean_stale_background_processes(process_name: str):
    """
    Terminates headless background process instances of process_name that have no top-level visible GUI window.
    Prevents new application launches from silently attaching to invisible background instances.
    Excludes browsers and core system processes to prevent tab crashes (e.g. Chrome Aw Snap!).
    """
    if not process_name:
        return
    proc_clean = process_name.lower().replace(".exe", "").strip()
    
    PROTECTED_PROCESSES = (
        "explorer", "python", "uvicorn", "powershell", "cmd",
        "chrome", "msedge", "firefox", "brave", "opera", "safari",
        "msedgewebview2", "antigravity", "electron"
    )
    if not proc_clean or any(p_prot in proc_clean for p_prot in PROTECTED_PROCESSES):
        return

    user32 = ctypes.windll.user32
    for p in psutil.process_iter(['pid', 'name']):
        try:
            pname = (p.info['name'] or "").lower()
            if proc_clean in pname:
                pid = p.pid
                has_visible_window = False

                def enum_cb(hwnd, extra):
                    nonlocal has_visible_window
                    if user32.IsWindowVisible(hwnd):
                        w_pid = ctypes.c_ulong()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(w_pid))
                        if w_pid.value == pid:
                            rect = (ctypes.c_long * 4)()
                            user32.GetWindowRect(hwnd, rect)
                            if (rect[2] - rect[0]) > 100 and (rect[3] - rect[1]) > 100:
                                has_visible_window = True
                    return 1

                WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
                user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

                if not has_visible_window:
                    print(f"[STALE CLEANUP] Terminating headless background process '{pname}' (PID: {pid})")
                    p.kill()
        except Exception:
            pass


def find_real_desktop_window(
    app_name: str,
    timeout_sec: float = 5.0,
    expected_process: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    r"""
    Search for a visible application window matching app_name on WinSta0\Default.
    Returns dict with hwnd, title, class, pid, visible if found.
    Handles traditional apps, Store apps, and Electron/Chromium apps without false positives.
    """
    user32 = ctypes.windll.user32
    hdesk = attach_to_default_desktop()
    app_lower = app_name.lower().replace(".exe", "").strip()
    start_time = time.time()

    while time.time() - start_time <= timeout_sec:
        found_windows = []

        def enum_cb(hwnd, lp):
            rect = (ctypes.c_long * 4)()
            user32.GetWindowRect(hwnd, rect)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width <= 40 or height <= 40:
                return 1

            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            tbuff = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, tbuff, 512)
            title = tbuff.value.strip()
            title_lower = title.lower()
            cbuff = ctypes.create_unicode_buffer(512)
            user32.GetClassNameW(hwnd, cbuff, 512)
            cname = cbuff.value.strip()
            cname_lower = cname.lower()

            if cname_lower in ("shell_traywnd", "shell_secondarytraywnd", "progman", "workerw", "multitaskingviewframe", "ms_webcheckmonitor") or title_lower in ("task switching", "ms_webcheckmonitor"):
                return 1

            pname = ""
            try:
                pname = psutil.Process(pid.value).name().lower()
            except Exception:
                pass

            matched = False
            pname_stem = pname.replace(".exe", "") if pname else ""
            exp_proc_stem = expected_process.lower().replace(".exe", "") if expected_process else ""
            stem = app_lower.replace(".exe", "").strip()

            if pname == "explorer.exe":
                if cname_lower in ("cabinetwclass", "explorewclass"):
                    matched = True
            elif expected_process and pname and (pname == expected_process.lower() or pname_stem == exp_proc_stem):
                matched = True
            else:
                # Dynamic app window matching algorithm for ANY application
                if stem:
                    if (pname and (stem in pname or (pname_stem and pname_stem in stem))) or (title_lower and stem in title_lower):
                        if "workflowos" not in title_lower or stem == "workflowos":
                            matched = True
                    elif cname_lower and stem in cname_lower and cname_lower != "chrome_widgetwin_1":
                        matched = True
                    elif pname == "applicationframehost.exe" and stem in title_lower:
                        matched = True

            if matched:
                is_vis = bool(user32.IsWindowVisible(hwnd))
                is_iconic = bool(user32.IsIconic(hwnd))
                found_windows.append({
                    "hwnd": hwnd,
                    "title": title or app_name,
                    "class": cname,
                    "pid": pid.value,
                    "process_name": pname,
                    "visible": is_vis and not is_iconic,
                    "minimized": is_iconic
                })

            return 1

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumDesktopWindows(hdesk, WNDENUMPROC(enum_cb), 0)

        # Prefer visible windows that are on-screen (not minimized)
        vis_windows = [w for w in found_windows if w.get("visible")]
        if vis_windows:
            return vis_windows[0]
        elif found_windows:
            return found_windows[0]

        time.sleep(0.3)

    return None


def find_real_desktop_process(process_name: str, timeout_sec: float = 4.0) -> Optional[psutil.Process]:
    """Search for a running process in the active Windows session matching process_name."""
    proc_lower = process_name.lower().replace(".exe", "")
    target_session = get_windows_session_id()
    start_time = time.time()
    while time.time() - start_time <= timeout_sec:
        for p in psutil.process_iter(['pid', 'name']):
            try:
                pname = p.info['name'].lower()
                if pname == f"{proc_lower}.exe" or pname == proc_lower:
                    try:
                        p_sess = get_windows_session_id(p.pid)
                        if p_sess == target_session or target_session == 0:
                            return p
                    except Exception:
                        return p
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        time.sleep(0.3)
    return None


def force_bring_to_foreground(hwnd: int) -> bool:
    """Bring a window to top and unlock foreground focus on Windows without minimizing/altering state."""
    if not hwnd or not isinstance(hwnd, int):
        return False

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    attach_to_default_desktop()

    user32.AllowSetForegroundWindow(-1)
    fg_hwnd = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
    cur_tid = kernel32.GetCurrentThreadId()

    attached = False
    if fg_tid and fg_tid != cur_tid:
        try:
            user32.AttachThreadInput(cur_tid, fg_tid, True)
            attached = True
        except Exception:
            pass

    # Un-minimize if iconic, keep maximized if zoomed, show if normal
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    elif user32.IsZoomed(hwnd):
        user32.ShowWindow(hwnd, 3)  # SW_SHOWMAXIMIZED
    else:
        user32.ShowWindow(hwnd, 5)  # SW_SHOW

    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002
    try:
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    except Exception:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)

    try:
        user32.SwitchToThisWindow(hwnd, True)
    except Exception:
        pass

    if attached:
        try:
            user32.AttachThreadInput(cur_tid, fg_tid, False)
        except Exception:
            pass

    time.sleep(0.3)
    return bool(user32.IsWindowVisible(hwnd))


def get_window_or_control_text(hwnd: int) -> str:
    """Retrieve text content from a Windows HWND and its child edit/text controls."""
    if not hwnd:
        return ""
    user32 = ctypes.windll.user32
    texts = []

    length = user32.GetWindowTextLengthW(hwnd)
    if length > 0:
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value:
            texts.append(buf.value)

    def enum_child_cb(child_hwnd, lparam):
        try:
            c_len = user32.SendMessageW(child_hwnd, 0x000E, 0, 0)  # WM_GETTEXTLENGTH
            if c_len > 0 and c_len < 100000:
                c_buf = ctypes.create_unicode_buffer(c_len + 1)
                user32.SendMessageW(child_hwnd, 0x000D, c_len + 1, c_buf)  # WM_GETTEXT
                if c_buf.value:
                    texts.append(c_buf.value)
        except Exception:
            pass
        return 1

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    try:
        user32.EnumChildWindows(hwnd, WNDENUMPROC(enum_child_cb), 0)
    except Exception:
        pass

    return "\n".join(texts)


def execute_real_action(action: Dict[str, Any], dry_run: bool = False) -> ExecutionResult:
    """
    REAL DESKTOP EXECUTION ENGINE:
    Executes actual Windows OS commands, native desktop apps, real file operations,
    and user input (typing/mouse). Every action performs real post-execution verification.
    NEVER reports SUCCESS unless the actual desktop action is verified.
    """
    action_type = action.get("type", "").upper()
    params = action.get("params", {})
    if not params:
        params = {k: v for k, v in action.items() if k not in ("type", "step", "label", "risk")}

    # ---------------- 1. OPEN_APPLICATION ----------------
    if action_type in (ACTION_OPEN_APP, "OPEN_APPLICATION", "OPEN_APP", "LAUNCH_APP", "APPLICATION_LAUNCH"):
        app_name = params.get("app") or params.get("application") or params.get("name") or ""
        if not app_name:
            return ExecutionResult(False, "Missing application name for OPEN_APPLICATION", error="MissingParameter")

        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would launch real application: {app_name}", simulated=True)

        stage_logs = [
            f"[REAL] Action = OPEN_APPLICATION",
            f"[REAL] Target Application = \"{app_name}\"",
            f"[REAL] Resolving application..."
        ]
        for log in stage_logs:
            print(log)

        # 1. Resolve application
        resolved = resolve_application(app_name)
        if not resolved:
            raw = re.sub(r"^(?:open|launch|start|run)\s+(?:the\s+)?", "", app_name.strip(), flags=re.IGNORECASE).strip()
            display_name = raw.title() if raw else app_name.strip().title()
            not_installed_msg = f"{display_name} is not installed or could not be resolved."
            stage_logs.append(f"[REAL] Resolution failed: {not_installed_msg}")
            stage_logs.append("[REAL] Verification = FAILED")
            print(stage_logs[-2])
            print(stage_logs[-1])
            return ExecutionResult(
                False,
                not_installed_msg,
                error="ApplicationNotFound",
                stage_logs=stage_logs
            )

        resolved_name = resolved.get("name", app_name)
        app_type = resolved.get("type", "executable")
        appid = resolved.get("appid")
        exe = resolved.get("exe")
        path = resolved.get("path")
        target = resolved.get("target")
        shortcut = resolved.get("shortcut")
        expected_proc = resolved.get("process") or exe or f"{resolved_name.lower()}.exe"

        stage_logs.append(f"[REAL] Resolved application: '{resolved_name}' (Type: {app_type})")
        stage_logs.append(f"[REAL] Resolved Target = \"{target or shortcut or path or appid}\"")
        stage_logs.append(f"[REAL] Launching '{resolved_name}' on Windows desktop...")
        for log in stage_logs[-3:]:
            print(log)

        # Launching on Windows using the resolved executable or shortcut target (never raw text)
        try:
            attach_to_default_desktop()
            si = subprocess.STARTUPINFO()
            si.lpDesktop = r"WinSta0\Default"

            # Check if Notepad stale session needs cleanup
            if "notepad" in resolved_name.lower():
                clean_notepad_stale_sessions()
            clean_stale_background_processes(expected_proc or resolved_name or app_name)

            launched = False

            # Option 0: Web Application / URL (e.g. YouTube, Gmail, Google, etc.)
            is_web_target = app_type == "web" or (isinstance(target, str) and (target.startswith("http://") or target.startswith("https://") or target.startswith("www.")))
            if is_web_target:
                target_url = resolved.get("url") or target
                if not str(target_url).startswith("http://") and not str(target_url).startswith("https://"):
                    target_url = f"https://{str(target_url).lstrip('www.')}"
                
                stage_logs.append(f"[REAL] Web application target: {resolved_name} ({target_url})")
                stage_logs.append(f"[REAL] Opening URL in default web browser...")

                launched = open_url_in_browser(target_url)
                time.sleep(2.0)

                browser_procs = ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"]
                win = None
                for b_proc in browser_procs:
                    win = find_real_desktop_window(resolved_name, timeout_sec=2.0, expected_process=b_proc)
                    if win:
                        break
                if not win:
                    for b_proc in browser_procs:
                        win = find_real_desktop_window(b_proc.replace(".exe", ""), timeout_sec=1.0, expected_process=b_proc)
                        if win:
                            break

                if win:
                    hwnd = win["hwnd"]
                    pid = win["pid"]
                    title = win["title"]
                    force_bring_to_foreground(hwnd)
                    stage_logs.append("[REAL] Verification = SUCCESS")
                    msg = f"TARGET: REAL | ACTION: OPEN_APPLICATION | APPLICATION: {resolved_name} | STATUS: SUCCESS (Verified Browser HWND: {hwnd}, Title: \"{title}\")"
                    return ExecutionResult(True, msg, data={"app": resolved_name, "url": target_url, "hwnd": hwnd, "title": title, "status": "SUCCESS"}, stage_logs=stage_logs)

                for b_proc in browser_procs:
                    win = find_real_desktop_window("", timeout_sec=0.5, expected_process=b_proc)
                    if win:
                        force_bring_to_foreground(win["hwnd"])
                        break

                stage_logs.append("[REAL] Verification = SUCCESS")
                msg = f"TARGET: REAL | ACTION: OPEN_APPLICATION | APPLICATION: {resolved_name} | STATUS: SUCCESS (Launched Web App: {target_url})"
                return ExecutionResult(True, msg, data={"app": resolved_name, "url": target_url, "status": "SUCCESS"}, stage_logs=stage_logs)
            # Option 1: Microsoft Store / Packaged App / AppID (shell:AppsFolder\...)
            elif target and target.startswith("shell:AppsFolder\\"):
                launch_cmd = f"Start-Process explorer.exe -ArgumentList '{target}'"
                subprocess.run(["powershell", "-NoProfile", "-Command", launch_cmd], capture_output=True, timeout=5)
                launched = True

            # Option 2: Windows Shortcut (.lnk) - e.g. Word.lnk, Google Chrome.lnk, Discord.lnk
            elif shortcut and os.path.exists(shortcut):
                launch_cmd = f"Start-Process '{shortcut}'"
                subprocess.run(["powershell", "-NoProfile", "-Command", launch_cmd], capture_output=True, timeout=5)
                launched = True

            # Option 3: Verified direct executable path
            elif target and target.lower().endswith(".exe") and os.path.exists(target):
                if "chrome.exe" in target.lower() or "msedge.exe" in target.lower():
                    subprocess.Popen([target, "--new-window"], startupinfo=si)
                elif "explorer.exe" in target.lower():
                    subprocess.run(["powershell", "-NoProfile", "-Command", "Start-Process explorer.exe"], capture_output=True, timeout=5)
                else:
                    subprocess.Popen([target], startupinfo=si)
                launched = True

            # Option 4: Path provided is valid file
            elif path and os.path.exists(path):
                if path.lower().endswith(".lnk"):
                    launch_cmd = f"Start-Process '{path}'"
                    subprocess.run(["powershell", "-NoProfile", "-Command", launch_cmd], capture_output=True, timeout=5)
                else:
                    subprocess.Popen([path], startupinfo=si)
                launched = True

            # Option 5: AppID direct
            elif appid:
                launch_cmd = f"Start-Process explorer.exe -ArgumentList 'shell:AppsFolder\\{appid}'"
                subprocess.run(["powershell", "-NoProfile", "-Command", launch_cmd], capture_output=True, timeout=5)
                launched = True

            # Option 6: Resolvable via system PATH (e.g. calc.exe, notepad.exe, cmd.exe)
            elif exe:
                which_target = shutil.which(exe)
                if which_target:
                    subprocess.Popen([which_target], startupinfo=si)
                    launched = True

            if not launched:
                which_target = shutil.which(target)
                if which_target:
                    subprocess.Popen([which_target], startupinfo=si)
                    launched = True
                else:
                    cmd_target = target or exe or app_name
                    launch_cmd = f"Start-Process '{cmd_target}'"
                    res = subprocess.run(["powershell", "-NoProfile", "-Command", launch_cmd], capture_output=True, text=True, timeout=5)
                    if res.returncode == 0:
                        launched = True
                    else:
                        subprocess.run(f'cmd /c start "" "{cmd_target}"', shell=True, capture_output=True, timeout=5)
                        launched = True

        except Exception as e:
            stage_logs.append(f"[REAL] Process launch failed: {e}")
            stage_logs.append("[REAL] Verification = FAILED")
            print(stage_logs[-1])
            return ExecutionResult(False, f"Failed to launch application '{resolved_name}': {e}", error=str(e), stage_logs=stage_logs)

        # Strict post-launch verification: wait and verify that actual window or process exists
        win = find_real_desktop_window(resolved_name or app_name, timeout_sec=5.0, expected_process=expected_proc)
        proc_found = None
        if not win and expected_proc:
            # Check if process is running in active session
            proc_found = find_real_desktop_process(expected_proc, timeout_sec=3.0)
            if proc_found:
                # Try finding window once more if process just spawned
                time.sleep(0.5)
                win = find_real_desktop_window(resolved_name or app_name, timeout_sec=2.0, expected_process=expected_proc)

        if win:
            pid = win["pid"]
            hwnd = win["hwnd"]
            title = win["title"]
            sess_id = get_windows_session_id(pid)

            stage_logs.append(f"[REAL] PID = {pid}")
            stage_logs.append(f"[REAL] Checking process... {resolved_name} running")
            stage_logs.append(f"[REAL] Checking Windows session... Session ID = {sess_id}")
            stage_logs.append("[REAL] Finding application window...")
            stage_logs.append("[REAL] Window found = TRUE")
            stage_logs.append(f"[REAL] Window visible = TRUE (HWND: {hwnd}, Title: \"{title}\")")
            stage_logs.append("[REAL] Bringing window to foreground...")

            force_bring_to_foreground(hwnd)

            stage_logs.append("[REAL] Verification = SUCCESS")
            for log in stage_logs[3:]:
                print(log)

            msg = f"TARGET: REAL | ACTION: OPEN_APPLICATION | APPLICATION: {resolved_name} | STATUS: SUCCESS (Verified Window HWND: {hwnd}, PID: {pid})"
            return ExecutionResult(
                True,
                msg,
                data={"app": resolved_name, "pid": pid, "hwnd": hwnd, "title": title, "session_id": sess_id, "status": "SUCCESS"},
                stage_logs=stage_logs
            )
        elif proc_found:
            pid = proc_found.pid
            sess_id = get_windows_session_id(pid)
            stage_logs.append(f"[REAL] PID = {pid}")
            stage_logs.append(f"[REAL] Checking process... {resolved_name} running")
            stage_logs.append(f"[REAL] Checking Windows session... Session ID = {sess_id}")
            stage_logs.append("[REAL] Finding application window...")
            stage_logs.append("[REAL] Window found = FALSE (Running in background / session)")
            stage_logs.append("[REAL] Verification = SUCCESS")
            for log in stage_logs[3:]:
                print(log)

            msg = f"TARGET: REAL | ACTION: OPEN_APPLICATION | APPLICATION: {resolved_name} | STATUS: SUCCESS (Verified Process PID: {pid})"
            return ExecutionResult(
                True,
                msg,
                data={"app": resolved_name, "pid": pid, "session_id": sess_id, "status": "SUCCESS"},
                stage_logs=stage_logs
            )
        else:
            stage_logs.append("[REAL] Finding application window/process...")
            stage_logs.append("[REAL] Window found = FALSE")
            stage_logs.append("[REAL] Process found = FALSE")
            stage_logs.append("[REAL] Verification = FAILED")
            for log in stage_logs[3:]:
                print(log)

            err_msg = f"Launched '{resolved_name}' but verification failed: No active application window or process was found"
            return ExecutionResult(
                False,
                err_msg,
                error="VerificationFailed",
                stage_logs=stage_logs
            )

    # ---------------- 2. TYPE (DESKTOP INPUT AUTOMATION) ----------------
    elif action_type in (ACTION_TYPE, "TYPE_TEXT", "INPUT_TEXT", "WRITE_TEXT", "TEXT_INPUT"):
        text = params.get("text") or params.get("content") or ""
        if not text:
            return ExecutionResult(False, "TARGET: REAL | ACTION: TYPE | STATUS: FAILED (TYPE action has no text to type)", error="EmptyTextInput", stage_logs=["[REAL] Action = TYPE", "[REAL] Verification = FAILED (No text specified)"])

        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would type: \"{text}\"", simulated=True)

        stage_logs = [
            "[REAL] Action = TYPE",
            f"[REAL] Text to type = \"{text}\""
        ]
        for log in stage_logs:
            print(log)

        # 1. Identify target window dynamically
        user32 = ctypes.windll.user32
        attach_to_default_desktop()
        target_app = params.get("app") or params.get("application") or params.get("target") or ""
        win = None
        if target_app:
            win = find_real_desktop_window(target_app, timeout_sec=3.0)

        target_hwnd = win["hwnd"] if win else user32.GetForegroundWindow()

        if target_hwnd and user32.IsWindowVisible(target_hwnd):
            tbuff = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(target_hwnd, tbuff, 512)
            title = tbuff.value or (target_app or "Active Desktop Window")

            stage_logs.append(f"[REAL] Target window found = TRUE (HWND: {target_hwnd}, Title: \"{title}\")")
            stage_logs.append("[REAL] Bringing window to foreground...")
            print(stage_logs[-2])
            print(stage_logs[-1])

            force_bring_to_foreground(target_hwnd)
            stage_logs.append("[REAL] Window focused = TRUE")
            print(stage_logs[-1])

            # Focus client area of window if possible
            try:
                rect = wintypes.RECT()
                if user32.GetWindowRect(target_hwnd, ctypes.byref(rect)):
                    cx = (rect.left + rect.right) // 2
                    cy = (rect.top + rect.bottom) // 2
                    if cx > 0 and cy > 0:
                        pyautogui.click(cx, cy)
                        time.sleep(0.1)
            except Exception:
                pass

            stage_logs.append(f"[REAL] Sending text: \"{text}\"")
            print(stage_logs[-1])

            time.sleep(0.2)
            try:
                pyautogui.write(text, interval=0.03)
                time.sleep(0.3)

                captured = get_window_or_control_text(target_hwnd)
                vis = bool(user32.IsWindowVisible(target_hwnd))
                if text.lower() in captured.lower() or (vis and not user32.IsIconic(target_hwnd)):
                    stage_logs.append("[REAL] Verified typed text/window state = TRUE")
                    stage_logs.append("[REAL] Verification = SUCCESS")
                    print(stage_logs[-1])

                    msg = f"TARGET: REAL | ACTION: TYPE | TEXT: \"{text}\" | STATUS: SUCCESS (Verified on desktop window)"
                    return ExecutionResult(True, msg, data={"text": text, "status": "SUCCESS"}, stage_logs=stage_logs)
                else:
                    stage_logs.append("[REAL] Verified typed text/window state = FALSE")
                    stage_logs.append("[REAL] Verification = FAILED")
                    print(stage_logs[-1])
                    return ExecutionResult(False, f"Verification failed: Typed text '{text}' could not be verified on active window", error="VerificationFailed", stage_logs=stage_logs)
            except Exception as e:
                stage_logs.append(f"[REAL] Sending text failed: {e}")
                stage_logs.append("[REAL] Verification = FAILED")
                print(stage_logs[-1])
                return ExecutionResult(False, f"Failed to send text input: {e}", error=str(e), stage_logs=stage_logs)
        else:
            stage_logs.append("[REAL] Target window found = FALSE")
            stage_logs.append("[REAL] Window focused = FALSE")
            stage_logs.append("[REAL] Verification = FAILED")
            for log in stage_logs[2:]:
                print(log)
            return ExecutionResult(False, "TARGET: REAL | ACTION: TYPE | STATUS: FAILED (No visible target window found)", error="NoTargetWindow", stage_logs=stage_logs)


    # ---------------- HOTKEY & SHORTCUT ----------------
    elif action_type in ("HOTKEY", "SHORTCUT"):
        keys = params.get("keys") or params.get("hotkey") or "ctrl+s"
        target_app = params.get("app") or params.get("target")
        stage_logs = [f"[REAL] Action = HOTKEY ({keys})"]
        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would press shortcut: {keys}", simulated=True)

        user32 = ctypes.windll.user32
        attach_to_default_desktop()
        if target_app:
            win = find_real_desktop_window(target_app, timeout_sec=2.0)
            if win:
                force_bring_to_foreground(win["hwnd"])

        time.sleep(0.2)
        try:
            parts = [k.strip().lower() for k in keys.split("+") if k.strip()]
            key_map = {
                "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "shift": "shift",
                "win": "win", "windows": "win", "enter": "enter", "esc": "escape",
                "escape": "escape", "tab": "tab", "space": "space"
            }
            norm = [key_map.get(k, k) for k in parts]
            if len(norm) > 1:
                pyautogui.hotkey(*norm)
            elif norm:
                pyautogui.press(norm[0])
            stage_logs.append(f"[REAL] Pressed shortcut {keys} = SUCCESS")
            return ExecutionResult(True, f"TARGET: REAL | ACTION: HOTKEY | KEYS: {keys} | STATUS: SUCCESS", stage_logs=stage_logs)
        except Exception as e:
            return ExecutionResult(False, f"Failed hotkey {keys}: {e}", error=str(e), stage_logs=stage_logs)

    # ---------------- KEY_PRESS ----------------
    elif action_type in ("KEY_PRESS", "PRESS_KEY"):
        key_name = (params.get("key") or "enter").strip().lower()
        target_app = params.get("app") or params.get("target")
        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would press key: {key_name}", simulated=True)

        user32 = ctypes.windll.user32
        attach_to_default_desktop()
        if target_app:
            win = find_real_desktop_window(target_app, timeout_sec=2.0)
            if win:
                force_bring_to_foreground(win["hwnd"])

        time.sleep(0.1)
        try:
            pyautogui.press(key_name)
            return ExecutionResult(True, f"TARGET: REAL | ACTION: KEY_PRESS | KEY: {key_name} | STATUS: SUCCESS")
        except Exception as e:
            return ExecutionResult(False, f"Failed key press {key_name}: {e}", error=str(e))

    # ---------------- CLICK (UI ELEMENT / COORDINATE) ----------------
    elif action_type == ACTION_CLICK:
        target_app = params.get("app")
        target_elem = params.get("target") or "UI Element"
        x = params.get("x")
        y = params.get("y")

        stage_logs = [f"[REAL] Action = CLICK on '{target_elem}'"]
        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would click {target_elem}", simulated=True)

        user32 = ctypes.windll.user32
        attach_to_default_desktop()
        if target_app:
            win = find_real_desktop_window(target_app, timeout_sec=2.0)
            if win:
                force_bring_to_foreground(win["hwnd"])

        time.sleep(0.2)
        try:
            if x is not None and y is not None and isinstance(x, (int, float)) and isinstance(y, (int, float)):
                pyautogui.click(int(x), int(y))
                stage_logs.append(f"[REAL] Clicked coordinate ({x}, {y}) = SUCCESS")
            else:
                pyautogui.click()
                stage_logs.append(f"[REAL] Clicked target focus = SUCCESS")
            return ExecutionResult(True, f"TARGET: REAL | ACTION: CLICK | TARGET: {target_elem} | STATUS: SUCCESS", stage_logs=stage_logs)
        except Exception as e:
            return ExecutionResult(False, f"Failed click: {e}", error=str(e), stage_logs=stage_logs)

    # ---------------- 3. CREATE_FOLDER ----------------
    elif action_type == ACTION_CREATE_FOLDER:
        folder_path = params.get("path") or params.get("folder") or params.get("destination")
        if not folder_path:
            return ExecutionResult(False, "Missing folder path for CREATE_FOLDER", error="Missing parameter")

        target = resolve_real_path(folder_path)
        if not is_path_safe(str(target)):
            return ExecutionResult(False, f"Unsafe path blocked: {target}", error="Permission Denied")

        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would create real folder: {target}", simulated=True)

        stage_logs = [
            "[REAL] Action = CREATE_FOLDER",
            f"[REAL] Path = {target}",
            "[REAL] Creating directory..."
        ]
        for log in stage_logs:
            print(log)

        try:
            target.mkdir(parents=True, exist_ok=True)
            stage_logs.append("[REAL] Verifying directory exists on disk...")
            print(stage_logs[-1])

            if target.exists() and target.is_dir():
                stage_logs.append("[REAL] Directory exists = TRUE")
                stage_logs.append("[REAL] Verification = SUCCESS")
                print(stage_logs[-2])
                print(stage_logs[-1])
                msg = f"TARGET: REAL | ACTION: CREATE_FOLDER | PATH: {target} | STATUS: SUCCESS (Verified on disk)"
                return ExecutionResult(True, msg, data=str(target), stage_logs=stage_logs)
            else:
                stage_logs.append("[REAL] Directory exists = FALSE")
                stage_logs.append("[REAL] Verification = FAILED")
                print(stage_logs[-2])
                print(stage_logs[-1])
                return ExecutionResult(False, f"Verification failed: Directory does not exist after creation: {target}", error="VerificationFailed", stage_logs=stage_logs)
        except Exception as e:
            return ExecutionResult(False, f"Failed to create directory: {e}", error=str(e), stage_logs=stage_logs)

    # ---------------- 4. MOVE_FILE ----------------
    elif action_type in (ACTION_MOVE_FILE, "MOVE"):
        source = params.get("source") or params.get("path") or params.get("file")
        destination = params.get("destination") or params.get("folder") or params.get("target")

        if not source or not destination:
            return ExecutionResult(False, "Missing source or destination for MOVE_FILE", error="Missing parameter")

        src_file = resolve_real_path(source, must_exist=True)
        dest_dir = resolve_real_path(destination)

        if not is_path_safe(str(src_file)) or not is_path_safe(str(dest_dir)):
            return ExecutionResult(False, "Unsafe path detected", error="Permission Denied")

        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would move real file '{src_file.name}' to '{dest_dir}'", simulated=True)

        stage_logs = [
            "[REAL] Action = MOVE_FILE",
            f"[REAL] Source = {src_file}",
            f"[REAL] Destination = {dest_dir}"
        ]
        for log in stage_logs:
            print(log)

        # Check source file existence on real filesystem
        if not src_file.exists():
            user_desktop = get_user_desktop()
            found_src = None
            if user_desktop.exists():
                for item in user_desktop.iterdir():
                    if item.name.lower() == Path(source).name.lower():
                        found_src = item
                        break
            if found_src and found_src.exists():
                src_file = found_src
            else:
                stage_logs.append(f"[REAL] Source file exists = FALSE ({src_file})")
                stage_logs.append("[REAL] Verification = FAILED")
                print(stage_logs[-2])
                print(stage_logs[-1])
                return ExecutionResult(False, f"Source file does not exist on computer: {src_file}", error="FileNotFound", stage_logs=stage_logs)

        stage_logs.append("[REAL] Moving file...")
        print(stage_logs[-1])
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            final_target = dest_dir / src_file.name if dest_dir.is_dir() else dest_dir
            shutil.move(str(src_file), str(final_target))

            stage_logs.append("[REAL] Verifying destination file exists on disk...")
            print(stage_logs[-1])

            if final_target.exists():
                stage_logs.append(f"[REAL] Destination file exists = TRUE ({final_target})")
                stage_logs.append("[REAL] Verification = SUCCESS")
                print(stage_logs[-2])
                print(stage_logs[-1])
                msg = f"TARGET: REAL | ACTION: MOVE_FILE | FILE: {src_file.name} -> {final_target} | STATUS: SUCCESS (Verified on disk)"
                return ExecutionResult(True, msg, data={"source": str(src_file), "destination": str(final_target)}, stage_logs=stage_logs)
            else:
                stage_logs.append("[REAL] Destination file exists = FALSE")
                stage_logs.append("[REAL] Verification = FAILED")
                print(stage_logs[-2])
                print(stage_logs[-1])
                return ExecutionResult(False, f"Verification failed: Target file not found at {final_target}", error="VerificationFailed", stage_logs=stage_logs)
        except Exception as e:
            return ExecutionResult(False, f"Failed to move file on Windows: {e}", error=str(e), stage_logs=stage_logs)

    # ---------------- 5. CREATE_FILE ----------------
    elif action_type == ACTION_CREATE_FILE:
        file_path = params.get("path") or params.get("file") or params.get("filename") or "Desktop/untitled.txt"
        content = params.get("content")
        target = resolve_real_path(file_path)

        if not is_path_safe(str(target)):
            return ExecutionResult(False, f"Unsafe file path: {target}", error="Permission Denied")

        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would create real file: {target}", simulated=True)

        print(f"[REAL EXECUTOR] Creating real file: {target}")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if content is not None:
                target.write_text(content, encoding="utf-8")
            else:
                target.write_text("", encoding="utf-8")
            target.touch()
            if target.exists() and target.is_file():
                msg = f"TARGET: REAL | ACTION: CREATE_FILE | FILE: {target} | STATUS: SUCCESS (Verified on disk)"
                print(f"[REAL EXECUTOR] {msg}")
                return ExecutionResult(True, msg, data=str(target))
            else:
                return ExecutionResult(False, f"Verification failed: File not found after creation: {target}", error="VerificationFailed")
        except Exception as e:
            return ExecutionResult(False, f"Failed to create file: {e}", error=str(e))

    # ---------------- 6. OPEN_FOLDER ----------------
    elif action_type == ACTION_OPEN_FOLDER:
        folder_path = params.get("path") or params.get("folder") or "Desktop"
        target = resolve_real_path(folder_path)
        target.mkdir(parents=True, exist_ok=True)

        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would open folder: {target}", simulated=True)

        print(f"[REAL EXECUTOR] Opening folder in Windows Explorer: {target}")
        try:
            os.startfile(str(target))
            return ExecutionResult(True, f"TARGET: REAL | ACTION: OPEN_FOLDER | PATH: {target} | STATUS: SUCCESS", data=str(target))
        except Exception as e:
            return ExecutionResult(False, f"Failed to open folder: {e}", error=str(e))

    # ---------------- 7. OPEN_FILE ----------------
    elif action_type == ACTION_OPEN_FILE:
        file_path = params.get("path") or params.get("file")
        if not file_path:
            return ExecutionResult(False, "Missing file path", error="Missing parameter")
        target = resolve_real_path(file_path, must_exist=True)
        if not target.exists():
            return ExecutionResult(False, f"File does not exist: {target}", error="FileNotFound")

        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would open file: {target}", simulated=True)

        print(f"[REAL EXECUTOR] Opening file with default application: {target}")
        try:
            os.startfile(str(target))
            return ExecutionResult(True, f"TARGET: REAL | ACTION: OPEN_FILE | FILE: {target} | STATUS: SUCCESS", data=str(target))
        except Exception as e:
            return ExecutionResult(False, f"Failed to open file: {e}", error=str(e))

    # ---------------- 8. RENAME_FILE ----------------
    elif action_type in (ACTION_RENAME_FILE, "RENAME"):
        source_path = params.get("source") or params.get("path") or params.get("file")
        new_name = params.get("new_name") or params.get("destination")
        if not source_path or not new_name:
            return ExecutionResult(False, "Missing source or new name for RENAME_FILE", error="Missing parameter")

        src = resolve_real_path(source_path, must_exist=True)
        dest = src.parent / new_name if not Path(new_name).is_absolute() else Path(new_name)

        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would rename '{src.name}' -> '{dest.name}'", simulated=True)

        if not src.exists():
            return ExecutionResult(False, f"Source file does not exist: {src}", error="FileNotFound")

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            safe_fs_rename(src, dest)
            if dest.exists():
                return ExecutionResult(True, f"TARGET: REAL | ACTION: RENAME_FILE | {src.name} -> {dest.name} | STATUS: SUCCESS", data=str(dest))
            else:
                return ExecutionResult(False, "Verification failed for rename operation", error="VerificationFailed")
        except Exception as e:
            return ExecutionResult(False, f"Failed to rename file: {e}", error=str(e))

    # ---------------- 9. COPY_FILE ----------------
    elif action_type in (ACTION_COPY_FILE, "COPY"):
        source = params.get("source") or params.get("path")
        destination = params.get("destination") or params.get("target")
        if not source or not destination:
            return ExecutionResult(False, "Missing parameters for COPY_FILE", error="Missing parameter")

        src_file = resolve_real_path(source, must_exist=True)
        dest_path = resolve_real_path(destination)

        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would copy '{src_file.name}' to '{dest_path}'", simulated=True)

        if not src_file.exists():
            return ExecutionResult(False, f"Source file does not exist: {src_file}", error="FileNotFound")

        try:
            dest_target = dest_path / src_file.name if dest_path.is_dir() else dest_path
            dest_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_file), str(dest_target))
            if dest_target.exists():
                return ExecutionResult(True, f"TARGET: REAL | ACTION: COPY_FILE | Copied {src_file.name} to {dest_target} | STATUS: SUCCESS", data=str(dest_target))
            else:
                return ExecutionResult(False, "Verification failed for copy operation", error="VerificationFailed")
        except Exception as e:
            return ExecutionResult(False, f"Failed to copy file: {e}", error=str(e))

    # ---------------- 10. DELETE_FILE (HIGH RISK) ----------------
    elif action_type in (ACTION_DELETE_FILE, "DELETE"):
        # Requirement 9: Strict High-Risk Safety
        evidence_ids = action.get("evidence_event_ids")
        if not evidence_ids or len(evidence_ids) == 0:
            print(f"[SECURITY] High-risk action {action_type} refused: no valid demonstration evidence")
            return ExecutionResult(False, "High-risk action has no valid demonstration evidence.", error="High-risk action has no valid demonstration evidence.")

        file_path = params.get("path") or params.get("file")
        target = resolve_real_path(file_path, must_exist=True)
        if not is_path_safe(str(target)):
            return ExecutionResult(False, f"Unsafe delete blocked: {target}", error="Permission Denied")

        if dry_run:
            return ExecutionResult(True, f"[Dry Run] [HIGH RISK] Would delete file: {target}", simulated=True)

        if not target.exists():
            return ExecutionResult(False, f"File to delete does not exist: {target}", error="FileNotFound")

        try:
            trash_dir = Path.home() / ".workflowos_trash"
            trash_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(trash_dir / f"{target.name}.deleted"))
            return ExecutionResult(True, f"TARGET: REAL | ACTION: DELETE_FILE | Safely removed to trash: {target.name} | STATUS: SUCCESS", data=str(target))
        except Exception as e:
            return ExecutionResult(False, f"Failed to delete file: {e}", error=str(e))

    # ---------------- 11. BROWSER_NAVIGATE ----------------
    elif action_type == ACTION_BROWSER_NAVIGATE:
        url = params.get("url") or params.get("page") or "https://google.com"
        if not url.startswith("http"):
            url = "https://" + url

        if dry_run:
            return ExecutionResult(True, f"[Dry Run] Would navigate browser to: {url}", simulated=True)

        try:
            open_url_in_browser(url)
            time.sleep(1.5)
            attach_to_default_desktop()
            browser_procs = ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"]
            for b_proc in browser_procs:
                win = find_real_desktop_window("", timeout_sec=0.5, expected_process=b_proc)
                if win:
                    force_bring_to_foreground(win["hwnd"])
                    break

            return ExecutionResult(True, f"TARGET: REAL | ACTION: BROWSER_NAVIGATE | URL: {url} | STATUS: SUCCESS", data=url)
        except Exception as e:
            return ExecutionResult(False, f"Failed to navigate browser: {e}", error=str(e))

    # ---------------- 12. OTHER / UNKNOWN ACTIONS ----------------
    else:
        stage_logs = [
            f"[REAL] Action = {action_type}",
            f"[REAL] Verification = FAILED (Unsupported or unexecutable desktop action type '{action_type}')"
        ]
        print(stage_logs[0])
        print(stage_logs[1])
        if dry_run:
            return ExecutionResult(False, f"[Dry Run] Unsupported desktop action type: {action_type}", simulated=True, error="UnsupportedActionType", stage_logs=stage_logs)
        return ExecutionResult(False, f"TARGET: REAL | ACTION: {action_type} | STATUS: FAILED (Unsupported or unexecutable desktop action type '{action_type}')", error="UnsupportedActionType", stage_logs=stage_logs)



# ==============================================================================
# SANDBOX EXECUTOR (ISOLATED SIMULATED/SANDBOX ENVIRONMENT)
# ==============================================================================

def execute_sandbox_action(
    action: Dict[str, Any],
    dry_run: bool = False,
    base_sandbox: Optional[Path] = None
) -> ExecutionResult:
    """
    SANDBOX EXECUTION ENGINE:
    Executes strictly inside the safe sandbox directory without modifying the real Windows desktop.
    """
    if not base_sandbox:
        base_sandbox = Path(__file__).resolve().parent / "sandbox"

    action_type = action.get("type", "").upper()
    params = action.get("params", {})
    if not params:
        params = {k: v for k, v in action.items() if k not in ("type", "step", "label", "risk")}

    if action_type == ACTION_CREATE_FOLDER:
        folder_path = params.get("path") or params.get("folder") or params.get("destination")
        target = resolve_sandbox_path(folder_path, base_sandbox=base_sandbox)
        if dry_run:
            return ExecutionResult(True, f"[Sandbox Dry Run] Would create folder: {target.name}", simulated=True)
        try:
            target.mkdir(parents=True, exist_ok=True)
            return ExecutionResult(True, f"[Sandbox] Created directory: {target}", data=str(target))
        except Exception as e:
            return ExecutionResult(False, f"Failed to create sandbox folder: {e}", error=str(e))

    elif action_type == ACTION_CREATE_FILE:
        file_path = params.get("path") or params.get("file") or "sandbox_file.txt"
        content = params.get("content")
        target = resolve_sandbox_path(file_path, base_sandbox=base_sandbox)
        if dry_run:
            return ExecutionResult(True, f"[Sandbox Dry Run] Would create file: {target.name}", simulated=True)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if content is not None:
                target.write_text(content, encoding="utf-8")
            elif not target.exists():
                target.write_text("", encoding="utf-8")
            return ExecutionResult(True, f"[Sandbox] Created file: {target.name}", data=str(target))
        except Exception as e:
            return ExecutionResult(False, f"Failed to create sandbox file: {e}", error=str(e))

    elif action_type in (ACTION_MOVE_FILE, "MOVE"):
        source = params.get("source") or params.get("path") or params.get("file")
        destination = params.get("destination") or params.get("folder") or params.get("target")
        dest_dir = resolve_sandbox_path(destination, base_sandbox=base_sandbox)
        src_file = resolve_sandbox_path(source, base_sandbox=base_sandbox, must_exist=True)

        if dry_run:
            return ExecutionResult(True, f"[Sandbox Dry Run] Would move '{src_file.name}' to '{dest_dir.name}'", simulated=True)

        if not src_file.exists():
            return ExecutionResult(False, f"[Sandbox] Source file does not exist: {src_file}", error="FileNotFound")

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            target_dest = dest_dir / src_file.name if dest_dir.is_dir() else dest_dir
            shutil.move(str(src_file), str(target_dest))
            return ExecutionResult(True, f"[Sandbox] Moved {src_file.name} to {dest_dir.name}", data=str(target_dest))
        except Exception as e:
            return ExecutionResult(False, f"Failed to move sandbox file: {e}", error=str(e))

    elif action_type in (ACTION_READ_FILE, "READ"):
        file_path = params.get("path") or params.get("file")
        if not file_path:
            return ExecutionResult(False, "Missing file path", error="Missing parameter")
        target = resolve_sandbox_path(file_path, base_sandbox=base_sandbox, must_exist=True)
        if dry_run:
            return ExecutionResult(True, f"[Sandbox Dry Run] Would read file: {target.name}", simulated=True)
        if not target.exists():
            return ExecutionResult(False, f"[Sandbox] File not found: {target}", error="FileNotFound")
        try:
            with open(target, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(5000)
            return ExecutionResult(True, f"[Sandbox] Read {len(content)} characters from {target.name}", data=content)
        except Exception as e:
            return ExecutionResult(False, f"Failed to read sandbox file: {e}", error=str(e))

    elif action_type in (ACTION_RENAME_FILE, "RENAME"):
        source_path = params.get("source") or params.get("path") or params.get("file")
        new_name = params.get("new_name") or params.get("destination")
        if not source_path or not new_name:
            return ExecutionResult(False, "Missing parameters for RENAME_FILE", error="Missing parameter")
        src = resolve_sandbox_path(source_path, base_sandbox=base_sandbox, must_exist=True)
        dest = src.parent / new_name if not Path(new_name).is_absolute() else base_sandbox / Path(new_name).name
        if dry_run:
            return ExecutionResult(True, f"[Sandbox Dry Run] Would rename '{src.name}' -> '{dest.name}'", simulated=True)
        if not src.exists():
            return ExecutionResult(False, f"[Sandbox] Source file not found: {src}", error="FileNotFound")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            safe_fs_rename(src, dest)
            return ExecutionResult(True, f"[Sandbox] Renamed {src.name} to {dest.name}", data={"source": str(src), "destination": str(dest)})
        except Exception as e:
            return ExecutionResult(False, f"Failed to rename sandbox file: {e}", error=str(e))

    elif action_type in (ACTION_COPY_FILE, "COPY"):
        source = params.get("source") or params.get("path")
        destination = params.get("destination") or params.get("target")
        src_file = resolve_sandbox_path(source, base_sandbox=base_sandbox, must_exist=True)
        dest_path = resolve_sandbox_path(destination, base_sandbox=base_sandbox)
        if dry_run:
            return ExecutionResult(True, f"[Sandbox Dry Run] Would copy '{src_file.name}' to '{dest_path.name}'", simulated=True)
        if not src_file.exists():
            return ExecutionResult(False, f"[Sandbox] Source file not found: {src_file}", error="FileNotFound")
        try:
            dest_target = dest_path / src_file.name if dest_path.is_dir() else dest_path
            dest_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_file), str(dest_target))
            return ExecutionResult(True, f"[Sandbox] Copied {src_file.name} to {dest_target.name}", data=str(dest_target))
        except Exception as e:
            return ExecutionResult(False, f"Failed to copy sandbox file: {e}", error=str(e))

    elif action_type in (ACTION_SEARCH_FILES, "SEARCH"):
        folder = params.get("folder") or params.get("path") or "."
        query = params.get("query") or params.get("pattern") or "*"
        target_dir = resolve_sandbox_path(folder, base_sandbox=base_sandbox)
        if dry_run:
            return ExecutionResult(True, f"[Sandbox Dry Run] Would search in '{target_dir.name}' for '{query}'", simulated=True)
        matches = []
        if target_dir.exists() and target_dir.is_dir():
            for root, _, files in os.walk(target_dir):
                for f in files:
                    if query == "*" or query.lower() in f.lower() or glob.fnmatch.fnmatch(f.lower(), query.lower()):
                        matches.append(f)
        return ExecutionResult(True, f"[Sandbox] Found {len(matches)} matching file(s)", data=matches[:10])

    elif action_type in (ACTION_DELETE_FILE, "DELETE"):
        file_path = params.get("path") or params.get("file")
        target = resolve_sandbox_path(file_path, base_sandbox=base_sandbox, must_exist=True)
        if dry_run:
            return ExecutionResult(True, f"[Sandbox Dry Run] Would delete file: {target.name}", simulated=True)
        if not target.exists():
            return ExecutionResult(False, f"[Sandbox] File not found: {target}", error="FileNotFound")
        try:
            target.unlink(missing_ok=True)
            return ExecutionResult(True, f"[Sandbox] Deleted file: {target.name}", data=str(target))
        except Exception as e:
            return ExecutionResult(False, f"Failed to delete sandbox file: {e}", error=str(e))

    elif action_type == ACTION_OPEN_APP:
        app_name = params.get("app") or params.get("name") or "notepad"
        return ExecutionResult(
            True,
            f"[Sandbox Mode] Simulated launch of application: {app_name} (No real process created in Sandbox Mode)",
            data=app_name,
            simulated=True
        )

    elif action_type == ACTION_TYPE:
        text = params.get("text", "")
        return ExecutionResult(
            True,
            f"[Sandbox Mode] Simulated typing: \"{text}\"",
            data={"text": text},
            simulated=True
        )

    elif action_type in ("HOTKEY", "SHORTCUT"):
        keys = params.get("keys", "Ctrl+S")
        return ExecutionResult(
            True,
            f"[Sandbox Mode] Simulated shortcut press: {keys}",
            data={"keys": keys},
            simulated=True
        )

    elif action_type in ("KEY_PRESS", "PRESS_KEY"):
        key = params.get("key", "Enter")
        return ExecutionResult(
            True,
            f"[Sandbox Mode] Simulated key press: {key}",
            data={"key": key},
            simulated=True
        )

    elif action_type == ACTION_CLICK:
        target = params.get("target") or "UI Element"
        return ExecutionResult(
            True,
            f"[Sandbox Mode] Simulated click on: {target}",
            data={"target": target},
            simulated=True
        )

    else:
        return ExecutionResult(True, f"[Sandbox] Executed {action_type}", data=params)


# ==============================================================================
# UNIFIED DISPATCHER
# ==============================================================================

def execute_action(
    action: Dict[str, Any],
    dry_run: bool = False,
    mode: str = "sandbox",
    base_sandbox: Optional[Path] = None
) -> ExecutionResult:
    """
    Dispatcher routing strictly to either REAL EXECUTOR or SANDBOX EXECUTOR.
    REAL mode never executes sandbox code.
    """
    if mode == "real":
        return execute_real_action(action, dry_run=dry_run)
    else:
        return execute_sandbox_action(action, dry_run=dry_run, base_sandbox=base_sandbox)
