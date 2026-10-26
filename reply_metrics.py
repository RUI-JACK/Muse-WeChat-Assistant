"""Content-free phase timings for finding actual reply bottlenecks."""
import json,time
from pathlib import Path


class ReplyTrace:
    def __init__(self,root,contact,observed_wait_seconds=0):
        self.root=Path(root);self.contact=contact;self.event_id=None
        self.started=time.perf_counter();self.changed=self.started
        self.current='prepare';self.phases={}
        self.observed_wait_ms=round(max(0,observed_wait_seconds)*1000,2)

    def mark(self,phase):
        now=time.perf_counter()
        self.phases[self.current]=self.phases.get(self.current,0)+(now-self.changed)*1000
        self.current=phase;self.changed=now

    def finish(self,result):
        now=time.perf_counter()
        self.phases[self.current]=self.phases.get(self.current,0)+(now-self.changed)*1000
        record={'event_id':self.event_id,'contact':self.contact,'updated':time.time(),'result':result,
                'observed_wait_ms':self.observed_wait_ms,'processing_ms':round((now-self.started)*1000,2),
                'phases_ms':{key:round(value,2) for key,value in self.phases.items()}}
        try:
            self.root.mkdir(parents=True,exist_ok=True)
            path=self.root/'reply-latency.jsonl'
            with path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(record,ensure_ascii=False)+'\n')
            if path.stat().st_size>1024*1024:
                lines=path.read_text(encoding='utf-8').splitlines()[-256:]
                path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        except (OSError,ValueError,TypeError):
            pass              # diagnostics must never change delivery behavior
        return record
