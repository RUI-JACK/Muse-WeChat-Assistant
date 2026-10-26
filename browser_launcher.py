"""Open Muse in a separate accessible app window, without copying logins."""
import ctypes,os,subprocess,winreg
from pathlib import Path
def browser_path():
    candidates=[]
    for name in ('chrome.exe','msedge.exe'):
        for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\'+name) as key:
                    candidates.append(Path(winreg.QueryValueEx(key,None)[0]))
            except OSError:pass
    for env in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
        for path in ('Google/Chrome/Application/chrome.exe','Microsoft/Edge/Application/msedge.exe'):
            candidates.append(Path(os.environ.get(env,''))/path)
    return next((x for x in candidates if x.is_file()),None)
def main():
    browser=browser_path()
    if not browser:raise RuntimeError('未找到 Chrome 或 Microsoft Edge，请先安装浏览器。')
    # A new local profile avoids sharing this computer's unrelated browser
    # state and guarantees the accessibility flags apply to this process.
    profile=Path(os.environ['LOCALAPPDATA'])/'MuseWeChatAssistant'/'BrowserProfile'
    subprocess.Popen([str(browser),'--app=https://muse.ai/?__pwa=1','--user-data-dir='+str(profile),
        '--disable-features=CalculateNativeWinOcclusion','--force-renderer-accessibility'],creationflags=subprocess.CREATE_NO_WINDOW)
if __name__=='__main__':
    try:main()
    except Exception as exc:ctypes.windll.user32.MessageBoxW(None,str(exc),'Muse 网页入口',0x10)
