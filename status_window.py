"""Visible lifecycle for one owned bridge worker; no message sending here."""
import json
import ctypes
import subprocess
import sys
import time
import uuid
import tkinter as tk
from tkinter import ttk
import win32api
import win32con
import win32event
import win32gui
import win32job
import win32process
from storage import ROOT
from integrated_confirmation import AutoConfirmation, read_settings, save_settings
from status_ui import build_interface, GREEN
from contact_settings import save_contact
from chat_settings import save_chat

TITLE = 'Muse 微信助手 · 运行状态'
MUTEX = 'Local\\MuseWeChatBridgeStatusWindow.v1'


def status_text(alive, state):
    if not alive:
        if state.get('state') == 'needs_attention' and state.get('phase') == 'startup':
            return '启动失败', state.get('reason') or '助手未能启动，请检查安装。'
        return '已停止', state.get('reason') or '微信助手进程已经结束。'
    names = {
        'starting': '正在启动…',
        'reading_context': '正在启动 · 读取最近对话',
        'listening': '正在运行 · 监听新消息',
        'waiting_muse': '正在运行 · 等待 Muse 回复',
        'reading_images': '正在运行 · 读取图片/表情包',
        'uploading_images': '正在运行 · 提交图片给 Muse',
        'waiting_muse_ui': '正在运行 · 等待 Muse 界面恢复',
        'awaiting_approval': '正在运行 · 等待确认',
        'sending': '正在运行 · 正在发送',
        'waiting_desktop': '正在运行 · 等待微信/Muse就绪',
        'reply_skipped': '正在运行 · 已跳过本条草稿',
        'draft_superseded': '正在运行 · 等待新消息处理',
        'sent_ui': '正在运行 · 本机已显示发送内容',
        'needs_attention': '即将停止 · 需要检查',
        'send_unconfirmed': '即将停止 · 发送结果不明',
        'stopped': '正在结束…',
    }
    return names.get(state.get('state'), '正在启动…'), state.get('reason', '')


class OwnedProcess:
    def __init__(self, handle, pid):
        self.handle = handle
        self.pid = pid
        self.returncode = None

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        if win32event.WaitForSingleObject(self.handle, 0) == win32con.WAIT_OBJECT_0:
            self.returncode = win32process.GetExitCodeProcess(self.handle)
            return self.returncode
        return None

    def terminate(self):
        win32api.TerminateProcess(self.handle, 0)

    def wait(self, timeout):
        if win32event.WaitForSingleObject(self.handle, int(timeout * 1000)) != win32con.WAIT_OBJECT_0:
            raise TimeoutError('等待微信助手进程结束超时。')
        self.returncode = win32process.GetExitCodeProcess(self.handle)


class BridgeWorker:
    """A Job Object makes the End button include the venv launcher's child."""
    def __init__(self, root=ROOT, command=None, resume_latest=False):
        self.root = root
        self.closed = False
        self.started = time.time()
        self.job = win32job.CreateJobObject(None, 'Local\\MuseBridgeWorker-' + uuid.uuid4().hex)
        limits = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
        limits['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, limits)
        self.process = None
        try:
            command = command or [str(root / '.venv/Scripts/pythonw.exe'), str(root / 'worker_entry.py'), 'resume' if resume_latest else 'run']
            # Assign the suspended launcher before it can create its venv child.
            handle, thread, pid, _ = win32process.CreateProcess(
                None, subprocess.list2cmdline(command), None, None, False,
                win32con.CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW,
                None, str(root), win32process.STARTUPINFO())
            self.process = OwnedProcess(handle, pid)
            try:
                win32job.AssignProcessToJobObject(self.job, handle)
                win32process.ResumeThread(thread)
            finally:
                thread.Close()
        except Exception:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=3)
            if self.process:
                self.process.handle.Close()
            self.job.Close()
            self.job = None
            raise

    def alive(self):
        return self.process.poll() is None

    def owns(self, pid):
        if not pid or not self.job:
            return False
        try:
            handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)
            try:
                return win32job.IsProcessInJob(handle, self.job)
            finally:
                handle.Close()
        except Exception:
            return False

    def read_status(self):
        try:
            data = json.loads((self.root / 'local/status.json').read_text(encoding='utf-8'))
            if data.get('updated', 0) < self.started:
                return {}
            if self.alive() and data.get('pid') and not self.owns(data['pid']):
                return {}
            return data
        except (OSError, ValueError):
            return {}

    def request_stop(self):
        local = self.root / 'local'
        local.mkdir(exist_ok=True)
        (local / 'STOP').touch()
        def dismiss(hwnd, _):
            if win32gui.GetClassName(hwnd) != '#32770' or win32gui.GetWindowText(hwnd) not in ('Muse 微信回复确认','Muse 微信群聊回复确认'):
                return
            if self.owns(win32process.GetWindowThreadProcessId(hwnd)[1]):
                cancel = win32gui.GetDlgItem(hwnd, 2)
                if cancel:
                    win32gui.PostMessage(cancel, win32con.BM_CLICK, 0, 0)
        win32gui.EnumWindows(dismiss, None)

    def close(self):
        if self.closed:
            return
        if self.job:
            win32job.TerminateJobObject(self.job, 0)
            self.job.Close()
            self.job = None
        if self.process:
            self.process.wait(timeout=3)
            self.process.handle.Close()
        self.closed = True


class StatusWindow:
    def __init__(self, root_path=ROOT, command=None, title=TITLE, resume_latest=False):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Ray.Muse.WeChatAssistant')
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
        self.root = tk.Tk()
        dpi = ctypes.windll.user32.GetDpiForWindow(self.root.winfo_id()) or 96
        self.ui_scale = dpi / 96
        self.root.tk.call('tk', 'scaling', dpi / 72)
        self.root.title(title)
        self.root.resizable(False, False)
        self.root_path = root_path
        self.command = command
        self.resume_latest = resume_latest
        self.worker = None
        self.stopping = False
        self.closed = False
        self.stop_deadline = None
        self.start_error = None
        self.auto_enabled = tk.BooleanVar(value=read_settings(root_path))
        self.selected_contact = None
        self.start_requested = False
        self.contact_input = tk.StringVar(value='')
        self.chat_mode = tk.StringVar(value='private')
        self.self_name_input = tk.StringVar(value='')
        self.selected_mode = 'private'
        self.selected_self_name = ''
        self.contact_notice = tk.StringVar(value='')
        self.contact_input.trace_add('write', lambda *args: self.contact_notice.set(''))
        self.confirmation = AutoConfirmation(None, self.auto_enabled.get())
        self.headline = tk.StringVar(value='等待选择好友')
        self.detail = tk.StringVar(value='请输入好友名称，再点击开始监测。')
        self.elapsed_seconds = 0
        build_interface(self, setup=True)
        self.root.protocol('WM_DELETE_WINDOW', self.request_stop)
        self.after_id = None

    def start(self):
        if self.closed or self.stopping or self.start_requested:
            return
        try:
            mode=self.chat_mode.get()
            if mode=='group':name=save_chat(self.root_path,mode,self.contact_input.get(),self.self_name_input.get())
            else:
                name=save_contact(self.root_path,self.contact_input.get())
                config=json.loads((self.root_path/'config.json').read_text(encoding='utf-8'))
                if config.get('chat_mode')=='group':save_chat(self.root_path,'private',name)
        except (ValueError, OSError) as exc:
            self.contact_notice.set(str(exc))
            self.contact_entry.focus_set()
            return
        self.start_requested = True
        self.selected_contact = name
        self.selected_mode = mode
        self.selected_self_name = self.self_name_input.get().strip() if mode=='group' else ''
        self.confirmation = AutoConfirmation(name, self.auto_enabled.get(),mode)
        self.headline.set('正在启动…')
        self.detail.set('正在连接所选群聊，仅正文 @ 本人时回复。' if mode=='group' else '正在连接所选好友的对话。')
        for widget in self.root.winfo_children():
            widget.destroy()
        build_interface(self)
        self.root.update_idletasks()
        try:
            self.worker = BridgeWorker(self.root_path, self.command, self.resume_latest)
        except Exception as exc:
            self.start_error = str(exc)
        self.refresh()

    def change_mode(self):
        if self.start_requested:return
        self.contact_input.set('');self.contact_notice.set('')
        for widget in self.root.winfo_children():widget.destroy()
        build_interface(self,setup=True)

    def toggle_auto(self):
        self.confirmation.enabled = self.auto_enabled.get()
        try:
            save_settings(self.root_path, self.confirmation.enabled)
        except OSError:
            self.auto_status.set('当前选择已生效，但未能保存到下次启动。')
            return
        self.update_auto_status()

    def update_auto_status(self):
        if self.confirmation.enabled:
            self.auto_status.set('确认弹窗会自动选择「是」并发送回复。\n下次启动沿用此设置。')
        else:
            self.auto_status.set('回复将等待你在弹窗中手动确认。\n下次启动沿用此设置。')
        if self.confirmation.enabled and self.confirmation.error:
            self.auto_status.set('自动确认遇到问题，正在重试：' + self.confirmation.error)

    def refresh(self):
        self.after_id = None
        if self.closed:
            return
        if self.stopping:
            if not self.worker or not self.worker.alive() or time.monotonic() >= self.stop_deadline:
                self.finish()
                return
        else:
            state = self.worker.read_status() if self.worker else {}
            alive = bool(self.worker and self.worker.alive())
            self.confirmation.poll(self.worker, state)
            self.update_auto_status()
            title, reason = status_text(alive, state)
            self.headline.set(title)
            if self.worker:
                if alive:
                    self.elapsed_seconds = int(time.time() - self.worker.started)
                hints = {
                    'listening': '等待所选好友的文字、图片或表情包。',
                    'reading_context': '正在整理当前好友最近的聊天，不会补发历史消息。',
                    'reading_images': '正在读取好友图片或表情包的可见画面。',
                    'uploading_images': '正在交给 Muse 看图，完成后将生成文字回复。',
                    'waiting_muse': 'Muse 正在生成回复，完成后将进入确认步骤。',
                    'awaiting_approval': '请在确认弹窗中选择是否发送本条回复。',
                    'sent_ui': '回复已在本机聊天中显示。',
                }
                if self.selected_mode=='group':
                    hints.update(listening='只回复正文 @'+self.selected_self_name+' 的新消息。',
                                 reading_context='正在整理本群上下文，历史消息不会补回。',
                                 reading_images='正在读取本次 @ 发言者的图片或表情包。')
                self.detail.set(reason or (hints.get(state.get('state'), '正在处理当前回复。') if alive else '助手已停止，关闭窗口后可重新启动。'))
                if alive and state.get('context_archive_error'):
                    self.detail.set('本地存档暂不可用，仍在监听并使用本次可见对话；请检查存档目录。')
            else:
                self.detail.set(self.start_error or '未能启动微信助手。')
            hours, remainder = divmod(self.elapsed_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.runtime_value.set(f'{hours:02d}:{minutes:02d}:{seconds:02d}')
            self.confirmed_value.set(str(self.confirmation.count) + ' 条')
            color = GREEN if alive else '#919C95'
            if state.get('state') in ('needs_attention', 'send_unconfirmed') or self.start_error:
                color = '#AE4545'
            elif state.get('state') in ('waiting_desktop', 'waiting_muse_ui'):
                color = '#A2742A'
            self.state_dot.configure(fg=color)
            self.end_button.configure(text='结束程序' if alive else '关闭窗口')
        self.after_id = self.root.after(300, self.refresh)

    def request_stop(self):
        if self.closed or self.stopping:
            return
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.stopping = True
        self.headline.set('正在结束…')
        if hasattr(self, 'state_dot'):
            self.state_dot.configure(fg='#919C95')
        self.end_button.configure(state='disabled')
        if hasattr(self, 'auto_checkbox'):
            self.auto_checkbox.configure(state='disabled')
        self.stop_deadline = time.monotonic() + 2
        if self.worker and self.worker.alive():
            try:
                self.worker.request_stop()
            except Exception:
                pass
        else:
            self.finish()
        if not self.closed:
            self.after_id = self.root.after(50, self.refresh)

    def finish(self):
        if self.closed:
            return
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        try:
            if self.worker:
                self.worker.close()
        finally:
            self.closed = True
            for callback in self.root.tk.call('after', 'info'):
                self.root.tk.call('after', 'cancel', callback)
            self.root.update_idletasks()
            self.root.destroy()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            if not self.closed:
                self.finish()


def show_existing():
    for _ in range(15):
        found = []
        win32gui.EnumWindows(lambda hwnd, unused: found.append(hwnd)
                             if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == TITLE else None, None)
        if found:
            win32gui.ShowWindow(found[0], win32con.SW_RESTORE)
            try:
                win32gui.SetForegroundWindow(found[0])
            except Exception:
                pass
            return
        time.sleep(.1)


def main():
    lock = win32event.CreateMutex(None, False, MUTEX)
    duplicate = win32api.GetLastError() == 183
    try:
        if duplicate:
            show_existing()
        else:
            StatusWindow(resume_latest='--resume' in sys.argv).run()
    finally:
        lock.Close()


if __name__ == '__main__':
    main()
