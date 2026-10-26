import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import win32con
import win32file
import storage


class StatusFileSharing(unittest.TestCase):
    def test_windows_reader_denying_delete_does_not_stop_status_writer(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary)
            with patch.object(storage, 'LOCAL', local):
                storage.status('listening', pid=123)
                target = local / 'status.json'
                handle = win32file.CreateFile(str(target), win32con.GENERIC_READ,
                                             win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                                             None, win32con.OPEN_EXISTING, 0, None)
                try:
                    storage.status('waiting_desktop', pid=123, reason='等待微信登录')
                    result = json.loads(target.read_text(encoding='utf-8'))
                    self.assertEqual(result['state'], 'waiting_desktop')
                    self.assertEqual(result['reason'], '等待微信登录')
                    self.assertEqual(result['pid'], 123)
                finally:
                    handle.Close()

    def test_transient_replace_failure_retries_and_keeps_valid_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary)
            original = Path.replace
            attempts = []
            def replace(path, target):
                attempts.append(target)
                if len(attempts) < 3:
                    raise PermissionError('synthetic Windows sharing violation')
                return original(path, target)
            with patch.object(storage, 'LOCAL', local), patch.object(Path, 'replace', replace), \
                 patch.object(storage.time, 'sleep'):
                storage.status('listening', pid=123)
            self.assertEqual(len(attempts), 3)
            self.assertEqual(json.loads((local / 'status.json').read_text(encoding='utf-8'))['state'], 'listening')


if __name__ == '__main__':
    unittest.main()
