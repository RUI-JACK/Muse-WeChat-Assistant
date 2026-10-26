import json,tempfile,time,unittest,os,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from desktop_adapter import NotReady,SendDeferred,build_request_text
from group_adapter import GroupMessage,GroupWeChat
from group_policy import mentioned,eligible,main_body,build_group_prompt,GROUP_TITLE
from group_context import GroupArchive,GroupContext
from group_ocr import resolve_sender
from group_runtime import GroupSession,process_group,muse_wait_reason
from group_diagnostics import ReceiveDiagnostics
from chat_settings import save_chat
from context_archive import ContactArchive
from bridge import MessageTracker
from integrated_confirmation import AutoConfirmation
import status_window,auto_y

def msg(key,text,sender='小明',direction='incoming',kind='mmui::ChatTextItemView'):
    return GroupMessage(key,text,kind,(0,0,500,80),sender,direction)

CFG={'chat_mode':'group','allowed_group':'测试群聊','group_self_name':'测试群昵称',
     'group_reply_policy':'mention','mode':'approve_each_reply','disclosure':'【AI辅助回复】',
     'max_reply_characters':500,'reply_timeout_seconds':1,'draft_poll_seconds':0}


class Policy(unittest.TestCase):
    def test_sender_ocr_resolves_only_unique_close_roster_match(self):
        self.assertEqual(resolve_sender('同 学 甲 乙',['同学甲乙丙','测试成员3','测试群昵称']),'同学甲乙丙')
        self.assertEqual(resolve_sender('甲',['甲','甲']),'')
        self.assertEqual(resolve_sender('完全陌生昵称',['测试成员3','测试群昵称']),'')
    def test_exact_mentions(self):
        for text in ('@测试群昵称\u2005你说呢','@测试群昵称','你好 @测试群昵称\u2005',
                     '中文@测试群昵称\u2005你说呢','hello@测试群昵称\u2005看看',
                     '@测试群昵称 普通空格','@测试群昵称\u00a0看看','@测试群昵称，看看'):
            self.assertTrue(mentioned(text,'测试群昵称'))
        for text in ('hello','@测试群昵称2\u2005','@所有人\u2005','@aurelius\u2005',
                     'user@测试群昵称.com','@@测试群昵称\u2005','@测试群昵称_extra'):
            self.assertFalse(mentioned(text,'测试群昵称'))

    def test_quote_only_never_triggers(self):
        self.assertFalse(mentioned('我也觉得\n引用 小明 的消息 : @测试群昵称\u2005你好','测试群昵称'))
        self.assertEqual(main_body('图片\n引用 小明 的消息 : @测试群昵称\u2005'),'图片')

    def test_self_unknown_sender_and_media_do_not_trigger(self):
        for m in (msg('1','@测试群昵称',direction='outgoing'),msg('2','@测试群昵称',sender=''),
                  msg('3','@测试群昵称',direction='unknown'),msg('4','@测试群昵称',kind='mmui::ChatImageItemView')):
            self.assertFalse(eligible(m,'测试群昵称'))

    def test_prompt_has_only_group_fields_and_sender_names(self):
        text=build_group_prompt('id','群','测试群昵称',[{'sender':'甲','content':'@测试群昵称'}],
             [{'sender':'乙','direction':'incoming','content':'火锅'}],500)
        self.assertIn('"sender": "乙"',text);self.assertIn('"chat_type": "group"',text)
        self.assertIn('DRAFT_END_id',text);self.assertNotIn('"speaker": "friend"',text)
        self.assertIn('百度贴吧老哥式的犀利回怼',text)
        self.assertNotIn('知性成熟、温暖体贴',text)
        self.assertNotIn('"chat_type": "group"',build_request_text('x','好友','你好',500))


class Archives(unittest.TestCase):
    def test_private_and_group_same_name_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);private=ContactArchive(root,'同名');group=GroupArchive(root,'同名')
            private.save([{'key':'p','speaker':'friend','content':'私密','kind':'text','observed_at':time.time()}])
            memory=GroupContext('同名','我','AI',group)
            self.assertEqual(list(memory.turns),[])
            memory.observe(msg('g','群内容','甲'),'incoming')
            self.assertNotEqual(private.path,group.path)
            self.assertEqual(group.load()[0]['sender'],'甲')
            self.assertNotIn('私密',group.path.read_text(encoding='utf-8'))
            self.assertEqual(private.load()[0]['content'],'私密')

    def test_mismatched_or_broken_archive_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive=GroupArchive(Path(tmp),'群');archive.directory.mkdir(parents=True)
            archive.path.write_text('{broken',encoding='utf-8')
            memory=GroupContext('群','我','AI',archive);memory.observe(msg('1','新内容'),'incoming')
            self.assertTrue(memory.archive_error);self.assertEqual(archive.path.read_text(encoding='utf-8'),'{broken')

    def test_sender_seed_restart_and_own_echo_no_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive=GroupArchive(Path(tmp),'群');memory=GroupContext('群','我','AI',archive)
            memory.observe(msg('1','同一句','甲'),'incoming');memory.observe(msg('2','同一句','乙'),'incoming')
            memory.confirm_sent('e','AI\n回答');memory.observe(msg('echo','AI\n回答','我','outgoing'),'outgoing')
            self.assertEqual(len(memory.turns),3)
            restarted=GroupContext('群','我','AI',archive)
            restarted.seed([(msg('new','同一句','乙'),'incoming'),(msg('new_echo','AI\n回答','我','outgoing'),'outgoing')])
            self.assertEqual(len(restarted.turns),3)
            with self.assertRaises(ValueError):restarted.before('别的群',[])


class Listener(unittest.TestCase):
    def setUp(self):
        patcher=patch('group_runtime.status');patcher.start();self.addCleanup(patcher.stop)
        patcher=patch('bridge.record_failure');patcher.start();self.addCleanup(patcher.stop)
    def session(self,rows=()):
        memory=GroupContext('测试群聊','测试群昵称',CFG['disclosure'],None)
        wx=Mock(contact='测试群聊',self_name='测试群昵称');wx.snapshot.return_value=list(rows)
        wx.send_signature.return_value=[];wx.send_approved.return_value=True
        return GroupSession(wx,memory,list(rows),'测试群昵称',MessageTracker)

    def test_history_and_regular_messages_do_not_queue(self):
        s=self.session([msg('old','@测试群昵称')]);s.pump();self.assertFalse(s.pending)
        s.wx.snapshot.return_value=[msg('old','@测试群昵称'),msg('new','你好')]
        s.pump();self.assertFalse(s.pending);self.assertEqual(len(s.memory.turns),2)

    def test_sender_ocr_failure_retries_same_source_after_newer_rows(self):
        s=self.session([msg('base','你好')])
        s.wx.snapshot.return_value=[msg('base','你好'),msg('miss','中文@测试群昵称\u2005看看',sender='')]
        s.pump()
        self.assertFalse(s.pending);self.assertIn('miss',s.tracker.waiting)
        self.assertEqual(s.waiting_sender_count,1)
        s.wx.snapshot.return_value=[msg('base','你好'),msg('miss','中文@测试群昵称\u2005看看',sender='甲'),msg('newer','另一个人的话','乙')]
        s.pump();self.assertEqual([m.key for m in s.pending],['miss'])
        s.pump();self.assertEqual([m.key for m in s.pending],['miss'])
        self.assertEqual(s.waiting_sender_count,0)

    def test_unknown_direction_is_retryable_and_never_assumed_incoming(self):
        s=self.session([msg('base','你好')])
        s.wx.snapshot.return_value+=[msg('unknown','@测试群昵称',direction='unknown')]
        s.pump();self.assertFalse(s.pending);self.assertIn('unknown',s.tracker.waiting)
        s.wx.snapshot.return_value[-1]=msg('unknown','@测试群昵称',sender='本人',direction='outgoing')
        s.pump();self.assertFalse(s.pending);self.assertNotIn('unknown',s.tracker.waiting)

    def test_busy_muse_defers_new_request_and_draft_is_not_overwritten(self):
        muse=Mock();muse.generating.return_value=True
        self.assertIn('排队',muse_wait_reason(muse));muse.composer.assert_not_called()
        muse.generating.return_value=False;edit=Mock();edit.GetValuePattern.return_value.Value='本人草稿'
        muse.composer.return_value=(edit,None,[])
        self.assertIn('不会覆盖',muse_wait_reason(muse));muse.request_group.assert_not_called()
        edit.GetValuePattern.return_value.Value=''
        self.assertEqual(muse_wait_reason(muse),'')

    def test_phone_reply_keeps_queued_mentions_and_future_mentions(self):
        s=self.session([msg('base','你好')]);s.wx.snapshot.return_value=[msg('base','你好'),msg('a','@测试群昵称')]
        s.pump();self.assertEqual(len(s.pending),1)
        s.wx.snapshot.return_value+=[msg('b','我回了','测试群昵称','outgoing')];s.pump();self.assertEqual([m.key for m in s.pending],['a'])
        s.wx.snapshot.return_value+=[msg('c','@测试群昵称')];s.pump();self.assertEqual([m.key for m in s.pending],['a','c'])

    def test_other_members_media_never_attached_to_caller(self):
        s=self.session([msg('base','你好')]);s.wx.snapshot.return_value+=[msg('a','@测试群昵称','甲'),msg('b','图片','乙',kind='mmui::ChatImageItemView')]
        s.pump();self.assertEqual([m.key for m in s.pending],['a'])

    def test_no_trigger_never_calls_muse(self):
        s=self.session();muse=Mock();journal=Mock()
        with self.assertRaises(NotReady):process_group(s,muse,journal,[msg('n','普通消息')],CFG)
        muse.request_group.assert_not_called();journal.claim_sources.assert_not_called()

    def test_unrelated_group_messages_do_not_cancel_reply(self):
        s=self.session();muse=Mock();journal=Mock();journal.create.return_value='event'
        s.pump=Mock();muse.draft.return_value='接住这个梗'
        with patch('bridge.STOP',SimpleNamespace(exists=lambda:False)):
            self.assertEqual(process_group(s,muse,journal,[msg('a','@测试群昵称')],CFG,lambda *args:6),'sent_ui')
        s.wx.send_approved.assert_called_once()
        self.assertEqual(journal.create.call_args.args[0],'群聊｜测试群聊')

    def test_phone_reply_during_generation_does_not_cancel_send(self):
        s=self.session();muse=Mock();journal=Mock();s.pump=Mock(side_effect=lambda:setattr(s,'manual_epoch',s.manual_epoch+1))
        journal.create.return_value='phone-event'
        muse.draft.return_value='当前这轮完成'
        with patch('bridge.STOP',SimpleNamespace(exists=lambda:False)):
            self.assertEqual(process_group(s,muse,journal,[msg('a','@测试群昵称')],CFG,lambda *a:6),'sent_ui')
        s.wx.send_approved.assert_called_once()

    def test_old_trigger_rolling_off_view_does_not_cancel_a_verified_text_reply(self):
        s=self.session();muse=Mock();journal=Mock()
        journal.create.return_value='scroll-event'
        muse.draft.return_value='当前这轮完成';s.pump=Mock()
        s.wx.send_signature.side_effect=NotReady('触发消息已滚出视图')
        with patch('bridge.STOP',SimpleNamespace(exists=lambda:False)):
            self.assertEqual(process_group(s,muse,journal,[msg('a','@测试群昵称')],CFG,lambda *a:6),'sent_ui')
        s.wx.send_signature.assert_not_called();s.wx.send_approved.assert_called_once()

    def test_no_and_cancel_and_duplicate_never_send(self):
        for decision,expected in ((7,'skipped'),(2,'pause')):
            s=self.session();s.pump=Mock();muse=Mock();muse.draft.return_value='你好';journal=Mock()
            with patch('bridge.STOP',SimpleNamespace(exists=lambda:False)):
                self.assertEqual(process_group(s,muse,journal,[msg('a','@测试群昵称')],CFG,lambda *a:decision),expected)
            s.wx.send_approved.assert_not_called()
        s=self.session();muse=Mock();journal=Mock();journal.claim_sources.return_value=False
        self.assertEqual(process_group(s,muse,journal,[msg('a','@测试群昵称')],CFG),'skipped')
        muse.request_group.assert_not_called()


class SendGuards(unittest.TestCase):
    def adapter(self,rows):
        wx=object.__new__(GroupWeChat);wx.required_sources={'trigger'};wx.snapshot=lambda:rows
        return wx

    def test_ordinary_group_arrivals_do_not_change_send_signature(self):
        rows=[msg('trigger','@测试群昵称')];wx=self.adapter(rows);before=wx.send_signature()
        rows.append(msg('other','另一成员新消息','乙'))
        self.assertEqual(wx.send_signature(),before)
        rows.append(msg('own','本人手动回复','测试群昵称','outgoing'))
        self.assertNotEqual(wx.send_signature(),before)

    def test_missing_trigger_or_unknown_new_direction_blocks_send(self):
        with self.assertRaises(NotReady):self.adapter([msg('other','你好')]).send_signature()
        with self.assertRaises(NotReady):self.adapter([msg('trigger','@测试群昵称'),msg('x','未知',direction='unknown')]).send_signature()
        wx=self.adapter([msg('old','被裁切历史',direction='unknown'),msg('trigger','@测试群昵称')])
        self.assertEqual(wx.send_signature(),[])

    def test_earlier_owner_row_rolling_off_does_not_invalidate_draft(self):
        rows=[msg('old-own','先前回复','本人','outgoing'),msg('trigger','@测试群昵称')]
        wx=self.adapter(rows);signature=wx.send_signature()
        rows.pop(0);rows.append(msg('new','群里又来了一句','乙'))
        self.assertEqual(wx.send_signature(),signature)
        rows.append(msg('manual','本人刚刚手动回复','本人','outgoing'))
        self.assertNotEqual(wx.send_signature(),signature)


class ReceiveTrace(unittest.TestCase):
    def test_local_trace_excludes_bodies_and_deduplicates_identical_waits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'group-receive.jsonl';trace=ReceiveDiagnostics(path)
            trace.record('key','waiting_sender',mentioned=True)
            trace.record('key','waiting_sender',mentioned=True)
            trace.record('key','queued',mentioned=True)
            records=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual([r['reason'] for r in records],['waiting_sender','queued'])
            self.assertTrue(all(set(r)=={'time','source','reason','mentioned'} for r in records))


class SetupAndConfirmation(unittest.TestCase):
    def test_native_group_dialog_only_confirms_its_own_event(self):
        import win32gui,win32con
        from group_runtime import approval
        state={'state':'awaiting_approval','contact':'合成群','chat_mode':'group','event_id':'group-native-test',
               'pid':os.getpid(),'group_self_name':'测试群昵称','mentioned_self':True,'group_reply_policy':'mention','trigger_keys':['x']}
        result=[]
        def watch():
            until=time.monotonic()+5
            while time.monotonic()<until:
                target=auto_y.find_target(state,'合成群')
                if target:
                    result.append(target);win32gui.PostMessage(target[1],win32con.BM_CLICK,0,0);return
                time.sleep(.03)
            hwnd=win32gui.FindWindow('#32770',GROUP_TITLE)
            if hwnd:win32gui.PostMessage(win32gui.GetDlgItem(hwnd,2),win32con.BM_CLICK,0,0)
        thread=threading.Thread(target=watch,daemon=True);thread.start()
        self.assertEqual(approval('合成群','按钮自检，不发微信','没有发送接口','group-native-test'),6)
        thread.join(timeout=1);self.assertTrue(result)
    def test_group_requires_self_name_and_preserves_private_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'config.json';p.write_text(json.dumps({'allowed_contact':'好友','mode':'approve_each_reply'}),encoding='utf-8')
            with self.assertRaises(ValueError):save_chat(root,'group','群','')
            save_chat(root,'group','群','测试群昵称');data=json.loads(p.read_text(encoding='utf-8'))
            self.assertEqual(data['allowed_contact'],'好友');self.assertEqual(data['mode'],'approve_each_reply')
            save_chat(root,'private','另一个好友');self.assertEqual(json.loads(p.read_text(encoding='utf-8'))['chat_mode'],'private')

    def test_confirmation_never_crosses_chat_modes(self):
        worker=Mock();worker.alive.return_value=True;worker.owns.return_value=True
        for mode,state_mode in (('private','group'),('group','private')):
            with patch('integrated_confirmation.find_target') as find:
                self.assertFalse(AutoConfirmation('同名',chat_mode=mode).poll(worker,{'chat_mode':state_mode,'event_id':'e','pid':1}))
                find.assert_not_called()

    def test_group_confirmation_requires_mention_proof(self):
        state={'state':'awaiting_approval','contact':'群','event_id':'e','pid':1,'chat_mode':'group'}
        with patch.object(auto_y.win32gui,'EnumWindows') as enum:
            self.assertIsNone(auto_y.find_target(state,'群'));enum.assert_not_called()

    def test_native_group_start_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'config.json').write_text(json.dumps({'allowed_contact':'好友'}),encoding='utf-8')
            with patch.object(status_window,'BridgeWorker') as factory:
                app=status_window.StatusWindow(root,title='Muse 群聊合成测试')
                try:
                    app.group_mode_button.invoke();app.contact_input.set('测试群聊')
                    app.start_button.invoke();factory.assert_not_called()
                    app.self_name_input.set('测试群昵称');factory.return_value.started=time.time();factory.return_value.read_status.return_value={}
                    app.start_button.invoke();factory.assert_called_once();self.assertEqual(app.confirmation.chat_mode,'group')
                finally:app.finish()


if __name__=='__main__':unittest.main()
