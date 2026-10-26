"""Group-only archives; preserve each visible sender, never load private data."""
import json,math,re,time
from context_archive import ContactArchive,ArchiveError,atomic_text,contact_id,MAX_ARCHIVE_TURNS
from conversation_context import ConversationContext
from image_support import media_type


class GroupArchive(ContactArchive):
    def __init__(self,root,group):
        super().__init__(root/'群聊',group)
        label=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',group).strip(' .')[:32]
        self.directory=self.root/('群-'+label+'-'+contact_id(group));self.path=self.directory/'context.json'

    def checked_records(self,records):
        if not isinstance(records,list):raise ArchiveError('群聊消息格式有误。')
        result=[];seen=set()
        for r in records[-MAX_ARCHIVE_TURNS:]:
            if (not isinstance(r,dict) or not isinstance(r.get('key'),str) or not r['key'] or len(r['key'])>300
                or not isinstance(r.get('sender'),str) or not 0<len(r['sender'])<=100
                or r.get('direction') not in ('incoming','outgoing')
                or not isinstance(r.get('content'),str) or len(r['content'])>100000
                or r.get('kind') not in ('text','image','sticker')
                or not isinstance(r.get('observed_at'),(int,float)) or not math.isfinite(r['observed_at'])):
                raise ArchiveError('群聊消息格式有误。')
            if r['key'] not in seen:
                result.append({k:r[k] for k in ('key','sender','direction','content','kind','observed_at')});seen.add(r['key'])
        return result

    def load(self):
        if not self.path.exists():return []
        try:
            if self.path.stat().st_size>100*1024*1024:raise ArchiveError('群聊存档过大。')
            data=json.loads(self.path.read_text(encoding='utf-8-sig'))
            if (data.get('format_version')!=1 or data.get('chat_type')!='group'
                or data.get('group_name')!=self.contact or data.get('group_id')!=contact_id(self.contact)):
                raise ArchiveError('群聊存档身份不匹配，原文件保留。')
            return self.checked_records(data.get('messages'))
        except ArchiveError:raise
        except Exception as exc:raise ArchiveError('群聊存档无法读取，原文件保留。') from exc

    def save(self,records):
        from datetime import datetime
        records=self.checked_records(list(records));self.directory.mkdir(parents=True,exist_ok=True)
        if self.directory.resolve().parent!=self.root.resolve():raise ArchiveError('群聊存档路径不匹配。')
        atomic_text(self.path,json.dumps({'format_version':1,'chat_type':'group','group_name':self.contact,
            'group_id':contact_id(self.contact),'updated_at':time.time(),'messages':records},ensure_ascii=False,indent=2)+'\n')
        lines=[f'群聊上下文 · {self.contact}','昵称为可见昵称，可能重名；时间为采集时间。最多保留1000条。','']
        for r in records:
            stamp=datetime.fromtimestamp(r['observed_at']).astimezone().isoformat(timespec='seconds')
            lines.extend([f"[{stamp}] {r['sender']}"+('（我）' if r['direction']=='outgoing' else ''),r['content'],''])
        atomic_text(self.directory/'聊天上下文.txt','\n'.join(lines)+'\n')


class GroupContext(ConversationContext):
    def __init__(self,group,self_name,disclosure,archive):
        self.self_name=self_name
        super().__init__(group,disclosure,archive)

    def record(self,message,direction):
        if direction not in ('incoming','outgoing') or not message.sender:return None
        kind=media_type(message)
        content='[历史'+('表情包' if kind=='sticker' else '图片')+'：画面未在本轮重传]' if kind else message.text.strip()
        if not kind and message.kind!='mmui::ChatTextItemView':return None
        if direction=='outgoing' and self.disclosure and content.startswith(self.disclosure):content=content[len(self.disclosure):].lstrip()
        return {'key':message.key,'sender':message.sender,'direction':direction,'content':content[:100000],
                'kind':kind or 'text','observed_at':time.time()} if content else None

    @staticmethod
    def signature(record):return record['sender'],record['direction'],record['kind'],record['content']

    def before(self,group,keys):
        if group!=self.contact:raise ValueError('上下文不属于当前群聊。')
        result=[]
        for r in self.turns:
            if r['key'] in keys:break
            result.append(dict(r))
        return result[-24:]

    def confirm_sent(self,event_id,text):
        from types import SimpleNamespace
        self.observe(SimpleNamespace(key='sent:'+event_id,sender=self.self_name,text=text,kind='mmui::ChatTextItemView'),'outgoing')
