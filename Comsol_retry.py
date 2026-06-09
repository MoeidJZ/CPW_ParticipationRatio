"""
comsol_retry.py
---------------
Repeatedly tries to launch COMSOL Multiphysics every 5 minutes.

Closes ONLY the COMSOL license error dialog, identified by:
  - Window title is exactly "Error"
  - The window belongs to a comsol.exe process

Everything else on your desktop is left completely untouched.
Once COMSOL stays alive past the load grace period the script exits
and COMSOL keeps running normally.

Usage:
    python comsol_retry.py

Requirements:
    pip install pywin32
"""

import subprocess
import time
import sys
import logging
import ctypes
import ctypes.wintypes
import threading

# ── Configuration ────────────────────────────────────────────────────────────
COMSOL_PATH            = r"C:\Program Files\COMSOL\COMSOL62\Multiphysics\bin\win64\comsol.exe"
RETRY_INTERVAL_SECONDS = 300   # seconds between failed attempts (5 minutes)
DIALOG_POLL_INTERVAL   = 2     # how often (s) the watcher scans for the dialog
LAUNCH_GRACE_PERIOD    = 60    # seconds to watch after launch before declaring success
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("comsol_retry.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
EnumWnd  = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _get_window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if not length:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_process_name(hwnd: int) -> str:
    """Return the exe name (e.g. 'comsol.exe') that owns this window."""
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.wintypes.DWORD(1024)
        # QueryFullProcessImageNameW gives the full path
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.split("\\")[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _is_comsol_error_dialog(hwnd: int) -> bool:
    """
    Return True only for a visible top-level window that:
      1. Has the title exactly "Error"
      2. Is owned by a comsol.exe process
    """
    if not user32.IsWindowVisible(hwnd):
        return False
    if _get_window_title(hwnd) != "Error":
        return False
    return _get_process_name(hwnd) == "comsol.exe"


def _close_comsol_error_dialogs():
    """Find and send WM_CLOSE to any COMSOL 'Error' dialog that is open."""
    def callback(hwnd, _):
        if _is_comsol_error_dialog(hwnd):
            log.info("  ↳ Found COMSOL license error dialog — closing it.")
            # Try clicking OK first (IDOK = 1)
            user32.PostMessageW(hwnd, 0x0111, 1, 0)   # WM_COMMAND, IDOK
            time.sleep(0.2)
            # Belt-and-suspenders: also send WM_CLOSE in case OK didn't land
            user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
        return True

    user32.EnumWindows(EnumWnd(callback), 0)


def _dialog_watcher(stop_event: threading.Event):
    """Background thread: polls for the COMSOL error dialog until told to stop."""
    while not stop_event.is_set():
        _close_comsol_error_dialogs()
        time.sleep(DIALOG_POLL_INTERVAL)


def try_launch() -> bool:
    """
    Launch COMSOL once and watch it for LAUNCH_GRACE_PERIOD seconds.
      - Process exits within that window  →  license denied  →  return False
      - Process still alive after window  →  loaded OK       →  return True
    On success the script exits; COMSOL keeps running normally.
    """
    log.info("Launching COMSOL ...")
    try:
        proc = subprocess.Popen(
            [COMSOL_PATH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        log.error("COMSOL executable not found at:\n  %s", COMSOL_PATH)
        log.error("Please verify the path and try again.")
        sys.exit(1)
    except Exception as exc:
        log.warning("Could not start process: %s", exc)
        return False

    log.info("Process started (PID %d). Monitoring for %d s ...",
             proc.pid, LAUNCH_GRACE_PERIOD)

    stop_event = threading.Event()
    watcher    = threading.Thread(target=_dialog_watcher, args=(stop_event,), daemon=True)
    watcher.start()

    deadline = time.time() + LAUNCH_GRACE_PERIOD
    while time.time() < deadline:
        if proc.poll() is not None:   # process exited on its own
            stop_event.set()
            log.warning("COMSOL process exited early — license not available.")
            return False
        time.sleep(2)

    # Still running → loaded successfully
    stop_event.set()
    log.info("COMSOL is running (PID %d). Exiting retry script — COMSOL stays open.",
             proc.pid)
    return True


def main():
    log.info("=" * 60)
    log.info("COMSOL License Retry Script started.")
    log.info("Retry interval : %d minutes", RETRY_INTERVAL_SECONDS // 60)
    log.info("Grace period   : %d s", LAUNCH_GRACE_PERIOD)
    log.info("Target         : %s", COMSOL_PATH)
    log.info("=" * 60)

    attempt = 0
    while True:
        attempt += 1
        log.info("-- Attempt #%d --", attempt)

        if try_launch():
            log.info("Done! COMSOL is open. Have a great session.")
            break

        log.info(
            "Attempt #%d failed. Retrying in %d minutes.  Press Ctrl-C to cancel.",
            attempt, RETRY_INTERVAL_SECONDS // 60,
        )
        try:
            time.sleep(RETRY_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            log.info("Cancelled by user. Goodbye.")
            sys.exit(0)


if __name__ == "__main__":
    main()