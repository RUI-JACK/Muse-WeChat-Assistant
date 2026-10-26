"""Explicitly select the one chat before starting a bridge worker."""
import json
import unicodedata


def validate_contact(value):
    if not isinstance(value, str):
        raise ValueError('请先输入好友昵称或备注。')
    if any(unicodedata.category(ch) == 'Cc' for ch in value):
        raise ValueError('好友名称不能包含换行、制表符等控制字符。')
    name = value.strip()
    if not name:
        raise ValueError('请先输入好友昵称或备注。')
    if len(name) > 100:
        raise ValueError('好友名称过长，请填写微信聊天顶部的名称。')
    return name


def save_contact(root, value):
    name = validate_contact(value)
    path = root / 'config.json'
    try:
        config = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ValueError('无法读取助手配置，请检查程序文件夹。') from exc
    if not isinstance(config, dict):
        raise ValueError('助手配置格式不正确，尚未开始监测。')
    config['allowed_contact'] = name
    temporary = path.with_suffix('.contact.tmp')
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    return name
