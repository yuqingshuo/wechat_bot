# -*- coding: utf-8 -*-
"""对话观察脚本：以进程内注入方式驱动 20 轮对话，验收机器人修复后的对话质量。

原理（不连微信、不启动完整机器人）：
  1. import main —— main.py 的启动逻辑全在 __main__ 里，import 无副作用；
  2. mock 掉 send_humanlike_reply —— 回复不真的发到微信，只记录；
  3. 放行白名单检查 —— is_listen_allowed 恒 True；
  4. 用独立测试用户 __acceptance_test__ —— 不碰阑珊/杨浩玉的真实数据；
  5. 起 queue_worker 线程（wx=None）—— 消息合并/好感度/LLM/记忆全走真实管线；
  6. 逐轮构造假 msg/chat 调 make_msg_handler 返回的 on_message —— 等价于真实来信。

数据安全：
  - 运行前自动备份 chat_histories.json / mind_state.json；
  - 运行结束后用备份恢复，抹掉测试用户产生的所有数据。

体检维度：
  - 跨轮指代承接（第 7/8/20 轮问「它」——上文第 3 轮的猫）；
  - 人设一致性（第 12 轮问年龄、第 14 轮问专业）；
  - 每轮好感度/阶段/情绪快照；
  - 兜底句与超时检测。

用法：python observe_dialog.py        （约需 5-10 分钟，视 API 限流情况）
报告：同目录 observe_report_YYYYMMDD_HHMMSS.md
"""
import datetime
import json
import os
import shutil
import sys
import threading
import time
import types

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.chdir(BASE)  # main.py 内部大量使用相对路径，必须先切工作目录

import main  # noqa: E402

TEST_UID = u"__acceptance_test__"
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

# ---------------------------------------------------------------------------
# 20 轮台词：自然口语，埋了 3 个指代陷阱 + 2 个人设探针 + 积极词
# ---------------------------------------------------------------------------
SCRIPT = [
    (1,  u"在吗"),
    (2,  u"我刚下班 累死了"),
    (3,  u"我家猫昨天吐了 吓死我了"),
    (4,  u"去医院看了 医生说吃太急 开了点药"),
    (5,  u"你今天上课了吗"),
    (6,  u"我们班昨天班会 老班拖堂半小时"),
    (7,  u"它今天好点了 会蹭我了"),                 # 指代陷阱①（猫）
    (8,  u"你说它会不会记仇我啊"),                   # 指代陷阱②
    (9,  u"哈哈也是 它可能就在耍小脾气"),
    (10, u"你吃饭了吗"),
    (11, u"我刚点了份麻辣烫 特辣"),
    (12, u"你多大了来着"),                           # 人设探针：年龄
    (13, u"我看你朋友圈照片好显小"),
    (14, u"你是学什么专业的"),                       # 人设探针：专业
    (15, u"我们专业也要学运营 以后多交流"),
    (16, u"不早啦 晚安 明天再聊"),
    (17, u"早安"),
    (18, u"今天地铁挤爆了 我差点没上去"),
    (19, u"谢谢你听我碎碎念"),                       # 积极词
    (20, u"它现在完全好啦 改天带你……啊你也见不到 哈哈"),  # 指代陷阱③ + 收尾
]

# 每轮等待回复的超时（秒）：debounce + LLM（含 429 重试）通常 10-30s
REPLY_TIMEOUT = 120

REPLIES = []   # [(轮次, 用户文本, 回复文本, 耗时s)]
CUR = {"n": 0, "user": u"", "t0": 0.0}

FALLBACK_HINTS = (u"刚在忙", u"怎么啦", u"稍等", u"再说一遍")


def log(msg):
    print(u"[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg))
    sys.stdout.flush()


def mock_send(wx, u_id, reply):
    """替换 send_humanlike_reply：记录回复，不真的发微信。"""
    elapsed = time.time() - CUR["t0"]
    REPLIES.append((CUR["n"], CUR["user"], reply, elapsed))
    main.record_sent_message(u_id, reply)  # 保持回弹过滤状态与真实一致
    log(u"第 %2d 轮回复（%.1fs）：%s" % (CUR["n"], elapsed, reply.replace("\n", u" / ")))


def snapshot(uid):
    """取该用户当前的好感度/阶段/情绪快照。"""
    try:
        aff, stage = main.get_user_affection_and_stage(uid)
        st = main.get_mind_engine().friend_state(uid).get("state") or {}
        return aff, main.STAGE_NAME_MAP.get(stage, stage), st.get("emotion", "?")
    except Exception as e:
        return -1, "?", "snapshot失败:%s" % e


def fire(round_no, text):
    """模拟一条来自测试用户的微信文本消息。"""
    CUR["n"] = round_no
    CUR["user"] = text
    CUR["t0"] = time.time()
    msg = types.SimpleNamespace(type="text", attr="friend", content=text)
    chat = types.SimpleNamespace(who=TEST_UID, _wxid="wxid_acceptance_test")
    HANDLER(msg, chat)


def wait_reply(round_no, timeout=REPLY_TIMEOUT):
    """轮询等待第 round_no 轮的回复出现。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if REPLIES and REPLIES[-1][0] == round_no:
            return True
        time.sleep(0.5)
    return False


def health_check():
    """自动体检：指代承接 / 人设一致 / 长度 / 兜底。"""
    report = []
    by_round = {r[0]: r for r in REPLIES}

    # 1) 跨轮指代承接：第 7/8/20 轮，上文第 3 轮提到猫
    for r in (7, 8, 20):
        if r in by_round:
            reply = by_round[r][2]
            hit = any(w in reply for w in (u"猫", u"吐", u"药", u"兽医", u"宠物"))
            report.append((u"指代承接·第%d轮" % r, u"✅ 接住了猫" if hit else u"❌ 脱锚：%s" % reply))
        else:
            report.append((u"指代承接·第%d轮" % r, u"⚠ 无回复"))

    # 2) 人设一致性：第 12 轮年龄（19岁）、第 14 轮专业（电商/学生）
    if 12 in by_round:
        r12 = by_round[12][2]
        ok = (u"19" in r12) or (u"十九" in r12) or (u"岁" in r12)
        report.append((u"人设一致·年龄", u"✅ %s" % r12 if ok else u"❌ %s" % r12))
    if 14 in by_round:
        r14 = by_round[14][2]
        ok = any(w in r14 for w in (u"电商", u"学生", u"上课", u"班", u"专业", u"学"))
        report.append((u"人设一致·专业", u"✅ %s" % r14 if ok else u"❌ %s" % r14))

    # 3) 长度与兜底
    if REPLIES:
        lens = [len(r[2]) for r in REPLIES]
        report.append((u"回复长度", u"平均 %.0f 字，最长 %d，最短 %d（人设要求短句口语）"
                       % (sum(lens) / float(len(lens)), max(lens), min(lens))))
        fb = [r[0] for r in REPLIES if any(h in r[2] for h in FALLBACK_HINTS)]
        report.append((u"兜底句", u"⚠ 第 %s 轮疑似兜底（API 限流时会出现）" % fb if fb else u"✅ 无兜底句"))
    else:
        report.append((u"总体", u"❌ 20 轮零回复，管线或 API 有严重问题"))
    return report


def write_report(snaps, elapsed_total):
    path = os.path.join(BASE, u"observe_report_%s.md" % STAMP)
    lines = [u"# 对话观察报告（%s）\n" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
             u"测试用户：`%s`（独立账号，未污染真实好友）\n" % TEST_UID,
             u"总耗时：%.1f 分钟，成功回复 %d/20 轮\n" % (elapsed_total / 60.0, len(REPLIES)),
             u"\n## 一、逐轮对话记录\n"]
    for r in REPLIES:
        lines.append(u"**%d. 用户**：%s" % (r[0], r[1]))
        lines.append(u"**苏晚**（%.1fs）：%s\n" % (r[3], r[2].replace("\n", u" / ")))
    missing = [n for n, _ in SCRIPT if n not in {r[0] for r in REPLIES}]
    if missing:
        lines.append(u"\n> ⚠ 无回复的轮次：%s\n" % missing)

    lines.append(u"\n## 二、每轮状态快照\n")
    lines.append(u"| 轮次 | 好感度 | 阶段 | 情绪 |")
    lines.append(u"|---|---|---|---|")
    for n, aff, stage, emo in snaps:
        lines.append(u"| %d | %s | %s | %s |" % (n, aff, stage, emo))

    lines.append(u"\n## 三、自动体检\n")
    for name, result in health_check():
        lines.append(u"- **%s**：%s" % (name, result))

    lines.append(u"\n## 四、结论参考\n")
    lines.append(u"- 指代承接全 ✅ → 前后不搭修复达标；仍有 ❌ → 模型背景退化，需换更强模型")
    lines.append(u"- 好感度从 0 正常增长且不停在相识 → 计分系统修复达标")
    lines.append(u"- 人设探针 ✅ → 人格锚定生效")
    with open(path, "w", encoding="utf-8") as f:
        f.write(u"\n".join(lines))
    return path


def main_():
    global HANDLER

    # ---- 0. 备份 ----
    backups = {}
    for fn in ("chat_histories.json", "mind_state.json"):
        src = os.path.join(BASE, fn)
        if os.path.exists(src):
            dst = src + ".observe-bak-" + STAMP
            shutil.copy2(src, dst)
            backups[fn] = dst
            log(u"已备份 %s -> %s" % (fn, os.path.basename(dst)))

    # ---- 1. mock ----
    main.send_humanlike_reply = mock_send
    main.is_listen_allowed = lambda who: True
    HANDLER = main.make_msg_handler(None)

    # ---- 2. 启动 queue_worker 线程 ----
    t = threading.Thread(target=main.queue_worker, args=(None,), daemon=True)
    t.start()
    log(u"queue_worker 已启动（发送环节已 mock），开始 20 轮对话…")

    snaps = []
    t_all = time.time()
    try:
        for n, text in SCRIPT:
            aff0, stage0, emo0 = snapshot(TEST_UID)
            fire(n, text)
            ok = wait_reply(n)
            aff1, stage1, emo1 = snapshot(TEST_UID)
            snaps.append((n, u"%s→%s" % (aff0, aff1), u"%s→%s" % (stage0, stage1), emo1))
            if not ok:
                log(u"第 %d 轮等待超时（%ds 内无回复）" % (n, REPLY_TIMEOUT))
            time.sleep(2.5)  # 轮间休息，降低 429 概率
    finally:
        elapsed = time.time() - t_all
        main.bot_stop_event.set()  # 停掉 queue_worker
        time.sleep(1)

    path = write_report(snaps, elapsed)
    log(u"报告已生成：%s" % os.path.basename(path))

    # ---- 3. 恢复备份，抹掉测试数据 ----
    for fn, dst in backups.items():
        shutil.copy2(dst, os.path.join(BASE, fn))
        log(u"已恢复 %s（测试数据已抹除）" % fn)

    # ---- 4. 摘要 ----
    log(u"\n===== 摘要 =====")
    log(u"成功回复 %d/20 轮，总耗时 %.1f 分钟" % (len(REPLIES), elapsed / 60.0))
    for name, result in health_check():
        log(u"%s：%s" % (name, result))


if __name__ == "__main__":
    main_()
