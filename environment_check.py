"""Readable local prerequisite check; never opens a chat or sends a message."""
import ctypes,json,os,sys
from pathlib import Path
def main():
    from browser_launcher import browser_path
    from winrt.windows.media.ocr import OcrEngine
    langs=[x.language_tag for x in OcrEngine.available_recognizer_languages]
    chinese=any(x.lower().startswith('zh') for x in langs)
    text=('Python 与程序依赖：已随安装包准备\n'
          +'浏览器：'+('已找到' if browser_path() else '请安装 Chrome 或 Edge')+'\n'
          +'中文文字识别：'+('已就绪' if chinese else '未安装；群聊需要此组件')+'\n\n'
          +'请安装微信 4.1.15.56，登录微信和 Muse，保持对应聊天界面打开。\n'
          +'使用桌面“打开 Muse”进入独立网页窗口，再打开助手选择模式和目标。\n\n'
          +('缺少中文识别时，请在开始菜单运行“安装中文文字识别”；需要管理员权限和 Windows 更新网络。\n\n' if not chinese else '')
          +'聊天上下文位于当前用户的“文档\\聊天上下文”，卸载不会删除这些存档。')
    ctypes.windll.user32.MessageBoxW(None,text,'Muse 微信助手 · 环境检查',0x40)
if __name__=='__main__':main()
