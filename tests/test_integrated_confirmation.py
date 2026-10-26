"""Unified auto-Y toggle tests; synthetic dialogs only, no real chat transport."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import auto_y
import integrated_confirmation as confirm
from status_window import StatusWindow
from storage import ROOT
from PIL import ImageGrab


class ConfirmationSwitch(unittest.TestCase):
    def setUp(self):
        self.state = {'state':'awaiting_approval', 'contact':'synthetic contact', 'event_id':'event-1', 'pid':123}
        self.worker = Mock()
        self.worker.alive.return_value = True
        self.worker.owns.return_value = True
        self.worker.read_status.return_value = dict(self.state)
        self.auto = confirm.AutoConfirmation('synthetic contact')

    def test_disabled_never_scans_or_clicks(self):
        self.auto.enabled = False
        with patch.object(confirm, 'find_target') as find, patch.object(confirm.win32gui, 'PostMessage') as post:
            self.assertFalse(self.auto.poll(self.worker, self.state))
        find.assert_not_called()
        post.assert_not_called()

    def test_owned_dialog_is_clicked_only_once_per_event(self):
        with patch.object(confirm, 'find_target', return_value=(10,60)), patch.object(confirm.win32gui, 'PostMessage') as post:
            self.assertTrue(self.auto.poll(self.worker, self.state))
            self.assertFalse(self.auto.poll(self.worker, self.state))
        post.assert_called_once_with(60, 0xF5, 0, 0)
        self.assertEqual(self.auto.count, 1)

    def test_toggle_off_stops_new_events_and_on_can_handle_pending_dialog(self):
        with patch.object(confirm, 'find_target', return_value=(10,60)), patch.object(confirm.win32gui, 'PostMessage') as post:
            self.auto.enabled = False
            self.assertFalse(self.auto.poll(self.worker, self.state))
            self.auto.enabled = True
            self.assertTrue(self.auto.poll(self.worker, self.state))
            self.auto.enabled = False
            self.state['event_id'] = 'event-2'
            self.worker.read_status.return_value = dict(self.state)
            self.assertFalse(self.auto.poll(self.worker, self.state))
        post.assert_called_once()

    def test_foreign_worker_is_never_clicked(self):
        self.worker.owns.return_value = False
        with patch.object(confirm, 'find_target') as find:
            self.assertFalse(self.auto.poll(self.worker, self.state))
        find.assert_not_called()

    def test_exited_worker_is_never_clicked(self):
        self.worker.alive.return_value = False
        with patch.object(confirm, 'find_target') as find:
            self.assertFalse(self.auto.poll(self.worker, self.state))
        find.assert_not_called()

    def test_changed_event_invalidates_click(self):
        self.worker.read_status.return_value = {**self.state, 'event_id':'another-event'}
        with patch.object(confirm, 'find_target', return_value=(10,60)), patch.object(confirm.win32gui, 'PostMessage') as post:
            self.assertFalse(self.auto.poll(self.worker, self.state))
        post.assert_not_called()

    def test_changed_dialog_invalidates_click(self):
        with patch.object(confirm, 'find_target', side_effect=[(10,60),(20,70)]), patch.object(confirm.win32gui, 'PostMessage') as post:
            self.assertFalse(self.auto.poll(self.worker, self.state))
        post.assert_not_called()

    def test_saved_switch_restores_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            confirm.save_settings(root, False)
            self.assertFalse(confirm.read_settings(root))
            confirm.save_settings(root, True)
            self.assertTrue(confirm.read_settings(root))

    def test_malformed_settings_fall_back_to_preserved_auto_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'local').mkdir()
            (root/'local/ui-settings.json').write_text('{broken',encoding='utf-8')
            self.assertTrue(confirm.read_settings(root))


class NativeUnifiedWindow(unittest.TestCase):
    def test_unchecked_leaves_dialog_pending_checked_confirms_and_end_stops_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'local').mkdir()
            (root/'config.json').write_text(json.dumps({'allowed_contact':'synthetic contact'}),encoding='utf-8')
            confirm.save_settings(root, False)
            title = 'Muse 本机合成弹窗 ' + str(os.getpid())
            script = root/'fake_bridge.py'
            script.write_text('''import ctypes,json,os,time
from pathlib import Path
root=Path.cwd()
local=root/'local'
while not (local/'TRIGGER').exists():time.sleep(.02)
(local/'status.json').write_text(json.dumps({'state':'awaiting_approval','contact':'synthetic contact','event_id':'native-event','pid':os.getpid(),'updated':time.time()}),encoding='utf-8')
result=ctypes.windll.user32.MessageBoxW(None,'联系人：synthetic contact\\n收到：synthetic only\\n拟发送的完整内容：no chat is sent',TITLE,0x3|0x20|0x100)
(local/'result.json').write_text(json.dumps({'result':result}),encoding='utf-8')
(local/'status.json').write_text(json.dumps({'state':'listening','pid':os.getpid(),'updated':time.time()}),encoding='utf-8')
while not (local/'STOP').exists():time.sleep(.05)
'''.replace('TITLE', repr(title)),encoding='utf-8')
            observed = []
            app = StatusWindow(root, [sys.executable,str(script)], title='Muse 微信助手 · 合并版合成测试')
            app.contact_input.set('synthetic contact')
            app.start_button.invoke()
            def trigger():
                (root/'local/TRIGGER').touch()
            def enable():
                observed.append(not (root/'local/result.json').exists())
                observed.append(not app.auto_enabled.get())
                app.auto_checkbox.invoke()
                observed.append(confirm.read_settings(root))
            def verify_and_end():
                try:
                    result=json.loads((root/'local/result.json').read_text(encoding='utf-8'))
                    observed.append(result['result']==6)
                    observed.append(app.confirmation.count==1)
                    observed.append(app.worker.alive())
                    app.root.update_idletasks()
                    x,y=app.root.winfo_rootx(),app.root.winfo_rooty()
                    ImageGrab.grab((x,y,x+app.root.winfo_width(),y+app.root.winfo_height())).save(ROOT/'local/diagnostics/unified-status-window.png')
                finally:
                    app.end_button.invoke()
            app.root.after(500,trigger)
            app.root.after(1600,enable)
            app.root.after(3000,verify_and_end)
            app.root.after(7000,app.finish)
            with patch.object(auto_y,'TITLE',title):
                app.run()
            self.assertEqual(observed,[True,True,True,True,True,True])
            self.assertFalse(app.worker.alive())


if __name__=='__main__':
    unittest.main()
