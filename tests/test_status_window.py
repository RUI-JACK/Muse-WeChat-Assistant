"""Real status-window/process lifecycle tests with synthetic workers only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from PIL import ImageGrab
from status_window import BridgeWorker, StatusWindow, status_text
from storage import ROOT
import status_window
import win32api
import win32con
import win32event


WORKER = r'''
import json, os, sys, time
from pathlib import Path
root = Path.cwd()
local = root / 'local'
local.mkdir(exist_ok=True)
(local/'STOP').unlink(missing_ok=True)
(local/'status.json').write_text(json.dumps({'state':'listening','updated':time.time(),'pid':os.getpid()}),encoding='utf-8')
if '--exit' in sys.argv:
    time.sleep(.3)
    (local/'status.json').write_text(json.dumps({'state':'needs_attention','updated':time.time(),'reason':'synthetic failure'}),encoding='utf-8')
    sys.exit(1)
while True:
    if '--ignore-stop' not in sys.argv and (local/'STOP').exists():
        break
    time.sleep(.05)
'''


class StatusLabels(unittest.TestCase):
    def test_exited_process_is_never_reported_as_running(self):
        self.assertEqual(status_text(False, {'state': 'listening'})[0], '已停止')

    def test_waiting_and_error_states_are_distinct(self):
        self.assertIn('等待确认', status_text(True, {'state': 'awaiting_approval'})[0])
        self.assertIn('即将停止', status_text(True, {'state': 'needs_attention'})[0])

    def test_duplicate_launch_reveals_existing_without_new_worker(self):
        name = 'Local\\MuseStatusTest-' + uuid.uuid4().hex
        lock = win32event.CreateMutex(None, False, name)
        try:
            with patch.object(status_window, 'MUTEX', name), \
                 patch.object(status_window, 'show_existing') as show, \
                 patch.object(status_window, 'StatusWindow') as window:
                status_window.main()
            show.assert_called_once()
            window.assert_not_called()
        finally:
            lock.Close()


class OwnedProcesses(unittest.TestCase):
    def make_worker(self, root, *args):
        path = root / 'fake_worker.py'
        path.write_text(WORKER, encoding='utf-8')
        return [sys.executable, str(path), *args]

    def wait_for(self, predicate, timeout=4):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if predicate():
                return
            time.sleep(.04)
        self.fail('Timed out waiting for synthetic worker')

    def test_job_ownership_status_and_graceful_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker = BridgeWorker(root, self.make_worker(root))
            try:
                self.wait_for(lambda: worker.read_status().get('state') == 'listening')
                self.assertTrue(worker.owns(worker.process.pid))
                self.assertFalse(worker.owns(os.getpid()))
                worker.request_stop()
                self.wait_for(lambda: not worker.alive())
            finally:
                worker.close()

    def test_closing_job_ends_stubborn_child_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker = BridgeWorker(root, self.make_worker(root, '--ignore-stop'))
            worker.close()
            self.assertFalse(worker.alive())

    def test_stale_or_foreign_status_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker = BridgeWorker(root, self.make_worker(root))
            try:
                self.wait_for(lambda: worker.read_status().get('state') == 'listening')
                status = root / 'local/status.json'
                status.write_text(json.dumps({'state':'listening','updated':worker.started-30,'pid':worker.process.pid}),encoding='utf-8')
                self.assertEqual(worker.read_status(), {})
                status.write_text(json.dumps({'state':'listening','updated':time.time(),'pid':os.getpid()}),encoding='utf-8')
                self.assertEqual(worker.read_status(), {})
            finally:
                worker.close()

    def test_end_terminates_worker_descendants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / 'parent.py'
            script.write_text("import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\nPath('child.pid').write_text(str(p.pid))\ntime.sleep(60)\n", encoding='utf-8')
            worker = BridgeWorker(root, [sys.executable, str(script)])
            handle = None
            try:
                self.wait_for(lambda: (root / 'child.pid').exists())
                pid = int((root / 'child.pid').read_text())
                self.assertTrue(worker.owns(pid))
                handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid)
                worker.close()
                self.assertEqual(win32event.WaitForSingleObject(handle, 3000), win32con.WAIT_OBJECT_0)
            finally:
                worker.close()
                if handle:
                    handle.Close()

    def test_window_shows_running_and_button_ends_owned_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = StatusWindow(root, self.make_worker(root), title='Muse 微信助手 · 合成状态测试')
            (root/'config.json').write_text(json.dumps({'allowed_contact':'old contact'}),encoding='utf-8')
            app.contact_input.set('synthetic contact')
            app.start_button.invoke()
            results = []
            def check_and_end():
                results.append('正在运行' in app.headline.get())
                results.append(app.worker is not None and app.worker.alive())
                app.root.update_idletasks()
                output = ROOT / 'local/diagnostics/bridge-status-window.png'
                output.parent.mkdir(exist_ok=True)
                x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
                ImageGrab.grab((x, y, x + app.root.winfo_width(), y + app.root.winfo_height())).save(output)
                app.end_button.invoke()
            app.root.after(1400, check_and_end)
            app.root.after(6000, app.finish)
            app.run()
            self.assertEqual(results, [True, True])
            self.assertTrue(app.closed)
            self.assertFalse(app.worker.alive())

    def test_unexpected_exit_is_displayed_and_window_stays_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = StatusWindow(root, self.make_worker(root, '--exit'), title='Muse 微信助手 · 合成退出测试')
            (root/'config.json').write_text(json.dumps({'allowed_contact':'old contact'}),encoding='utf-8')
            app.contact_input.set('synthetic contact')
            app.start_button.invoke()
            results = []
            def check_and_close():
                results.append(app.headline.get())
                results.append('synthetic failure' in app.detail.get())
                app.end_button.invoke()
            app.root.after(1500, check_and_close)
            app.root.after(6000, app.finish)
            app.run()
            self.assertEqual(results, ['已停止', True])


if __name__ == '__main__':
    unittest.main()
