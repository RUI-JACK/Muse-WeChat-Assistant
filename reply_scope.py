"""One-use reply authorization bound to an exact adapter, process and target."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ReplyScope:
    contact: str
    event_id: str
    chat_mode: str
    pid: object
    hwnd: object


def begin_reply(wx,contact,event_id,chat_mode='private'):
    if not contact or not event_id or chat_mode not in ('private','group'):
        raise ValueError('回复事件或目标不完整。')
    scope=ReplyScope(contact,event_id,chat_mode,getattr(wx,'pid',None),getattr(wx,'hwnd',None))
    wx._active_reply_scope=scope
    return scope


def end_reply(wx,scope):
    if getattr(wx,'_active_reply_scope',None) is scope:wx._active_reply_scope=None
