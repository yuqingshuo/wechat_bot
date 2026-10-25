# -*- coding: utf-8 -*-
"""清理 chat_histories.json 里的「回弹污染」。

回弹污染的特征：一条 role=user 的消息，内容和紧邻的前一条 role=assistant
完全一致（机器人自己发出去的话被监听回调当成了对方消息收回来）。
本脚本只删这类 user 条目，不动其他任何记录；运行前自动备份。

用法：python cleanup_echo_history.py
"""
import json
import os
import re
import shutil
import time

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_histories.json")


def norm(s):
    return re.sub(r"\s+", "", str(s or ""))


def main():
    if not os.path.exists(PATH):
        print("找不到 chat_histories.json，无需清理。")
        return

    backup = PATH + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy(PATH, backup)
    print("已备份 -> %s" % backup)

    with open(PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_removed = 0
    for uid, msgs in list(data.items()):
        if not isinstance(msgs, list):
            continue
        cleaned = []
        removed_here = 0
        for m in msgs:
            if (isinstance(m, dict)
                    and m.get("role") == "user"
                    and cleaned
                    and cleaned[-1].get("role") == "assistant"
                    and norm(m.get("content")) == norm(cleaned[-1].get("content"))):
                removed_here += 1
                continue
            cleaned.append(m)
        if removed_here:
            print("[%s] 删除回弹条目 %d 条，剩余 %d 条" % (uid, removed_here, len(cleaned)))
            data[uid] = cleaned
            total_removed += removed_here

    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("完成：共删除 %d 条回弹记录。" % total_removed)


if __name__ == "__main__":
    main()
