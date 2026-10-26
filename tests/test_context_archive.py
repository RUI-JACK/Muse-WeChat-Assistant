import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from context_archive import ContactArchive,ArchiveError,archive_folder,MAX_ARCHIVE_TURNS
from conversation_context import ConversationContext
from desktop_adapter import Message
import bridge


def row(key,text):return Message(key,text,'mmui::ChatTextItemView',(0,0,100,50))


class PersistentContext(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def memory(self,name):return ConversationContext(name,archive=ContactArchive(self.root,name))

    def test_each_contact_survives_restart_without_sharing_messages(self):
        a=self.memory('测试好友丙');a.observe(row('a','张的专属话题'),'incoming')
        b=self.memory('测试好友乙');b.observe(row('b','徐的专属话题'),'incoming')
        self.assertEqual(self.memory('测试好友丙').before('测试好友丙',[]),[{'speaker':'friend','content':'张的专属话题'}])
        self.assertEqual(self.memory('测试好友乙').before('测试好友乙',[]),[{'speaker':'friend','content':'徐的专属话题'}])
        self.assertNotEqual(a.archive_path,b.archive_path)

    def test_readable_export_has_speakers_and_actual_text(self):
        memory=self.memory('测试好友乙');memory.observe(row('a','上下文内容'),'incoming')
        memory.observe(row('b','手动回复'),'outgoing')
        text=(memory.archive.directory/'聊天上下文.txt').read_text(encoding='utf-8')
        self.assertIn('测试好友乙',text);self.assertIn('对方\n上下文内容',text);self.assertIn('我\n手动回复',text)

    def test_repainted_visible_tail_merges_once_and_appends_only_new_rows(self):
        memory=self.memory('A')
        for key in ('a','b','c'):memory.observe(row(key,key),'incoming')
        restored=self.memory('A')
        restored.seed([(row('new-b','b'),'incoming'),(row('new-c','c'),'incoming'),(row('new-d','d'),'incoming')])
        self.assertEqual([r['content'] for r in restored.archive.load()],['a','b','c','d'])
        self.assertEqual(restored.before('A',['new-d']),[{'speaker':'friend','content':x} for x in ('a','b','c')])

    def test_seed_does_not_reappend_an_older_visible_segment(self):
        memory=self.memory('A')
        for key in ('a','b','c'):memory.observe(row(key,key),'incoming')
        restored=self.memory('A');restored.seed([(row('old-a','a'),'incoming'),(row('old-b','b'),'incoming')])
        self.assertEqual(len(restored.archive.load()),3)

    def test_repeated_live_words_are_not_collapsed(self):
        memory=self.memory('A');memory.observe(row('1','哈哈'),'incoming');memory.observe(row('2','哈哈'),'incoming')
        restored=self.memory('A');restored.seed([(row('r1','哈哈'),'incoming'),(row('r2','哈哈'),'incoming'),(row('r3','哈哈'),'incoming')])
        self.assertEqual(len(restored.archive.load()),3)

    def test_cross_contact_file_is_rejected_and_preserved(self):
        a=self.memory('A');a.observe(row('a','A SECRET'),'incoming')
        wrong=ContactArchive(self.root,'B');wrong.directory.mkdir();wrong.path.write_bytes(a.archive.path.read_bytes())
        before=wrong.path.read_bytes();b=self.memory('B')
        self.assertTrue(b.archive_error)
        self.assertEqual(b.before('B',[]),[])
        b.observe(row('new','B visible'),'incoming')
        self.assertEqual(wrong.path.read_bytes(),before)
        self.assertNotIn('A SECRET',str(b.before('B',[])))

    def test_invalid_archive_is_not_overwritten(self):
        archive=ContactArchive(self.root,'A');archive.directory.mkdir();archive.path.write_text('broken',encoding='utf-8')
        memory=self.memory('A');memory.observe(row('new','still listening'),'incoming')
        self.assertTrue(memory.archive_error)
        self.assertEqual(archive.path.read_text(encoding='utf-8'),'broken')
        self.assertEqual(memory.before('A',[])[0]['content'],'still listening')

    def test_file_write_failure_keeps_in_memory_context_and_retries(self):
        memory=self.memory('A')
        with patch.object(memory.archive,'save',side_effect=PermissionError('locked')):
            memory.observe(row('a','not lost'),'incoming')
        self.assertTrue(memory.dirty);self.assertTrue(memory.archive_error)
        self.assertEqual(memory.before('A',[])[0]['content'],'not lost')
        self.assertTrue(memory.flush());self.assertFalse(memory.archive_error)
        self.assertEqual(self.memory('A').before('A',[])[0]['content'],'not lost')

    def test_archive_has_1000_turn_limit_while_prompt_remains_24(self):
        memory=ConversationContext('A')
        for i in range(MAX_ARCHIVE_TURNS+12):memory.observe(row(str(i),str(i)),'incoming')
        archive=ContactArchive(self.root,'A');archive.save(memory.turns)
        self.assertEqual(len(archive.load()),MAX_ARCHIVE_TURNS)
        self.assertEqual(len(memory.before('A',[])),24)

    def test_unfriendly_file_names_remain_separate_inside_archive_root(self):
        names=['../张:杰','../张?杰','CON','测试好友乙']
        self.assertEqual(len({archive_folder(n) for n in names}),4)
        for name in names:
            memory=self.memory(name);memory.flush()
            self.assertEqual(memory.archive.directory.resolve().parent,self.root.resolve())

    def test_confirmed_reply_is_saved_immediately_and_echo_is_not_duplicated(self):
        memory=self.memory('A');memory.confirm_sent('event','【AI辅助回复】\n已发送回复')
        self.assertEqual(len(memory.archive.load()),1)
        memory.observe(row('next','新来信'),'incoming')
        memory.observe(row('echo','【AI辅助回复】\n已发送回复'),'outgoing')
        self.assertEqual(len(memory.archive.load()),2)
        self.assertEqual([r['content'] for r in memory.archive.load()],['新来信','已发送回复'])

    def test_archive_identity_is_verified_even_with_same_visible_folder_name(self):
        archive=ContactArchive(self.root,'A');archive.save([])
        data=json.loads(archive.path.read_text(encoding='utf-8'));data['contact_id']='wrong'
        archive.path.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(ArchiveError):archive.load()


class SavedReplyBoundary(unittest.TestCase):
    def test_only_confirmed_local_send_is_added_to_context(self):
        for decision,visible,expected in [(7,True,False),(2,True,False),(6,False,False),(6,True,True)]:
            with self.subTest(decision=decision,visible=visible):
                wx=Mock();wx.contact=bridge.CONFIG['allowed_contact'];wx.snapshot.return_value=[];wx.send_approved.return_value=visible
                journal=Mock();journal.create.return_value='event';sink=Mock()
                with patch.object(bridge,'status'),patch.object(bridge,'record_failure'),patch.object(bridge,'wait_draft',return_value='answer'),patch.object(bridge.STOP.__class__,'exists',return_value=False):
                    bridge.process_batch(wx,Mock(),journal,wx.contact,'incoming',bridge.CONFIG,review=lambda *a:decision,on_sent=sink)
                self.assertEqual(sink.called,expected)

    def test_archive_error_after_confirmed_send_does_not_turn_it_into_uncertain_send(self):
        wx=Mock();wx.contact=bridge.CONFIG['allowed_contact'];wx.snapshot.return_value=[];wx.send_approved.return_value=True
        journal=Mock();journal.create.return_value='event'
        with patch.object(bridge,'status'),patch.object(bridge,'record_failure'),patch.object(bridge,'wait_draft',return_value='answer'),patch.object(bridge.STOP.__class__,'exists',return_value=False):
            result=bridge.process_batch(wx,Mock(),journal,wx.contact,'incoming',bridge.CONFIG,review=lambda *a:6,on_sent=Mock(side_effect=PermissionError('locked')))
        self.assertEqual(result,'sent_ui')
        wx.send_approved.assert_called_once()


if __name__=='__main__':unittest.main()
