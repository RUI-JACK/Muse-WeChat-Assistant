import unittest
from unittest.mock import patch
import local_confirmation as c

class OwnedDialogBoundary(unittest.TestCase):
    def find(self,title,owner):
        with patch.object(c.win32gui,'EnumWindows',side_effect=lambda callback,arg:callback(10,arg)), \
             patch.object(c.win32gui,'IsWindowVisible',return_value=True), \
             patch.object(c.win32gui,'GetWindowText',return_value=title), \
             patch.object(c.win32gui,'GetClassName',side_effect=lambda hwnd:'#32770' if hwnd==10 else 'Button'), \
             patch.object(c.win32process,'GetWindowThreadProcessId',return_value=(1,owner)), \
             patch.object(c.win32gui,'GetDlgItem',return_value=60) as item, \
             patch.object(c.win32gui,'IsWindowEnabled',return_value=True):
            result=c.find_own_yes_button(123)
            return result,item.call_args

    def test_exact_owned_auto_dialog_uses_idyes(self):
        result,args=self.find(c.AUTO_TITLE,123)
        self.assertEqual(result,60)
        self.assertEqual(args.args,(10,6))

    def test_other_process_is_never_selected(self):
        result,args=self.find(c.AUTO_TITLE,456)
        self.assertIsNone(result)
        self.assertIsNone(args)

    def test_manual_dialog_is_never_selected(self):
        result,args=self.find('Muse 微信回复确认',123)
        self.assertIsNone(result)
        self.assertIsNone(args)

    def test_muse_platform_permission_is_never_selected(self):
        result,args=self.find('Muse 授权确认',123)
        self.assertIsNone(result)
        self.assertIsNone(args)

if __name__=='__main__':unittest.main()
