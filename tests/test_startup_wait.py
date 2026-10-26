import unittest
from unittest.mock import Mock, patch
import bridge
from desktop_adapter import NotReady

CONFIG = {'allowed_contact': '测试好友', 'expected_wechat_version': '4.1.15.56',
          'mode': 'approve_each_reply', 'poll_seconds': 2}


class StartupWaiting(unittest.TestCase):
    def test_login_unavailable_then_ready_enters_with_fresh_baseline(self):
        wx, muse = Mock(), Mock()
        wx.snapshot.return_value = ['current baseline']
        stop = Mock()
        stop.exists.return_value = False
        with patch.object(bridge, 'WeChat', side_effect=[NotReady('等待微信登录'), wx]), \
             patch.object(bridge, 'Muse', return_value=muse), \
             patch.object(bridge, 'status') as status, patch.object(bridge.time, 'sleep'):
            self.assertEqual(bridge.connect_desktop(CONFIG, stop), (wx, muse, ['current baseline']))
        self.assertEqual(status.call_args.args[0], 'waiting_desktop')
        self.assertIn('登录', status.call_args.kwargs['reason'])
        wx.send_approved.assert_not_called()
        muse.request.assert_not_called()

    def test_stop_during_startup_wait_does_not_connect_or_send(self):
        stop = Mock()
        stop.exists.side_effect = [False, True]
        with patch.object(bridge, 'WeChat', side_effect=NotReady('尚未登录')), \
             patch.object(bridge, 'Muse') as muse, \
             patch.object(bridge, 'status'), patch.object(bridge.time, 'sleep'):
            self.assertIsNone(bridge.connect_desktop(CONFIG, stop))
        muse.assert_not_called()

    def test_muse_page_not_ready_is_retried_without_requests(self):
        wx, muse = Mock(), Mock()
        wx.snapshot.return_value = ['latest baseline']
        muse.document.side_effect = [NotReady('请打开主聊天'), object()]
        stop = Mock()
        stop.exists.return_value = False
        with patch.object(bridge, 'WeChat', return_value=wx), \
             patch.object(bridge, 'Muse', return_value=muse), \
             patch.object(bridge, 'status') as status, patch.object(bridge.time, 'sleep'):
            self.assertEqual(bridge.connect_desktop(CONFIG, stop)[2], ['latest baseline'])
        self.assertEqual(status.call_count, 1)
        self.assertEqual(muse.document.call_count, 2)
        muse.request.assert_not_called()
        wx.send_approved.assert_not_called()


if __name__ == '__main__':
    unittest.main()
