"""Bounded prompt history backed by one optional archive per selected contact."""
from collections import deque
import time
from image_support import media_type
from context_archive import MAX_ARCHIVE_TURNS

MAX_TURNS=24
MAX_CONTEXT_CHARS=6000
MAX_TURN_CHARS=1200


def limited_text(text):
    text=str(text).strip()
    if len(text)>MAX_TURN_CHARS:
        return text[:1000]+'\n[长消息中段已省略]\n'+text[-160:]
    return text


def clean_context(turns):
    """Only expected data fields reach the prompt; preserve newest chronology."""
    result=[]
    remaining=MAX_CONTEXT_CHARS
    for turn in reversed(list(turns or [])[-MAX_TURNS:]):
        if not isinstance(turn,dict) or turn.get('speaker') not in ('friend','self'):
            continue
        if not isinstance(turn.get('content'),str):
            continue
        content=limited_text(turn['content'])
        if not content:
            continue
        if len(content)>remaining:
            break
        result.append({'speaker':turn['speaker'],'content':content})
        remaining-=len(content)
    return list(reversed(result))


class ConversationContext:
    def __init__(self,contact,disclosure='【AI辅助回复】',archive=None):
        self.contact=contact
        self.disclosure=disclosure
        self.archive=archive
        self.archive_path=str(archive.path) if archive else ''
        self.archive_error=''
        self.dirty=False
        records=[]
        if archive:
            if archive.contact!=contact:raise ValueError('上下文存档不属于当前好友。')
            try:
                records=archive.load()
                self.dirty=not archive.path.exists()
            except Exception as exc:
                # Preserve a damaged or mismatched file. Keep the chat usable
                # with fresh visible context; never overwrite an unread archive.
                self.archive_error=str(exc)
                self.archive=None
        self.turns=deque(records,maxlen=MAX_ARCHIVE_TURNS)
        self.seen=deque(maxlen=160)
        self.seen.extend(record['key'] for record in records[-160:])

    def record(self,message,direction):
        if direction not in ('incoming','outgoing'):return None
        media=media_type(message)
        if media:
            text='[历史表情包：只保留消息位置，画面未在本轮重传]' if media=='sticker' else '[历史图片：只保留消息位置，图片未在本轮重传]'
        elif message.kind=='mmui::ChatTextItemView':
            text=message.text.strip()
            if direction=='outgoing' and self.disclosure and text.startswith(self.disclosure):
                text=text[len(self.disclosure):].lstrip()
        else:
            return None
        if not text:return None
        return {'key':message.key,'speaker':'friend' if direction=='incoming' else 'self',
                'content':text[:100000],'kind':media or 'text','observed_at':time.time()}

    def observe(self,message,direction):
        if message.key in self.seen:return
        record=self.record(message,direction)
        if record is None:return
        self.seen.append(message.key)
        if direction=='outgoing':
            for pending in reversed(list(self.turns)[-8:]):
                if pending['key'].startswith('sent:') and self.signature(pending)==self.signature(record):
                    self.turns.remove(pending)
                    pending['key']=message.key
                    self.turns.append(pending)
                    self.dirty=True;self.flush()
                    return
        self.turns.append(record)
        self.dirty=True
        self.flush()

    def confirm_sent(self,event_id,text):
        from types import SimpleNamespace
        self.observe(SimpleNamespace(key='sent:'+event_id,text=text,kind='mmui::ChatTextItemView'),'outgoing')

    @staticmethod
    def signature(record):
        return record['speaker'],record.get('kind','text'),record['content']

    def seed(self,observations):
        """Merge the visible tail across a restart without duplicating history."""
        visible=[self.record(message,direction) for message,direction in observations]
        visible=[record for record in visible if record is not None]
        existing=list(self.turns)
        count,start=0,0
        for index in range(len(visible)):
            for length in range(min(len(existing),len(visible)-index),0,-1):
                if length<=count:break
                if ([self.signature(r) for r in existing[-length:]]==
                        [self.signature(r) for r in visible[index:index+length]]):
                    count,start=length,index
                    break
        if count:
            for offset in range(count):
                old=existing[len(existing)-count+offset];new=visible[start+offset]
                if old['key']!=new['key']:
                    old['key']=new['key'];self.dirty=True
            additions=visible[start+count:]
        elif existing:
            known={self.signature(record) for record in existing}
            additions=[record for record in visible if self.signature(record) not in known]
        else:
            additions=visible
        keys={record['key'] for record in existing}
        for record in additions:
            if record['key'] not in keys:
                existing.append(record);keys.add(record['key']);self.dirty=True
        self.turns=deque(existing,maxlen=MAX_ARCHIVE_TURNS)
        self.seen.clear()
        self.seen.extend(record['key'] for record in list(self.turns)[-148:])
        self.seen.extend(record['key'] for record in visible[-12:])
        self.flush()

    def flush(self):
        if self.archive is None:return not self.archive_error
        if not self.dirty:return True
        try:
            self.archive.save(self.turns)
            self.dirty=False;self.archive_error=''
            return True
        except Exception as exc:
            self.archive_error=str(exc)
            return False

    def before(self,contact,source_keys):
        if contact!=self.contact:
            raise ValueError('上下文不属于当前所选好友。')
        keys=set(source_keys or [])
        previous=[]
        for turn in self.turns:
            if turn['key'] in keys:
                break
            previous.append(turn)
        return clean_context(previous)
