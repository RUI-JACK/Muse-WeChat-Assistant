import ctypes
import os
import threading
import time
import unittest
from unittest.mock import patch
import win32con
import win32gui
import auto_y

class DedicatedAutoY(unittest.TestCase):
    def state(self,pid=123):
        return {'state':'awaiting_approval','contact':'测试好友甲','event_id':'test-only','pid':pid}

    def target(self,title=auto_y.TITLE,owner=123,body=None,state=None):
        body=body or '联系人：测试好友甲\n收到：测试\n拟发送的完整内容：测试'
        with patch.object(auto_y.win32gui,'EnumWindows',side_effect=lambda callback,arg:callback(10,arg)), \
             patch.object(auto_y.win32gui,'IsWindowVisible',return_value=True), \
             patch.object(auto_y.win32gui,'GetWindowText',return_value=title), \
             patch.object(auto_y.win32gui,'GetClassName',side_effect=lambda hwnd:'#32770' if hwnd==10 else 'Button'), \
             patch.object(auto_y.win32process,'GetWindowThreadProcessId',return_value=(1,owner)), \
             patch.object(auto_y,'dialog_body',return_value=body), \
             patch.object(auto_y.win32gui,'GetDlgItem',return_value=60) as item, \
             patch.object(auto_y.win32gui,'IsWindowEnabled',return_value=True):
            result=auto_y.find_target(state or self.state(),'测试好友甲')
            return result,item.call_args

    def test_expected_window_chooses_yes_id_six(self):
        result,args=self.target()
        self.assertEqual(result,(10,60))
        self.assertEqual(args.args,(10,6))

    def test_other_contact_is_rejected(self):
        result,args=self.target(body='联系人：其他好友\n拟发送的完整内容：测试好友甲')
        self.assertIsNone(result)
        self.assertIsNone(args)

    def test_other_process_is_rejected(self):
        self.assertIsNone(self.target(owner=456)[0])

    def test_other_dialog_is_rejected(self):
        self.assertIsNone(self.target(title='Muse 授权确认')[0])

    def test_non_approval_state_is_rejected(self):
        self.assertIsNone(self.target(state={**self.state(),'state':'waiting_muse'})[0])

    def test_native_dialog_selects_yes_with_no_global_keys(self):
        # This synthetic message box has no WeChat sender attached.
        state=self.state(os.getpid())
        def worker():
            until=time.monotonic()+5
            while time.monotonic()<until:
                target=auto_y.find_target(state,'测试好友甲')
                if target:
                    win32gui.PostMessage(target[1],win32con.BM_CLICK,0,0)
                    return
                time.sleep(.05)
        thread=threading.Thread(target=worker,daemon=True)
        thread.start()
        result=ctypes.windll.user32.MessageBoxW(None,
            '联系人：测试好友甲\n收到：按钮自检，不会发微信\n拟发送的完整内容：只检测自动选择是(Y)。',
            auto_y.TITLE,win32con.MB_YESNOCANCEL|win32con.MB_DEFBUTTON2|win32con.MB_TOPMOST)
        thread.join(timeout=1)
        self.assertEqual(result,6)

if __name__=='__main__':unittest.main()
