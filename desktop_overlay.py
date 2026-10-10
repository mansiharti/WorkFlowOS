"""
WorkFlowOS Always-On-Top Desktop Recording Overlay.
A sleek, draggable floating HUD widget that displays the real desktop recording state:
- Live action count
- Current action description
- Currently active application
- Direct 'STOP TEACHING' button
Independent of the browser window; stays visible above Chrome, Explorer, or any other app.
"""

import sys
import time
import threading
import tkinter as tk
from typing import Optional

BASE_URL = "http://127.0.0.1:8000"

class DesktopRecordingOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("WorkFlowOS Teach by Doing")
        
        # Dimensions & screen placement (top-right corner)
        width = 310
        height = 190
        screen_w = self.root.winfo_screenwidth()
        x_pos = max(20, screen_w - width - 30)
        y_pos = 40
        self.root.geometry(f"{width}x{height}+{x_pos}+{y_pos}")
        self.root.resizable(False, False)

        # Always on top
        self.root.attributes("-topmost", True)
        
        # Borderless window with custom dark titlebar
        self.root.overrideredirect(True)
        self.root.configure(bg="#0b0f19")

        # Variables for dragging
        self._drag_start_x = 0
        self._drag_start_y = 0

        # State tracking
        self.is_stopping = False
        self.consecutive_errors = 0

        self._build_ui()
        self._bind_drag_events()

        # Start periodic polling loop
        self.root.after(200, self._poll_status)

    def _build_ui(self):
        # Outer border frame
        self.border_frame = tk.Frame(self.root, bg="#2563eb", bd=1)
        self.border_frame.pack(fill=tk.BOTH, expand=True)

        self.main_container = tk.Frame(self.border_frame, bg="#090d16", padx=14, pady=10)
        self.main_container.pack(fill=tk.BOTH, expand=True)

        # Header: Red recording dot + TEACHING title + drag hint
        header_frame = tk.Frame(self.main_container, bg="#090d16")
        header_frame.pack(fill=tk.X, pady=(0, 6))

        self.dot_label = tk.Label(
            header_frame,
            text="🔴",
            font=("Segoe UI", 11),
            fg="#ef4444",
            bg="#090d16"
        )
        self.dot_label.pack(side=tk.LEFT, padx=(0, 5))

        self.title_label = tk.Label(
            header_frame,
            text="TEACHING RECORDING",
            font=("Segoe UI", 9, "bold"),
            fg="#f87171",
            bg="#090d16"
        )
        self.title_label.pack(side=tk.LEFT)

        self.drag_hint = tk.Label(
            header_frame,
            text="⋮⋮ Drag",
            font=("Segoe UI", 8),
            fg="#64748b",
            bg="#090d16",
            cursor="fleur"
        )
        self.drag_hint.pack(side=tk.RIGHT)

        # Actions captured counter
        self.count_frame = tk.Frame(self.main_container, bg="#090d16")
        self.count_frame.pack(fill=tk.X, pady=(0, 3))

        self.count_label = tk.Label(
            self.count_frame,
            text="Actions captured: 0",
            font=("Segoe UI", 10, "bold"),
            fg="#34d399",
            bg="#090d16"
        )
        self.count_label.pack(anchor="w")

        # Current action
        self.action_label = tk.Label(
            self.main_container,
            text="Current action: Waiting for user...",
            font=("Segoe UI", 9),
            fg="#e2e8f0",
            bg="#090d16",
            anchor="w",
            justify=tk.LEFT
        )
        self.action_label.pack(fill=tk.X, pady=(0, 2))

        # Active application
        self.app_label = tk.Label(
            self.main_container,
            text="Active app: Desktop",
            font=("Segoe UI", 8),
            fg="#94a3b8",
            bg="#090d16",
            anchor="w",
            justify=tk.LEFT
        )
        self.app_label.pack(fill=tk.X, pady=(0, 10))

        # Stop Teaching button
        self.stop_btn = tk.Button(
            self.main_container,
            text="⏹  STOP TEACHING",
            font=("Segoe UI", 9, "bold"),
            bg="#dc2626",
            fg="#ffffff",
            activebackground="#b91c1c",
            activeforeground="#ffffff",
            bd=0,
            padx=10,
            pady=5,
            cursor="hand2",
            command=self._on_stop_clicked
        )
        self.stop_btn.pack(fill=tk.X)

    def _bind_drag_events(self):
        # Enable dragging the window from any part of the header or background
        for w in [self.root, self.border_frame, self.main_container, self.title_label, self.drag_hint, self.dot_label]:
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._do_drag)

    def _start_drag(self, event):
        self._drag_start_x = event.x_root - self.root.winfo_x()
        self._drag_start_y = event.y_root - self.root.winfo_y()

    def _do_drag(self, event):
        x = event.x_root - self._drag_start_x
        y = event.y_root - self._drag_start_y
        self.root.geometry(f"+{x}+{y}")

    def _poll_status(self):
        if self.is_stopping:
            return

        # Keep on top
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
        except Exception:
            pass

        def _fetch():
            import requests
            try:
                r = requests.get(f"{BASE_URL}/api/teach/status", timeout=1.5)
                if r.status_code == 200:
                    data = r.json()
                    self.consecutive_errors = 0
                    self.root.after(0, self._apply_status, data)
                else:
                    self.consecutive_errors += 1
            except Exception:
                self.consecutive_errors += 1

            if self.consecutive_errors >= 15:
                # Server disconnected or session closed
                self.root.after(0, self.root.destroy)

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()

        # Schedule next poll
        self.root.after(250, self._poll_status)

    def _apply_status(self, data):
        if not data.get("is_recording", False):
            # Recording stopped by user in browser
            self._close_overlay("Teaching stopped.")
            return

        cnt = data.get("events_count", 0)
        curr_act = data.get("current_action", "Observing...")
        act_app = data.get("active_app", "Desktop")

        self.count_label.config(text=f"Actions captured: {cnt}")
        
        # Truncate action display if long
        if len(curr_act) > 36:
            curr_act = curr_act[:33] + "..."
        self.action_label.config(text=f"Current action: {curr_act}")

        if len(act_app) > 30:
            act_app = act_app[:27] + "..."
        self.app_label.config(text=f"Active app: {act_app}")

    def _on_stop_clicked(self):
        if self.is_stopping:
            return
        self.is_stopping = True
        self.stop_btn.config(text="Processing...", state=tk.DISABLED, bg="#475569")
        self.title_label.config(text="PROCESSING WORKFLOW...", fg="#38bdf8")

        def _stop_api():
            import requests
            try:
                requests.post(f"{BASE_URL}/api/teach/stop", timeout=4.0)
            except Exception:
                pass
            self.root.after(400, self._close_overlay, "Workflow generated.")

        t = threading.Thread(target=_stop_api, daemon=True)
        t.start()

    def _close_overlay(self, msg=""):
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    overlay = DesktopRecordingOverlay()
    overlay.run()
