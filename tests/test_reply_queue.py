"""Phone echo and continuous-arrival regressions; no actual chat transport."""
import tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
import bridge
from desktop_adapter import Message,WeChat,SendDeferred
from conversation_context import ConversationContext
from group_adapter import GroupMessage,GroupWeChat
from group_context import GroupContext
from group_runtime import GroupSession,process_group
from reply_queue import PrivateSession,batch_ready
from reply_scope import ReplyScope,begin_reply,end_reply
from storage import Journal

def row(key,text=None):return Message(key,text or key,'mmui::ChatTextItemView',(0,0,500,70))


class QueueOrdering(unittest.TestCase):
    def session(self):
        wx=Mock();wx.snapshot.return_value=[row('base')]
        wx.direction.side_effect=lambda m:'outgoing' if m.key.startswith('out') else 'incoming'
        memory=ConversationContext('测试好友')
        return PrivateSession(wx,memory,wx.snapshot(),bridge.MessageTracker)

    def test_continuous_incoming_cannot_push_first_batch_deadline_back(self):
        s=self.session()
        for stamp,key in ((10,'first'),(10.6,'second'),(11.2,'third')):
            s.wx.snapshot.return_value.append(row(key))
            with patch('reply_queue.time.monotonic',return_value=stamp):s.pump()
        with patch('reply_queue.time.monotonic',return_value=11.2):self.assertTrue(s.ready(1))
        self.assertEqual([m.key for m in s.take()],['first','second','third'])

    def test_phone_echo_is_context_and_never_clears_pending(self):
        s=self.session();s.wx.snapshot.return_value.extend([row('first'),row('out-phone','手机刚刚回复'),row('second')])
        s.pump()
        self.assertEqual([m.key for m in s.pending],['first','second'])
        self.assertIn({'speaker':'self','content':'手机刚刚回复'},s.memory.for_reply('测试好友',['first','second']))

    def test_phone_sends_after_draft_ready_but_before_dispatch_still_sends_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            wx=Mock(contact='测试好友');wx.snapshot.return_value=[row('first','待答的问题')]
            wx.send_approved.return_value=True;journal=Journal(Path(tmp)/'journal.db')
            def phone_before_send(*args):
                self.assertEqual(journal.db.execute('select state from events').fetchone()[0],'draft')
                wx.snapshot.return_value.append(row('out-phone','我手机上先发一句'))
                return 6
            with patch.object(bridge,'status'),patch.object(bridge,'record_failure'), \
                 patch.object(bridge,'wait_draft',return_value='AI已经想好的完整原句'), \
                 patch.object(bridge,'STOP',NS(exists=lambda:False)):
                try:
                    result=bridge.process_batch(wx,Mock(),journal,'测试好友','待答的问题',
                         {**bridge.CONFIG,'allowed_contact':'测试好友'},source_keys=['first'],review=phone_before_send)
                    self.assertEqual(result,'sent_ui')
                    wx.send_approved.assert_called_once()
                    self.assertTrue(wx.send_approved.call_args.args[0].endswith('AI已经想好的完整原句'))
                    self.assertIsInstance(wx.send_approved.call_args.args[1],ReplyScope)
                finally:journal.db.close()

    def test_private_two_batches_finish_once_despite_phone_and_new_arrivals(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=self.session();s.wx.contact='测试好友';s.wx.send_approved.return_value=True
            s.wx.snapshot.return_value.append(row('first','第一句'))
            s.pump();first=s.take();muse=Mock();journal=Journal(Path(tmp)/'journal.db')
            reads=[0]
            def draft(event,limit):
                reads[0]+=1
                if reads[0]==1:s.wx.snapshot.return_value.extend([row('second','第二句'),row('out-phone','我从手机插一句')])
                if reads[0]==2:s.wx.snapshot.return_value.append(row('third','第三句'))
                return '回复-'+event[:6]
            muse.draft.side_effect=draft
            config={**bridge.CONFIG,'allowed_contact':'测试好友','draft_poll_seconds':0}
            with patch.object(bridge,'status'),patch.object(bridge,'record_failure'),patch.object(bridge,'STOP',NS(exists=lambda:False)):
                try:
                    first_result=bridge.process_batch(s.wx,muse,journal,'测试好友','第一句',config,
                      source_keys=[m.key for m in first],review=lambda *a:6,on_poll=s.poll_during_reply,on_sent=s.memory.confirm_sent)
                    self.assertEqual(first_result,'sent_ui')
                    self.assertEqual([m.key for m in s.pending],['second','third'])
                    second=s.take();keys=[m.key for m in second];history=s.memory.for_reply('测试好友',keys)
                    self.assertTrue(any(r['speaker']=='self' and r['content'].startswith('回复-') for r in history))
                    self.assertIn({'speaker':'self','content':'我从手机插一句'},history)
                    self.assertEqual(bridge.process_batch(s.wx,muse,journal,'测试好友','第二句\n第三句',config,
                      source_keys=keys,review=lambda *a:6,on_poll=s.poll_during_reply,conversation=history),'sent_ui')
                    self.assertEqual(bridge.process_batch(s.wx,muse,journal,'测试好友','第二句\n第三句',config,
                      source_keys=keys,review=lambda *a:6),'skipped')
                    self.assertEqual(s.wx.send_approved.call_count,2);self.assertEqual(muse.request.call_count,2)
                    self.assertEqual([c.args[2] for c in muse.request.call_args_list],['第一句','第二句\n第三句'])
                    self.assertTrue(all(isinstance(c.args[1],ReplyScope) for c in s.wx.send_approved.call_args_list))
                finally:journal.db.close()

    def test_group_phone_and_new_mention_do_not_abort_current_reply(self):
        def gm(key,text,sender='甲',direction='incoming'):
            return GroupMessage(key,text,'mmui::ChatTextItemView',(0,0,500,80),sender,direction)
        wx=Mock(contact='测试群',self_name='本人');wx.snapshot.return_value=[gm('base','旧消息')]
        wx.send_approved.return_value=True
        memory=GroupContext('测试群','本人','AI',None)
        session=GroupSession(wx,memory,wx.snapshot(),'本人',bridge.MessageTracker)
        wx.snapshot.return_value.append(gm('first','@本人\u2005第一句'));session.pump()
        first=session.pending;session.pending=[];muse=Mock();reads=[0]
        def draft(event,limit):
            reads[0]+=1
            if reads[0]==1:wx.snapshot.return_value.extend([gm('second','@本人\u2005第二句','乙'),gm('out-phone','手机补一句','本人','outgoing')])
            return '当前回复'
        muse.draft.side_effect=draft
        cfg={'chat_mode':'group','allowed_group':'测试群','group_self_name':'本人','group_reply_policy':'mention',
             'mode':'approve_each_reply','disclosure':'AI','max_reply_characters':500,'reply_timeout_seconds':2,'draft_poll_seconds':0}
        with tempfile.TemporaryDirectory() as tmp:
            journal=Journal(Path(tmp)/'journal.db')
            with patch('group_runtime.status'),patch.object(bridge,'STOP',NS(exists=lambda:False)):
                try:self.assertEqual(process_group(session,muse,journal,first,cfg,lambda *a:6),'sent_ui')
                finally:journal.db.close()
        self.assertEqual([m.key for m in session.pending],['second'])
        wx.send_approved.assert_called_once();wx.send_signature.assert_not_called()
        next_context=memory.for_reply('测试群',['second'])
        self.assertTrue(any(r['sender']=='本人' and r['content']=='当前回复' for r in next_context))
        self.assertTrue(any(r['sender']=='本人' and r['content']=='手机补一句' for r in next_context))
        with self.assertRaises(ValueError):memory.for_reply('其他群',['second'])

    def test_group_first_mention_deadline_is_not_reset_by_second_mention(self):
        gm=lambda key,text:GroupMessage(key,text,'mmui::ChatTextItemView',(0,0,500,80),'甲','incoming')
        wx=Mock();wx.snapshot.return_value=[gm('base','旧消息')]
        session=GroupSession(wx,GroupContext('群','本人','AI',None),wx.snapshot(),'本人',bridge.MessageTracker)
        for stamp,key in ((10,'first'),(10.8,'second')):
            wx.snapshot.return_value.append(gm(key,'@本人\u2005'+key))
            with patch('group_runtime.time.monotonic',return_value=stamp):session.pump()
        with patch('reply_queue.time.monotonic',return_value=11.1):
            self.assertTrue(batch_ready(session.pending,session.first_incoming,1))


class ScopedSendSafety(unittest.TestCase):
    def adapter(self,initial='',during_input=None):
        wx=WeChat.__new__(WeChat);wx.hwnd=11;wx.pid=22;wx.contact='测试好友'
        value=NS(Value=initial);value.SetValue=Mock(side_effect=lambda text:setattr(value,'Value',during_input if during_input is not None else text))
        edit=Mock(Name=wx.contact);edit.Name=wx.contact;edit.GetValuePattern.return_value=value
        button=Mock();button.IsEnabled=True;button.BoundingRectangle=NS(left=0,top=0,right=20,bottom=20)
        detail=Mock();detail.ButtonControl.return_value=button
        wx.controls=Mock(return_value=(detail,edit,None))
        wx.snapshot=Mock(return_value=[row('phone'),row('new-incoming')])
        button.Click.side_effect=lambda **kwargs:setattr(value,'Value','')
        wx.snapshot.return_value.append(row('echo','这轮回复'))
        return wx,value,button

    def send(self,wx,scope):
        with patch('desktop_adapter.win32gui.ShowWindow'),patch('desktop_adapter.win32gui.SetForegroundWindow'), \
             patch('desktop_adapter.win32gui.GetForegroundWindow',return_value=11), \
             patch('desktop_adapter.win32gui.WindowFromPoint',return_value=11), \
             patch('desktop_adapter.win32gui.GetAncestor',return_value=11),patch('desktop_adapter.time.sleep'):
            return wx.send_approved('这轮回复',scope)

    def test_interleaved_phone_and_friend_rows_do_not_cancel_and_scope_is_one_use(self):
        wx,value,button=self.adapter();scope=begin_reply(wx,'测试好友','event')
        wx.send_signature=Mock(side_effect=AssertionError('must not compare changing chat tail'))
        self.assertTrue(self.send(wx,scope));button.Click.assert_called_once()
        with self.assertRaises(SendDeferred):self.send(wx,scope)
        self.assertEqual(button.Click.call_count,1)

    def test_owner_editor_is_preserved_before_or_during_input(self):
        for initial,during in (('本人正打字',None),('','本人修改了输入')):
            wx,value,button=self.adapter(initial,during);scope=begin_reply(wx,'测试好友','event')
            with self.assertRaises(SendDeferred):self.send(wx,scope)
            self.assertEqual(value.Value,initial or during);button.Click.assert_not_called()

    def test_group_scope_uses_same_interleaving_safe_send_checks(self):
        private,value,button=self.adapter()
        wx=GroupWeChat.__new__(GroupWeChat);wx.__dict__.update(private.__dict__)
        scope=begin_reply(wx,'测试好友','group-event','group')
        self.assertTrue(self.send(wx,scope));button.Click.assert_called_once()

    def test_wrong_contact_process_window_mode_and_expired_scope_cannot_send(self):
        for change in ('contact','pid','hwnd','mode','expired'):
            wx,value,button=self.adapter();scope=begin_reply(wx,'测试好友','event')
            if change=='contact':wx.contact='其他好友'
            elif change=='pid':wx.pid=23
            elif change=='hwnd':wx.hwnd=12
            elif change=='mode':wx.chat_kind='group'
            else:end_reply(wx,scope)
            with self.assertRaises(SendDeferred):self.send(wx,scope)
            value.SetValue.assert_not_called();button.Click.assert_not_called()


if __name__=='__main__':unittest.main()
