"""Dedicated YES watcher for this bridge's local review dialog only."""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
import win32api
import win32con
import win32event
import win32gui
import win32process
from storage import ROOT,LOCAL

TITLE='Muse 微信回复确认'
STOP=LOCAL/'STOP_AUTO_Y'
STATE=LOCAL/'auto-y-status.json'
CLICK=LOCAL/'auto-y-click.json'
SEEN=LOCAL/'auto-y-handled.json'

def start_watcher():
    current=read_json(STATE,{})
    if current.get('state')=='watching' and time.time()-current.get('updated',0)<3 and not STOP.exists():
        return
    if current.get('state')=='watching' and STOP.exists():
        deadline=time.monotonic()+2
        while time.monotonic()<deadline and read_json(STATE,{}).get('state')=='watching':
            time.sleep(.1)
    startup=subprocess.STARTUPINFO()
    startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow=0
    subprocess.Popen([str(ROOT/'.venv/Scripts/pythonw.exe'),str(ROOT/'auto_y.py'),'run'],
                     cwd=ROOT,startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW)
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        current=read_json(STATE,{})
        if current.get('state')=='watching' and time.time()-current.get('updated',0)<2 and not STOP.exists():
            return
        time.sleep(.1)
    raise RuntimeError('自动Y监视器未启动，请检查程序权限和状态。')

def read_json(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return default

def write_json(path,value):
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    for attempt in range(5):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt==4:raise
            time.sleep(.03)

def dialog_body(hwnd):
    texts=[]
    def child(handle,_):
        if win32gui.GetClassName(handle)=='Static':
            text=win32gui.GetWindowText(handle)
            if text:texts.append(text)
    win32gui.EnumChildWindows(hwnd,child,None)
    return '\n'.join(texts)

def find_target(state,contact):
    if state.get('state')!='awaiting_approval' or state.get('contact')!=contact or not state.get('event_id'):
        return None
    owner=state.get('pid')
    if not isinstance(owner,int):return None
    group=state.get('chat_mode','private')=='group'
    if state.get('chat_mode','private') not in ('private','group'):return None
    title=TITLE
    if group:
        from group_policy import GROUP_TITLE
        title=GROUP_TITLE
        if (state.get('mentioned_self') is not True or state.get('group_reply_policy')!='mention'
            or not state.get('group_self_name') or not isinstance(state.get('trigger_keys'),list)
            or not state['trigger_keys']):return None
    found=[]
    def enum(hwnd,_):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindowText(hwnd)!=title:
            return
        if win32gui.GetClassName(hwnd)!='#32770' or win32process.GetWindowThreadProcessId(hwnd)[1]!=owner:
            return
        body=dialog_body(hwnd)
        match=re.search(r'^'+('群聊' if group else '联系人')+r'[：:]\s*([^\r\n]+)',body,re.M)
        if not match or match.group(1).strip()!=contact or '拟发送的完整内容' not in body:
            return
        if group and ('请求：'+state['event_id']) not in body:return
        yes=win32gui.GetDlgItem(hwnd,win32con.IDYES)
        if yes and win32gui.GetClassName(yes)=='Button' and win32gui.IsWindowEnabled(yes):
            found.append((hwnd,yes))
    win32gui.EnumWindows(enum,None)
    return found[0] if len(found)==1 else None

def run():
    LOCAL.mkdir(exist_ok=True)
    # Disabled on purpose: this build asks Muse for a draft the owner reviews
    # per message. A watcher that clicks 是 would make that request untrue.
    if read_json(ROOT/'config.json',{}).get('mode')!='auto_confirm_local':
        write_json(STATE,{'state':'disabled','updated':time.time(),
                          'reason':'当前按“待本人审批”工作，自动Y已停用。'})
        return 0
    mutex=win32event.CreateMutex(None,False,'Local\\MuseWeChatDedicatedAutoY')
    if win32api.GetLastError()==183:
        win32api.CloseHandle(mutex)
        return 0
    STOP.unlink(missing_ok=True)
    contact=read_json(ROOT/'config.json',{}).get('allowed_contact')
    if not contact:raise RuntimeError('未配置白名单联系人。')
    handled=read_json(SEEN,[])
    count=0
    last_update=0
    error=None
    try:
        while not STOP.exists():
            state=read_json(LOCAL/'status.json',{})
            event=state.get('event_id')
            try:
                target=find_target(state,contact) if event not in handled else None
                if target:
                    # Confirm the same event/window immediately before selecting
                    # IDYES=6. This does not depend on keyboard focus or Enter.
                    time.sleep(.15)
                    fresh=read_json(LOCAL/'status.json',{})
                    if (not STOP.exists() and fresh.get('event_id')==event
                            and find_target(fresh,contact)==target):
                        handled.append(event)
                        handled=handled[-512:]
                        write_json(SEEN,handled)
                        write_json(CLICK,{'event_id':event,'contact':contact,'owner_pid':fresh['pid'],
                                          'source':'local_auto_y','time':time.time()})
                        win32gui.PostMessage(target[1],win32con.BM_CLICK,0,0)
                        count+=1
                        error=None
            except Exception as exc:
                error=type(exc).__name__
            if time.monotonic()-last_update>=1:
                write_json(STATE,{'state':'watching','pid':os.getpid(),'updated':time.time(),
                                  'contact':contact,'confirmed_count':count,'error':error})
                last_update=time.monotonic()
            time.sleep(.15)
    finally:
        write_json(STATE,{'state':'stopped','updated':time.time(),'confirmed_count':count,'contact':contact})
        win32api.CloseHandle(mutex)
    return 0

def main():
    LOCAL.mkdir(exist_ok=True)
    command=sys.argv[1] if len(sys.argv)>1 else 'run'
    if command=='run':return run()
    if command=='stop':STOP.touch();return 0
    if command=='status':
        print(json.dumps(read_json(STATE,{'state':'not_started'}),ensure_ascii=False,indent=2))
        return 0
    raise ValueError('Unknown command')

if __name__=='__main__':sys.exit(main())
