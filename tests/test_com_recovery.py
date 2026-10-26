import unittest
from unittest.mock import Mock,patch
from comtypes import COMError
import bridge
from desktop_adapter import invoke_muse_request_once,NotReady

def stale():
    return COMError(-2147220991,'UI Automation element is no longer available',None)

class ComRecovery(unittest.TestCase):
    def test_transient_read_failure_does_not_lose_generated_reply(self):
        muse=Mock()
        muse.draft.side_effect=[stale(),None,'已收到。',stale(),'已收到。','已收到。']
        with patch.object(bridge.STOP.__class__,'exists',return_value=False), \
             patch.object(bridge.time,'sleep'),patch.object(bridge,'status'):
            result=bridge.wait_draft(muse,'unique-event',{**bridge.CONFIG,'reply_timeout_seconds':20})
        self.assertEqual(result,'已收到。')
        self.assertEqual(muse.request.call_count,0)

    def test_persistent_read_failure_stops_without_sending(self):
        muse=Mock()
        muse.draft.side_effect=stale()
        with patch.object(bridge.STOP.__class__,'exists',return_value=False), \
             patch.object(bridge.time,'sleep'),patch.object(bridge,'status'):
            with self.assertRaises(NotReady):
                bridge.wait_draft(muse,'event',{**bridge.CONFIG,'reply_timeout_seconds':20})
        self.assertEqual(muse.draft.call_count,10)
        self.assertEqual(muse.request.call_count,0)

    def test_submission_com_error_never_clicks_again(self):
        button=Mock()
        button.GetInvokePattern.return_value.Invoke.side_effect=stale()
        invoke_muse_request_once(button)
        self.assertEqual(button.GetInvokePattern.return_value.Invoke.call_count,1)

    def test_stop_during_read_recovery_is_respected(self):
        muse=Mock()
        muse.draft.side_effect=stale()
        with patch.object(bridge.STOP.__class__,'exists',side_effect=[False,True]), \
             patch.object(bridge.time,'sleep'),patch.object(bridge,'status'):
            with self.assertRaises(NotReady):
                bridge.wait_draft(muse,'event',{**bridge.CONFIG,'reply_timeout_seconds':20})
        self.assertEqual(muse.draft.call_count,1)

if __name__=='__main__':unittest.main()
