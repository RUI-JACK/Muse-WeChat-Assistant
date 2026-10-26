"""Synthetic test target, in this test process only."""
import bridge
bridge.CONFIG={**bridge.CONFIG,'allowed_contact':'测试好友甲','chat_mode':'private'}
from storage import LOCAL
(LOCAL/'diagnostics').mkdir(parents=True,exist_ok=True)
