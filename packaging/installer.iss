#ifndef PayloadDir
 #error PayloadDir is required
#endif
#ifndef OutputDir
 #define OutputDir "."
#endif
[Setup]
AppId={{74E9AB93-89ED-462D-A361-A8B0A823CA90}
AppName=Muse 微信助手
AppVersion=1.0.2
AppPublisher=RUI-JACK
AppPublisherURL=https://github.com/RUI-JACK/Muse-WeChat-Assistant
DefaultDirName={localappdata}\Programs\MuseWeChatAssistant
DefaultGroupName=Muse 微信助手
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.19041
OutputDir={#OutputDir}
OutputBaseFilename=Muse-WeChat-Assistant-Setup-1.0.2-x64
SetupIconFile={#PayloadDir}\assets\muse.ico
UninstallDisplayIcon={app}\Muse微信助手.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=no
RestartApplications=no
InfoBeforeFile={#PayloadDir}\INSTALL-NOTES.txt
[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce
Name: "chineseocr"; Description: "安装中文文字识别组件（群聊需要，缺失时选用，需要管理员权限和联网）"; Flags: unchecked
[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Excludes: "config.json"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PayloadDir}\config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
[Icons]
Name: "{group}\Muse 微信助手"; Filename: "{app}\Muse微信助手.exe"
Name: "{group}\打开 Muse"; Filename: "{app}\Muse微信助手.exe"; Parameters: "--muse"
Name: "{group}\环境检查"; Filename: "{app}\Muse微信助手.exe"; Parameters: "--check"
Name: "{group}\安装中文文字识别"; Filename: "{app}\Muse微信助手.exe"; Parameters: "--install-ocr"
Name: "{group}\卸载 Muse 微信助手"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Muse 微信助手"; Filename: "{app}\Muse微信助手.exe"; Tasks: desktopicon
Name: "{autodesktop}\打开 Muse"; Filename: "{app}\Muse微信助手.exe"; Parameters: "--muse"; Tasks: desktopicon
[Run]
Filename: "{app}\Muse微信助手.exe"; Parameters: "--install-ocr"; Tasks: chineseocr; StatusMsg: "正在安装 Windows 中文识别组件…"; Flags: waituntilterminated
Filename: "{app}\Muse微信助手.exe"; Description: "打开 Muse 微信助手"; Flags: postinstall nowait skipifsilent
[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\.install"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\__pycache__"
[Code]
function InitializeSetup(): Boolean;
begin
  Result := not CheckForMutexes('Local\MuseWeChatBridgeStatusWindow.v1');
  if not Result then MsgBox('请先结束正在运行的 Muse 微信助手，再安装或升级。', mbInformation, MB_OK);
end;
procedure CurStepChanged(CurStep: TSetupStep);
var ResultCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    WizardForm.StatusLabel.Caption := '正在离线准备 Python 和依赖，请稍候…';
    if not Exec(ExpandConstant('{app}\Muse微信助手.exe'), '--bootstrap', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('无法启动环境配置，请检查安装目录权限。');
    if ResultCode <> 0 then RaiseException('环境配置失败，代码 '+IntToStr(ResultCode)+'。请查看安装目录的 .install\bootstrap-console.log，然后重新运行安装包。');
  end;
end;
