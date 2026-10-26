"""Build an offline, relocatable Windows x64 installer from explicit inputs."""
import argparse,hashlib,json,os,shutil,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
MODULES=('auto_y bridge chat_settings contact_settings context_archive conversation_context desktop_adapter '
 'group_adapter group_context group_ocr group_policy group_runtime image_support integrated_confirmation '
 'reply_metrics reply_style status_ui status_window storage uia_fast_read worker_entry browser_launcher environment_check').split()
def run(args):subprocess.run([str(x) for x in args],check=True)
def main():
 p=argparse.ArgumentParser();p.add_argument('--runtime',required=True,type=Path);p.add_argument('--wheels',required=True,type=Path)
 p.add_argument('--redist',required=True,type=Path);p.add_argument('--iscc',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
 a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);payload=a.out/'payload'
 # Refuse to reuse dirty staging directories: user state must never enter a release.
 if payload.exists():raise RuntimeError('Payload directory already exists; use a new output directory.')
 payload.mkdir()
 for name in MODULES:shutil.copy2(ROOT/(name+'.py'),payload/(name+'.py'))
 for name in ('config.json','requirements.txt','README.md','THIRD-PARTY-NOTICES.md','INSTALL-NOTES.txt'):
  shutil.copy2(ROOT/name,payload/name)
 shutil.copytree(ROOT/'assets',payload/'assets')
 (payload/'packaging').mkdir()
 for name in ('bootstrap.py','smoke.py'):shutil.copy2(ROOT/'packaging'/name,payload/'packaging'/name)
 def ignore(path,names):return [n for n in names if n in ('__pycache__','site-packages','Scripts','include','libs') or n.endswith(('.pyc','.pdb')) or n.lower().startswith('msvcp140')]
 shutil.copytree(a.runtime,payload/'runtime/python',ignore=ignore)
 shutil.copytree(a.wheels,payload/'wheels')
 (payload/'prerequisites').mkdir();shutil.copy2(a.redist,payload/'prerequisites/vc_redist.x64.exe')
 licenses=payload/'third-party-licenses';licenses.mkdir()
 shutil.copy2(a.runtime/'LICENSE.txt',licenses/'PYTHON-LICENSE.txt')
 for wheel in a.wheels.glob('*.whl'):
  with zipfile.ZipFile(wheel) as z:
   for info in z.infolist():
    if any(x in Path(info.filename).name.lower() for x in ('license','copying','copyright','notice')) and not info.is_dir():
     target=licenses/wheel.stem/Path(info.filename).name;target.parent.mkdir(exist_ok=True)
     target.write_bytes(z.read(info))
 compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
 run([compiler,'/nologo','/target:winexe','/platform:x64','/r:System.Windows.Forms.dll',
      '/win32icon:'+str(ROOT/'assets/muse.ico'),'/out:'+str(payload/'Muse微信助手.exe'),ROOT/'packaging/Launcher.cs'])
 manifest={str(x.relative_to(payload)).replace('\\','/'):hashlib.sha256(x.read_bytes()).hexdigest() for x in payload.rglob('*') if x.is_file()}
 (a.out/'payload-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 run([a.iscc,'/DPayloadDir='+str(payload),'/DOutputDir='+str(a.out),ROOT/'packaging/installer.iss'])
 setup=a.out/'Muse-WeChat-Assistant-Setup-1.0.0-x64.exe'
 (a.out/'SHA256SUMS.txt').write_text(hashlib.sha256(setup.read_bytes()).hexdigest()+'  '+setup.name+'\n',encoding='ascii')
 print('BUILT',setup,setup.stat().st_size,flush=True)
if __name__=='__main__':main()
