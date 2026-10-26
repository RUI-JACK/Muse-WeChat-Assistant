"""Version-pinned native group view, separate from private chat routing."""
import ctypes,hashlib,re,time
from dataclasses import dataclass
import uiautomation as auto
import win32gui,win32process,win32con
from PIL import ImageStat
from desktop_adapter import WeChat,Message,NotReady,capture_window
from image_support import media_type
from group_policy import main_body


@dataclass
class GroupMessage(Message):
    sender:str=''
    direction:str='unsupported'


class GroupWeChat(WeChat):
    media_top_inset=27
    def __init__(self,group,self_name,expected_version=None,reader=None):
        super().__init__(group,expected_version)
        self.self_name=self_name
        if reader is None:
            from group_ocr import SenderReader
            reader=SenderReader()
        self.reader=reader;self.cache={};self.required_sources=set();self.members=None

    def read_members(self):
        root=auto.ControlFromHandle(self.hwnd)
        detail,_,_=self.controls()
        button=detail.ButtonControl(Name='聊天信息',searchDepth=24)
        if not button.Exists(.2):raise NotReady('未找到群聊信息入口，无法核对发言者。')
        was_topmost=bool(win32gui.GetWindowLong(self.hwnd,win32con.GWL_EXSTYLE)&win32con.WS_EX_TOPMOST)
        win32gui.ShowWindow(self.hwnd,9)
        win32gui.SetWindowPos(self.hwnd,win32con.HWND_TOPMOST,0,0,0,0,win32con.SWP_NOMOVE|win32con.SWP_NOSIZE)
        members=root.ListControl(AutomationId='chat_member_list',searchDepth=30)
        try:
            if not members.Exists(.2):button.Click(waitTime=.3)
            if not members.Exists(.5):raise NotReady('群成员列表不可用。')
            self.controls()
            names=[n.Name.strip() for n in members.GetChildren() if n.ClassName=='mmui::ChatMemberCell' and n.Name.strip()]
            if self.self_name not in names:
                raise NotReady('当前可见群成员中没有本人群昵称，请核对昵称并展开群成员。')
            self.members=names
        finally:
            if members.Exists(.1):button.Click(waitTime=.2)
            if not was_topmost:win32gui.SetWindowPos(self.hwnd,win32con.HWND_NOTOPMOST,0,0,0,0,win32con.SWP_NOMOVE|win32con.SWP_NOSIZE|win32con.SWP_NOACTIVATE)

    def controls(self):
        detail,edit,view=super().controls()
        parent=detail.TextControl(AutomationId=self.TITLE_ID.rsplit('.',1)[0],searchDepth=18)
        if not parent.Exists(.2) or not re.fullmatch(re.escape(self.contact)+r'[（(][1-9]\d*[）)]',parent.Name):
            raise NotReady('当前会话没有匹配的群名和人数标识，群聊模式不会读取或发送。')
        return detail,edit,view

    def snapshot(self):
        if self.members is None:self.read_members()
        _,_,view=self.controls()
        bounds=view.BoundingRectangle;rows=view.GetChildren();records=[]
        before=[(n.GetRuntimeId(),str(n.BoundingRectangle)) for n in rows]
        scale=ctypes.windll.user32.GetDpiForWindow(self.hwnd)/96
        picture=None;window=None;new_cache={}
        for row in rows:
            r=row.BoundingRectangle
            key=hashlib.sha256(repr(('group',self.contact,self.pid,self.hwnd,row.GetRuntimeId(),row.Name)).encode()).hexdigest()
            m=GroupMessage(key,main_body(row.Name),row.ClassName,(r.left,r.top,r.right,r.bottom))
            supported=m.kind=='mmui::ChatTextItemView' or media_type(m)
            if supported:
                if key in self.cache:m.sender,m.direction=self.cache[key]
                elif r.top>=bounds.top and r.bottom<=bounds.bottom and r.bottom-r.top>=40:
                    if picture is None:picture,window=capture_window(self.hwnd)
                    ox,oy=window[:2];inset,side,dy=round(18*scale),round(34*scale),round(9*scale)
                    boxes=[(r.left+inset,r.top+dy,r.left+inset+side,r.top+dy+side),
                           (r.right-inset-side,r.top+dy,r.right-inset,r.top+dy+side)]
                    scores=[sum(ImageStat.Stat(picture.crop((a-ox,b-oy,c-ox,d-oy))).var)/3 for a,b,c,d in boxes]
                    left,right=scores
                    if left>80 and left>right*6+40:
                        m.direction='incoming'
                        crop=picture.crop((r.left+round(60*scale)-ox,r.top+round(6*scale)-oy,
                                           r.right-round(65*scale)-ox,r.top+round(26*scale)-oy))
                        from group_ocr import resolve_sender
                        m.sender=resolve_sender(self.reader.read(crop),self.members)
                        if not m.sender:m.sender=resolve_sender(self.reader.read(crop,enhance=False),self.members)
                    elif right>80 and right>left*6+40:m.direction='outgoing';m.sender=self.self_name
                    else:m.direction='unknown'
                    # Unknown/partially clipped rows are retried on later polls.
                    if m.direction!='unknown' and m.sender:new_cache[key]=(m.sender,m.direction)
                else:m.direction='unknown'
            records.append(m)
        # Verify the crop belonged to this same view and layout, after OCR.
        self.controls()
        after=[(n.GetRuntimeId(),str(n.BoundingRectangle)) for n in view.GetChildren()]
        if after!=before:raise NotReady('识别期间群消息布局变化，稍后重读。')
        self.cache.update(new_cache)
        if len(self.cache)>600:self.cache={m.key:self.cache[m.key] for m in records if m.key in self.cache}
        return records

    def direction(self,message):return message.direction

    def send_signature(self):
        rows=self.snapshot()
        if not self.required_sources.issubset({m.key for m in rows}):
            raise NotReady('触发本次回复的 @ 消息已不在视图中，本条跳过。')
        if any(m.direction=='unknown' for m in rows if m.kind=='mmui::ChatTextItemView' or media_type(m)):
            # A clipped historical top row is normal; only unknown rows after
            # the trigger can conceal a manual owner reply.
            trigger_index=max((i for i,m in enumerate(rows) if m.key in self.required_sources),default=-1)
            if any(m.direction=='unknown' for m in rows[trigger_index+1:] if m.kind=='mmui::ChatTextItemView' or media_type(m)):
                raise NotReady('触发消息后存在无法判断发送方向的消息，本条跳过。')
        # Older owner messages rolling off the top are not a manual reply.
        # Only new owner rows AFTER this batch's first trigger invalidate it.
        first=min((i for i,m in enumerate(rows) if m.key in self.required_sources),default=-1)
        return [(m.key,m.text) for m in rows[first+1:] if m.direction=='outgoing']
