"""Exercise missing-DLL failures through the actual windowless child process."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from status_window import BridgeWorker, status_text


class WorkerStartup(unittest.TestCase):
    def prepare(self, root, bridge_source):
        shutil.copyfile(Path(__file__).resolve().parents[1]/'worker_entry.py', root / 'worker_entry.py')
        (root / 'bridge.py').write_text(bridge_source, encoding='utf-8')
        return [str(Path(sys.executable).with_name('pythonw.exe')), str(root / 'worker_entry.py')]

    def wait_exit(self, worker):
        deadline = time.monotonic() + 8
        while worker.alive() and time.monotonic() < deadline:
            time.sleep(.03)
        self.assertFalse(worker.alive(), 'worker did not finish')

    def test_missing_dll_is_visible_after_windowless_worker_exits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = self.prepare(root, "raise ImportError('DLL load failed while importing win32ui: synthetic missing runtime')")
            worker = BridgeWorker(root, command + ['run'])
            try:
                self.wait_exit(worker)
                state = worker.read_status()
                self.assertEqual(worker.process.returncode, 1)
                self.assertEqual(state['state'], 'needs_attention')
                self.assertEqual(state['phase'], 'startup')
                self.assertIn('系统运行库', state['reason'])
                self.assertEqual(status_text(False, state)[0], '启动失败')
                diagnostic = json.loads((root / 'local/worker-error.json').read_text(encoding='utf-8'))
                self.assertEqual(diagnostic['error_type'], 'ImportError')
                self.assertIn('win32ui', diagnostic['error'])
            finally:
                worker.close()

    def test_resume_argument_reaches_bridge_without_false_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = self.prepare(root, "from pathlib import Path\nimport sys\ndef main():\n Path('argument.txt').write_text(sys.argv[1], encoding='utf-8')\n return 0\n")
            worker = BridgeWorker(root, command + ['resume'])
            try:
                self.wait_exit(worker)
                self.assertEqual(worker.process.returncode, 0)
                self.assertEqual((root / 'argument.txt').read_text(encoding='utf-8'), 'resume')
                self.assertFalse((root / 'local/worker-error.json').exists())
            finally:
                worker.close()


if __name__ == '__main__':
    unittest.main()
