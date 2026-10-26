"""Native, compact status UI; all behaviour stays in status_window.py."""
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from PIL import Image, ImageTk

ASSETS = Path(__file__).resolve().parent / 'assets'
GROUND = '#F5F7F6'
SURFACE = '#FFFFFF'
INK = '#202A25'
MUTED = '#606E66'
RULE = '#E4E9E6'
GREEN = '#208766'
FONT = 'Microsoft YaHei UI'


def panel(parent, x, y, width, height):
    canvas = tk.Canvas(parent, width=width, height=height, bg=GROUND, highlightthickness=0)
    canvas.place(x=x,y=y,width=width,height=height)
    r=10
    points=(r,1,width-r,1,width-1,1,width-1,r,width-1,height-r,width-1,height-1,
            width-r,height-1,r,height-1,1,height-1,1,height-r,1,r,1,1)
    canvas.create_polygon(points,smooth=True,splinesteps=24,fill=SURFACE,outline=RULE,width=1)
    return canvas


def label(parent, text=None, variable=None, size=10, color=INK, weight='normal', anchor='w', **kwargs):
    return tk.Label(parent,text=text,textvariable=variable,font=(FONT,size,weight),
                    fg=color,bg=SURFACE,anchor=anchor,borderwidth=0,**kwargs)


def scale_layout(root, scale):
    stack=list(root.winfo_children())
    while stack:
        widget=stack.pop()
        stack.extend(widget.winfo_children())
        placement=widget.place_info()
        if placement:
            widget.place_configure(**{key:round(float(placement[key])*scale) for key in ('x','y','width','height')})
        if isinstance(widget,tk.Canvas):
            widget.scale('all',0,0,scale,scale)
        if widget.winfo_class()=='Label' and float(str(widget.cget('wraplength') or 0)):
            widget.configure(wraplength=round(float(str(widget.cget('wraplength')))*scale))


def build_setup(app):
    root=app.root
    style=ttk.Style(root)
    style.theme_use('clam')
    style.configure('Contact.TEntry',fieldbackground=SURFACE,foreground=INK,bordercolor='#B8C4BC',
                    lightcolor=SURFACE,darkcolor=SURFACE,padding=(10,5),borderwidth=1)
    style.map('Contact.TEntry',bordercolor=[('focus',GREEN)])
    style.configure('Start.TButton',font=(FONT,10),background=INK,foreground='white',
                    bordercolor=INK,lightcolor=INK,darkcolor=INK,focuscolor='white',padding=(16,8))
    style.map('Start.TButton',background=[('active','#354A3D'),('pressed','#14231A')])
    style.configure('Exit.TButton',font=(FONT,10),background=SURFACE,foreground=MUTED,
                    bordercolor='#C6CECA',lightcolor=SURFACE,darkcolor=SURFACE,padding=(16,8))
    group=app.chat_mode.get()=='group'
    area=panel(root,24,102,512,440 if group else 344)
    label(area,text='选择对话模式',size=13).place(x=24,y=16,width=464,height=32)
    style.configure('Mode.TRadiobutton',font=(FONT,10),background=SURFACE,foreground=INK)
    app.private_mode_button=ttk.Radiobutton(area,text='好友私聊',variable=app.chat_mode,value='private',command=app.change_mode,style='Mode.TRadiobutton')
    app.private_mode_button.place(x=24,y=56,width=170,height=30)
    app.group_mode_button=ttk.Radiobutton(area,text='群聊 · 仅被 @ 时回复',variable=app.chat_mode,value='group',command=app.change_mode,style='Mode.TRadiobutton')
    app.group_mode_button.place(x=220,y=56,width=268,height=30)
    label(area,text='微信群完整名称' if group else '好友昵称或备注',size=10).place(x=24,y=104,width=464,height=24)
    app.contact_entry=ttk.Entry(area,textvariable=app.contact_input,font=(FONT,11),style='Contact.TEntry')
    app.contact_entry.place(x=24,y=136,width=464,height=40)
    app.contact_entry.bind('<Return>',lambda event:app.start())
    help_text='填写聊天顶部的完整群名，并在微信中选中此群。\n只有正文 @ 下面昵称的新消息才会触发。' if group else '填写微信聊天顶部的好友昵称或备注。\n请先在微信中选中这位好友的聊天。'
    label(area,text=help_text,size=9,color=MUTED,
          wraplength=464,justify='left',anchor='nw').place(x=24,y=184,width=464,height=44)
    if group:
        label(area,text='本人在这个群里的昵称（不含 @）',size=10).place(x=24,y=232,width=464,height=24)
        app.self_name_entry=ttk.Entry(area,textvariable=app.self_name_input,font=(FONT,11),style='Contact.TEntry')
        app.self_name_entry.place(x=24,y=264,width=464,height=40)
        app.self_name_entry.bind('<Return>',lambda event:app.start())
        label(area,text='引用中的 @ 和 @所有人 不触发，群上下文单独存档。',size=9,color=MUTED).place(x=24,y=312,width=464,height=24)
    label(area,variable=app.contact_notice,size=9,color='#A03939',wraplength=464,justify='left',
          anchor='nw').place(x=24,y=340 if group else 236,width=464,height=40)
    app.start_button=ttk.Button(area,text='开始监测',command=app.start,style='Start.TButton')
    app.start_button.place(x=24,y=388 if group else 284,width=464,height=36)
    footer=570 if group else 474
    tk.Label(root,text='开始前不会监听或回复任何消息',font=(FONT,9),fg=MUTED,bg=GROUND,
             anchor='w').place(x=26,y=footer,width=335,height=36)
    app.end_button=ttk.Button(root,text='退出程序',command=app.request_stop,style='Exit.TButton')
    app.end_button.place(x=384,y=footer,width=152,height=38)
    app.contact_entry.focus_set()


def build_interface(app, setup=False):
    global FONT
    root=app.root
    families=root.tk.call('font','families')
    FONT='Noto Sans SC' if 'Noto Sans SC' in families else 'Microsoft YaHei UI'
    scale=app.ui_scale
    height=(640 if app.chat_mode.get()=='group' else 544) if setup else 548
    root.geometry(str(round(560*scale))+'x'+str(round(height*scale)))
    root.configure(bg=GROUND)
    root.iconbitmap(str(ASSETS/'muse.ico'))
    if not hasattr(app,'ui_images'):
        app.ui_images={}
        for name in ('muse-mark-40.png','switch-on.png','switch-off.png','switch-on-focus.png','switch-off-focus.png'):
            source='muse-mark-256.png' if name.startswith('muse') else name.replace('.png','-4x.png')
            size=(round(40*scale),round(40*scale)) if name.startswith('muse') else (round(48*scale),round(28*scale))
            with Image.open(ASSETS/source) as image:
                app.ui_images[name]=ImageTk.PhotoImage(image.resize(size,Image.Resampling.LANCZOS),master=root)
    tk.Label(root,image=app.ui_images['muse-mark-40.png'],bg=GROUND,borderwidth=0).place(x=24,y=27,width=40,height=40)
    tk.Label(root,text='Muse 微信助手',font=(FONT,16,'bold'),fg=INK,bg=GROUND,
             anchor='w').place(x=76,y=22,width=300,height=40)
    contact=app.selected_contact or ''
    subtitle='先选择模式和对话，再开始监听' if setup else ('群聊：'+contact[:18]+' · 仅 @'+app.selected_self_name+' 回复' if app.selected_mode=='group' else '监测好友：'+contact[:26]+('…' if len(contact)>26 else ''))
    tk.Label(root,text=subtitle,font=(FONT,9),fg=MUTED,bg=GROUND,
             anchor='w').place(x=77,y=62,width=455,height=26)
    if setup:
        build_setup(app)
        scale_layout(root,scale)
        return

    # 24 + 512 + 24 = 560. Every section shares these outer edges;
    # content in each panel is inset 24, for one continuous text column at x=48.
    state=panel(root,24,102,512,224)
    label(state,text='当前状态',size=9,color=MUTED).place(x=24,y=18,width=400,height=22)
    app.state_dot=label(state,text='●',size=11,color='#9AA49E')
    app.state_dot.place(x=462,y=16,width=22,height=26)
    label(state,variable=app.headline,size=15).place(x=24,y=47,width=464,height=36)
    label(state,variable=app.detail,size=10,color=MUTED,wraplength=456,justify='left',anchor='nw').place(x=24,y=87,width=464,height=60)
    state.create_line(24,149,488,149,fill=RULE,width=1)
    state.create_line(254,167,254,201,fill=RULE,width=1)
    app.runtime_value=tk.StringVar(value='—')
    app.confirmed_value=tk.StringVar(value='0 条')
    label(state,text='运行时长',size=9,color=MUTED).place(x=24,y=162,width=210,height=22)
    label(state,variable=app.runtime_value,size=13).place(x=24,y=184,width=210,height=30)
    label(state,text='本次自动确认',size=9,color=MUTED).place(x=278,y=162,width=210,height=22)
    label(state,variable=app.confirmed_value,size=13).place(x=278,y=184,width=210,height=30)

    settings=panel(root,24,342,512,108)
    label(settings,text='自动点击 Y',size=11).place(x=24,y=17,width=350,height=26)
    style=ttk.Style(root)
    style.theme_use('clam')
    style.element_create('Muse.Switch','image',app.ui_images['switch-off.png'],
                         ('selected','focus',app.ui_images['switch-on-focus.png']),
                         ('selected',app.ui_images['switch-on.png']),
                         ('focus',app.ui_images['switch-off-focus.png']))
    style.layout('Muse.TCheckbutton',[('Muse.Switch',{'sticky':''})])
    style.configure('Muse.TCheckbutton',background=SURFACE,borderwidth=0)
    app.auto_checkbox=ttk.Checkbutton(settings,text='开启自动点击 Y',variable=app.auto_enabled,command=app.toggle_auto,
                                    style='Muse.TCheckbutton',takefocus=True)
    app.auto_checkbox.place(x=440,y=16,width=48,height=28)
    app.auto_status=tk.StringVar(value='')
    label(settings,variable=app.auto_status,size=9,color=MUTED,wraplength=464,justify='left',anchor='nw').place(x=24,y=50,width=464,height=44)

    tk.Label(root,text='最小化后继续运行\n关闭窗口会同时停止所有功能',font=(FONT,9),
             fg=MUTED,bg=GROUND,justify='left',anchor='w').place(x=26,y=480,width=320,height=44)
    style.configure('End.TButton',font=(FONT,10),foreground='#A03939',background=SURFACE,
                    bordercolor='#C6CECA',lightcolor=SURFACE,darkcolor=SURFACE,focuscolor=INK,
                    borderwidth=1,padding=(16,8))
    style.map('End.TButton',background=[('disabled','#EEF1EF'),('active','#FAEEEE'),('pressed','#F2E3E3')],
              foreground=[('disabled',MUTED)],bordercolor=[('active','#C79898'),('focus',INK)])
    app.end_button=ttk.Button(root,text='结束程序',command=app.request_stop,style='End.TButton')
    app.end_button.place(x=384,y=482,width=152,height=38)
    # All positions are authored in 96-DPI units. Scale geometry together with
    # native fonts and source artwork, rather than letting Windows blur a bitmap.
    scale_layout(root,scale)
