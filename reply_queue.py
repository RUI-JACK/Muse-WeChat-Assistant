"""Freeze batches on a first-arrival deadline; observe without cancelling."""
import time
from comtypes import COMError
from desktop_adapter import NotReady


def batch_ready(pending,first_incoming,merge_seconds):
    return bool(pending) and time.monotonic()-first_incoming>=merge_seconds


def muse_wait_reason(muse):
    if muse.generating():return 'Muse 仍在完成上一条回复，新的消息已排队，继续监听。'
    edit,_,_=muse.composer()
    if edit.GetValuePattern().Value:return 'Muse 有未发送草稿，新的消息已排队，不会覆盖草稿。'
    return ''


class PrivateSession:
    def __init__(self,wx,memory,initial,tracker_class,resume_latest=False):
        self.wx=wx;self.memory=memory;self.tracker=tracker_class(initial,resume_latest)
        self.pending=[];self.first_incoming=0;self.last_incoming=0;self.ignored=0
        self.read_error=''

    def pump(self):
        current=self.wx.snapshot()
        for message in self.tracker.update(current):
            direction=self.wx.direction(message)
            if direction=='unknown':continue
            self.memory.observe(message,direction)
            self.tracker.handled(message.key)
            if direction=='incoming':
                now=time.monotonic()
                if not self.pending:self.first_incoming=now
                self.pending.append(message);self.last_incoming=now
            else:
                # A phone/PC self-message belongs in context, not in the
                # incoming queue, and does not cancel the current reply.
                self.ignored+=1
        self.read_error='';self.memory.flush()
        return current

    def poll_during_reply(self):
        try:return self.pump()
        except (NotReady,COMError) as exc:
            # Do not discard the model's request during a transient refresh.
            # The adapter rechecks exact target/process/editor before Send.
            self.read_error=str(exc)

    def ready(self,merge_seconds):return batch_ready(self.pending,self.first_incoming,merge_seconds)

    def take(self):
        batch=self.pending;self.pending=[];self.first_incoming=0
        return batch
