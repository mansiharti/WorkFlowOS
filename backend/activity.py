"""
Generic Desktop Activity Learning System for WorkFlowOS.
Observes and records real user desktop actions during 'Teach by Doing' sessions:
- Active applications & window changes
- Global mouse clicks and UI element targeting
- Keystrokes, text input aggregation & keyboard shortcuts (hotkeys)
- Real-time multi-directory file & folder operations (created, moved, renamed, deleted)
- Browser navigation and interactions

Converts low-level Windows interactions into normalized, high-level semantic actions.
Zero hardcoding: Works with ANY application, folder, website, or workflow.
"""

import os
import re
import sys
import time
import uuid
import ctypes
import threading
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from database import log_activity_event, get_recent_activity

# Try importing win32gui/win32process for Windows window and control inspection
try:
    import win32gui
    import win32process
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

# Try importing pynput for global mouse and keyboard observation
try:
    from pynput import mouse, keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False

# Try importing watchdog for real-time filesystem tracking
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False


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

    # Ignore browser internal utility pages (New Tab, Settings, Extensions, Downloads, History, Blank)
    ignored_internal_titles = ("new tab", "about:blank", "settings", "extensions", "downloads", "history", "bookmarks", "chrome://", "edge://", "about:")
    if not clean_title or clean_title.lower() in ignored_internal_titles:
        return {"url": None, "domain": None}

    # 4. Extract site slug from clean title (e.g. "YouTube", "Wikipedia", "GitHub")
    words = [w for w in re.split(r"[\s\-\|\:\,]", clean_title) if w.strip()]
    if words:
        first_word = words[0].strip().lower()
        site_slug = re.sub(r"[^a-z0-9]", "", first_word)
        if len(site_slug) >= 2 and site_slug not in ("home", "page", "welcome", "untitled", "index", "main", "new"):
            common_tlds = {"wikipedia": "wikipedia.org", "w3schools": "w3schools.com"}
            dom = common_tlds.get(site_slug, f"{site_slug}.com")
            return {"url": f"https://{dom}", "domain": dom}

    return {"url": None, "domain": None}


def attach_thread_to_desktop():
    """Ensure the calling thread has access to the interactive Windows desktop."""
    try:
        user32 = ctypes.windll.user32
        hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
    except Exception:
        pass


class FileActivityHandler(FileSystemEventHandler if HAS_WATCHDOG else object):
    """Watchdog event handler for file & directory operations across watched paths."""
    def __init__(self, collector: "ActivityCollector"):
        super().__init__()
        self.collector = collector

    def on_created(self, event):
        if not self.collector.is_recording:
            return
        src_path = str(event.src_path)
        # Filter out transient files
        if any(ign in src_path for ign in (".tmp", ".crdownload", "~$", ".trash", "__pycache__")):
            return
        is_dir = event.is_directory
        ev_type = "DIRECTORY_CREATED" if is_dir else "FILE_CREATED"
        sem = "CREATE_FOLDER" if is_dir else "CREATE_FILE"
        self.collector.record_event(
            event_type=ev_type,
            app_name="explorer.exe",
            window_title="File Explorer",
            details={
                "path": src_path,
                "name": Path(src_path).name,
                "is_directory": is_dir
            },
            semantic_action=sem
        )

    def on_moved(self, event):
        if not self.collector.is_recording:
            return
        src_path = str(event.src_path)
        dest_path = str(event.dest_path)
        if any(ign in src_path or ign in dest_path for ign in (".tmp", ".trash", "~$")):
            return

        src = Path(src_path)
        dest = Path(dest_path)

        if src.parent == dest.parent:
            # File or folder rename
            self.collector.record_event(
                event_type="FILE_RENAMED",
                app_name="explorer.exe",
                window_title="File Explorer",
                details={
                    "source": src_path,
                    "new_name": dest.name,
                    "destination": dest_path
                },
                semantic_action="RENAME"
            )
        else:
            # File or folder move
            self.collector.record_event(
                event_type="FILE_MOVED",
                app_name="explorer.exe",
                window_title="File Explorer",
                details={
                    "source": src_path,
                    "destination": str(dest.parent),
                    "filename": dest.name,
                    "target_path": dest_path
                },
                semantic_action="MOVE"
            )

    def on_deleted(self, event):
        if not self.collector.is_recording:
            return
        src_path = str(event.src_path)
        if any(ign in src_path for ign in (".tmp", "~$", ".trash", "__pycache__")):
            return

        # Requirement 1, 5 & 6: Strict user demonstration evidence check
        # A file deletion on the OS level is only a user demonstration if the user
        # actually pressed Delete or clicked a Delete UI control within the active window.
        now = time.time()
        time_since_del_key = now - getattr(self.collector, "last_user_delete_key_time", 0.0)
        time_since_del_click = now - getattr(self.collector, "last_user_delete_click_time", 0.0)
        has_user_delete = (time_since_del_key < 3.0) or (time_since_del_click < 3.0)

        if not has_user_delete:
            # File was overwritten, truncated, or cleaned up internally by an application or OS (e.g. Notepad saving)
            print(f"[ActivityCollector] Ignoring background/internal file change: {src_path} (no user delete demonstration)")
            return

        self.collector.record_event(
            event_type="FILE_DELETED",
            app_name=self.collector.last_foreground_app or "explorer.exe",
            window_title=self.collector.last_foreground_title or "File Explorer",
            details={
                "file": src_path,
                "name": Path(src_path).name,
                "user_evidence": "User interaction observed (Delete key/click)"
            },
            semantic_action="DELETE",
            source="USER_INPUT"
        )


class ActivityCollector:
    """
    Generic Real Desktop Activity Collector.
    Observes real Windows desktop interactions between START RECORDING and STOP RECORDING:
    - Foreground window switches and application launches
    - Keystrokes, aggregated typing, and keyboard shortcuts
    - Global mouse clicks with target UI element discovery
    - Real-time filesystem changes across user directories and sandbox
    """
    def __init__(self, sandbox_dir: Optional[Path] = None):
        self.is_recording = False
        self.current_session_id: Optional[str] = None
        self.current_recording_id: Optional[str] = None
        self.events_buffer: List[Dict[str, Any]] = []
        self.lock = threading.Lock()

        # Listeners & threads
        self.mouse_listener: Optional[Any] = None
        self.keyboard_listener: Optional[Any] = None
        self.window_observer_thread: Optional[threading.Thread] = None
        self.typing_flusher_thread: Optional[threading.Thread] = None
        self.fs_observer: Optional[Any] = None

        # Typing aggregation state
        self.typing_buffer: str = ""
        self.typing_last_time: float = 0.0
        self.typing_app: str = "Active Application"
        self.typing_window: str = "Active Window"
        self.modifier_keys: set = set()

        # Window tracking state
        self.last_foreground_hwnd: int = 0
        self.last_foreground_app: str = ""
        self.last_foreground_title: str = ""

        # User interaction timing & context (generic evidence for user launches vs background processes)
        self.last_user_click_time: float = 0.0
        self.last_user_click_pos: tuple = (0, 0)
        self.last_user_click_element: str = ""
        self.last_user_click_app: str = ""
        self.last_user_key_time: float = 0.0

        # User explicit delete interaction evidence tracking (Requirement 1, 5, 6, 9)
        self.last_user_delete_key_time: float = 0.0
        self.last_user_delete_click_time: float = 0.0

        # Desktop Recording Overlay HUD process & PID tracking
        self.overlay_pid: Optional[int] = None
        self.overlay_process: Optional[Any] = None

        # Default directories to watch
        self.base_sandbox = sandbox_dir or (Path(__file__).resolve().parent / "sandbox")

    def set_overlay_pid(self, pid: int):
        """Register the desktop recording overlay PID to suppress self-recording."""
        self.overlay_pid = pid

    def get_active_window_info(self) -> Dict[str, Any]:
        """Retrieve the currently focused window, application, class, and process path safely."""
        app_name = "Desktop"
        window_title = "Desktop Workspace"
        class_name = ""
        exe_path = ""
        pid_val = 0

        if HAS_WIN32:
            try:
                attach_thread_to_desktop()
                hwnd = win32gui.GetForegroundWindow()
                if hwnd:
                    title = win32gui.GetWindowText(hwnd)
                    if title:
                        window_title = title.strip()
                    cname = win32gui.GetClassName(hwnd)
                    if cname:
                        class_name = cname.strip()
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if pid:
                        pid_val = pid
                        try:
                            proc = psutil.Process(pid)
                            app_name = proc.name()
                            exe_path = proc.exe()
                        except Exception:
                            pass
            except Exception:
                pass
        return {
            "app_name": app_name,
            "window_title": window_title,
            "class_name": class_name,
            "exe_path": exe_path,
            "pid": pid_val
        }

    def start_recording(self, session_name: Optional[str] = None) -> str:
        """Start a new generic desktop observation session."""
        with self.lock:
            self.is_recording = True
            rec_id = f"rec_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            self.current_recording_id = rec_id
            self.current_session_id = rec_id
            self.events_buffer.clear()
            self.typing_buffer = ""
            self.modifier_keys.clear()
            self.last_foreground_hwnd = 0
            self.last_user_click_time = 0.0
            self.last_user_click_pos = (0, 0)
            self.last_user_click_element = ""
            self.last_user_click_app = ""
            self.last_user_key_time = 0.0
            self.last_user_delete_key_time = 0.0
            self.last_user_delete_click_time = 0.0

        print(f"\n==================================================")
        print(f"[TEACH] New recording_id = {rec_id}")
        print(f"==================================================")

        # 1. Start Window & Process Focus Observer Thread
        self.window_observer_thread = threading.Thread(
            target=self._window_observer_loop,
            daemon=True,
            name="ActivityWindowObserver"
        )
        self.window_observer_thread.start()

        # Launch always-on-top desktop recording overlay (Tkinter HUD)
        try:
            overlay_script = Path(__file__).resolve().parent / "desktop_overlay.py"
            if overlay_script.exists():
                self.overlay_process = subprocess.Popen([sys.executable, str(overlay_script)])
                self.overlay_pid = self.overlay_process.pid
        except Exception as e:
            print(f"[ActivityCollector] Desktop overlay skipped: {e}")

        # 2. Start Typing Flush Daemon Thread
        self.typing_flusher_thread = threading.Thread(
            target=self._typing_flusher_loop,
            daemon=True,
            name="ActivityTypingFlusher"
        )
        self.typing_flusher_thread.start()

        # 3. Start Global Mouse Listener
        if HAS_PYNPUT:
            try:
                self.mouse_listener = mouse.Listener(on_click=self._on_mouse_click)
                self.mouse_listener.daemon = True
                self.mouse_listener.start()
            except Exception as e:
                print(f"[ActivityCollector] Mouse listener initialization skipped: {e}")
                self.mouse_listener = None

        # 4. Start Global Keyboard Listener
        if HAS_PYNPUT:
            try:
                self.keyboard_listener = keyboard.Listener(
                    on_press=self._on_key_press,
                    on_release=self._on_key_release
                )
                self.keyboard_listener.daemon = True
                self.keyboard_listener.start()
            except Exception as e:
                print(f"[ActivityCollector] Keyboard listener initialization skipped: {e}")
                self.keyboard_listener = None

        # 5. Start Real Multi-Directory Filesystem Observer
        if HAS_WATCHDOG:
            try:
                self.fs_observer = Observer()
                fs_handler = FileActivityHandler(self)

                # Schedule on Sandbox
                self.base_sandbox.mkdir(parents=True, exist_ok=True)
                self.fs_observer.schedule(fs_handler, str(self.base_sandbox), recursive=True)

                # Schedule on standard user directories if accessible
                watch_candidates = [
                    Path.home() / "Desktop",
                    Path.home() / "OneDrive" / "Desktop",
                    Path.home() / "Downloads",
                    Path.home() / "Documents"
                ]
                for p in watch_candidates:
                    if p.exists() and p.is_dir():
                        try:
                            self.fs_observer.schedule(fs_handler, str(p), recursive=False)
                        except Exception:
                            pass

                self.fs_observer.start()
            except Exception as e:
                print(f"[ActivityCollector] Filesystem observer skipped: {e}")
                self.fs_observer = None

        # Record Initial Session Trigger Event
        win_info = self.get_active_window_info()
        self.record_event(
            event_type="SESSION_START",
            app_name=win_info["app_name"],
            window_title=win_info["window_title"],
            details={"session_id": self.current_session_id, "name": session_name or "Teaching Session"},
            semantic_action="START_TEACHING"
        )
        return self.current_session_id

    def stop_recording(self) -> List[Dict[str, Any]]:
        """Stop teaching session and return collected structured events."""
        with self.lock:
            self.is_recording = False
            session_id = self.current_session_id

        # Flush any pending typing buffer
        self.flush_typing_buffer()

        # Stop Mouse Listener
        if self.mouse_listener:
            try:
                self.mouse_listener.stop()
            except Exception:
                pass
            self.mouse_listener = None

        # Stop Keyboard Listener
        if self.keyboard_listener:
            try:
                self.keyboard_listener.stop()
            except Exception:
                pass
            self.keyboard_listener = None

        # Stop Filesystem Observer
        if self.fs_observer:
            try:
                self.fs_observer.stop()
                self.fs_observer.join(timeout=1.0)
            except Exception:
                pass
            self.fs_observer = None

        # Stop Desktop Recording Overlay
        if self.overlay_process:
            try:
                self.overlay_process.terminate()
                self.overlay_process.wait(timeout=1.0)
            except Exception:
                pass
            self.overlay_process = None
            self.overlay_pid = None

        if session_id:
            win_info = self.get_active_window_info()
            self.record_event(
                event_type="SESSION_STOP",
                app_name=win_info["app_name"],
                window_title=win_info["window_title"],
                details={"session_id": session_id, "recording_id": self.current_recording_id, "event_count": len(self.events_buffer)},
                semantic_action="STOP_TEACHING",
                source="SYSTEM"
            )

        with self.lock:
            # Requirement 2: Strict Session Isolation
            rec_id = self.current_recording_id or self.current_session_id
            isolated_events = [e for e in self.events_buffer if e.get("recording_id") == rec_id or e.get("session_id") == rec_id]
            return list(isolated_events)

    def record_event(
        self,
        event_type: str,
        app_name: str,
        window_title: str,
        details: Dict[str, Any],
        semantic_action: Optional[str] = None,
        source: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Record an individual normalized event into memory and SQLite."""
        if not self.is_recording:
            return None

        # Filter out self-referential IDE/server window events if irrelevant
        app_lower = app_name.lower()
        if "antigravity" in app_lower and event_type in ("WINDOW_FOCUS", "UI_CLICK"):
            # Still record if intentional, but skip transient focus switches
            pass

        clean_sem = semantic_action or event_type
        clean_target = (
            details.get("path")
            or details.get("file")
            or details.get("folder")
            or details.get("app")
            or details.get("element")
            or details.get("hotkey")
            or details.get("url")
            or window_title
        )

        # Derive event source
        if not source:
            if event_type in ("KEY_PRESS", "SHORTCUT", "TEXT_INPUT", "TYPE", "UI_CLICK"):
                source = "USER_INPUT"
            elif event_type in ("WINDOW_FOCUS", "SESSION_START", "SESSION_STOP"):
                source = "WINDOW"
            elif event_type.startswith("FILE_") or event_type.startswith("DIRECTORY_"):
                source = "FILESYSTEM"
            else:
                source = "OBSERVED"

        rec_id = self.current_recording_id or self.current_session_id or "rec_default"
        ev_idx = len(self.events_buffer) + 1
        ev_id = f"{rec_id}_ev_{ev_idx}"

        event = {
            "event_id": ev_id,
            "session_id": rec_id,
            "recording_id": rec_id,
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "app_name": app_name,
            "window_title": window_title,
            "details": details,
            "semantic_action": clean_sem,
            "action_type": clean_sem,
            "target": str(clean_target),
            "source": source,
            "parameters": details,
            "confidence": 0.85
        }

        with self.lock:
            self.events_buffer.append(event)

        try:
            log_activity_event(
                session_id=rec_id,
                event_type=event_type,
                app_name=app_name,
                window_title=window_title,
                details=details,
                semantic_action=clean_sem
            )
        except Exception:
            pass

        return event

    def flush_typing_buffer(self):
        """Flush accumulated typing into a single high-level semantic TYPE action."""
        text_to_flush = ""
        app_name = ""
        win_title = ""
        with self.lock:
            if self.typing_buffer:
                text_to_flush = self.typing_buffer
                app_name = self.typing_app
                win_title = self.typing_window
                self.typing_buffer = ""

        if text_to_flush:
            self.record_event(
                event_type="TEXT_INPUT",
                app_name=app_name or "Active Application",
                window_title=win_title or "Active Window",
                details={"text": text_to_flush, "target": win_title, "length": len(text_to_flush)},
                semantic_action="TYPE",
                source="USER_INPUT"
            )

    def _typing_flusher_loop(self):
        """Background loop flushing typing buffer when user pauses typing."""
        while self.is_recording:
            time.sleep(0.2)
            should_flush = False
            with self.lock:
                if self.typing_buffer and (time.time() - self.typing_last_time > 0.65):
                    should_flush = True
            if should_flush:
                self.flush_typing_buffer()

    def _window_observer_loop(self):
        """Background loop actively tracking foreground window & active application changes."""
        attach_thread_to_desktop()

        while self.is_recording:
            try:
                if HAS_WIN32:
                    hwnd = win32gui.GetForegroundWindow()
                    if hwnd and hwnd != self.last_foreground_hwnd:
                        title = win32gui.GetWindowText(hwnd).strip()
                        cname = win32gui.GetClassName(hwnd).strip()
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)

                        # Ignore the recording overlay itself so it never becomes an action target
                        if (self.overlay_pid and pid == self.overlay_pid) or ("workflowos teach by doing" in title.lower()):
                            continue

                        pname = "Desktop"
                        exe_path = ""
                        ppid = 0
                        parent_name = ""
                        try:
                            p = psutil.Process(pid)
                            pname = p.name()
                            exe_path = p.exe()
                            ppid = p.ppid()
                            if ppid:
                                try:
                                    parent_proc = psutil.Process(ppid)
                                    parent_name = parent_proc.name()
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        # Window geometry & style evidence
                        is_visible = win32gui.IsWindowVisible(hwnd) if HAS_WIN32 else True
                        width = 0
                        height = 0
                        is_tool_window = False
                        is_app_window = False
                        has_owner = False
                        try:
                            rect = win32gui.GetWindowRect(hwnd)
                            width = rect[2] - rect[0]
                            height = rect[3] - rect[1]
                            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                            is_tool_window = bool(ex_style & win32con.WS_EX_TOOLWINDOW)
                            is_app_window = bool(ex_style & win32con.WS_EX_APPWINDOW)
                            owner_hwnd = win32gui.GetWindow(hwnd, win32con.GW_OWNER)
                            has_owner = bool(owner_hwnd != 0)
                        except Exception:
                            pass

                        # Flush any typing from previous window
                        self.flush_typing_buffer()

                        # Discern window type dynamically
                        is_folder = (pname.lower() == "explorer.exe" and cname in ("CabinetWClass", "ExploreWClass"))
                        is_browser = pname.lower() in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe")

                        # Timing correlation with user input
                        now = time.time()
                        time_since_click = (now - self.last_user_click_time) if self.last_user_click_time > 0 else 9999.0
                        time_since_key = (now - self.last_user_key_time) if self.last_user_key_time > 0 else 9999.0

                        clean_app = pname.replace(".exe", "")

                        details = {
                            "app": clean_app,
                            "exe": exe_path,
                            "pid": pid,
                            "ppid": ppid,
                            "parent_name": parent_name,
                            "class": cname,
                            "title": title,
                            "width": width,
                            "height": height,
                            "is_visible": is_visible,
                            "is_tool_window": is_tool_window,
                            "is_app_window": is_app_window,
                            "has_owner": has_owner,
                            "time_since_click": round(time_since_click, 3),
                            "time_since_key": round(time_since_key, 3),
                            "last_clicked_element": self.last_user_click_element
                        }

                        if is_folder and title:
                            details.update({"folder": title, "path": title})
                            self.record_event(
                                event_type="WINDOW_FOCUS",
                                app_name=pname,
                                window_title=title,
                                details=details,
                                semantic_action="OPEN_FOLDER"
                            )
                        elif is_browser:
                            # Generic URL/Domain extraction from browser window title
                            url_info = extract_browser_url_and_domain(title=title)
                            url = url_info.get("url")
                            domain = url_info.get("domain")
                            details.update({"url": url, "domain": domain, "browser": True})
                            self.record_event(
                                event_type="BROWSER_NAVIGATE" if url else "WINDOW_FOCUS",
                                app_name=pname,
                                window_title=title,
                                details=details,
                                semantic_action="BROWSER_NAVIGATE" if url else "WINDOW_FOCUS"
                            )
                        else:
                            self.record_event(
                                event_type="WINDOW_FOCUS",
                                app_name=pname,
                                window_title=title,
                                details=details,
                                semantic_action="WINDOW_FOCUS"
                            )

                        self.last_foreground_hwnd = hwnd
                        self.last_foreground_app = pname
                        self.last_foreground_title = title
                        self.typing_app = pname
                        self.typing_window = title

            except Exception:
                pass

            time.sleep(0.15)

    def _on_mouse_click(self, x, y, button, pressed):
        """Global mouse click callback for discovering clicked UI elements."""
        if not self.is_recording or not pressed:
            return
        try:
            # Flush typing before a click
            self.flush_typing_buffer()

            attach_thread_to_desktop()
            ctrl_title = ""
            ctrl_class = ""
            if HAS_WIN32:
                ctrl_hwnd = win32gui.WindowFromPoint((x, y))
                if ctrl_hwnd:
                    ctrl_title = win32gui.GetWindowText(ctrl_hwnd).strip()
                    ctrl_class = win32gui.GetClassName(ctrl_hwnd).strip()
                    _, click_pid = win32process.GetWindowThreadProcessId(ctrl_hwnd)

                    # Ignore clicks on the recording overlay so it is never recorded
                    if (self.overlay_pid and click_pid == self.overlay_pid) or ("workflowos teach by doing" in ctrl_title.lower()):
                        return

            btn_name = button.name if hasattr(button, "name") else str(button)
            element_desc = ctrl_title or ctrl_class or f"Point({x}, {y})"

            # Record telemetry for user-initiated launch correlation
            now = time.time()
            self.last_user_click_time = now
            self.last_user_click_pos = (x, y)
            self.last_user_click_element = element_desc
            self.last_user_click_app = self.last_foreground_app or "Active Application"
            if any(del_kw in element_desc.lower() for del_kw in ("delete", "remove", "trash", "recycle")):
                self.last_user_delete_click_time = now

            self.record_event(
                event_type="UI_CLICK",
                app_name=self.last_foreground_app or "Active Application",
                window_title=self.last_foreground_title or "Active Window",
                details={
                    "x": x,
                    "y": y,
                    "button": btn_name,
                    "element": element_desc,
                    "control_class": ctrl_class,
                    "target": element_desc
                },
                semantic_action="CLICK",
                source="USER_INPUT"
            )
        except Exception:
            pass

    def _on_key_press(self, key):
        """Global key press listener handling modifiers, hotkeys, and typing."""
        if not self.is_recording:
            return
        try:
            # Ignore keystrokes directed at the overlay window
            if self.last_foreground_hwnd and HAS_WIN32:
                _, fg_pid = win32process.GetWindowThreadProcessId(self.last_foreground_hwnd)
                if self.overlay_pid and fg_pid == self.overlay_pid:
                    return

            self.last_user_key_time = time.time()
            # Modifier keys tracking
            if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
                self.modifier_keys.add("ctrl")
                return
            elif key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
                self.modifier_keys.add("alt")
                return
            elif key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
                self.modifier_keys.add("shift")
                return
            elif key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
                self.modifier_keys.add("win")
                return

            # Explicit user Delete key press (Requirement 1, 5, 6)
            if hasattr(keyboard.Key, "delete") and key == keyboard.Key.delete:
                self.flush_typing_buffer()
                self.last_user_delete_key_time = time.time()
                self.record_event(
                    event_type="KEY_PRESS",
                    app_name=self.last_foreground_app or "Active Application",
                    window_title=self.last_foreground_title or "Active Window",
                    details={"key": "Delete", "target": self.last_foreground_title},
                    semantic_action="DELETE",
                    source="USER_INPUT"
                )
                return

            # Hotkeys combinations (Ctrl + <key>)
            if "ctrl" in self.modifier_keys:
                char = ""
                try:
                    char = key.char.lower() if hasattr(key, "char") and key.char else ""
                except Exception:
                    pass
                if char:
                    self.flush_typing_buffer()
                    hk = f"Ctrl+{char.upper()}"
                    sem_map = {
                        "c": "COPY",
                        "v": "PASTE",
                        "s": "SAVE",
                        "a": "SELECT_ALL",
                        "z": "UNDO",
                        "f": "FIND",
                        "n": "NEW",
                        "w": "CLOSE_TAB"
                    }
                    sem = sem_map.get(char, "HOTKEY")
                    self.record_event(
                        event_type="SHORTCUT",
                        app_name=self.last_foreground_app or "Active Application",
                        window_title=self.last_foreground_title or "Active Window",
                        details={"hotkey": hk, "keys": f"ctrl+{char}", "target": self.last_foreground_title},
                        semantic_action=sem,
                        source="USER_INPUT"
                    )
                    return

            # Special Navigation / Enter / Escape keys
            if key == keyboard.Key.enter:
                self.flush_typing_buffer()
                self.record_event(
                    event_type="KEY_PRESS",
                    app_name=self.last_foreground_app or "Active Application",
                    window_title=self.last_foreground_title or "Active Window",
                    details={"key": "Enter", "target": self.last_foreground_title},
                    semantic_action="SUBMIT",
                    source="USER_INPUT"
                )
                return
            elif key == keyboard.Key.tab:
                self.flush_typing_buffer()
                self.record_event(
                    event_type="KEY_PRESS",
                    app_name=self.last_foreground_app or "Active Application",
                    window_title=self.last_foreground_title or "Active Window",
                    details={"key": "Tab"},
                    semantic_action="KEY_PRESS",
                    source="USER_INPUT"
                )
                return
            elif key == keyboard.Key.esc:
                self.flush_typing_buffer()
                self.record_event(
                    event_type="KEY_PRESS",
                    app_name=self.last_foreground_app or "Active Application",
                    window_title=self.last_foreground_title or "Active Window",
                    details={"key": "Escape"},
                    semantic_action="KEY_PRESS",
                    source="USER_INPUT"
                )
                return

            # Normal printable typing characters
            char = None
            try:
                char = key.char
            except AttributeError:
                if key == keyboard.Key.space:
                    char = " "
                elif key == keyboard.Key.backspace:
                    with self.lock:
                        if self.typing_buffer:
                            self.typing_buffer = self.typing_buffer[:-1]
                    return

            if char:
                with self.lock:
                    self.typing_buffer += char
                    self.typing_last_time = time.time()
                    self.typing_app = self.last_foreground_app or "Active Application"
                    self.typing_window = self.last_foreground_title or "Active Window"

        except Exception:
            pass

    def _on_key_release(self, key):
        """Global key release handler updating modifier state."""
        try:
            if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
                self.modifier_keys.discard("ctrl")
            elif key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r):
                self.modifier_keys.discard("alt")
            elif key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
                self.modifier_keys.discard("shift")
            elif key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
                self.modifier_keys.discard("win")
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        """Return the current recording status for real-time UI polling and desktop overlay."""
        with self.lock:
            count = len(self.events_buffer)
            recent = [
                {
                    "event_type": e.get("event_type"),
                    "semantic_action": e.get("semantic_action"),
                    "app_name": e.get("app_name"),
                    "window_title": e.get("window_title"),
                    "details": e.get("details"),
                    "timestamp": e.get("timestamp")
                }
                for e in self.events_buffer[-10:]
            ]

            active_app = self.last_foreground_app or "Desktop"
            clean_app = active_app.replace(".exe", "")
            if clean_app.lower() == "explorer":
                clean_app = "File Explorer"
            active_title = self.last_foreground_title or "Active Window"

            current_action = "Waiting for user action..."
            if self.typing_buffer:
                current_action = f"Typing: \"{self.typing_buffer[-22:]}\""
            elif self.events_buffer:
                last_ev = self.events_buffer[-1]
                sem = (last_ev.get("semantic_action") or last_ev.get("event_type") or "").upper()
                d = last_ev.get("details", {})
                if sem in ("TYPE", "TEXT_INPUT"):
                    current_action = f"Type: \"{d.get('text', '')[:22]}\""
                elif sem in ("CLICK", "UI_CLICK"):
                    elem = d.get("element") or d.get("target") or "UI Element"
                    current_action = f"Click: {str(elem)[:22]}"
                elif sem in ("HOTKEY", "SHORTCUT"):
                    current_action = f"Press {d.get('keys') or d.get('hotkey')}"
                elif sem in ("KEY_PRESS", "SUBMIT"):
                    current_action = f"Press {d.get('key', 'Enter')}"
                elif sem in ("BROWSER_NAVIGATE", "BROWSER_URL"):
                    url = d.get("url") or d.get("domain") or "Web"
                    current_action = f"Navigate: {str(url)[:25]}"
                elif sem in ("OPEN_FOLDER", "FOLDER_OPEN"):
                    current_action = f"Open folder: {d.get('folder', '')[:22]}"
                elif sem in ("OPEN_FILE", "FILE_OPEN"):
                    current_action = f"Open file: {Path(d.get('file', '')).name}"
                elif sem in ("MOVE", "FILE_MOVED"):
                    current_action = f"Move: {Path(d.get('source', '')).name}"
                elif sem in ("CREATE_FILE", "FILE_CREATED"):
                    current_action = f"Create file: {Path(d.get('path', '')).name}"
                elif sem in ("CREATE_FOLDER", "DIRECTORY_CREATED"):
                    current_action = f"Create directory: {Path(d.get('path', '')).name}"
                elif sem in ("WINDOW_FOCUS", "OPEN_APPLICATION"):
                    app_nm = d.get("app") or last_ev.get("app_name", "").replace(".exe", "")
                    current_action = f"Focus app: {app_nm}"

            return {
                "is_recording": self.is_recording,
                "session_id": self.current_session_id,
                "events_count": count,
                "active_app": clean_app,
                "active_title": active_title,
                "current_action": current_action,
                "latest_events": recent
            }

    def simulate_demonstration(self, demo_id: str) -> List[Dict[str, Any]]:
        """
        Inject a verified demonstration scenario for testing/demoing Teach-By-Doing
        without requiring manual hardware events.
        """
        self.start_recording(f"Demonstration: {demo_id}")

        if demo_id == "demo1_file_org":
            self.record_event(
                event_type="WINDOW_FOCUS",
                app_name="explorer.exe",
                window_title="Downloads",
                details={"folder": "Downloads", "path": "Downloads"},
                semantic_action="OPEN_FOLDER"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="FILE_OPEN",
                app_name="Acrobat.exe",
                window_title="offer_letter_draft.pdf",
                details={"file": "Downloads/offer_letter_draft.pdf", "format": "pdf"},
                semantic_action="OPEN_FILE"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="DOCUMENT_READ",
                app_name="Acrobat.exe",
                window_title="offer_letter_draft.pdf",
                details={"file": "Downloads/offer_letter_draft.pdf"},
                semantic_action="READ"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="FILE_RENAMED",
                app_name="explorer.exe",
                window_title="Downloads",
                details={"source": "Downloads/offer_letter_draft.pdf", "new_name": "Placement_Offer_Letter.pdf"},
                semantic_action="RENAME"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="FILE_MOVED",
                app_name="explorer.exe",
                window_title="Placement",
                details={"source": "Downloads/Placement_Offer_Letter.pdf", "destination": "Placement", "target": "Placement"},
                semantic_action="MOVE"
            )

        elif demo_id == "demo3_evolution":
            self.record_event(
                event_type="WINDOW_FOCUS",
                app_name="explorer.exe",
                window_title="Downloads",
                details={"folder": "Downloads", "path": "Downloads"},
                semantic_action="OPEN_FOLDER"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="DOCUMENT_READ",
                app_name="Acrobat.exe",
                window_title="offer_letter_draft.pdf",
                details={"file": "Downloads/offer_letter_draft.pdf", "category": "Placement/College"},
                semantic_action="READ"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="FILE_RENAMED",
                app_name="explorer.exe",
                window_title="Downloads",
                details={"source": "Downloads/offer_letter_draft.pdf", "new_name": "Placement_Offer_Letter.pdf"},
                semantic_action="RENAME"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="FILE_MOVED",
                app_name="explorer.exe",
                window_title="College/Placement",
                details={"source": "Downloads/Placement_Offer_Letter.pdf", "destination": "College/Placement", "target": "College/Placement"},
                semantic_action="MOVE"
            )

        elif demo_id == "browser_report":
            self.record_event(
                event_type="BROWSER_URL",
                app_name="chrome.exe",
                window_title="Company Portal - Reports",
                details={"url": "https://portal.internal/reports", "domain": "portal.internal"},
                semantic_action="BROWSER_NAVIGATE"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="UI_CLICK",
                app_name="chrome.exe",
                window_title="Company Portal - Reports",
                details={"element": "Reports Menu", "selector": "#reports-nav"},
                semantic_action="CLICK"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="UI_CLICK",
                app_name="chrome.exe",
                window_title="Monthly Report Tab",
                details={"element": "Monthly Report", "selector": "#monthly-tab"},
                semantic_action="CLICK"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="FILE_DOWNLOAD",
                app_name="chrome.exe",
                window_title="Downloads",
                details={"file": "Monthly_Report_March.pdf", "destination": "Reports"},
                semantic_action="DOWNLOAD"
            )

        elif demo_id == "browser_report_evolved":
            self.record_event(
                event_type="BROWSER_URL",
                app_name="chrome.exe",
                window_title="Company Portal - Analytics",
                details={"url": "https://portal.internal/analytics", "domain": "portal.internal"},
                semantic_action="BROWSER_NAVIGATE"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="UI_CLICK",
                app_name="chrome.exe",
                window_title="Company Portal - Analytics",
                details={"element": "Analytics Menu", "selector": "#analytics-nav"},
                semantic_action="CLICK"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="UI_CLICK",
                app_name="chrome.exe",
                window_title="Company Portal - Export",
                details={"element": "Export Data", "selector": "#export-btn"},
                semantic_action="CLICK"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="UI_CLICK",
                app_name="chrome.exe",
                window_title="Monthly Report Option",
                details={"element": "Monthly Report", "selector": "#monthly-report-opt"},
                semantic_action="CLICK"
            )
            time.sleep(0.05)
            self.record_event(
                event_type="FILE_DOWNLOAD",
                app_name="chrome.exe",
                window_title="Downloads",
                details={"file": "Monthly_Report_March.pdf", "destination": "Reports"},
                semantic_action="DOWNLOAD"
            )

        return self.stop_recording()


# Global activity collector instance
collector = ActivityCollector()
