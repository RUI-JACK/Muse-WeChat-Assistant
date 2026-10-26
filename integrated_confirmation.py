"""Optional local confirmation in the unified app, limited to its owned worker."""
import json
import win32con
import win32gui
from auto_y import find_target


def read_settings(root):
    try:
        data = json.loads((root / 'local/ui-settings.json').read_text(encoding='utf-8'))
        value = data.get('auto_click_y', True)
        return value if isinstance(value, bool) else True
    except (OSError, ValueError):
        return True


def save_settings(root, enabled):
    local = root / 'local'
    local.mkdir(exist_ok=True)
    target = local / 'ui-settings.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'auto_click_y': bool(enabled)}, indent=2), encoding='utf-8')
    temporary.replace(target)


class AutoConfirmation:
    def __init__(self, contact, enabled=True, chat_mode='private'):
        self.contact = contact
        self.chat_mode = chat_mode
        self.enabled = enabled
        self.handled = set()
        self.count = 0
        self.error = None

    def poll(self, worker, state):
        if not self.enabled or not self.contact or not worker or not worker.alive():
            return False
        if state.get('chat_mode','private')!=self.chat_mode:return False
        event = state.get('event_id')
        if not event or event in self.handled or not worker.owns(state.get('pid')):
            return False
        try:
            target = find_target(state, self.contact)
            if not target:
                return False
            # Recheck the same event, exact dialog and owned worker immediately
            # before dispatch. Disabling the checkbox stops all future polls.
            fresh = worker.read_status()
            if (not self.enabled or fresh.get('event_id') != event
                    or fresh.get('chat_mode','private') != self.chat_mode
                    or not worker.owns(fresh.get('pid'))
                    or find_target(fresh, self.contact) != target):
                return False
            win32gui.PostMessage(target[1], win32con.BM_CLICK, 0, 0)
            self.handled.add(event)
            self.count += 1
            self.error = None
            return True
        except Exception as exc:
            self.error = type(exc).__name__
            return False
