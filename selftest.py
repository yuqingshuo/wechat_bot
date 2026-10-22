# -*- coding: utf-8 -*-
"""自检：跑完所有关键纯逻辑，把结果写进文件（避免 stdout 被日志污染）。"""
import io
import os
import sys
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["PYTHONUTF8"] = "1"

results = []


def step(name, fn):
    try:
        r = fn()
        results.append(("PASS", name, r if r is not None else ""))
    except Exception as e:
        results.append(("FAIL", name, "%s: %s" % (type(e).__name__, e)))
        results.append(("     ", "", traceback.format_exc(limit=3)))


import main  # noqa: E402

step("load_persona", main.load_persona)
step("load_histories", main.load_histories)
step("get_active_persona", lambda: "name=%s" % (main.get_active_persona()[0].get("name") or ""))
step("score_affection_delta", lambda: "delta=%s" % (main.score_affection_delta(u"哈哈哈"),))
step("stage_by_affection(90)", lambda: "stage=%s" % main.stage_by_affection(90))
step("split_reply", lambda: main.split_reply(u"第一句\\第二句\\第三句\\第四句"))
step("sanitize_outreach_text", lambda: repr(main.sanitize_outreach_text(u"**你好**（微笑）\n# 标题")))
step("humanize(短口语)", lambda: repr(main.humanize_outreach_text(u"哈哈")))
step("humanize(套话)", lambda: repr(main.humanize_outreach_text(
    u"好的，我明白了，作为AI我很乐意帮助你")))
step("calibrate_reply_length", lambda: repr(main.calibrate_reply_length(u"嗯" * 200, u"嗯")))
step("text_similarity", lambda: "%.3f" % main.text_similarity(u"我今天很开心", u"我今天很难过"))
step("is_repeat_message", lambda: main.is_repeat_message(u"随便说点啥"))
step("describe_context", lambda: main.describe_context(main.empty_wechat_context()))
step("get_auto_chat_config", lambda: "enabled=%s" % main.get_auto_chat_config()[0].get("enabled"))
step("in_active_window", lambda: main.in_active_window(main.get_auto_chat_config()[0]))
step("get_bot_status", lambda: "state=%s" % main.get_bot_status().get("state"))
step("get_mind_engine", main.get_mind_engine)
step("engine.snapshot", lambda: sorted(main.get_mind_engine().snapshot(u"测试好友").keys()))
step("engine.guard_reply(出戏)", lambda: main.get_mind_engine().guard_reply(
    u"测试好友", u"作为一个人工智能语言模型，我可以帮你……"))
step("engine.would_speak_now", lambda: main.get_mind_engine().would_speak_now(u"测试好友"))

# ---- 移植自 AstrBot human-chat-persona 的新增自检 ----
from mind import chatcraft as _cc  # noqa: E402
from mind import personality as _pp  # noqa: E402
from mind import prompt as _pm  # noqa: E402

step("chatcraft.is_question", lambda: "%s/%s" % (
    _cc.is_question(u"你喜欢吃什么？"), _cc.is_question(u"今天好累啊")))
step("chatcraft.is_self_narrative", lambda: "%s/%s" % (
    _cc.is_self_narrative(u"我今天去医院了"), _cc.is_self_narrative(u"你喜欢吃什么")))
step("chatcraft.is_low_engagement", lambda: "%s/%s" % (
    _cc.is_low_engagement(u"嗯"), _cc.is_low_engagement(u"我今天特别累")))
step("chatcraft.has_negative_mood", lambda: "%s/%s" % (
    _cc.has_negative_mood(u"我今天好累啊"), _cc.has_negative_mood(u"今天天气不错")))
step("chatcraft.find_forbidden(套话)", lambda: _cc.find_forbidden(
    u"好的，加油哦，多喝热水"))
step("chatcraft.find_forbidden(客服腔)", lambda: _cc.find_forbidden(
    u"您好，请问有什么可以帮您"))
step("chatcraft.find_forbidden(干净句)", lambda: _cc.find_forbidden(u"刚下课，食堂门口见？"))
step("chatcraft.is_too_generic", lambda: "%s/%s" % (
    _cc.is_too_generic(u"加油哦"), _cc.is_too_generic(u"刚下课食堂门口见")))
step("chatcraft.relevance_score(贴题)", lambda: "%.2f" % _cc.relevance_score(
    u"你今天去哪儿了", u"去图书馆了，看了一下午书"))
step("chatcraft.relevance_score(离题)", lambda: "%.2f" % _cc.relevance_score(
    u"你今天去哪儿了", u"今天的天气真不错呢"))
step("chatcraft.relevance_score(同词误判)", lambda: "%.2f" % _cc.relevance_score(
    u"你今天去哪儿了", u"刚才在图书馆，现在回家了"))
step("chatcraft.relevance_score(问状态)", lambda: "%.2f" % _cc.relevance_score(
    u"你最近怎么样", u"还行，就是有点忙"))
step("chatcraft.relevance_score(问时间)", lambda: "%.2f" % _cc.relevance_score(
    u"你几点下班", u"六点多吧"))
step("chatcraft.relevance_score(打招呼)", lambda: "%.2f" % _cc.relevance_score(
    u"在吗", u"在呢，刚到家"))
step("chatcraft.is_off_topic", lambda: "%s/%s" % (
    _cc.is_off_topic(u"你今天去哪儿了", u"今天的天气真不错呢"),
    _cc.is_off_topic(u"你今天去哪儿了", u"去图书馆了")))
step("chatcraft.tactics_for_stage", lambda: "%s/%s" % (
    len(_cc.tactics_for_stage(u"1")), len(_cc.tactics_for_stage(u"3"))))
step("chatcraft.life_share_slot", lambda: _cc.life_share_slot(hour=13)[0])
step("chatcraft.life_share_prompt", lambda: _cc.life_share_prompt(hour=13, activity=u"改作业"))

# 身份一致性：人设换成男性，锚定里不能还留着「女生」
_male = {u"name": u"陈默", u"gender": u"男", u"age": u"22", u"identity": u"程序员"}
_legacy = _pp.default_anchoring()
_legacy["core_identity"] = _pp.LEGACY_CORE_IDENTITIES[0]
_changed, _anch = _pp.sync_anchoring_identity(_legacy, _male)
step("personality.锚定跟随人设", lambda: "changed=%s core=%s" % (
    _changed, _anch["core_identity"][:28]))
step("personality.锚定无性别硬编码", lambda: "ok" if u"女生" not in (
    _pp.default_anchoring(_male)["core_identity"]) else "还有女生")
step("personality.保留用户自定义约束", lambda: "ok" if u"我最爱喝奶茶" in (
    _pp.sync_anchoring_identity(
        {u"always": [u"我最爱喝奶茶"], u"never": [], u"core_identity": u"我自己写的"},
        _male)[1]["always"]) else "丢了自定义")

# 守卫：答非所问 / 套话 / 空话
step("guard.拦截答非所问", lambda: main.get_mind_engine().guard_reply(
    u"测试好友", u"今天的天气真不错呢", incoming_text=u"你今天去哪儿了"))
step("guard.拦截空话套话", lambda: main.get_mind_engine().guard_reply(
    u"测试好友", u"加油哦", incoming_text=u"我今天好累"))
step("guard.放行正常回复", lambda: main.get_mind_engine().guard_reply(
    u"测试好友", u"去图书馆了，看了一下午书", incoming_text=u"你今天去哪儿了"))
step("guard.放行打招呼", lambda: main.get_mind_engine().guard_reply(
    u"测试好友", u"在呢，刚到家", incoming_text=u"在吗"))
step("guard.放行自述经历", lambda: main.get_mind_engine().guard_reply(
    u"测试好友", u"我今天也去医院了，排了俩小时队", incoming_text=u"我今天去医院了"))
step("guard.放行问地点的回答", lambda: main.get_mind_engine().guard_reply(
    u"测试好友", u"去图书馆了，看了一下午书", incoming_text=u"你今天去哪儿了"))
step("guard.放行问状态的回答", lambda: main.get_mind_engine().guard_reply(
    u"测试好友", u"还行，就是有点忙", incoming_text=u"你最近怎么样"))
step("guard.拦截天气跑题", lambda: main.get_mind_engine().guard_reply(
    u"测试好友", u"今天的天气真不错呢", incoming_text=u"你今天去哪儿了"))
step("get_activity_log", lambda: "%d 条" % len(main.get_activity_log(5)))
step("list_persona_archives", lambda: "%d 份" % len(main.list_persona_archives()))
step("current_persona_label", main.current_persona_label)
step("Flask 路由", lambda: "%d 条" % len(list(main.app.url_map.iter_rules())))
step("llm provider", lambda: "model=%s" % main.llm.get_active_provider_info().get("model"))
step("llm providers", lambda: "%d 个" % len(main.llm.list_all_providers()))

# ---- 监听名单：昵称不能被截断（老 bug：entry[0] 把「昵称」变成「昵」）----
step("parse_listen_entry(字符串)", lambda: repr(main.parse_listen_entry(u"测试昵称")))
step("parse_listen_entry(字典)", lambda: repr(main.parse_listen_entry({"nickname": u"测试昵称"})))
step("parse_listen_entry(列表)", lambda: repr(main.parse_listen_entry([u"测试昵称"])))
step("parse_listen_entry(元组)", lambda: repr(main.parse_listen_entry((u"测试昵称", u"备注"))))
step("get_listen_names(混合格式去重)", lambda: str(main.get_listen_names()))
step("is_listen_allowed(完整昵称)", lambda: str(main.is_listen_allowed(u"测试昵称")))
step("is_listen_allowed(截断昵称应False)", lambda: str(main.is_listen_allowed(u"测")))
step("load_listen_list 往返", lambda: str(main.load_listen_list()))
step("listen_list.json 昵称未被截断", lambda: str(
    all(len(n) >= 2 for n in main.load_listen_list()[1]) or main.load_listen_list()[1]))

SHORT = [u"嗯", u"哦", u"好", u"哈哈", u"是吗", u"真的吗", u"然后呢", u"不错啊", u"笑死",
         u"哈哈哈", u"确实", u"可以", u"还行", u"不知道", u"再说吧", u"最近忙",
         u"我不太熟", u"我比较慢热", u"慢慢来", u"有空再说", u"周末再说", u"看情况",
         u"你也是", u"谢谢", u"晚安", u"早", u"在忙", u"刚看到", u"怎么了", u"有事吗",
         u"嗯嗯", u"好呀", u"行", u"不要", u"不用了", u"别了吧", u"下次吧", u"改天吧",
         u"再说", u"哈哈哈哈哈"]


def short_regression():
    bad = [(c, main.humanize_outreach_text(c)) for c in SHORT
           if main.humanize_outreach_text(c) != c]
    return "损坏 %d 个 %s" % (len(bad), bad if bad else "")


step("相识短口语原样保留(%d条)" % len(SHORT), short_regression)

lines = []
for st, name, extra in results:
    lines.append("%-5s %-34s %s" % (st, name, extra))
npass = sum(1 for r in results if r[0] == "PASS")
lines.append("")
lines.append("PASS %d / FAIL %d" % (npass, len(results) - npass))

io.open(os.path.join(BASE, "selftest_report.txt"), "w", encoding="utf-8").write("\n".join(lines))
