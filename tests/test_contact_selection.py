"""Explicit contact selection before any listener or auto-confirmation starts."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import status_window
from status_window import StatusWindow
from contact_settings import save_contact, validate_contact
from integrated_confirmation import AutoConfirmation


class ContactSettings(unittest.TestCase):
    def test_empty_and_control_names_are_rejected(self):
        for value in ('', '   ', '\n', 'friend\nother', 'friend\t', 'a'*101):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    validate_contact(value)

    def test_unicode_contact_and_surrounding_spaces(self):
        self.assertEqual(validate_contact('  新好友🙂  '), '新好友🙂')

    def test_only_contact_configuration_is_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            original={'allowed_contact':'old','mode':'approve_each_reply','disclosure':'AI','poll_seconds':2}
            (root/'config.json').write_text(json.dumps(original),encoding='utf-8')
            self.assertEqual(save_contact(root,'新好友'),'新好友')
            self.assertEqual(json.loads((root/'config.json').read_text(encoding='utf-8')),
                             {**original,'allowed_contact':'新好友'})

    def test_invalid_name_never_changes_saved_contact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            path=root/'config.json'
            path.write_text('{"allowed_contact":"old"}',encoding='utf-8')
            before=path.read_bytes()
            with self.assertRaises(ValueError):save_contact(root,' ')
            self.assertEqual(path.read_bytes(),before)

    def test_bad_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            path=root/'config.json'
            path.write_text('{broken',encoding='utf-8')
            with self.assertRaises(ValueError):save_contact(root,'new')
            self.assertEqual(path.read_text(encoding='utf-8'),'{broken')


class StartGate(unittest.TestCase):
    def prepare(self, root):
        (root/'config.json').write_text(json.dumps({'allowed_contact':'previous friend','poll_seconds':2}),encoding='utf-8')

    def test_opening_window_and_empty_start_never_start_or_change_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.prepare(root)
            original=(root/'config.json').read_bytes()
            with patch.object(status_window,'BridgeWorker') as factory:
                app=StatusWindow(root,title='Muse · 合成选择测试')
                self.assertEqual(app.contact_input.get(),'')
                self.assertIsNone(app.worker)
                app.start_button.invoke()
                self.assertIn('请先输入',app.contact_notice.get())
                app.root.after(450,app.end_button.invoke)
                app.run()
                factory.assert_not_called()
            self.assertEqual((root/'config.json').read_bytes(),original)
            self.assertFalse((root/'local/STOP').exists())

    def test_valid_contact_starts_exactly_once_and_binds_auto_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.prepare(root)
            fake=Mock()
            fake.started=time.time()
            fake.read_status.return_value={'state':'listening'}
            fake.alive.return_value=True
            with patch.object(status_window,'BridgeWorker',return_value=fake) as factory:
                app=StatusWindow(root,title='Muse · 合成选择测试')
                try:
                    app.contact_input.set('  新好友🙂  ')
                    app.start_button.invoke()
                    app.start()
                    factory.assert_called_once()
                    self.assertEqual(app.selected_contact,'新好友🙂')
                    self.assertEqual(app.confirmation.contact,'新好友🙂')
                    self.assertEqual(json.loads((root/'config.json').read_text(encoding='utf-8'))['allowed_contact'],'新好友🙂')
                finally:
                    app.finish()

    def test_save_failure_does_not_start_listener(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.prepare(root)
            with patch.object(status_window,'BridgeWorker') as factory, \
                 patch.object(status_window,'save_contact',side_effect=OSError('synthetic write failure')):
                app=StatusWindow(root,title='Muse · 合成选择测试')
                try:
                    app.contact_input.set('new friend')
                    app.start_button.invoke()
                    self.assertFalse(app.start_requested)
                    self.assertIsNone(app.worker)
                    self.assertIn('synthetic write failure',app.contact_notice.get())
                    factory.assert_not_called()
                finally:
                    app.finish()

    def test_real_synthetic_worker_loads_new_contact_only_after_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.prepare(root)
            script=root/'worker.py'
            script.write_text('''import json,os,time
from pathlib import Path
r=Path.cwd();p=r/'local';p.mkdir(exist_ok=True)
contact=json.loads((r/'config.json').read_text(encoding='utf-8'))['allowed_contact']
(p/'status.json').write_text(json.dumps({'state':'listening','contact':contact,'pid':os.getpid(),'updated':time.time()}),encoding='utf-8')
while not (p/'STOP').exists():time.sleep(.02)
''',encoding='utf-8')
            app=StatusWindow(root,[sys.executable,str(script)],title='Muse · 合成选择测试')
            self.assertFalse((root/'local/status.json').exists())
            self.assertIsNone(app.worker)
            app.contact_input.set('自定义好友')
            app.start_button.invoke()
            observed=[]
            def verify_and_close():
                observed.append(app.worker.read_status().get('contact'))
                app.end_button.invoke()
            app.root.after(1000,verify_and_close)
            app.root.after(5000,app.finish)
            app.run()
            self.assertEqual(observed,['自定义好友'])
            self.assertFalse(app.worker.alive())

    def test_old_contact_dialog_is_not_confirmed_for_new_selection(self):
        watcher=AutoConfirmation('new friend')
        worker=Mock()
        worker.alive.return_value=True
        worker.owns.return_value=True
        state={'state':'awaiting_approval','contact':'previous friend','event_id':'old-event','pid':123}
        with patch('integrated_confirmation.win32gui.PostMessage') as post:
            self.assertFalse(watcher.poll(worker,state))
        post.assert_not_called()


if __name__=='__main__':
    unittest.main()
