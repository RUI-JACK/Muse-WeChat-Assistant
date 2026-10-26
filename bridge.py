"""Local Muse -> per-message owner approval -> one allowlisted WeChat chat."""
import ctypes
import json
import os
from pathlib import Path
import sys
import time
import traceback
import tempfile
import shutil
from comtypes import COMError
import win32api
import win32event
from desktop_adapter import WeChat, Muse, NotReady, SendDeferred, chat_tail, capture_window, walk
from image_support import media_type, extract_attachment, ImageUnavailable, MAX_ATTACHMENTS
from storage import ROOT, LOCAL, Journal, status
from conversation_context import ConversationContext, clean_context
from context_archive import ContactArchive, default_archive_root, migrate_runtime_archives
from reply_metrics import ReplyTrace

CONFIG = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
STOP = LOCAL / 'STOP'

def ensure_manual_approval(config):
    """Every draft must be approved by the account owner in this process."""
    if config.get('mode') != 'approve_each_reply':
        raise ValueError('模式必须为逐条审批（approve_each_reply）。')
    if not config.get('allowed_contact'):
        raise ValueError('必须明确指定一位好友。')
    if config.get('auto_y_enabled'):
        raise NotReady('本机自动Y会代替本人点“是”，与“待本人审批”的请求方式冲突；'
                       '请先双击“切换为逐条确认”。')
    return True

def check_config(config):
    if not 1 <= config['max_reply_characters'] <= 800:
        raise ValueError('回复长度配置超出范围。')
    ensure_manual_approval(config)

def approval(contact,incoming,draft,demo=False,moved=False):
    intro = '演示：所有按钮都不会向微信发送。\n\n' if demo else ''
    if moved:
        intro += ('注意：起草期间聊天里出现了新内容（例如图片、表情或语音），这条草稿只针对下面的来信，'
                  '请确认是否仍要发送。\n\n')
    preview = incoming[:600] + ('\n[来信预览已截短]' if len(incoming)>600 else '')
    text = (intro + f'联系人：{contact}\n\n收到：\n{preview}\n\n拟发送的完整内容：\n{draft}\n\n'
            '【是】发送本条  【否】跳过本条  【取消】暂停桥接器\n'
            '请核对内容，尤其是个人信息与承诺。')
    flags = 0x3 | 0x20 | 0x100 | 0x10000 | 0x40000
    title = 'Muse 微信回复确认' + (' · 演示' if demo else '')
    return ctypes.windll.user32.MessageBoxW(None,text,title,flags)

def wait_draft(muse,event_id,config,on_poll=None):
    until = time.monotonic() + config['reply_timeout_seconds']
    previous = None
    stable = 0
    com_failures = 0
    while time.monotonic() < until:
        if STOP.exists():
            raise NotReady('已停止。')
        if on_poll is not None:on_poll()
        try:
            candidate = muse.draft(event_id,config['max_reply_characters'])
            com_failures = 0
        except COMError as exc:
            com_failures += 1
            stable = 0
            status('waiting_muse_ui',pid=os.getpid(),event_id=event_id,
                   reason='Muse 网页控件正在刷新，重新读取同一回复。',
                   retry=com_failures,hresult=getattr(exc,'hresult',None))
            if com_failures >= 10:
                raise NotReady('Muse 网页控件连续读取失败；未发送微信，请重新打开网页后继续。') from exc
            time.sleep(.5)
            continue
        stable = stable + 1 if candidate and candidate == previous else 0
        if candidate and stable >= 2:
            return candidate
        previous = candidate
        time.sleep(config.get('draft_poll_seconds',.3))
    raise NotReady('Muse 回复超时，未向微信发送；不会自动重新提交。')

def record_failure(event_id,stage,exc):
    LOCAL.mkdir(exist_ok=True)
    frames=traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    diagnostic={'event_id':event_id,'stage':stage,'type':type(exc).__name__,
                'hresult':getattr(exc,'hresult',None),'time':time.time(),
                'stack':[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in frames]}
    (LOCAL/'last-error.json').write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding='utf-8')

def process_batch(wx,muse,journal,contact,incoming,config,demo=False,review=approval,source_keys=None,image_messages=None,conversation=None,on_sent=None,metrics=None):
    check_config(config)
    if contact != config['allowed_contact'] or getattr(wx,'contact',contact) != contact:
        raise NotReady('目标不在当前白名单内，拒绝处理。')
    if not demo and source_keys and not journal.claim_sources(source_keys):
        return 'skipped'
    signature = chat_tail(wx.snapshot()) if not demo else []
    event_id = journal.create(contact,incoming)
    if metrics is not None:metrics.event_id=event_id
    status('waiting_muse',pid=os.getpid(),contact=contact,event_id=event_id,demo=demo,mode=config['mode'])
    journal.state(event_id,'submitted')
    stage = 'requesting_muse'
    workspace = None
    try:
        history=clean_context(conversation)
        context_options={'context':history} if history else {}
        if image_messages and not demo:
            stage = 'reading_images'
            if metrics is not None:metrics.mark('image_read')
            status('reading_images',pid=os.getpid(),contact=contact,event_id=event_id,
                   image_count=len(image_messages),mode=config['mode'])
            if len(image_messages)>MAX_ATTACHMENTS:
                raise ImageUnavailable(f'单次最多识别{MAX_ATTACHMENTS}张图片/表情包，本批已跳过。')
            work_root=LOCAL/'image-work'
            work_root.mkdir(parents=True,exist_ok=True)
            workspace=tempfile.TemporaryDirectory(prefix='request-',dir=work_root,ignore_cleanup_errors=True)
            attachments=[extract_attachment(wx,m,workspace.name,capture_window,walk,STOP.exists)
                         for m in image_messages]
            # UI extraction must not substitute an old picture if a newer
            # arrival or a manual response changed the selected conversation.
            if chat_tail(wx.snapshot())!=signature:
                journal.state(event_id,'superseded')
                return 'superseded'
            stage='requesting_muse'
            if metrics is not None:metrics.mark('muse_submit')
            status('uploading_images',pid=os.getpid(),contact=contact,event_id=event_id,
                   image_count=len(attachments),mode=config['mode'])
            muse.request_images(event_id,contact,incoming,config['max_reply_characters'],attachments,STOP.exists,**context_options)
        else:
            if metrics is not None:metrics.mark('muse_submit')
            muse.request(event_id,contact,incoming,config['max_reply_characters'],**context_options)
        stage = 'reading_muse'
        if metrics is not None:metrics.mark('muse_wait')
        answer = wait_draft(muse,event_id,config)
        if metrics is not None:metrics.mark('validation')
        outgoing = config['disclosure'] + '\n' + answer
        journal.draft(event_id,outgoing)
        stage = 'validating_chat'
        current_tail = [] if demo else chat_tail(wx.snapshot())
        moved = current_tail != signature
        if moved:
            # Text and supported media supersede an older draft. Unsupported
            # voice/file arrivals retain the original warning and review path.
            added = [kind for kind,name in current_tail if (kind,name) not in signature]
            if any(kind == 'mmui::ChatTextItemView' for kind in added) or any(
                    media_type(m) and chat_tail([m])[0] not in signature
                    for m in wx.snapshot()):
                journal.state(event_id,'superseded')
                status('draft_superseded',pid=os.getpid(),contact=contact,event_id=event_id,
                       added_kinds=added[:3])
                return 'superseded'
            # Rows are only compared by content, so a repaint with the same
            # text does not count as a move.
            moved = bool(added)
        status('awaiting_approval',pid=os.getpid(),contact=contact,event_id=event_id,demo=demo,
               mode=config['mode'],chat_moved=moved)
        stage = 'awaiting_approval'
        if metrics is not None:metrics.mark('approval')
        approval_tail = chat_tail(wx.snapshot()) if moved and not demo else signature
        decision = review(contact,incoming,outgoing,demo,moved)
        if demo:
            journal.state(event_id,'demo')
            status('demo_passed',pid=os.getpid(),contact=contact,event_id=event_id,sent=False)
            return 'demo'
        if STOP.exists():
            journal.state(event_id,'skipped','stopped')
            return 'pause'
        if decision == 2:
            journal.state(event_id,'skipped','paused')
            return 'pause'
        if decision != 6:  # IDYES is the only path to send.
            journal.state(event_id,'skipped')
            return 'skipped'
        journal.state(event_id,'approved',config['mode'])
        status('sending',pid=os.getpid(),contact=contact,event_id=event_id,mode=config['mode'])
        journal.state(event_id,'sending',config['mode'])
        stage = 'sending_wechat'
        if metrics is not None:metrics.mark('wechat_send')
        visible = wx.send_approved(outgoing,approval_tail,STOP.exists)
        if metrics is not None:metrics.mark('archive')
        journal.state(event_id,'sent_ui' if visible else 'unconfirmed',config['mode'])
        if visible and on_sent is not None:
            try:on_sent(event_id,outgoing)
            except Exception as exc:record_failure(event_id,'saving_context',exc)
        status('sent_ui' if visible else 'send_unconfirmed',pid=os.getpid(),contact=contact,event_id=event_id,mode=config['mode'])
        return 'sent_ui' if visible else 'unconfirmed'
    except ImageUnavailable as exc:
        record_failure(event_id,stage,exc)
        journal.state(event_id,'skipped',str(exc))
        status('reply_skipped',pid=os.getpid(),contact=contact,event_id=event_id,
               reason=str(exc),stage=stage)
        return 'pause' if STOP.exists() else 'skipped'
    except SendDeferred as exc:
        record_failure(event_id,stage,exc)
        journal.state(event_id,'skipped',str(exc))
        status('reply_skipped',pid=os.getpid(),contact=contact,event_id=event_id,
               reason=str(exc),stage=stage)
        return 'pause' if STOP.exists() else 'skipped'
    except NotReady as exc:
        record_failure(event_id,stage,exc)
        if stage=='reading_images':
            journal.state(event_id,'skipped',str(exc))
            status('reply_skipped',pid=os.getpid(),contact=contact,event_id=event_id,
                   reason=str(exc),stage=stage)
            return 'pause' if STOP.exists() else 'skipped'
        journal.state(event_id,'unconfirmed' if stage=='sending_wechat' else 'failed',str(exc))
        status('needs_attention',pid=os.getpid(),contact=contact,event_id=event_id,reason=str(exc),stage=stage)
        return 'pause'
    except Exception as exc:
        # No blind retry: the last UI invocation may already have succeeded.
        record_failure(event_id,stage,exc)
        if stage=='reading_images':
            journal.state(event_id,'skipped',type(exc).__name__)
            status('reply_skipped',pid=os.getpid(),contact=contact,event_id=event_id,
                   reason='图片读取失败，本条已跳过，继续监听后续消息。',stage=stage)
            return 'pause' if STOP.exists() else 'skipped'
        journal.state(event_id,'unconfirmed' if stage=='sending_wechat' else 'failed',type(exc).__name__)
        status('needs_attention',pid=os.getpid(),contact=contact,event_id=event_id,reason=type(exc).__name__,stage=stage)
        return 'pause'
    finally:
        if workspace is not None:
            workspace.cleanup()

def acquire_lock():
    handle = win32event.CreateMutex(None,False,'Local\\MuseWeChatBridgePerMessageApproval')
    if win32api.GetLastError() == 183:
        win32api.CloseHandle(handle)
        raise NotReady('桥接器已经运行。')
    return handle

def doctor():
    target=CONFIG['allowed_contact']
    factory=lambda:WeChat(target,CONFIG['expected_wechat_version'])
    if CONFIG.get('chat_mode','private')=='group':
        from chat_settings import group_config
        from group_adapter import GroupWeChat
        target,self_name=group_config(CONFIG)
        factory=lambda:GroupWeChat(target,self_name,CONFIG['expected_wechat_version'])
    results = {'contact':target,'chat_mode':CONFIG.get('chat_mode','private'),'mode':CONFIG['mode'],'sent':False}
    for label,factory in (('wechat',factory),('muse',Muse)):
        try:
            app = factory()
            if label == 'wechat':
                detail,edit,view = app.controls()
                results[label]={'ready':True,'version':app.version,'title_matches':True,
                                'visible_rows':len(app.snapshot()),'draft_empty':edit.GetValuePattern().Value==''}
            else:
                doc = app.document()
                edit = doc.EditControl(Name='消息',searchDepth=12)
                results[label]={'ready':True,'draft_empty':edit.GetValuePattern().Value==''}
        except Exception as exc:
            results[label]={'ready':False,'reason':str(exc)}
    LOCAL.mkdir(exist_ok=True)
    (LOCAL/'doctor.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
    return 0 if all(results[x]['ready'] for x in ('wechat','muse')) else 1

def resume_candidate(messages):
    # Explicit resume handles only the latest visible text, never an entire
    # historical conversation. Its sender is checked by the normal input path.
    return next((m for m in reversed(messages) if m.kind=='mmui::ChatTextItemView'),None)

class MessageTracker:
    def __init__(self,messages,resume_latest=False):
        self.tail = messages[-1].key if messages else None
        latest = resume_candidate(messages) if resume_latest else None
        self.waiting = {latest.key} if latest else set()

    def update(self,messages):
        keys = [m.key for m in messages]
        if self.tail in keys:
            self.waiting.update(keys[keys.index(self.tail)+1:])
        # Rows newly materialized ABOVE the previous tail are history, not
        # arrivals. A rebuilt view with no tail is conservatively baselined.
        self.waiting.intersection_update(keys)
        self.tail = keys[-1] if keys else None
        return [m for m in messages if m.key in self.waiting]

    def handled(self,key):
        self.waiting.discard(key)

def connect_desktop(config, stop=None):
    """Wait for login, the selected chat and Muse without sending anything."""
    stop = STOP if stop is None else stop
    contact = config['allowed_contact']
    while not stop.exists():
        try:
            wx = WeChat(contact, config['expected_wechat_version'])
            muse = Muse(config.get('muse_sender_label', 'Nora'))
            initial = wx.snapshot()
            muse.document()
            return wx, muse, initial
        except (NotReady, COMError) as exc:
            reason = (str(exc) if isinstance(exc, NotReady) else
                      '桌面控件正在刷新，正在重新连接微信和 Muse。')
            status('waiting_desktop', pid=os.getpid(), contact=contact,
                   reason=reason, mode=config['mode'])
            time.sleep(min(2, config.get('poll_seconds', 2)))
    return None


def seed_context(wx,memory,messages):
    """Read recent visible history for context; never queue it as an arrival."""
    observed=[]
    for message in messages[-12:]:
        if STOP.exists():
            break
        if message.kind!='mmui::ChatTextItemView' and not media_type(message):
            continue
        try:
            observed.append((message,wx.direction(message)))
        except (NotReady,COMError):
            # A partially visible row or a refreshing UI is not reliable
            # context. Normal listening revalidates the chat independently.
            continue
    memory.seed(observed)


def listener_delay(poll_seconds,merge_seconds,pending,last_incoming):
    if not pending:return poll_seconds
    remaining=merge_seconds-(time.monotonic()-last_incoming)
    return min(poll_seconds,max(.05,remaining))


def run(demo=False,no_dialog=False,resume_latest=False):
    if CONFIG.get('chat_mode','private')=='group':
        if demo:raise NotReady('群聊不向真实群发送演示消息。')
        from group_runtime import run_group
        return run_group(CONFIG)
    check_config(CONFIG)
    lock = acquire_lock()
    LOCAL.mkdir(exist_ok=True)
    STOP.unlink(missing_ok=True)
    # A terminated worker may leave temporary media. Only delete our own
    # request directories after acquiring the one-worker mutex.
    media_root=(LOCAL/'image-work').resolve()
    if media_root.is_dir() and not (LOCAL/'image-work').is_symlink():
        for directory in media_root.glob('request-*'):
            if directory.is_dir() and not directory.is_symlink() and directory.resolve().parent==media_root:
                shutil.rmtree(directory,ignore_errors=True)
    # Retire any YES-watcher left running by an older build: it would approve
    # drafts without the owner, which the request wording no longer claims.
    (LOCAL/'STOP_AUTO_Y').touch()
    journal = Journal()
    journal.recover()
    journal.purge(CONFIG['retention_days'])
    contact = CONFIG['allowed_contact']
    if demo:
        wx,muse = WeChat(contact,CONFIG['expected_wechat_version']),Muse(CONFIG.get('muse_sender_label','Nora'))
        review = (lambda *args:7) if no_dialog else approval
        result = process_batch(wx,muse,journal,contact,'你好，你现在方便聊两句吗？',CONFIG,True,review)
        print(json.dumps({'result':result,'sent':False},ensure_ascii=False))
        return 0 if result=='demo' else 1
    connected = connect_desktop(CONFIG)
    if connected is None:
        status('stopped',contact=contact,sent_count=0)
        win32api.CloseHandle(lock)
        return 0
    wx, muse, initial = connected
    archive_root=default_archive_root()
    migrate_runtime_archives(LOCAL/'contexts',archive_root)
    memory=ConversationContext(contact,CONFIG['disclosure'],ContactArchive(archive_root,contact))
    status('reading_context',pid=os.getpid(),contact=contact,mode=CONFIG['mode'])
    seed_context(wx,memory,initial)
    tracker = MessageTracker(initial,resume_latest)
    pending = []
    last_incoming = 0
    ignored = 0
    status('listening',pid=os.getpid(),contact=contact,baseline_rows=len(initial),sent_count=0,mode=CONFIG['mode'],
           context_archive=memory.archive_path,context_archive_error=memory.archive_error)
    sent_count = 0
    com_failures = 0
    while not STOP.exists():
        sleep_delay=CONFIG['poll_seconds']
        try:
            current = wx.snapshot()
            for message in tracker.update(current):
                direction = wx.direction(message)
                if direction == 'unknown':
                    raise NotReady('无法可靠区分消息发送者，保持暂停识别。')
                memory.observe(message,direction)
                tracker.handled(message.key)
                if direction == 'incoming':
                    pending.append(message)
                    last_incoming = time.monotonic()
                elif direction == 'outgoing':
                    # The owner has already answered these pending arrivals.
                    # A later incoming row in this same snapshot starts a new batch.
                    pending.clear()
                    last_incoming = 0
                    ignored += 1
                else:
                    ignored += 1
            if pending and time.monotonic()-last_incoming >= CONFIG['merge_seconds']:
                images=[m for m in pending if media_type(m)]
                labels={m.key:i for i,m in enumerate(images,1)}
                incoming = '\n'.join((f'[附件{labels[m.key]}：'+('表情包' if media_type(m)=='sticker' else '图片')+']')
                                     if media_type(m) else m.text for m in pending)
                source_keys = [m.key for m in pending]
                pending.clear()
                options={'image_messages':images} if images else {}
                options['conversation']=memory.before(contact,source_keys)
                options['on_sent']=memory.confirm_sent
                trace=ReplyTrace(LOCAL,contact,time.monotonic()-last_incoming)
                options['metrics']=trace
                result = process_batch(wx,muse,journal,contact,incoming,CONFIG,source_keys=source_keys,**options)
                trace.finish(result)
                if result in ('pause','unconfirmed'):
                    break
                if result == 'sent_ui':
                    sent_count += 1
            memory.flush()
            status('listening',pid=os.getpid(),contact=contact,sent_count=sent_count,ignored_rows=ignored,pending_count=len(pending),mode=CONFIG['mode'],
                   context_archive=memory.archive_path,context_archive_error=memory.archive_error)
            com_failures = 0
            sleep_delay=listener_delay(CONFIG['poll_seconds'],CONFIG['merge_seconds'],pending,last_incoming)
        except COMError as exc:
            com_failures += 1
            status('waiting_desktop',pid=os.getpid(),contact=contact,
                   reason='微信界面控件正在刷新，稍后重新读取。',retry=com_failures,
                   sent_count=sent_count,mode=CONFIG['mode'])
            if com_failures>=10:
                record_failure(None,'reading_wechat',exc)
                status('needs_attention',pid=os.getpid(),contact=contact,reason='微信界面连续读取失败。')
                break
        except NotReady as exc:
            status('waiting_desktop',pid=os.getpid(),contact=contact,reason=str(exc),sent_count=sent_count,mode=CONFIG['mode'])
        except Exception as exc:
            status('needs_attention',pid=os.getpid(),contact=contact,reason=type(exc).__name__,sent_count=sent_count)
            break
        time.sleep(sleep_delay)
    current_status = json.loads((LOCAL/'status.json').read_text(encoding='utf-8'))
    if current_status['state'] not in ('needs_attention','send_unconfirmed'):
        status('stopped',contact=contact,sent_count=sent_count)
    win32api.CloseHandle(lock)
    return 0

def main():
    command = sys.argv[1] if len(sys.argv)>1 else 'doctor'
    if command == 'doctor':
        return doctor()
    if command == 'status':
        path = LOCAL/'status.json'
        if path.exists():
            data=json.loads(path.read_text(encoding='utf-8'))
            watcher=LOCAL/'auto-y-status.json'
            if watcher.exists():data['auto_y']=json.loads(watcher.read_text(encoding='utf-8'))
            print(json.dumps(data,ensure_ascii=False,indent=2))
        else:print('尚未启动。')
        return 0
    if command == 'stop':
        LOCAL.mkdir(exist_ok=True)
        STOP.touch()
        (LOCAL/'STOP_AUTO_Y').touch()
        print('停止请求已写入；已打开的确认框也不会在停止后发送。')
        return 0
    if command in ('run','demo','resume'):
        return run(command=='demo','--no-dialog' in sys.argv,command=='resume')
    raise ValueError('未知命令。')

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        (LOCAL/'STOP_AUTO_Y').touch()
        status('needs_attention',reason=str(exc))
        if sys.stderr:
            print(str(exc),file=sys.stderr)
        sys.exit(1)
