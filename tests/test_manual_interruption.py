"""Manual interruption recovery, using fake UI and transports only."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import bridge
from comtypes import COMError
from desktop_adapter import Message, NotReady, SendDeferred, WeChat
from storage import Journal


def row(key):
    return Message(key, key, 'mmui::ChatTextItemView', (0, 0, 100, 50))


class SendPhaseBoundary(unittest.TestCase):
    def setUp(self):
        self.wx = WeChat.__new__(WeChat)

    def test_input_readback_mismatch_is_recoverable_before_send(self):
        with patch.object(self.wx, '_prepare_send', side_effect=NotReady('input changed')):
            with self.assertRaises(SendDeferred):
                self.wx.send_approved('synthetic draft', [])

    def test_stale_ui_before_click_is_recoverable(self):
        stale = COMError(-2147220991, 'element unavailable', None)
        with patch.object(self.wx, '_prepare_send', side_effect=stale):
            with self.assertRaises(SendDeferred):
                self.wx.send_approved('synthetic draft', [])

    def test_click_exception_is_never_marked_as_unsent(self):
        button = Mock()
        button.Click.side_effect = COMError(-2147220991, 'click result uncertain', None)
        with patch.object(self.wx, '_prepare_send', return_value=(button, True)):
            with self.assertRaises(COMError):
                self.wx.send_approved('synthetic draft', [])
        button.Click.assert_called_once()

    def test_unconfirmed_delivery_is_not_clicked_twice(self):
        button = Mock()
        with patch.object(self.wx, '_prepare_send', return_value=(button, True)), \
             patch('desktop_adapter.time.monotonic', side_effect=[0, 6]):
            self.assertFalse(self.wx.send_approved('synthetic draft', []))
        button.Click.assert_called_once()

    def exercise_editor(self, initial, readback=None):
        self.wx.hwnd = 123
        self.wx.contact = 'synthetic contact'
        detail, edit, value = Mock(), Mock(), Mock()
        value.Value = initial
        edit.GetValuePattern.return_value = value
        if readback is not None:
            value.SetValue.side_effect = lambda text: setattr(value, 'Value', readback)
        with ExitStack() as stack:
            stack.enter_context(patch.object(self.wx, 'controls', return_value=(detail, edit, Mock())))
            stack.enter_context(patch.object(self.wx, 'snapshot', return_value=[]))
            for method in ('ShowWindow', 'SetForegroundWindow'):
                stack.enter_context(patch('desktop_adapter.win32gui.' + method))
            stack.enter_context(patch('desktop_adapter.win32gui.GetForegroundWindow', return_value=123))
            stack.enter_context(patch('desktop_adapter.time.sleep'))
            with self.assertRaises(SendDeferred):
                self.wx.send_approved('synthetic draft', [])
        detail.ButtonControl.assert_not_called()
        return value

    def test_existing_owner_draft_is_not_overwritten(self):
        value = self.exercise_editor('owner typing')
        value.SetValue.assert_not_called()
        self.assertEqual(value.Value, 'owner typing')

    def test_owner_edit_during_setvalue_is_preserved_without_click(self):
        value = self.exercise_editor('', 'owner changed the editor')
        value.SetValue.assert_called_once_with('synthetic draft')
        self.assertEqual(value.Value, 'owner changed the editor')


class BatchRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.tmp.name) / 'test.sqlite3')
        self.wx = Mock()
        self.wx.contact = bridge.CONFIG['allowed_contact']
        self.wx.snapshot.return_value = [row('in-0')]
        self.config = {**bridge.CONFIG, 'auto_y_enabled': False}
        self.patches = [patch.object(bridge, 'status'),
                        patch.object(bridge, 'record_failure'),
                        patch.object(bridge, 'wait_draft', return_value='synthetic reply'),
                        patch.object(bridge.STOP.__class__, 'exists', return_value=False)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.journal.db.close()
        self.tmp.cleanup()

    def process(self, key):
        return bridge.process_batch(self.wx, Mock(), self.journal,
                                    self.config['allowed_contact'], 'synthetic incoming',
                                    self.config, review=lambda *a: 6, source_keys=[key])

    def test_manual_interruption_skips_event_and_next_message_can_send(self):
        self.wx.send_approved.side_effect = [SendDeferred('input changed'), True]
        self.assertEqual(self.process('in-1'), 'skipped')
        self.assertEqual(self.process('in-2'), 'sent_ui')
        states = [r[0] for r in self.journal.db.execute('select state from events order by rowid')]
        self.assertEqual(states, ['skipped', 'sent_ui'])
        self.assertEqual(self.wx.send_approved.call_count, 2)

    def test_skipped_source_is_never_replayed(self):
        self.wx.send_approved.side_effect = SendDeferred('chat changed')
        self.assertEqual(self.process('same-incoming'), 'skipped')
        self.assertEqual(self.process('same-incoming'), 'skipped')
        self.wx.send_approved.assert_called_once()

    def test_stop_during_preparation_still_stops_listener(self):
        def stopped(*args):
            self.patches[-1].stop()
            self.patches[-1] = patch.object(bridge.STOP.__class__, 'exists', return_value=True)
            self.patches[-1].start()
            raise SendDeferred('stop requested')
        self.wx.send_approved.side_effect = stopped
        self.assertEqual(self.process('in-stop'), 'pause')

    def test_uncertain_click_still_requires_attention(self):
        self.wx.send_approved.side_effect = RuntimeError('click may have succeeded')
        self.assertEqual(self.process('in-uncertain'), 'pause')
        self.assertEqual(self.journal.db.execute('select state from events').fetchone()[0], 'unconfirmed')
        self.wx.send_approved.assert_called_once()


class ListenerRecovery(unittest.TestCase):
    def run_fake_listener(self, frames, times, outcomes, merge_seconds):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp)
            index = [0]
            stopped = [False]
            stop = Mock()
            stop.exists.side_effect = lambda: stopped[0]
            wx = Mock()
            wx.snapshot.side_effect = lambda: frames[index[0]]
            wx.direction.side_effect = lambda m: 'outgoing' if m.key.startswith('out') else 'incoming'
            calls = []
            states = []

            def on_status(state, **details):
                states.append(state)
                (local / 'status.json').write_text(json.dumps({'state': state}), encoding='utf-8')

            def on_batch(*args, **kwargs):
                calls.append(args[4])
                return outcomes[len(calls)-1]

            def tick(_):
                if index[0] >= len(frames)-1:
                    stopped[0] = True
                else:
                    index[0] += 1

            # run() takes its baseline before entering the loop. The first
            # current snapshot contains the first real arrival.
            def snapshot():
                if not getattr(snapshot, 'baselined', False):
                    snapshot.baselined = True
                    return frames[0]
                return frames[index[0]]

            wx.snapshot.side_effect = snapshot
            index[0] = 1
            config = {**bridge.CONFIG, 'merge_seconds': merge_seconds}
            with patch.object(bridge, 'LOCAL', local), patch.object(bridge, 'STOP', stop), \
                 patch.object(bridge, 'default_archive_root',return_value=local/'Documents'), \
                 patch.object(bridge, 'CONFIG', config), patch.object(bridge, 'acquire_lock', return_value=99), \
                 patch.object(bridge.win32api, 'CloseHandle'), patch.object(bridge, 'Journal'), \
                 patch.object(bridge, 'WeChat', return_value=wx), patch.object(bridge, 'Muse'), \
                 patch.object(bridge, 'status', side_effect=on_status), \
                 patch.object(bridge, 'process_batch', side_effect=on_batch), \
                 patch.object(bridge.time, 'sleep', side_effect=tick), \
                 patch.object(bridge.time, 'monotonic', side_effect=lambda: times[index[0]]):
                bridge.run()
            return calls, states

    def test_listener_continues_after_skipped_send(self):
        base, first, second = row('base'), row('in-first'), row('in-second')
        calls, states = self.run_fake_listener(
            [[base], [base, first], [base, first, second]],
            [0, 1, 2], ['skipped', 'sent_ui'], 0)
        self.assertEqual(calls, ['in-first', 'in-second'])
        self.assertNotIn('needs_attention', states)

    def test_manual_reply_clears_pending_but_next_incoming_is_processed(self):
        base, first, owner, second = row('base'), row('in-first'), row('out-owner'), row('in-second')
        calls, states = self.run_fake_listener(
            [[base], [base, first], [base, first, owner],
             [base, first, owner, second], [base, first, owner, second]],
            [0, 0, 4, 10, 14], ['sent_ui'], 3)
        self.assertEqual(calls, ['in-second'])


if __name__ == '__main__':
    unittest.main()
