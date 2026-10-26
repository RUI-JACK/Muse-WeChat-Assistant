using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.Reflection;
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyProduct("Muse WeChat Assistant")]
internal static class Launcher {
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 static extern IntPtr LoadLibraryEx(string name, IntPtr file, uint flags);
 [DllImport("kernel32.dll")] static extern bool FreeLibrary(IntPtr handle);
 static string Root { get { return AppDomain.CurrentDomain.BaseDirectory; } }
 static string Quote(string value) { return "\""+value+"\""; }
 static int Run(string exe,string arguments,bool wait,string log) {
  var info=new ProcessStartInfo(exe,arguments) {WorkingDirectory=Root,UseShellExecute=false,CreateNoWindow=true};
  if(log!=null){info.RedirectStandardOutput=true;info.RedirectStandardError=true;}
  using(var process=Process.Start(info)) {
   if(log!=null){var output=process.StandardOutput.ReadToEndAsync();var error=process.StandardError.ReadToEndAsync();process.WaitForExit();
    Directory.CreateDirectory(Path.GetDirectoryName(log));File.WriteAllText(log,output.Result+error.Result);return process.ExitCode;}
   if(wait){process.WaitForExit();return process.ExitCode;}
  }
  return 0;
 }
 static int EnsureRuntime() {
  var module=LoadLibraryEx("mfc140u.dll",IntPtr.Zero,0x800);
  if(module!=IntPtr.Zero){FreeLibrary(module);return 0;}
  var info=new ProcessStartInfo(Path.Combine(Root,@"prerequisites\vc_redist.x64.exe"),"/install /quiet /norestart")
   {UseShellExecute=true,Verb="runas",WindowStyle=ProcessWindowStyle.Hidden};
  using(var p=Process.Start(info)){p.WaitForExit();return (p.ExitCode==0||p.ExitCode==3010||p.ExitCode==1638||p.ExitCode==-2147023258)?0:p.ExitCode;}
 }
 [STAThread] static int Main(string[] args) {
  try {
   string mode=args.Length>0?args[0]:"";
   if(mode=="--bootstrap") {
    int runtime=EnsureRuntime();if(runtime!=0)throw new Exception("Microsoft C++ 运行库安装失败，代码 "+runtime);
    return Run(Path.Combine(Root,@"runtime\python\python.exe"),Quote(Path.Combine(Root,@"packaging\bootstrap.py")),true,
     Path.Combine(Root,@".install\bootstrap-console.log"));
   }
   if(mode=="--install-ocr") {
    var info=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows),@"System32\dism.exe"),
     "/Online /Add-Capability /CapabilityName:Language.OCR~~~zh-CN~0.0.1.0 /NoRestart")
     {UseShellExecute=true,Verb="runas",WindowStyle=ProcessWindowStyle.Hidden};
    using(var p=Process.Start(info)){p.WaitForExit();MessageBox.Show(p.ExitCode==0||p.ExitCode==3010?"中文文字识别组件已安装。请重新打开助手。":"组件安装未完成，代码 "+p.ExitCode+"。请检查 Windows 更新和网络后重试。","中文文字识别");return p.ExitCode;}
   }
   string script=mode=="--muse"?"browser_launcher.py":mode=="--check"?"environment_check.py":mode=="--smoke"?@"packaging\smoke.py":"status_window.py";
   string python=Path.Combine(Root,@".venv\Scripts\pythonw.exe");
   if(!File.Exists(python)||!File.Exists(Path.Combine(Root,script)))throw new Exception("安装环境不完整，请重新运行安装包修复。不会清除文档中的聊天上下文。");
   return Run(python,Quote(Path.Combine(Root,script)),mode=="--smoke",null);
  } catch(Exception ex){MessageBox.Show(ex.Message,"Muse 微信助手 · 启动失败",MessageBoxButtons.OK,MessageBoxIcon.Error);return 1;}
 }
}
