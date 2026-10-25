# -*- coding: utf-8 -*-
"""把 mind_state.json 里所有好友的 core_identity 同步成当前人设。

背景：旧预设（虞清铄·男·直播）残留的身份句写在每个好友的锚定里，和当前
启用的人设（persona.json 的 bot_profile）矛盾，模型会同时收到两个身份。
本脚本按 mind/personality.py:_identity_core 的相同逻辑生成正确身份句，
整体替换所有好友的 core_identity。always/never 等其他锚定一律不动。

用法：python fix_anchoring_identity.py
"""
import json
import os
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PERSONA = os.path.join(BASE, "persona.json")
STATE = os.path.join(BASE, "mind_state.json")


def identity_core(prof):
    """与 mind/personality.py:_identity_core 保持一致的生成逻辑。"""
    bits = []
    name = (prof.get("name") or "").strip()
    gender = (prof.get("gender") or "").strip()
    age = (prof.get("age") or "").strip()
    identity = (prof.get("identity") or "").strip()
    if name:
        bits.append(u"我叫%s" % name)
    if gender:
        bits.append(u"是%s" % gender)
    if age:
        bits.append(u"%s" % age)
    if identity:
        bits.append(u"身份是%s" % identity)
    if bits:
        return (u"我就是一个真实存在的人：%s。我有自己独立的生活和作息，"
                u"不是只会问答的聊天机器人" % u"，".join(bits))
    return (u"我就是一个真实存在的人，有自己独立的生活和作息，"
            u"不是只会问答的聊天机器人")


def main():
    persona = json.load(open(PERSONA, encoding="utf-8"))
    prof = persona.get("bot_profile") or {}
    core = identity_core(prof)
    print("当前人设身份句：%s" % core)

    backup = STATE + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
    with open(STATE, "r", encoding="utf-8") as f:
        state = json.load(f)
    with open(backup, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print("已备份 -> %s" % backup)

    friends = state.get("friends") or {}
    changed = 0
    for uid, fs in friends.items():
        anchoring = fs.setdefault("anchoring", {})
        old = anchoring.get("core_identity") or ""
        if old != core:
            anchoring["core_identity"] = core
            changed += 1
            print("[%s] %s -> %s" % (uid, old[:30] or "(空)", core[:30]))

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print("完成：修正 %d/%d 位好友的身份锚定。" % (changed, len(friends)))


if __name__ == "__main__":
    main()
