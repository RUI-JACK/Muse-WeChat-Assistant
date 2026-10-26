"""A local journal. Message bodies are encrypted for this Windows user."""
import json
import sqlite3
import time
import uuid
from pathlib import Path
import win32crypt

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / 'local'

def protect(text):
    return win32crypt.CryptProtectData(text.encode('utf-8'), 'Muse WeChat draft', None, None, None, 0)

def unprotect(blob):
    return win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1].decode('utf-8')

class Journal:
    def __init__(self, path=None):
        LOCAL.mkdir(exist_ok=True)
        self.db = sqlite3.connect(path or LOCAL / 'journal.sqlite3')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, created REAL NOT NULL, state TEXT NOT NULL,
            contact TEXT NOT NULL, incoming BLOB NOT NULL, draft BLOB,
            detail TEXT NOT NULL DEFAULT '')''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS handled_sources (
            source_key TEXT PRIMARY KEY, created REAL NOT NULL)''')
        self.db.commit()

    def create(self, contact, incoming):
        event_id = uuid.uuid4().hex
        self.db.execute('INSERT INTO events(id,created,state,contact,incoming) VALUES(?,?,?,?,?)',
                        (event_id, time.time(), 'created', contact, protect(incoming)))
        self.db.commit()
        return event_id

    def state(self, event_id, state, detail=''):
        self.db.execute('UPDATE events SET state=?,detail=? WHERE id=?', (state, detail, event_id))
        self.db.commit()

    def draft(self, event_id, text):
        self.db.execute('UPDATE events SET state=?,draft=? WHERE id=?', ('draft', protect(text), event_id))
        self.db.commit()

    def recover(self):
        # Never replay a possibly sent operation after a crash.
        self.db.execute("UPDATE events SET state='interrupted' WHERE state NOT IN ('sent_ui','skipped','failed','superseded','interrupted','unconfirmed','demo')")
        self.db.commit()

    def purge(self, days):
        self.db.execute('DELETE FROM events WHERE created<?', (time.time()-days*86400,))
        self.db.execute('DELETE FROM handled_sources WHERE created<?', (time.time()-days*86400,))
        self.db.commit()
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    def claim_source(self, source_key):
        return self.claim_sources([source_key])

    def claim_sources(self, source_keys):
        with self.db:
            for key in source_keys:
                if self.db.execute('SELECT 1 FROM handled_sources WHERE source_key=?',(key,)).fetchone():
                    return False
            self.db.executemany('INSERT INTO handled_sources(source_key,created) VALUES(?,?)',
                                [(key,time.time()) for key in source_keys])
        return True

def status(state, **details):
    LOCAL.mkdir(exist_ok=True)
    target = LOCAL / 'status.json'
    tmp = target.with_suffix('.tmp')
    payload = json.dumps({'state':state,'updated':time.time(),**details},ensure_ascii=False,indent=2)
    try:
        tmp.write_text(payload, encoding='utf-8')
    except PermissionError:
        target.write_text(payload, encoding='utf-8')
        return
    for attempt in range(10):
        try:
            tmp.replace(target)
            return
        except PermissionError:
            if attempt < 9:
                time.sleep(.025)
    # Windows readers can permit writes while denying file replacement. The UI
    # ignores an incomplete JSON read and retries on its next refresh.
    target.write_text(payload, encoding='utf-8')
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
