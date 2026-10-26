"""Only selected-group, fresh visible @ triggers enter the shared draft pipeline."""
import ctypes,os,tempfile,time
from comtypes import COMError
import win32api
from chat_settings import group_config
from desktop_adapter import Muse,NotReady,SendDeferred,capture_window,walk
from group_adapter import GroupWeChat
from group_policy import eligible,mentioned,GROUP_TITLE
from group_diagnostics import ReceiveDiagnostics
from group_context import GroupArchive,GroupContext
from context_archive import default_archive_root
from image_support import media_type,extract_attachment,ImageUnavailable,MAX_ATTACHMENTS
from storage import LOCAL,Journal,status
from reply_scope import begin_reply,end_reply
from reply_queue import batch_ready,muse_wait_reason


def approval(group,incoming,draft,event):
    text=(f'群聊：{group}\n请求：{event}\n\n触发：正文 @ 本人\n\n收到：\n{incoming[:900]}\n\n'
          f'拟发送的完整内容：\n{draft}\n\n【是】发送到本群  【否】跳过  【取消】结束监听')
    return ctypes.windll.user32.MessageBoxW(None,text,GROUP_TITLE,0x3|0x20|0x100|0x10000|0x40000)


class GroupSession:
    def __init__(self,wx,memory,initial,self_name,tracker_class,diagnostics=None):
        self.wx=wx;self.memory=memory;self.self_name=self_name
        self.tracker=tracker_class(initial);self.pending=[];self.last_incoming=0;self.manual_epoch=0
        self.first_incoming=0
        self.diagnostics=diagnostics or ReceiveDiagnostics();self.waiting_sender_count=0;self.receive_reason=''
        self.memory.seed([(m,m.direction) for m in initial[-12:]])

    def pump(self):
        from group_context import GroupContext
        current=self.wx.snapshot()
        self.waiting_sender_count=0;self.receive_reason=''
        for m in self.tracker.update(current):
            is_mention=mentioned(m.text,self.self_name)
            if m.direction=='unknown' or (m.direction=='incoming' and not m.sender):
                reason='waiting_direction' if m.direction=='unknown' else 'waiting_sender'
                self.diagnostics.record(m.key,reason,mentioned=is_mention)
                if is_mention:
                    self.waiting_sender_count+=1
                    self.receive_reason='有 @ 消息仍在核对'+('发送方向' if m.direction=='unknown' else '发言者昵称')+'，正在重试。'
                # Do not consume this source: a later OCR/layout pass can
                # resolve it even though a newer row became the tracker tail.
                continue
            self.tracker.handled(m.key)
            if m.direction=='outgoing':
                record=self.memory.record(m,m.direction)
                echo=record is not None and any(r['key'].startswith('sent:') and GroupContext.signature(r)==GroupContext.signature(record) for r in list(self.memory.turns)[-8:])
                if not echo:
                    self.manual_epoch+=1
            self.memory.observe(m,m.direction)
            if eligible(m,self.self_name):
                if not self.pending:self.first_incoming=time.monotonic()
                self.pending.append(m);self.last_incoming=time.monotonic()
                self.diagnostics.record(m.key,'queued',mentioned=True)
            elif media_type(m) and m.direction=='incoming' and m.sender and self.pending and self.pending[-1].sender==m.sender:
                # Associate only immediately adjacent same-speaker attachments.
                previous=[r for r in current if r.kind!='mmui::ChatItemView']
                i=next((i for i,r in enumerate(previous) if r.key==m.key),-1)
                if i>0 and previous[i-1].key==self.pending[-1].key:
                    self.pending.append(m);self.last_incoming=time.monotonic()
            else:self.diagnostics.record(m.key,'not_triggered',mentioned=is_mention,direction=m.direction)
        self.memory.flush()
        return current


def process_group(session,muse,journal,batch,config,review=approval):
    from bridge import wait_draft,STOP,record_failure
    group,self_name=group_config(config);wx=session.wx
    if wx.contact!=group or wx.self_name!=self_name or not any(eligible(m,self_name) for m in batch):
        raise NotReady('群聊目标或 @ 触发证据不匹配。')
    keys=[m.key for m in batch]
    if not journal.claim_sources(keys):return 'skipped'
    wx.required_sources=set(keys)
    event=journal.create('群聊｜'+group,'\n'.join(m.sender+'：'+m.text for m in batch))
    base={'pid':os.getpid(),'contact':group,'chat_mode':'group','group_self_name':self_name,
          'group_reply_policy':'mention','mentioned_self':True,'trigger_keys':keys,'event_id':event,'mode':config['mode']}
    workspace=None;stage='preparing'
    scope=begin_reply(wx,group,event,'group')
    history=session.memory.for_reply(group,keys)
    incoming=[{'sender':m.sender,'content':m.text,'kind':media_type(m) or 'text'} for m in batch]
    def check():
        try:session.pump()
        except (NotReady,COMError):pass
    try:
        attachments=[]
        images=[m for m in batch if media_type(m)]
        if images:
            if len(images)>MAX_ATTACHMENTS:raise ImageUnavailable('本批图片过多，跳过。')
            work=LOCAL/'image-work';work.mkdir(parents=True,exist_ok=True)
            workspace=tempfile.TemporaryDirectory(prefix='group-',dir=work,ignore_cleanup_errors=True)
            status('reading_images',**base)
            attachments=[extract_attachment(wx,m,workspace.name,capture_window,walk,STOP.exists) for m in images]
        check();journal.state(event,'submitted');stage='muse'
        status('waiting_muse',**base)
        muse.request_group(event,group,self_name,incoming,history,config['max_reply_characters'],attachments,STOP.exists)
        answer=wait_draft(muse,event,config,on_poll=check)
        check();outgoing=config['disclosure']+'\n'+answer;journal.draft(event,outgoing)
        status('awaiting_approval',**base);stage='review'
        decision=review(group,'\n'.join(m.sender+'：'+m.text for m in batch),outgoing,event)
        if STOP.exists() or decision==2:journal.state(event,'skipped','stopped');return 'pause'
        if decision!=6:journal.state(event,'skipped');return 'skipped'
        check();journal.state(event,'approved');status('sending',**base)
        journal.state(event,'sending');stage='sending'
        visible=wx.send_approved(outgoing,scope,STOP.exists)
        journal.state(event,'sent_ui' if visible else 'unconfirmed')
        if visible:session.memory.confirm_sent(event,outgoing)
        status('sent_ui' if visible else 'send_unconfirmed',**base)
        return 'sent_ui' if visible else 'unconfirmed'
    except (SendDeferred,ImageUnavailable) as exc:
        journal.state(event,'skipped',str(exc));status('reply_skipped',reason=str(exc),**base)
        return 'skipped'
    except NotReady as exc:
        if stage in ('preparing','review'):
            # No Send action was attempted. A moved/hidden row or a changed
            # chat must not terminate listening for every future mention.
            journal.state(event,'skipped',str(exc));status('reply_skipped',reason=str(exc),**base)
            return 'skipped'
        record_failure(event,'group_'+stage,exc)
        journal.state(event,'unconfirmed' if stage=='sending' else 'failed',str(exc))
        status('send_unconfirmed' if stage=='sending' else 'needs_attention',reason=str(exc),**base)
        return 'pause'
    except Exception as exc:
        record_failure(event,'group_'+stage,exc)
        journal.state(event,'unconfirmed' if stage=='sending' else 'failed',str(exc))
        status('send_unconfirmed' if stage=='sending' else 'needs_attention',reason=str(exc),**base)
        return 'pause'
    finally:
        end_reply(wx,scope)
        wx.required_sources=set()
        if workspace:workspace.cleanup()


def run_group(config):
    from bridge import acquire_lock,MessageTracker,STOP
    group,self_name=group_config(config)
    if config.get('mode')!='approve_each_reply' or config.get('auto_y_enabled'):
        raise ValueError('群聊必须使用本机逐条确认流程。')
    if not 1<=config['max_reply_characters']<=800:raise ValueError('回复长度配置有误。')
    lock=acquire_lock();LOCAL.mkdir(exist_ok=True);STOP.unlink(missing_ok=True);(LOCAL/'STOP_AUTO_Y').touch()
    base={'pid':os.getpid(),'contact':group,'chat_mode':'group','group_self_name':self_name,'group_reply_policy':'mention'}
    journal=Journal();journal.recover();journal.purge(config['retention_days']);sent=0
    try:
        while not STOP.exists():
            try:
                wx=GroupWeChat(group,self_name,config['expected_wechat_version']);initial=wx.snapshot()
                muse=Muse(config.get('muse_sender_label','Nora'));muse.document();break
            except (NotReady,COMError) as exc:
                status('waiting_desktop',reason=str(exc),**base);time.sleep(1)
        else:return 0
        memory=GroupContext(group,self_name,config['disclosure'],GroupArchive(default_archive_root(),group))
        session=GroupSession(wx,memory,initial,self_name,MessageTracker,ReceiveDiagnostics(LOCAL/'group-receive.jsonl'))
        while not STOP.exists():
            try:
                session.pump()
                if batch_ready(session.pending,session.first_incoming,config['merge_seconds']):
                    wait_reason=muse_wait_reason(muse)
                    if wait_reason:
                        status('waiting_desktop',reason=wait_reason,pending_count=len(session.pending),**base)
                        time.sleep(config['poll_seconds']);continue
                    batch=session.pending;session.pending=[];session.first_incoming=0
                    result=process_group(session,muse,journal,batch,config)
                    for message in batch:session.diagnostics.record(message.key,'result_'+result,mentioned=mentioned(message.text,self_name))
                    if result in ('pause','unconfirmed'):return 1
                    if result=='sent_ui':sent+=1
                status('listening',sent_count=sent,pending_count=len(session.pending),context_archive=memory.archive_path,
                       context_archive_error=memory.archive_error,waiting_sender_count=session.waiting_sender_count,
                       reason=session.receive_reason,**base)
            except (NotReady,COMError) as exc:status('waiting_desktop',reason=str(exc),**base)
            time.sleep(config['poll_seconds'])
        status('stopped',sent_count=sent,**base)
        return 0
    finally:win32api.CloseHandle(lock)
