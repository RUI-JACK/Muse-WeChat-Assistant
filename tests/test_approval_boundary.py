"""Exercise the approval boundary with fake transports; never send a message."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import bridge
from desktop_adapter import Message, NotReady
from storage import Journal, protect, unprotect

class FakeWeChat:
    def __init__(self):
        self.calls = []
        self.rows = [Message('original','hello','mmui::ChatTextItemView',(0,0,1,1))]
    def snapshot(self):
        return self.rows
    def send_approved(self,text,signature,stop):
        self.calls.append(text)
        return True

class FakeMuse:
    def request(self,*args,**kwargs):
        pass

class ApprovalBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.tmp.name)/'test.sqlite3')
        self.wx = FakeWeChat()
        self.config = {**bridge.CONFIG,'mode':'approve_each_reply','auto_y_enabled':False}
        self.patches = [patch.object(bridge,'status'),patch.object(bridge,'record_failure'),patch.object(bridge,'wait_draft',return_value='你好，稍后和你聊。'),patch.object(bridge.STOP.__class__,'exists',return_value=False)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.journal.db.close()
        self.tmp.cleanup()
    def process(self,decision,demo=False):
        return bridge.process_batch(self.wx,FakeMuse(),self.journal,'测试好友甲','hello',self.config,demo,lambda *a:decision)
    def test_no_never_sends(self):
        self.assertEqual(self.process(7),'skipped')
        self.assertEqual(self.wx.calls,[])
    def test_cancel_never_sends(self):
        self.assertEqual(self.process(2),'pause')
        self.assertEqual(self.wx.calls,[])
    def test_only_yes_invokes_once_with_disclosure(self):
        self.assertEqual(self.process(6),'sent_ui')
        self.assertEqual(len(self.wx.calls),1)
        self.assertTrue(self.wx.calls[0].startswith(bridge.CONFIG['disclosure']))
    def test_demo_yes_never_sends(self):
        self.assertEqual(self.process(6,True),'demo')
        self.assertEqual(self.wx.calls,[])
    def test_chat_change_invalidates_before_review(self):
        def changed(*args):
            self.wx.rows.append(Message('new','new message','mmui::ChatTextItemView',(0,0,1,1)))
            return '旧草稿'
        with patch.object(bridge,'wait_draft',side_effect=changed):
            self.assertEqual(self.process(6),'superseded')
        self.assertEqual(self.wx.calls,[])
    def test_stop_after_review_never_sends(self):
        with patch.object(bridge.STOP.__class__,'exists',return_value=True):
            self.assertEqual(self.process(6),'pause')
        self.assertEqual(self.wx.calls,[])
    def test_unconfirmed_send_is_not_retried(self):
        def uncertain(*args):
            self.wx.calls.append('attempt')
            raise RuntimeError('transport ended')
        self.wx.send_approved = uncertain
        self.assertEqual(self.process(6),'pause')
        self.assertEqual(self.wx.calls,['attempt'])
    def test_message_body_encrypted(self):
        value='private message text'
        blob=protect(value)
        self.assertNotIn(value.encode(),blob)
        self.assertEqual(unprotect(blob),value)
    def test_crashed_send_cannot_be_automatically_replayed(self):
        event=self.journal.create('测试好友甲','hello')
        self.journal.state(event,'sending')
        self.journal.recover()
        self.assertEqual(self.journal.db.execute('SELECT state FROM events WHERE id=?',(event,)).fetchone()[0],'interrupted')
    def test_auto_mode_rejected(self):
        config={**bridge.CONFIG,'mode':'auto_confirm_local'}
        with self.assertRaises(ValueError):bridge.check_config(config)

    def test_automatic_local_yes_is_rejected(self):
        config={**bridge.CONFIG,'mode':'approve_each_reply','auto_y_enabled':True}
        with self.assertRaises(NotReady):bridge.check_config(config)

    def test_source_claim_survives_restart(self):
        self.assertTrue(self.journal.claim_source('live-source'))
        another=Journal(Path(self.tmp.name)/'test.sqlite3')
        try:
            self.assertFalse(another.claim_source('live-source'))
        finally:
            another.db.close()

    def test_resume_selects_only_latest_text(self):
        old=Message('old','old','mmui::ChatTextItemView',(0,0,1,1))
        latest=Message('latest','new','mmui::ChatTextItemView',(0,0,1,1))
        timestamp=Message('time','12:00','mmui::ChatItemView',(0,0,1,1))
        self.assertEqual(bridge.resume_candidate([old,latest,timestamp]),latest)

    def test_restoring_window_does_not_replay_history_above_tail(self):
        old=Message('old','old','mmui::ChatTextItemView',(0,0,1,1))
        tail=Message('tail','new','mmui::ChatTextItemView',(0,0,1,1))
        tracker=bridge.MessageTracker([tail],True)
        self.assertEqual(tracker.update([old,tail]),[tail])
        tracker.handled(tail.key)
        self.assertEqual(tracker.update([old,tail]),[])

    def test_unclassified_arrival_is_retried_without_losing_tail(self):
        old=Message('old','old','mmui::ChatTextItemView',(0,0,1,1))
        new=Message('new','new','mmui::ChatTextItemView',(0,0,1,1))
        tracker=bridge.MessageTracker([old])
        self.assertEqual(tracker.update([old,new]),[new])
        self.assertEqual(tracker.update([old,new]),[new])

    def test_duplicate_source_cannot_open_second_send_flow(self):
        kwargs={'source_keys':['same-source'],'review':lambda *a:6}
        first=bridge.process_batch(self.wx,FakeMuse(),self.journal,'测试好友甲','hello',self.config,**kwargs)
        second=bridge.process_batch(self.wx,FakeMuse(),self.journal,'测试好友甲','hello',self.config,**kwargs)
        self.assertEqual((first,second),('sent_ui','skipped'))
        self.assertEqual(len(self.wx.calls),1)

    def test_request_carries_no_automatic_flag(self):
        calls=[]
        class RecordingMuse:
            def request(self,*args,**kwargs):calls.append((args,kwargs))
        bridge.process_batch(self.wx,RecordingMuse(),self.journal,'测试好友甲','hello',self.config,False,lambda *a:7)
        self.assertEqual(calls[0][1],{})
        self.assertEqual(calls[0][0][1:],('测试好友甲','hello',self.config['max_reply_characters']))

    def test_chat_tail_ignores_ids_and_time_rows(self):
        first=[Message('k1','hello','mmui::ChatTextItemView',(0,0,1,1)),
               Message('t1','01:25','mmui::ChatItemView',(0,0,1,1))]
        rerendered=[Message('k2','hello','mmui::ChatTextItemView',(0,0,1,1)),
                    Message('t2','01:26','mmui::ChatItemView',(0,0,1,1))]
        self.assertEqual(bridge.chat_tail(first),bridge.chat_tail(rerendered))

    def test_new_sticker_supersedes_old_text_draft(self):
        # Stickers now have their own image reply path, so an old text draft
        # must not be sent after the friend has supplied a newer reaction.
        seen=[]
        def arrive(*args):
            self.wx.rows.append(Message('sticker','动画表情','mmui::ChatBubbleReferItemView',(0,0,1,1)))
            return '草稿'
        def review(*args):
            seen.append(args[-1])
            return 6
        with patch.object(bridge,'wait_draft',side_effect=arrive):
            result=bridge.process_batch(self.wx,FakeMuse(),self.journal,'测试好友甲','hello',
                                        self.config,review=review)
        self.assertEqual(result,'superseded')
        self.assertEqual(seen,[])
        self.assertEqual(len(self.wx.calls),0)

    def test_auto_confirmation_mode_is_gone(self):
        config={**self.config,'mode':'auto_confirm_local'}
        with self.assertRaises(ValueError):
            bridge.process_batch(self.wx,FakeMuse(),self.journal,'测试好友甲','hello',config,review=lambda *a:6)
        self.assertEqual(self.wx.calls,[])

    def test_automatic_local_yes_is_refused_before_any_send(self):
        config={**self.config,'auto_y_enabled':True}
        with self.assertRaises(NotReady):
            bridge.process_batch(self.wx,FakeMuse(),self.journal,'测试好友甲','hello',config,review=lambda *a:6)
        self.assertEqual(self.wx.calls,[])

    def test_approval_dialog_has_no_auto_confirm_branch(self):
        with patch.object(bridge.ctypes.windll.user32,'MessageBoxW',return_value=7) as box:
            self.assertEqual(bridge.approval('测试联系人','合成来信','合成草稿',demo=True),7)
        title,text=box.call_args.args[2],box.call_args.args[1]
        self.assertIn('演示',title)
        self.assertIn('演示：所有按钮都不会向微信发送。',text)
        self.assertNotIn('自动确认已启用',text)



if __name__=='__main__':
    unittest.main()
