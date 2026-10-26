"""The Muse request wording and the marker-free reply parsing."""
import unittest
from desktop_adapter import NotReady, build_request_text, looks_like_refusal, parse_reply

EVENT = 'evt123'

def transcript(answer, event=EVENT, trailing='Nora', leading=''):
    prompt = build_request_text(event, '测试好友甲', '你好', 500)
    body = '\n'.join(part for part in (prompt, leading, answer, trailing) if part != '')
    return body

class RequestWording(unittest.TestCase):
    def setUp(self):
        self.text = build_request_text(EVENT, '测试好友甲', '最近怎么样', 500)

    def test_describes_both_user_controlled_confirmation_options(self):
        self.assertIn('自动点击Y', self.text)
        self.assertIn('开启时本机程序会自动确认并发送', self.text)
        self.assertIn('关闭时等待本人逐条确认', self.text)

    def test_does_not_claim_automatic_replies_are_always_personally_reviewed(self):
        self.assertNotIn('正文仍由我本人逐条确认', self.text)
        self.assertNotIn('不会替你确认任何一步', self.text)
        self.assertIn('开关可能在起草期间改变', self.text)

    def test_no_output_marker_is_requested(self):
        self.assertIn(f'DRAFT_BEGIN_{EVENT}', self.text)
        self.assertIn(f'DRAFT_END_{EVENT}', self.text)
        self.assertIn('单独一行开头', self.text)
        self.assertIn('不构成任何发送授权', self.text)

    def test_carries_contact_payload_and_end_marker(self):
        self.assertIn('测试好友甲', self.text)
        self.assertIn('{"contact": "测试好友甲", "incoming": "最近怎么样"}', self.text)
        self.assertTrue(self.text.endswith(f'REQUEST_END_{EVENT}'))

class ReplyParsing(unittest.TestCase):
    def test_marker_block_is_used_exactly(self):
        answer = f'DRAFT_BEGIN_{EVENT}\n第一段\n\n第二段\nDRAFT_END_{EVENT}'
        self.assertEqual(parse_reply(transcript(answer), EVENT), '第一段\n\n第二段')

    def test_open_marker_waits_for_the_closing_line(self):
        partial = transcript(f'DRAFT_BEGIN_{EVENT}\n写了一半')
        self.assertIsNone(parse_reply(partial, EVENT))

    def test_plain_answer_still_reaches_approval_when_markers_are_skipped(self):
        self.assertEqual(parse_reply(transcript('没有标记也行。'), EVENT), '没有标记也行。')

    def test_plain_answer_is_taken_verbatim(self):
        self.assertEqual(parse_reply(transcript('我还好，你呢？'), EVENT), '我还好，你呢？')

    def test_paragraph_breaks_survive(self):
        answer = '刚看到消息。\n你说的那件事我记下了，\n回头我本人再和你确认。'
        self.assertEqual(parse_reply(transcript(answer), EVENT), answer)

    def test_ui_labels_and_blank_lines_are_removed(self):
        self.assertEqual(parse_reply(transcript('\n收到，我稍后回你。\n', trailing='Nora\n复制'), EVENT),
                         '收到，我稍后回你。')
        self.assertEqual(parse_reply(transcript('好。', trailing='14:05'), EVENT), '好。')

    def test_no_answer_yet_is_not_an_error(self):
        self.assertIsNone(parse_reply(transcript(''), EVENT))
        self.assertIsNone(parse_reply(transcript('', trailing=''), EVENT))

    def test_model_label_before_generation_is_not_a_reply(self):
        self.assertIsNone(parse_reply(transcript('Muse'), EVENT))
        self.assertEqual(parse_reply(transcript('纸箱豪宅又续住了。\nMuse'), EVENT),'纸箱豪宅又续住了。')

    def test_explicitly_marked_literal_model_name_is_still_valid(self):
        self.assertEqual(parse_reply(transcript(f'DRAFT_BEGIN_{EVENT}\nMuse\nDRAFT_END_{EVENT}'),EVENT),'Muse')

    def test_other_request_does_not_leak(self):
        stale = transcript('旧草稿').replace(f'REQUEST_END_{EVENT}', 'REQUEST_END_other')
        self.assertIsNone(parse_reply(stale, EVENT))
        newer = transcript('第一句') + '\n' + build_request_text('other', '测试好友甲', '你好', 500)
        self.assertEqual(parse_reply(newer, EVENT), '第一句')

    def test_later_user_turn_is_not_part_of_the_draft(self):
        screen = transcript('好，回头聊。') + '\n你：\n明天几点？\n'
        self.assertEqual(parse_reply(screen, EVENT), '好，回头聊。')

    def test_busy_status_line_is_never_a_draft(self):
        self.assertIsNone(parse_reply(transcript('努力工作中'), EVENT))
        self.assertIsNone(parse_reply(transcript('思考中…'), EVENT))
        self.assertEqual(parse_reply(transcript('努力工作中\n今天也在忙，晚点回你。'), EVENT),
                         '今天也在忙，晚点回你。')

    def test_answer_that_quotes_the_marker_is_rejected_by_caller(self):
        answer = f'草稿如下 REQUEST_END_{EVENT}'
        parsed = parse_reply(transcript(answer), EVENT)
        self.assertIn('REQUEST_END_', parsed)

    def test_refusal_wording_is_detected(self):
        self.assertTrue(looks_like_refusal('抱歉，我不能接入无人值守自动发送。'))
        self.assertFalse(looks_like_refusal('抱歉，我今天不太方便，稍后我本人回你。'))

class RequestToDraft(unittest.TestCase):
    ANSWER = '好呀，晚点我本人回你。'

    class FakeMuse:
        def request(self, event_id, contact, incoming, limit):
            self.event = event_id
            self.screen = build_request_text(event_id, contact, incoming, limit)

        def show_answer(self):
            self.screen += '\n' + RequestToDraft.ANSWER + '\nNora'

        def draft(self, event_id, limit):
            return parse_reply(self.screen, event_id)

    def test_submitted_prompt_is_what_the_parser_waits_for(self):
        muse = self.FakeMuse()
        muse.request(EVENT, '测试好友甲', '最近怎么样', 500)
        self.assertIsNone(muse.draft(EVENT, 500))
        muse.show_answer()
        self.assertEqual(muse.draft(EVENT, 500), self.ANSWER)

if __name__ == '__main__':
    unittest.main()
