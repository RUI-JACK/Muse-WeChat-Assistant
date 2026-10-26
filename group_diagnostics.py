"""Bounded local receive diagnostics, without message bodies or sender names."""
import json,time
from pathlib import Path


class ReceiveDiagnostics:
    def __init__(self,path=None):
        self.path=Path(path) if path else None;self.last={}

    def record(self,key,reason,**details):
        signature=(reason,tuple(sorted(details.items())))
        if self.last.get(key)==signature:return
        self.last[key]=signature
        if len(self.last)>1000:self.last={key:signature}
        if not self.path:return
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            if self.path.exists() and self.path.stat().st_size>2*1024*1024:
                self.path.replace(self.path.with_suffix('.previous.jsonl'))
            with self.path.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({'time':time.time(),'source':key[:16],'reason':reason,**details},ensure_ascii=False)+'\n')
        except OSError:pass
