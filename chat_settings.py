"""Explicit, separate private/group targets. Approval mode remains unchanged."""
import json
from contact_settings import validate_contact
from context_archive import atomic_text


def save_chat(root, mode, target, self_name=''):
    if mode not in ('private','group'):raise ValueError('请选择私聊或群聊。')
    target=validate_contact(target)
    if mode=='group':
        self_name=validate_contact(self_name)
        if self_name in ('所有人','全体成员') or self_name.startswith('@'):
            raise ValueError('请填写本人的群昵称，不含 @。')
    path=root/'config.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    data['chat_mode']=mode
    if mode=='group':
        data.update(allowed_group=target,group_self_name=self_name,group_reply_policy='mention')
    else:data['allowed_contact']=target
    atomic_text(path,json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    return target


def group_config(config):
    if config.get('chat_mode')!='group' or config.get('group_reply_policy')!='mention':
        raise ValueError('群聊只支持明确选择的仅 @ 回复模式。')
    return validate_contact(config.get('allowed_group','')),validate_contact(config.get('group_self_name',''))
