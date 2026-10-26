"""One local, readable context archive per exact selected WeChat contact."""
import hashlib,json,math,os,re,tempfile,time
from pathlib import Path

MAX_ARCHIVE_TURNS=1000


def default_archive_root():
    # Resolve this Windows user's actual Documents, including redirected paths.
    from win32com.shell import shell,shellcon
    documents=Path(shell.SHGetFolderPath(0,shellcon.CSIDL_PERSONAL,None,0))
    return documents/'聊天上下文'


class ArchiveError(RuntimeError):
    pass


def contact_id(contact):
    return hashlib.sha256(contact.encode('utf-8')).hexdigest()[:16]


def archive_folder(contact):
    label=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',contact).strip(' .')[:32] or '好友'
    return '好友-'+label+'-'+contact_id(contact)


def atomic_text(path,text):
    path=Path(path)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                                         prefix='.context-',suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name)
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        for attempt in range(10):
            try:temporary.replace(path);return
            except PermissionError:
                if attempt==9:raise
                time.sleep(.025)
    finally:
        if temporary:
            try:temporary.unlink(missing_ok=True)
            except OSError:pass


class ContactArchive:
    def __init__(self,root,contact):
        self.root=Path(root)
        self.contact=contact
        self.directory=self.root/archive_folder(contact)
        self.path=self.directory/'context.json'

    def checked_records(self,records):
        if not isinstance(records,list):raise ArchiveError('上下文消息格式有误。')
        result=[];seen=set()
        for record in records[-MAX_ARCHIVE_TURNS:]:
            if not isinstance(record,dict):raise ArchiveError('上下文消息格式有误。')
            key=record.get('key');role=record.get('speaker');content=record.get('content')
            kind=record.get('kind','text');stamp=record.get('observed_at',time.time())
            if (not isinstance(key,str) or not key or len(key)>300 or role not in ('friend','self')
                    or not isinstance(content,str) or len(content)>100000
                    or kind not in ('text','image','sticker')
                    or not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or not 0<=stamp<=4102444800):
                raise ArchiveError('上下文消息格式有误。')
            if key not in seen:
                result.append({'key':key,'speaker':role,'content':content,'kind':kind,'observed_at':stamp})
                seen.add(key)
        return result

    def load(self):
        if not self.path.exists():return []
        try:
            if self.path.stat().st_size>100*1024*1024:raise ArchiveError('上下文存档过大。')
            data=json.loads(self.path.read_text(encoding='utf-8-sig'))
            if (not isinstance(data,dict) or data.get('format_version')!=1
                    or data.get('contact_name')!=self.contact or data.get('contact_id')!=contact_id(self.contact)):
                raise ArchiveError('存档身份与当前好友不符，未读取其中内容。')
            return self.checked_records(data.get('messages'))
        except ArchiveError:raise
        except (OSError,ValueError,TypeError) as exc:
            raise ArchiveError('无法读取上下文存档，原文件已保留。') from exc

    def save(self,records):
        from datetime import datetime
        records=self.checked_records(list(records))
        self.directory.mkdir(parents=True,exist_ok=True)
        if self.directory.resolve().parent!=self.root.resolve():
            raise ArchiveError('上下文目录超出预期位置，未写入。')
        data={'format_version':1,'contact_id':contact_id(self.contact),'contact_name':self.contact,
              'updated_at':time.time(),'message_count':len(records),'messages':records}
        atomic_text(self.path,json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        lines=[f'微信助手 · {self.contact} 的上下文存档',
               '仅记录助手实际采集到的对话；时间为采集时间。最多保留最近1000条。',
               '自动生成，请勿直接编辑此文本；程序读取同目录 context.json。','']
        for record in records:
            stamp=datetime.fromtimestamp(record['observed_at']).astimezone().isoformat(timespec='seconds')
            label='对方' if record['speaker']=='friend' else '我'
            lines.extend([f'[{stamp}] {label}',record['content'],''])
        if not records:lines.append('尚无已采集消息。')
        atomic_text(self.directory/'聊天上下文.txt','\n'.join(lines)+'\n')


def migrate_archives(legacy_root,destination_root):
    """Copy valid legacy archives once; preserve source and existing targets."""
    legacy_root=Path(legacy_root);destination_root=Path(destination_root)
    report={'copied':[],'existing':[],'errors':[]}
    if not legacy_root.is_dir() or legacy_root.resolve()==destination_root.resolve():return report
    for folder in legacy_root.iterdir():
        if not folder.is_dir() or folder.is_symlink() or not (folder/'context.json').is_file():continue
        try:
            data=json.loads((folder/'context.json').read_text(encoding='utf-8-sig'))
            contact=data.get('contact_name')
            if not isinstance(contact,str) or folder.name!=archive_folder(contact):
                raise ArchiveError('旧存档目录与好友身份不一致。')
            source=ContactArchive(legacy_root,contact)
            records=source.load()
            target=ContactArchive(destination_root,contact)
            if target.path.exists():
                target.load()
                report['existing'].append(contact)
            else:
                target.save(records)
                if target.load()!=records:raise ArchiveError('迁移后的存档校验不一致。')
                report['copied'].append({'contact':contact,'messages':len(records)})
        except Exception as exc:
            report['errors'].append({'folder':folder.name,'error':str(exc)})
    return report


def migrate_runtime_archives(legacy_root,destination_root):
    # Prefer the most recent Documents location over the older app directory.
    destination_root=Path(destination_root)
    previous_documents=destination_root.parent/'微信助手上下文存档'
    reports=[migrate_archives(previous_documents,destination_root),
             migrate_archives(legacy_root,destination_root)]
    return {key:[item for report in reports for item in report[key]]
            for key in ('copied','existing','errors')}
