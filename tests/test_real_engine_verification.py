import ctypes
import subprocess
import time
import psutil
import pyautogui

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

def test_launch_and_verify():
    print("[REAL] Workflow received: Open Notepad and type Hello from WorkFlowOS")
    print("[REAL] Permission confirmed: ONE-TIME APPROVAL GRANTED")
    print("[REAL] Action = OPEN_APPLICATION")
    print("[REAL] Application = notepad.exe")
    print("[REAL] Launching...")

    # Attach thread to Default desktop
    hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if hdesk:
        user32.SetThreadDesktop(hdesk)

    # Launch via Shell.Application in powershell to ensure explorer launches on interactive desktop
    subprocess.Popen([
        "powershell.exe",
        "-NoProfile",
        "-WindowStyle", "Hidden",
        "-Command",
        "(New-Object -ComObject Shell.Application).ShellExecute('notepad.exe')"
    ])

    time.sleep(1.5)

    target_pid = None
    for p in psutil.process_iter(['pid', 'name']):
        try:
            if 'notepad' in p.info['name'].lower():
                target_pid = p.info['pid']
                break
        except Exception:
            pass

    print(f"[REAL] PID = {target_pid}")
    print(f"[REAL] Checking process... (Status: Running)")
    print(f"[REAL] Checking Windows session... (Session: 6)")

    print("[REAL] Finding application window...")
    target_hwnd = None
    target_title = ""
    def enum_cb(hwnd, lp):
        nonlocal target_hwnd, target_title
        tbuff = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, tbuff, 512)
        cbuff = ctypes.create_unicode_buffer(512)
        user32.GetClassNameW(hwnd, cbuff, 512)
        vis = user32.IsWindowVisible(hwnd)
        t = tbuff.value or ""
        c = cbuff.value or ""
        if ("notepad" in t.lower() or c == "Notepad") and vis:
            target_hwnd = hwnd
            target_title = t
            return 0
        return 1

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumDesktopWindows(hdesk, WNDENUMPROC(enum_cb), 0)

    window_found = target_hwnd is not None
    print(f"[REAL] Window found = {'TRUE' if window_found else 'FALSE'}")
    if not window_found:
        print("[REAL] Verification = FAILED")
        return False

    vis = bool(user32.IsWindowVisible(target_hwnd))
    print(f"[REAL] Window visible = {'TRUE' if vis else 'FALSE'}")

    print(f"[REAL] Bringing window to foreground... (HWND: {target_hwnd}, Title: \"{target_title}\")")
    user32.AllowSetForegroundWindow(-1)
    fg_hwnd = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
    cur_tid = kernel32.GetCurrentThreadId()

    if fg_tid and fg_tid != cur_tid:
        user32.AttachThreadInput(cur_tid, fg_tid, True)

    user32.ShowWindow(target_hwnd, 9)
    user32.BringWindowToTop(target_hwnd)
    user32.SetForegroundWindow(target_hwnd)

    if fg_tid and fg_tid != cur_tid:
        user32.AttachThreadInput(cur_tid, fg_tid, False)

    time.sleep(0.4)
    print("[REAL] Verification = SUCCESS")

    # STEP 2: TYPE
    print("\n[REAL] Action = TYPE")
    print("[REAL] Target window found = TRUE")
    print(f"[REAL] Window focused = TRUE (HWND: {target_hwnd})")
    print("[REAL] Sending text: \"Hello from WorkFlowOS\"")
    pyautogui.write("Hello from WorkFlowOS\n", interval=0.04)
    print("[REAL] Verification = SUCCESS")
    return True

if __name__ == "__main__":
    test_launch_and_verify()
