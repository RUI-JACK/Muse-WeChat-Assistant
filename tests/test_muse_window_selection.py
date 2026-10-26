import unittest
from unittest.mock import patch
from desktop_adapter import Muse, is_muse_chat_title


class MuseWindowSelection(unittest.TestCase):
    def test_current_guest_app_title_is_recognized_alongside_installed_pwa(self):
        self.assertTrue(is_muse_chat_title('Chat — Muse'))
        self.assertTrue(is_muse_chat_title('Muse - Chat'))
        self.assertTrue(is_muse_chat_title('Muse - Chat - Nora'))
        self.assertFalse(is_muse_chat_title('Muse 微信助手 · 运行状态'))
        self.assertFalse(is_muse_chat_title('Chat — Other'))

    def test_constructor_uses_current_title_without_selecting_status_window(self):
        def select(predicate):
            candidates = [(1, 'Muse 微信助手 · 运行状态'), (2, 'Chat — Muse')]
            matches = [hwnd for hwnd, title in candidates if predicate(title)]
            self.assertEqual(matches, [2])
            return matches[0]
        with patch('desktop_adapter.window_for', side_effect=select):
            self.assertEqual(Muse().hwnd, 2)


if __name__ == '__main__':
    unittest.main()
