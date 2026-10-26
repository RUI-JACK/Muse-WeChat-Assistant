"""No chat or network actions: imports, Tcl/Tk and native dependency readiness."""
import json,os,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
report={'passed':False,'sent_messages':0,'python':sys.version,'executable':sys.executable}
try:
    import tkinter,win32api,win32gui,win32crypt,win32ui,win32job,uiautomation
    import status_window,bridge,group_runtime,group_ocr,reply_style
    from PIL import Image
    from winrt.windows.media.ocr import OcrEngine
    root=tkinter.Tk();root.withdraw();report['tk']=root.tk.call('info','patchlevel');root.destroy()
    report['ocr_languages']=[x.language_tag for x in OcrEngine.available_recognizer_languages]
    report['passed']=True
except Exception as exc:report.update(error=repr(exc),trace=traceback.format_exc())
target=ROOT/'.install';target.mkdir(exist_ok=True)
(target/'smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
sys.exit(0 if report['passed'] else 1)
