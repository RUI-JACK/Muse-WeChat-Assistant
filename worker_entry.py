"""Report startup/import failures even when pythonw has no error console."""
import importlib
import json
import os
from pathlib import Path
import time
import traceback

ROOT = Path(__file__).resolve().parent


def main():
    phase = 'startup'
    try:
        bridge = importlib.import_module('bridge')
        phase = 'running'
        return bridge.main()
    except Exception as exc:
        local = ROOT / 'local'
        local.mkdir(exist_ok=True)
        reason = str(exc)
        if phase == 'startup' and isinstance(exc, ImportError):
            reason = ('启动失败：缺少系统运行库，请修复助手安装。'
                      if 'DLL load failed' in str(exc) else
                      '启动失败：缺少程序组件，请修复助手安装。')
        diagnostic = {'phase': phase, 'error_type': type(exc).__name__,
                      'error': str(exc), 'updated': time.time(), 'pid': os.getpid()}
        (local / 'worker-error.json').write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding='utf-8')
        if phase == 'startup':
            (local / 'worker-startup.log').write_text(traceback.format_exc(), encoding='utf-8')
        (local / 'STOP_AUTO_Y').touch()
        target = local / 'status.json'
        temporary = target.with_suffix('.tmp')
        payload = json.dumps({'state': 'needs_attention', 'updated': time.time(),
                              'pid': os.getpid(), 'reason': reason, 'phase': phase},
                             ensure_ascii=False, indent=2)
        for attempt in range(10):
            try:
                temporary.write_text(payload, encoding='utf-8')
                temporary.replace(target)
                break
            except PermissionError:
                if attempt < 9:
                    time.sleep(.025)
                else:
                    target.write_text(payload, encoding='utf-8')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
