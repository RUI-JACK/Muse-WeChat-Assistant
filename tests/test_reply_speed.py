import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from comtypes import COMError
import bridge,desktop_adapter as desktop
from desktop_adapter import Muse,NotReady
from reply_metrics import ReplyTrace
from uia_fast_read import button_names,document_text


class FastMuseRead(unittest.TestCase):
    def setUp(self):
        self.muse=Muse.__new__(Muse);self.muse.end_label='Nora'
        self.doc=Mock();self.p=patch.object(self.muse,'document',return_value=self.doc);self.p.start()
    def tearDown(self):self.p.stop()

    def test_busy_cached_button_blocks_even_a_complete_old_block(self):
        with patch.object(desktop,'button_names',return_value=['停止生成']),patch.object(desktop,'document_text') as text:
            self.assertIsNone(self.muse.draft('event',500))
        text.assert_not_called()

    def test_complete_exact_event_uses_fast_text_without_tree_walk(self):
        text='REQUEST_END_event\nDRAFT_BEGIN_event\n纸箱豪宅又续住了。\nDRAFT_END_event'
        with patch.object(desktop,'button_names',return_value=['发送']),patch.object(desktop,'document_text',return_value=text),patch.object(desktop,'walk') as walk:
            self.assertEqual(self.muse.draft('event',500),'纸箱豪宅又续住了。')
        walk.assert_not_called()

    def test_unmarked_fast_text_never_bypasses_existing_control_reader(self):
        text='REQUEST_END_event\npossibly incomplete'
        nodes=[NS(ControlTypeName='TextControl',Name='REQUEST_END_event'),NS(ControlTypeName='TextControl',Name='safe old reader')]
        with patch.object(desktop,'button_names',return_value=[]),patch.object(desktop,'document_text',return_value=text),patch.object(desktop,'walk',return_value=iter(nodes)):
            self.assertEqual(self.muse.draft('event',500),'safe old reader')

    def test_missing_closing_marker_waits(self):
        text='REQUEST_END_event\nDRAFT_BEGIN_event\n写了一半'
        with patch.object(desktop,'button_names',return_value=[]),patch.object(desktop,'document_text',return_value=text),patch.object(desktop,'walk',return_value=iter([NS(ControlTypeName='TextControl',Name=text)])):
            self.assertIsNone(self.muse.draft('event',500))

    def test_wrong_event_fast_text_does_not_become_this_events_reply(self):
        text='REQUEST_END_other\nDRAFT_BEGIN_other\nwrong friend\nDRAFT_END_other'
        with patch.object(desktop,'button_names',return_value=[]),patch.object(desktop,'document_text',return_value=text),patch.object(desktop,'walk',return_value=iter([])):
            self.assertIsNone(self.muse.draft('event',500))

    def test_unsupported_fast_busy_query_uses_old_check(self):
        with patch.object(desktop,'button_names',return_value=None),patch.object(desktop,'walk',return_value=iter([NS(ControlTypeName='ButtonControl',Name='停止')])):
            self.assertTrue(self.muse.generating())

    def test_fast_path_still_applies_reply_length_limit(self):
        text='REQUEST_END_event\nDRAFT_BEGIN_event\n'+('长'*501)+'\nDRAFT_END_event'
        with patch.object(desktop,'button_names',return_value=[]),patch.object(desktop,'document_text',return_value=text):
            with self.assertRaises(NotReady):self.muse.draft('event',500)

    def test_stale_fast_text_query_is_not_treated_as_a_complete_reply(self):
        error=COMError(-2147220991,'stale',None)
        with patch.object(desktop,'button_names',return_value=[]),patch.object(desktop,'document_text',side_effect=error):
            with self.assertRaises(COMError):self.muse.draft('event',500)


class PollingBehavior(unittest.TestCase):
    def test_near_deadline_sleep_is_shortened_without_shortening_merge_window(self):
        with patch.object(bridge.time,'monotonic',return_value=10.85):
            self.assertAlmostEqual(bridge.listener_delay(.4,1,True,10),.15)
        with patch.object(bridge.time,'monotonic',return_value=10.2):
            self.assertAlmostEqual(bridge.listener_delay(.4,1,True,10),.4)

    def test_no_pending_input_uses_normal_poll_and_overdue_does_not_spin(self):
        self.assertEqual(bridge.listener_delay(.4,1,False,0),.4)
        with patch.object(bridge.time,'monotonic',return_value=20):
            self.assertEqual(bridge.listener_delay(.4,1,True,10),.05)

    def test_faster_poll_still_requires_three_matching_draft_reads(self):
        muse=Mock();muse.draft.side_effect=[None,'first partial','final','final','final']
        with patch.object(bridge.STOP.__class__,'exists',return_value=False),patch.object(bridge.time,'sleep') as sleep:
            answer=bridge.wait_draft(muse,'event',{**bridge.CONFIG,'draft_poll_seconds':.3})
        self.assertEqual(answer,'final');self.assertEqual(muse.draft.call_count,5)
        self.assertTrue(all(call.args[0]==.3 for call in sleep.call_args_list))
        muse.request.assert_not_called()


class PerformanceDiagnostics(unittest.TestCase):
    def test_phase_diagnostics_contain_timings_without_chat_body(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('reply_metrics.time.perf_counter',side_effect=[0,1,4,4.1]):
                trace=ReplyTrace(directory,'friend',1)
                trace.event_id='event';trace.mark('muse_wait');trace.mark('approval');report=trace.finish('skipped')
            self.assertEqual(report['phases_ms']['prepare'],1000)
            self.assertEqual(report['phases_ms']['muse_wait'],3000)
            self.assertAlmostEqual(report['phases_ms']['approval'],100)
            stored=json.loads((Path(directory)/'reply-latency.jsonl').read_text(encoding='utf-8'))
            self.assertNotIn('incoming',stored);self.assertNotIn('draft',stored);self.assertEqual(stored['result'],'skipped')

    def test_diagnostics_io_failure_does_not_stop_reply_handling(self):
        trace=ReplyTrace('unused','friend')
        with patch.object(Path,'mkdir',side_effect=PermissionError('locked')):
            self.assertEqual(trace.finish('sent_ui')['result'],'sent_ui')


if __name__=='__main__':unittest.main()
