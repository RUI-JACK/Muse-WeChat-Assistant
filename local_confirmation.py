"""Select YES only in this process's own explicitly automatic dialog."""
import os
import threading
import time
import win32con
import win32gui
import win32process

AUTO_TITLE = 'Muse 微信回复确认 · 本机自动确认'

def find_own_yes_button(owner_pid):
    found = []
    def enum(hwnd, _):
        if (win32gui.IsWindowVisible(hwnd)
                and win32gui.GetWindowText(hwnd) == AUTO_TITLE
                and win32gui.GetClassName(hwnd) == '#32770'
                and win32process.GetWindowThreadProcessId(hwnd)[1] == owner_pid):
            button = win32gui.GetDlgItem(hwnd,win32con.IDYES)
            if button and win32gui.GetClassName(button) == 'Button' and win32gui.IsWindowEnabled(button):
                found.append(button)
    win32gui.EnumWindows(enum,None)
    return found[0] if len(found)==1 else None

def confirm_own_dialog_when_ready(cancel,timeout=15):
    deadline = time.monotonic()+timeout
    while not cancel.is_set() and time.monotonic()<deadline:
        button = find_own_yes_button(os.getpid())
        if button:
            if cancel.wait(.5):
                return
            # Revalidate the exact button after the delay. No keyboard events,
            # desktop-wide clicking, foreign process, or platform permission UI.
            if find_own_yes_button(os.getpid()) == button and not cancel.is_set():
                win32gui.PostMessage(button,win32con.BM_CLICK,0,0)
            return
        cancel.wait(.05)

def start_confirmation_worker():
    cancel = threading.Event()
    thread = threading.Thread(target=confirm_own_dialog_when_ready,args=(cancel,),daemon=True)
    thread.start()
    return cancel,thread
