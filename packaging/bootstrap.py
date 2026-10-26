"""Create a location-specific venv and install only bundled, locked wheels."""
import json,os,subprocess,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
def run(args):
    subprocess.run([str(x) for x in args],cwd=ROOT,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
def main():
    target=ROOT/'.venv';python=target/'Scripts/python.exe'
    # --upgrade repairs executable paths after an in-place upgrade. Never
    # copy a venv from the build machine or retain its pyvenv.cfg.
    run([sys.executable,'-m','venv','--upgrade' if python.exists() else '--copies',target])
    run([python,'-m','pip','install','--no-index','--disable-pip-version-check','--find-links',ROOT/'wheels','-r',ROOT/'requirements.txt'])
    run([python,ROOT/'packaging/smoke.py'])
    report=json.loads((ROOT/'.install/smoke.json').read_text(encoding='utf-8'))
    if not report.get('passed'):raise RuntimeError('依赖检查失败，请查看 .install/smoke.json。')
    print('OFFLINE_INSTALL_READY',flush=True)
if __name__=='__main__':
    try:main()
    except Exception:
        traceback.print_exc();sys.exit(1)
