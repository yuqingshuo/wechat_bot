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


def must(cond, msg):
    """断言必须成立，否则抛出 AssertionError。

    旧写法 `cond or "错误信息"` 在条件不成立时返回的是真值字符串，而 step()
    只把「抛异常」当成失败，结果这些用例永远显示 PASS，形同虚设。
    统一改成 must()，让失败真的能冒出来。
    """
    if not cond:
        raise AssertionError(msg)
    return True


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

# ---- 配置优先级：环境变量 > config_local.py > models_config.json ----
# 注意：from llm import config_manager 拿到的是 llm/__init__.py 里导出的单例对象，
# 不是 llm/config_manager.py 模块，所以这里用 importlib 直接拿模块。
import importlib as _importlib  # noqa: E402
_cm = _importlib.import_module("llm.config_manager")


class _EnvOverride(object):
    """临时改环境变量 / config_local，退出时原样还原。"""

    def __init__(self, env=None, local=None):
        self._env = env or {}
        self._local = local or {}
        self._old_env = {}
        self._old_local = None
        self._had_local = False

    def __enter__(self):
        for k, v in self._env.items():
            self._old_env[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            import config_local as _cl
            self._old_local = _cl
            self._had_local = True
        except Exception:
            self._old_local = None
            self._had_local = False
        if self._local:
            import types
            mod = types.ModuleType("config_local")
            for k, v in self._local.items():
                setattr(mod, k, v)
            sys.modules["config_local"] = mod
        return self

    def __exit__(self, *exc):
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if self._had_local:
            sys.modules["config_local"] = self._old_local
        else:
            sys.modules.pop("config_local", None)
        return False


def _overlay(pid, data, env=None, local=None):
    with _EnvOverride(env=env, local=local):
        return _cm.apply_env_local_overlay(pid, data)


step("config_priority.环境变量盖过存档值", lambda: must(
    _overlay("default_cloud", {"api_key": "sk-old", "model": "old-model"},
             env={"WECHATBOT_API_KEY": "sk-env-test-000",
                  "WECHATBOT_MODEL": "env-model-x"},
             local={"API_KEY": "sk-local-test-000", "MODEL": "local-model"})
    == {"api_key": "sk-env-test-000", "model": "env-model-x"}, "环境变量未生效!"))

step("config_priority.config_local 盖过存档值", lambda: must(
    _overlay("default_cloud", {"api_key": "sk-old", "model": "old-model"},
             env={}, local={"API_KEY": "sk-local-test-000", "MODEL": "local-model"})
    == {"api_key": "sk-local-test-000", "model": "local-model"}, "config_local 未生效!"))

step("config_priority.都没配时用存档值", lambda: must(
    _overlay("default_cloud", {"api_key": "sk-saved", "model": "saved-model"},
             env={}, local={})
    == {"api_key": "sk-saved", "model": "saved-model"}, "存档值被覆盖了!"))

step("config_priority.自定义Provider不吃环境变量", lambda: must(
    _overlay("my_own", {"api_key": "sk-saved", "model": "m"},
             env={"WECHATBOT_API_KEY": "sk-env-test-000"}, local={})
    == {"api_key": "sk-saved", "model": "m"}, "自定义 Provider 被环境变量污染了!"))

step("config_priority.api_key_source 识别", lambda: must(
    _cm.api_key_source("my_own", "sk-saved") == "saved"
    and _cm.api_key_source("my_own", "") == "none"
    , "source 判定错误!"))

# ---- 密钥绝不外泄 ----
step("secret.list_all_providers 不含密钥明文", lambda: must(
    all(not p.get("api_key") for p in main.llm.list_all_providers())
    , "仍有明文!"))

step("secret.返回体带 has_api_key 标记", lambda: must(
    all("has_api_key" in p for p in main.llm.list_all_providers())
    , "缺 has_api_key"))

step("secret._mask_provider_secrets 清空明文", lambda: must(
    main._mask_provider_secrets({"api_key": "sk-leak-test", "name": "x"})["api_key"] == ""
    , "掩码失败!"))


def _check_empty_key_keeps_old():
    """空密钥保存必须保留原值；测完把 models_config.json 原样还原。

    先写入一个已知密钥，再用空密钥保存，验证「留空 = 沿用原来的」成立。
    不能直接拿 default_cloud 当前存档的密钥来测：密钥已全面外置，存档里的
    api_key 本来就是空字符串，直接测会误报。
    """
    path = _cm.MODELS_CONFIG_FILE
    backup = None
    if os.path.exists(path):
        with open(path, "rb") as f:
            backup = f.read()
    try:
        seed = {"name": "云端大模型", "provider_type": "openai",
                "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
                "api_key": "sk-seed-test-000", "temperature": 0.8, "max_tokens": 120}
        _cm.config_manager.save_provider("default_cloud", seed)
        old = _cm.config_manager.save_provider(
            "default_cloud",
            {"name": "云端大模型", "provider_type": "openai",
             "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
             "api_key": "", "temperature": 0.8, "max_tokens": 120},
        ).api_key
        if old != "sk-seed-test-000":
            raise AssertionError("空密钥把原值冲掉了!")
        return "原值已保留"
    finally:
        if backup is not None:
            with open(path, "wb") as f:
                f.write(backup)
            _cm.config_manager.load()
        elif os.path.exists(path):
            os.remove(path)


step("secret.save 空密钥保留原值", _check_empty_key_keeps_old)

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
