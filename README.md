# Muse 微信助手

Windows 桌面助手：读取明确选择的微信会话，交给已登录的 Muse 起草文字，再通过本机确认流程发送。支持好友私聊、仅被 @ 时回复的独立群聊模式、图片/表情当前画面、分开保存的本地上下文。

## 安装与使用

1. 从 [Releases](https://github.com/RUI-JACK/Muse-WeChat-Assistant/releases) 下载 `Muse-WeChat-Assistant-Setup-1.0.0-x64.exe`，安装时会离线准备 Python 与程序依赖。
2. 自行安装并登录 **微信 4.1.15.56**。运行桌面“打开 Muse”，在独立浏览器窗口登录自己的 Muse 账号。
3. 运行“Muse 微信助手”，选择私聊或群聊，输入准确会话名；群聊填写被 @ 时显示的本人群昵称，不含 @。在微信中选中该聊天后点击开始。
4. “自动点击 Y”开启时自动确认并发送草稿，关闭时由本人逐条确认。开始前不监听历史；关闭状态窗口会结束它管理的工作进程。

支持 Windows 10 2004+ / Windows 11 **Intel、AMD x64**。首版安装实际验证范围为 Windows 11 x64，不能保证每台电脑、所有 DPI、所有网页及微信版本通用。Python、Tcl/Tk、Python 依赖已包含；C++ 系统库缺失时安装器会请求管理员权限。群聊需要 Windows 中文 OCR，缺失时运行开始菜单“安装中文文字识别”，该系统组件可能需要联网。

微信、Muse、Chrome/Edge 不打包分发；目标机器需要 Chrome 或系统 Edge，Muse 需要网络及有效账号。软件使用普通桌面可访问性界面，不是微信官方接口，不支持锁屏、注销或完全脱离界面的服务运行。

## 功能与边界

- 私聊与群聊读取、发送边界独立；群聊只回复新消息正文里的精确 `@本人昵称`，引用、@其他人、仅@所有人不触发。检测基于可见文本，不能完全区分手打的同形文字与原生 @ 元数据。
- 私聊风格为知性成熟、温暖体贴；群聊为贴吧式犀利回怼。二者在 `reply_style.py` 分别定义，可独立修改。
- 图片理解后发文字；表情只识别当前可见帧，不理解完整动画。语音、视频、文件尚不识别。群聊仅关联相邻且核实为同一发言者的附件。
- 群成员昵称用 Windows 本机 OCR 与可见成员名单核对，识别不确定时不猜测；昵称可能重名，不能当作唯一账号身份。
- 每个好友、每个群独立存档于当前用户实际的 **文档\聊天上下文**，群聊在子目录“群聊”。不跨机器自动同步，不把私聊上下文提供给群聊。
- 不覆盖微信或 Muse 既有输入草稿；发送结果不明确时停止而不重复发送。自动确认只匹配所属工作进程、目标、模式和事件，不发送全局 Y 按键。
- 群聊采用一个目标、一个模式的监听流程。微信/Muse 窗口需保持可用，切换会话或最小化会影响读取。客户端与网页更新可能需要重新适配。
- 来信和图片会提交到登录的 Muse。文档上下文是可读文件，本地事件库正文使用当前 Windows 用户 DPAPI 加密。
- 真实群界面只读、合成 Muse 草稿、原生确认窗口均经过验证；发布版本不宣称所有真实聊天、跨机器收发或所有系统组合均通过。

## 开发

使用 Windows x64 Python 3.11：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe status_window.py
.\.venv\Scripts\python.exe -m unittest discover -v
```

测试仅使用合成窗口/工作进程和临时存档，不向实际联系人发送测试消息。`config.json` 中会话名称默认为空，必须先在 UI 选择后开始。

## 构建安装包

构建器需要 Windows x64、Python 3.11 完整可重定位运行时（含 Tcl/Tk 与 ensurepip）、离线 wheel 集合、微软官方 x64 C++ Redistributable、Inno Setup 6.7.3 和系统 .NET Framework C# 编译器。运行时和二进制发布到 Release，不放进 Git 源码历史。

```powershell
python -m pip download --only-binary=:all: -r requirements.txt --dest build-wheels
python packaging/build.py --runtime C:\build-inputs\python --wheels C:\build-inputs\wheels --redist C:\build-inputs\vc_redist.x64.exe --iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" --out C:\build-output\release-1.0.0
```

安装时在目标路径创建新的虚拟环境，拒绝直接搬运开发机 `.venv`；所有 Python 依赖使用 `--no-index` 离线安装。`SHA256SUMS.txt` 提供安装包校验值，`payload-manifest.json` 列出构建输入文件哈希。

## 数据与授权

仓库与安装包不包含聊天存档、联系人名单、浏览器 profile、登录 cookie、虚拟机凭据或开发机调试日志。卸载不删除用户文档中的上下文和独立浏览器用户数据。

项目源代码尚未声明额外开源许可证；公开可见不等同于授予任意再分发授权。第三方组件各自的许可见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) 和安装目录 `third-party-licenses`。微信与 Muse 归各自权利人所有，本项目不代表其官方产品。
