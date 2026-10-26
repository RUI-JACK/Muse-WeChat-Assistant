import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from context_archive import ContactArchive,default_archive_root,migrate_archives,migrate_runtime_archives


def records(text,key='key'):
    return [{'key':key,'speaker':'friend','content':text,'kind':'text','observed_at':1700000000}]


class DocumentsMigration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.old=self.root/'app/local/contexts';self.docs=self.root/'user/Documents/聊天上下文'
    def tearDown(self):self.tmp.cleanup()

    def test_uses_current_users_redirected_documents_folder(self):
        from win32com.shell import shell
        with patch.object(shell,'SHGetFolderPath',return_value=r'D:\UserData\Documents'):
            self.assertEqual(default_archive_root(),Path(r'D:\UserData\Documents')/'聊天上下文')

    def test_all_contacts_migrate_separately_with_originals_preserved(self):
        for name in ('测试好友乙','测试好友丙'):
            ContactArchive(self.old,name).save(records(name+'的内容'))
        before={p:p.read_bytes() for p in self.old.rglob('*') if p.is_file()}
        report=migrate_archives(self.old,self.docs)
        self.assertFalse(report['errors']);self.assertEqual(len(report['copied']),2)
        for name in ('测试好友乙','测试好友丙'):
            self.assertEqual(ContactArchive(self.docs,name).load(),records(name+'的内容'))
        self.assertTrue(all(p.read_bytes()==body for p,body in before.items()))

    def test_repeat_startup_does_not_duplicate_or_rewrite_documents(self):
        ContactArchive(self.old,'A').save(records('history'))
        migrate_archives(self.old,self.docs)
        path=ContactArchive(self.docs,'A').path;before=path.read_bytes()
        report=migrate_archives(self.old,self.docs)
        self.assertEqual(report['existing'],['A']);self.assertEqual(path.read_bytes(),before)

    def test_old_copy_never_overwrites_newer_documents_archive(self):
        ContactArchive(self.old,'A').save(records('old'))
        ContactArchive(self.docs,'A').save(records('new','new-key'))
        migrate_archives(self.old,self.docs)
        self.assertEqual(ContactArchive(self.docs,'A').load(),records('new','new-key'))

    def test_damaged_legacy_file_is_preserved_and_not_imported(self):
        archive=ContactArchive(self.old,'A');archive.directory.mkdir(parents=True)
        archive.path.write_text('broken',encoding='utf-8')
        report=migrate_archives(self.old,self.docs)
        self.assertEqual(len(report['errors']),1)
        self.assertFalse(ContactArchive(self.docs,'A').path.exists())
        self.assertEqual(archive.path.read_text(encoding='utf-8'),'broken')

    def test_mismatched_person_is_never_imported_under_wrong_directory(self):
        archive=ContactArchive(self.old,'A');archive.save(records('private A'))
        data=json.loads(archive.path.read_text(encoding='utf-8'));data['contact_name']='B'
        archive.path.write_text(json.dumps(data),encoding='utf-8')
        report=migrate_archives(self.old,self.docs)
        self.assertTrue(report['errors']);self.assertFalse(self.docs.exists())

    def test_existing_invalid_documents_are_not_overwritten(self):
        ContactArchive(self.old,'A').save(records('old'))
        target=ContactArchive(self.docs,'A');target.directory.mkdir(parents=True)
        target.path.write_text('keep this file',encoding='utf-8')
        report=migrate_archives(self.old,self.docs)
        self.assertTrue(report['errors']);self.assertEqual(target.path.read_text(encoding='utf-8'),'keep this file')

    def test_recent_documents_copy_takes_precedence_over_older_application_copy(self):
        ContactArchive(self.old,'A').save(records('older app history'))
        previous=self.docs.parent/'微信助手上下文存档'
        ContactArchive(previous,'A').save(records('latest documents history','latest'))
        report=migrate_runtime_archives(self.old,self.docs)
        self.assertFalse(report['errors'])
        self.assertEqual(ContactArchive(self.docs,'A').load(),records('latest documents history','latest'))
        self.assertTrue(ContactArchive(previous,'A').path.exists())


if __name__=='__main__':unittest.main()
