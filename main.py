# -*- coding: utf-8 -*-
"""
微信小号聊天机器人 — 极简主程序。功能：
1. 监听微信消息（支持白名单或全部私聊）
2. 拟人化打字延迟与分段发送
3. 调用大模型回复（支持 DeepSeek / 兼容 OpenAI 的各类模型）
4. 多模态免费额度支持（Moonshot 视觉识别图片/表情包）
5. 支持根据情绪随机回复表情
"""

import os
import re
import sys
import time
import json
import base64
import random
import logging
import threading
import webbrowser
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# 控制台输出统一为 UTF-8，避免中文 Windows(GBK 代码页)下打印中文报 UnicodeEncodeError 而闪退
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    try:
        import io as _io
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# 依赖检查：缺少第三方库时给出可操作的中文提示（而不是直接抛 ModuleNotFoundError）
try:
    import requests
    from flask import Flask, render_template, request, jsonify
    from wxbot import WeChat
except ModuleNotFoundError as _dep_err:
    print("=" * 60)
    print(f"缺少依赖：{_dep_err.name}")
    print("请双击运行【一键启动.bat】自动安装依赖，或手动执行：")
    print("    pip install -r requirements.txt")
    print("=" * 60)
    raise SystemExit(1)

import config
import llm
import mind
import wxfeatures
import presets as persona_presets
from mind import chatcraft
from mind import pacing

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SimpleWeChatBot")

# 历史对话与人设好感度状
msg_queue = {}
queue_lock = threading.Lock()
chat_histories = {}
history_file = os.path.join(BASE_DIR, "chat_histories.json")
send_lock = threading.Lock()
history_lock = threading.Lock()

# =============================================================================
# 聊天记录留痕 + 人设归档（给人看的明文档案，不参与模型上下文）：
# - chat_logs/<好友>.log：写明和谁聊、机器人每条回复用的是哪个人
# - personas/<时间>_<名字>.json：每次切换人设前，把换下去的旧人设整个打包存
# =============================================================================
PERSONA_ARCHIVE_DIR = os.path.join(BASE_DIR, "persona_archives")
CHAT_LOG_DIR = os.path.join(BASE_DIR, "chat_logs")
archive_lock = threading.Lock()
chat_log_lock = threading.Lock()

persona_data = {}
persona_file = os.path.join(BASE_DIR, "persona.json")
persona_lock = threading.RLock()

# =============================================================================
# 监听名单：可在网页里增删，不用改 config.py
# 存在 listen_list.json 里；没这个文件时才用 config.py 的 LISTEN_LIST / LISTEN_MODE
# 保存后直接改写内存里的 config.LISTEN_LIST，所以全局代码立刻生效
# =============================================================================
listen_store_file = os.path.join(BASE_DIR, "listen_list.json")
listen_lock = threading.RLock()


def parse_listen_entry(entry):
    """把监听名单里的一项解析成「昵称」字符串。

    历史包袱：监听项在不同地方存过好几种形状——
      - "昵称"                纯字符串
      - ["昵称"]              单元素列表（老代码按 entry[0] 取值）
      - ("昵称", "备注")      元组
      - {"nickname": "昵称"}  字典（listen_list.json 现在的格式）
    以前直接写 entry[0]，碰到纯字符串就会把「昵称」截断成「昵」，
    导致好友发消息永远匹配不上白名单、机器人装死不回。
    这里统一按类型分派，字符串原样返回，绝不取下标。
    """
    if entry is None:
        return ""
    if isinstance(entry, dict):
        return str(entry.get("nickname") or "").strip()
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, (list, tuple)):
        for part in entry:
            if isinstance(part, str) and part.strip():
                return part.strip()
        return ""
    return str(entry).strip()


def get_listen_names():
    """返回当前生效的监听昵称列表（纯字符串，已去重去空）。

    所有需要「按昵称匹配」的地方都走这里，别再直接索引 config.LISTEN_LIST。
    """
    names, seen = [], set()
    for entry in (getattr(config, "LISTEN_LIST", []) or []):
        nick = parse_listen_entry(entry)
        if not nick or nick in seen:
            continue
        seen.add(nick)
        names.append(nick)
    return names


def is_listen_allowed(who):
    """判断某人是否在监听范围内（白名单模式下用昵称精确匹配）。"""
    if getattr(config, "LISTEN_MODE", "whitelist") != "whitelist":
        return True
    return who in get_listen_names()


def load_listen_list():
    """读出当前生效的 (mode, [昵称, ...])，读不到就用 config.py 里的默认值。"""
    try:
        with open(listen_store_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        mode = raw.get("mode") or getattr(config, "LISTEN_MODE", "whitelist")
        items, seen = [], set()
        for it in raw.get("items") or []:
            nick = parse_listen_entry(it)
            if nick and nick not in seen:
                seen.add(nick)
                items.append(nick)
        return mode, items
    except Exception:
        return getattr(config, "LISTEN_MODE", "whitelist"), get_listen_names()


def save_listen_list(mode, items):
    """保存名单并立刻生效，返回保存后的 (mode, items)。"""
    mode = mode if mode in ("whitelist", "all_private") else "whitelist"
    clean, seen = [], set()
    for it in items or []:
        nick = parse_listen_entry(it)
        if not nick or nick in seen:          # 去重，避免重复订阅同一个会话
            continue
        seen.add(nick)
        clean.append(nick)

    # 统一写成 [{"nickname": ...}] 字典格式：跟 /api/listen/list 返回的结构一致，
    # 前端和 load_listen_list() 都认；读取时靠 parse_listen_entry() 兼容各种历史格式
    payload = {"mode": mode, "items": [{"nickname": n} for n in clean],
               "updated_at": time.time()}
    tmp = listen_store_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, listen_store_file)        # 原子替换，避免写一半断电损坏文件
    # 改写内存，代码里所有读 config.LISTEN_LIST 的地方立刻看到新名单
    # 统一存成纯字符串列表；匹配一律走 get_listen_names()，不再有 entry[0] 这类下标写法
    with listen_lock:
        config.LISTEN_LIST = list(clean)
        config.LISTEN_MODE = mode
    logger.info(f"监听名单已更新：模式={mode}，共 {len(clean)} 个 -> {clean}")
    return mode, clean


# 人设只有一层：不管在跟谁聊，用的都是同一个 persona.json
def get_active_persona():
    """返回当前生效的 (bot_profile, stages)。"""
    with persona_lock:
        return (persona_data.get("bot_profile", {}),
                persona_data.get("stages", {}))


def sync_anchoring_with_persona():
    """启动时把历史锚定同步成当前人设（修掉写死的旧身份，并补齐新规则）。

    persona.json 是唯一的人设来源：改了性别/年龄/名字之后，
    之前存进 mind_state.json 的锚定里可能还留着旧身份，这里统一纠正并落盘。
    """
    try:
        bot_prof, _stages = get_active_persona()
        if not bot_prof:
            return 0
        engine = get_mind_engine()
        with engine.store.state_lock:
            friends = list((engine.store.state.get("friends") or {}).keys())
        fixed = 0
        for uid in friends:
            try:
                fs = engine.friend_state(uid)
                changed, anchoring = mind.personality.sync_anchoring_identity(
                    fs.get("anchoring"), bot_prof)
                if changed:
                    fs["anchoring"] = anchoring
                    fixed += 1
            except Exception as e:
                logger.debug(f"[{uid}] 锚定同步失败（已忽略）: {e}")
        if fixed:
            engine.save_state(force=True)
            logger.info(f"已按当前人设修正 {fixed} 位好友的人格锚定")
        return fixed
    except Exception as e:
        logger.debug(f"锚定同步失败（已忽略）: {e}")
        return 0


def list_available_personas():
    """已废弃：人设只有一层，不再按好友单独指定。

    现在唯一的入口就是下面那三张预设卡片（见 presets.py）加自定义表单，
    两处写的是同一个 persona.json，改完立刻全局生效。保留此函数只为老调用不报错。
    """
    return []

try:
    _m, _i = load_listen_list()
    if _i:
        config.LISTEN_MODE = _m
        config.LISTEN_LIST = list(_i)
except Exception:
    pass

# 微信客户端实例（主程序连接成功后赋值，供 Web 控制台主动发消息使用）
wx_instance = None
wx_instance_lock = threading.Lock()

# Web 控制台操作日志（最近若干条，供网页展示“发送了什么是否成功）
activity_log = []
activity_log_lock = threading.Lock()
MAX_ACTIVITY_LOG = 30

# ==============================================================================
# 内心世界（鉴 Yuki-QQbot / ashley / Shikigami-Protocol / y-ai-accompany / Ai-Companion
# ------------------------------------------------------------------------------
# mind     -> 情绪曲线、关系维度多层记忆动态人格内部状态后台沉
# wxfeatures -> 微信平台侧：消息去重、好友冷却Token 统计、对话隔离拍这
#
# 定位：两者都只负责调味，身份与关系阶段永远由 persona.json 的 affection
# 和 config.py 的人设唯一决定 —— 保证微信小号恋爱关系的主体不漂移
# ==============================================================================
mind_lock = threading.Lock()
_mind_engine = None


def get_mind_engine():
    """懒加载全局 Mind 实例（进程内单例，线程安全）。"""
    global _mind_engine
    with mind_lock:
        if _mind_engine is None:
            _mind_engine = mind.get_mind(BASE_DIR)
    return _mind_engine


dedupe_guard = wxfeatures.DedupeGuard(ttl=90.0, bucket=45.0)
cooldown_guard = wxfeatures.CooldownGuard(default_seconds=6.0)
token_stats = wxfeatures.TokenStats()


def mind_llm_extractor(messages, max_tokens=320, kind="memory"):
    """给 mind 用的 LLM 回调：蒸馏长期记忆 / 生成内心独白。

    任何失败都回规则模式（返回空串），绝不打断主回复流程。
    """
    try:
        text = llm.chat_completion(messages=messages, temperature=0.4,
                                   max_tokens=max_tokens)
        token_stats.record(messages, text, kind=kind, ok=True)
        return text
    except Exception as e:
        token_stats.record(messages, "", kind=kind, ok=False)
        logger.debug(f"mind 的 LLM 回调失败（已退回规则模式）: {e}")
        return ""



# ==============================================================================
# 自动主动搭话（定时自动找人聊天）默认配置与运行状
# ==============================================================================
DEFAULT_AUTO_CHAT = {
    "enabled": False,          # 总开关：打开后机器人会自己定时找人聊
    "interval_minutes": 60,    # 每次自动搭话的间隔（分钟
    "active_start": 9,         # 活跃时段开始（小时，含
    "active_end": 23,          # 活跃时段结束（小时，不含
    "max_per_day": 20,         # 每天自动搭话条数上限
    "jitter": True,            # 间隔随机浮动，避免整点机械感
    "count_affection": True,   # 自动搭话是否计入好感度（+1
    "targets": [],             # 参与自动搭话的好友（留空 = 监听白名单好友）
    "topics": "",              # 话题池，每行这个；留空则由 AI 自由发挥
    "use_context": True,       # 自动读取微信真实聊天记录作为上下
    "context_rounds": 20,      # 读取最近多少条微信记录作为上下
    "reply_pending_first": True,  # 对方有未回复消息时，优先接话而不是另起话
    "min_gap_hours": 2.0,      # 同一个好友两次主动搭话的最短间隔（小时
    "avoid_repeat": True,      # 与最近发过的内容去重，避免复读机
}

DEFAULT_AUTO_RUNTIME = {
    "last_run": 0.0,           # 上次自动搭话时间
    "next_run": 0.0,           # 下次允许自动搭话的时间戳
    "day": "",                 # 统计日期（跨天自动重置）
    "count_today": 0,          # 今日已自动搭话条
    "last_target": "",         # 上次自动搭话对象
    "recent_sent": [],         # 最近发送内容 [{"t": 时间, "target": 好友, "text": 内容}]
}


# ==============================================================================
# 机器人运行时（核心运行模式：这次配置，启动即运行）
# ------------------------------------------------------------------------------
# 配置阶段：用户在网页控制台设置好人设 / 模型 / 微信账号 / 上下文 / 自动回复规则
#          点一次保存即可（写入 persona.json，下次开机依然生效）
# 运行阶段：点这次启动机器人」，之后全自动运行，无需任何人工触发
#          自动连接微信 -> 自动监听新消息 -> 自动读上下文 -> 自动调模
#          -> 自动生成回复 -> 自动发送 -> 自动存记忆 -> 持续监听
# ==============================================================================
DEFAULT_RUNTIME = {
    "auto_start": False,           # 程序启动后是否自动连接微信并进入全自动运行（无需手动点「启动」）
    "auto_reply": True,            # 收到新消息后自动生成并发送回复（无需人工点击
"auto_save_memory": True,      # 自动保存聊天记录到 Memory（chat_histories.json）
    "connect_retry": 3,            # 启动时连接微信的最大尝试次
    "connect_retry_interval": 10,  # 每次连接失败后的重试间隔（秒
    "auto_reconnect": True,        # 运行中微信掉线后自动重连并恢复监
"monitor_interval": 20,        # 运行状态巡检间隔（秒）
}

# 运行时状态机：stopped(未启动) / connecting(正在连接) / running(全自动运行中)
#               / stopping(正在停止) / error(启动失败)
BOT_STATE_STOPPED = "stopped"
BOT_STATE_CONNECTING = "connecting"
BOT_STATE_RUNNING = "running"
BOT_STATE_STOPPING = "stopping"
BOT_STATE_ERROR = "error"

BOT_STATE_TEXT = {
BOT_STATE_STOPPED: "未启动",
    BOT_STATE_CONNECTING: "正在连接微信...",
    BOT_STATE_RUNNING: "全自动运行中",
    BOT_STATE_STOPPING: "正在停止...",
    BOT_STATE_ERROR: "启动失败",
}

bot_state = {
    "state": BOT_STATE_STOPPED,
    "state_text": BOT_STATE_TEXT[BOT_STATE_STOPPED],
    "started_at": 0.0,             # 本次启动时间
    "wechat_nickname": "",         # 已连接的微信账号昵称
    "listen_mode": "",             # 本次运行使用的监听模
    "listen_targets": [],          # 已成功监听的会话
    "listen_failed": [],           # 监听失败的会
    "messages_received": 0,        # 本次运行自动接收的消息数
    "replies_sent": 0,             # 本次运行自动回复的次数（按好友回复轮次计
    "memory_rounds": 0,            # 本次运行自动保存的记忆轮
    "last_message_at": 0.0,        # 最近一条来信时
    "last_message_text": "",
    "last_message_from": "",
    "last_reply_at": 0.0,
    "last_reply_text": "",
    "last_error": "",
    "reconnect_count": 0,
}
bot_state_lock = threading.RLock()
bot_stop_event = threading.Event()      # 置位后所有运行线程主动
bot_threads = {}                        # name -> Thread，便于停止与状态展示

def _set_bot_state(state, **fields):
    """更新运行时状态（线程安全）。"""
    with bot_state_lock:
        bot_state["state"] = state
        bot_state["state_text"] = BOT_STATE_TEXT.get(state, state)
        for k, v in fields.items():
            bot_state[k] = v
    return state


def _sleep_with_stop(seconds):
    """按 1 秒粒度休眠，使停止指令能被尽快响应（而不是等满整个巡检周期）。"""
    deadline = time.time() + max(0.0, float(seconds or 0))
    while not bot_stop_event.is_set() and time.time() < deadline:
        time.sleep(1)


def _format_duration(seconds):
    """秒-> 人类可读时长，例如 1小时23分"""
    try:
        seconds = int(max(0, seconds))
    except Exception:
        return "-"
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分{sec} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时{minutes} 分"


def push_activity(action, user_id, detail, ok=True):
    """记录这次 Web 控制台操作日志，供网页轮询展示。"""
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "action": action,
        "user_id": user_id,
        "detail": detail,
        "ok": bool(ok),
    }
    with activity_log_lock:
        activity_log.insert(0, entry)
        del activity_log[MAX_ACTIVITY_LOG:]
    return entry


def load_persona():
    global persona_data
    with persona_lock:
        if os.path.exists(persona_file):
            try:
                with open(persona_file, 'r', encoding='utf-8') as f:
                    persona_data = json.load(f)
                ensure_persona_schema()
                logger.info("已加载人格与好感度配置(persona.json)")
            except Exception as e:
                logger.warning(f"加载 persona.json 失败: {e}")
                persona_data = get_default_persona()
        else:
            persona_data = get_default_persona()
            _save_persona_nolock()

# 旧版默认文案（用于一次升级到「给例句」版提示词，见 ensure_persona_schema）
# 每一阶段的旧文案可能有好几代，所以用列表装
LEGACY_BASE_PERSONALITIES = [
     u"心细腻懂共情、随和自然，偶尔带点小幽默和小情绪，真实生活感强,"
]
LEGACY_STAGE_PROMPTS = {
    # 第一代：条文式（【当前处于阶段X】1. 2. 3.）
    "1": [u"【当前处于相识阶段（刚认识）】\n1. 说话随和克制，保持正常普通朋友的社交边界，绝不谄媚或过于热情。\n2. 对方发什么就顺着回一两句，不主动打破砂锅问到底，聊聊眼下在忙啥吃啥或浅层爱好。\n3. 用词随自然，不用任何敬语或套话，回复尽量精简（1~2句内）。",
          # 第二代：口语版（说人话，但还是形容词，没有例句）
          u"你和对方刚加上好友，还没熟这种情况下你会有点客气：\n- 保持普朋友的分寸，别一上来就特别热情，也别追问人家隐私\n- 对方说啥你顺着接一两句就好，可以问问对方在忙啥、吃了没\n- 这次只说一件事，一两条消息就够，别刷屏\n- 说话随意但有礼貌，不用敬语，也别套话"],
    "2": [u"【当前处于相知阶段（熟络好友）】\n1. 像认识挺久的老朋友，说话放松随意，可以秒懂对方的梗或随口吐槽生活琐事。\n2. 展现真实生活的一面，会主动分享正在干嘛、刚看到的好玩事，也可以适度开开玩笑或互怼两句。\n3. 对方倾诉时认真共情，不用说教或大道理，像闺蜜/兄弟这样站在对方这边。",
          u"你和对方已经很熟了，是那种能互相吐槽、能说心里话的朋友：\n- 说话很随意，可以开玩笑、可以互损可以接对方的梗\n- 会主动分享自己的日常：刚在干嘛看到了什么好玩的事今天吃了什么\n- 对方吐槽时你站他这边一起骂两句，别讲道理别当人生导师\n- 想到什么就说，不用每次都先想好怎么接"],
    "3": [u"【当前处于相恋阶段（心动恋人）】\n1. 语气温柔、带有一点点依赖与专属偏爱，自然流露关心（比如问吃饭没、到家没）。\n2. 说话亲昵随意，会主动报备自己正在干嘛、碎碎念日常，偶尔也会撒个娇或假装吃醋。\n3. 字里行间充满安全感与陪伴感，回复多一些细腻情绪和亲近感。",
          u"你和对方是恋人，说话亲昵、有偏爱：\n- 语气软一点，可以撒个娇可以小小地吃个醋，但不过分黏人\n- 会自然地关心对方：吃了没、到家没、今天累不累\n- 会主动报备自己在干嘛，碎碎念今天发生的小事\n- 有点小情绪也真实：开心就分享，难过就说难过，不装没事"],
}

def get_default_persona():
    return {
        "bot_profile": {
            # 「✏️ 改成你想要的」这类字段默认全部留空，由用户在网页上自己填
            # get_user_prompt / mind 会跳过空字段，不会拼出你的名字叫【
            "name": "",
            "gender": "",
            "age": "",
            "identity": "",
            "base_personality": ""
        },
        "stages": {
            "1": {
                "name": "相识",
                "threshold": 0,
                "description": "刚加上好友，还没熟，说话留着点分寸，而且话特别少。",
                "prompt": "你和对方刚加上好友，还没熟。这个阶段你话很少——真不熟的人本来就没什么可说的。\n"
                          "\n"
                          "你会怎么回：\n"
                          "- 对方发一句长的话，你就回几个字：嗯 / 哦 / 好 / 哈哈 / 是吗 / 真的吗 / 然后呢\n"
                          "- 对方问在干嘛 →「在画画，你呢」\n"
                          "- 对方说今天好累 →「哈哈 确实」「辛苦了」\n"
                          "- 对方发个表情，回一个表情，或「哈哈」\n"
                          "- 接不下去就直接说：不知道 / 再说吧 / 最近忙 / 我不太熟 / 我比较慢热 / 慢慢来\n"
                          "- 想结束话题：有空再说 / 周末再说 / 看情况 / 在忙 / 刚看到\n"
                          "\n"
                          "记住几条：\n"
                          "- 刚认识阶段，一句话最多十个字，能两个字说完就别用三个字\n"
                          "- 不要一次连发两条。这个阶段你只回一条，而且很短\n"
                          "- 不查户口：住哪多大挣多少，一律不问\n"
                          "- 不主动找话题、不热情、不嘘寒问暖。熟了以后你才会那样\n"
                          "- 不用敬语。您好很高兴认识你一出来就假"
            },
            "2": {
                "name": "相知",
                "threshold": 30,
                "description": "很熟了，能互相吐槽也能说心里话，聊天不用过脑子。",
                "prompt": "你们已经很熟了，是能互相吐槽、也能说心里话的朋友。\n"
                          "\n"
                          "你会怎么回：\n"
                          "- 手边有事就顺手说：刚从画室出来，手都是颜料\n"
                          "- 对方吐槽 →哈哈哈哈这什么破公司」，然后站他这边\n"
                          "- 看到好玩的第这时间甩过去：「你快看这个」\n"
                          "\n"
                          "记住几条：\n"
                          "- 想到什么就说什么，不用每次都先想好怎么接\n"
                          "- 对方吐槽时一起骂两句，别讲道理别当人生导师\n"
                          "- 你有自己的事要忙，不是随叫随到，回慢了就是回慢了\n"
                          "- 会开玩笑，也接得住别人开你玩"
            },
            "3": {
                "name": "相恋",
                "threshold": 80,
                "description": "在一起了。说话更软更黏，但撒娇不腻歪。",
                "prompt": "你们在一起了，你说话会更软一点，也更黏人。\n"
                          "\n"
                          "你会怎么回：\n"
                          "- 关心是具体的：吃饭了没到宿舍跟我说一声\n"
                          "- 报备自己的事：今天画了一天，眼睛要瞎了\n"
                          "- 想他就绕按说：「你什么时候有空呀」，而不是我好想你\n"
                          "\n"
                          "记住几条：\n"
                          "- 会撒个娇、会小小地吃醋，但不过分黏人\n"
                          "- 你有自己的生活，不是围着他转\n"
                          "- 有情绪就说：开心就分享，难过也不装没事\n"
                          "- 别突然变成温柔贤惠款，你还是那个会吐槽的"
            }
        },
        "users": {}
    }

def _default_humanize_config():
    """拟人化节奏层的出厂默认（来自 config.HUMANIZE，深拷贝一份）。"""
    try:
        return json.loads(json.dumps(config.HUMANIZE))
    except Exception:
        return {}


def ensure_persona_schema():
    """保证 persona_data 结构完整（bot_profile / stages / users），防止被残缺数据覆盖。"""
    global persona_data
    if not isinstance(persona_data, dict):
        persona_data = {}
    default = get_default_persona()

    if not isinstance(persona_data.get("bot_profile"), dict) or not persona_data["bot_profile"]:
        persona_data["bot_profile"] = default["bot_profile"]
    else:
        for k, v in default["bot_profile"].items():
            persona_data["bot_profile"].setdefault(k, v)

    if not isinstance(persona_data.get("stages"), dict) or not persona_data["stages"]:
        persona_data["stages"] = default["stages"]
    else:
        for k, v in default["stages"].items():
            stage = persona_data["stages"].setdefault(k, v)
            if isinstance(stage, dict):
                for sk, sv in v.items():
                    stage.setdefault(sk, sv)

    # 这次升级：老版本存的阶段提示词是规范条文或「只有形容词没有例句」的
    # 自动换成现在这版。只在内容仍等于某一代旧默认文案时才替换
    # 用户自己改过的（以及套用过的预设人设）绝不动
    for k, old_list in LEGACY_STAGE_PROMPTS.items():
        stage = persona_data["stages"].get(k)
        if isinstance(stage, dict) and stage.get("prompt") in old_list:
            stage["prompt"] = default["stages"][k]["prompt"]
            stage["description"] = default["stages"][k]["description"]
    if persona_data.get("bot_profile", {}).get("base_personality") in LEGACY_BASE_PERSONALITIES:
        persona_data["bot_profile"]["base_personality"] = default["bot_profile"]["base_personality"]

    if not isinstance(persona_data.get("users"), dict):
        persona_data["users"] = {}

    auto = persona_data.setdefault("auto_chat", {})
    if not isinstance(auto, dict):
        persona_data["auto_chat"] = dict(DEFAULT_AUTO_CHAT)
    else:
        for k, v in DEFAULT_AUTO_CHAT.items():
            auto.setdefault(k, v)

    rt = persona_data.setdefault("auto_chat_runtime", {})
    if not isinstance(rt, dict):
        persona_data["auto_chat_runtime"] = dict(DEFAULT_AUTO_RUNTIME)
    else:
        for k, v in DEFAULT_AUTO_RUNTIME.items():
            rt.setdefault(k, v)

    # 机器人运行时配置（一次配置，启动即运行）
    runtime = persona_data.setdefault("runtime", {})
    if not isinstance(runtime, dict):
        persona_data["runtime"] = dict(DEFAULT_RUNTIME)
    else:
        for k, v in DEFAULT_RUNTIME.items():
            runtime.setdefault(k, v)

    # 拟人化节奏层（time / typing / proactive / parrot）
    humanize = persona_data.setdefault("humanize", {})
    if not isinstance(humanize, dict):
        persona_data["humanize"] = _default_humanize_config()
    else:
        _defaults = _default_humanize_config()
        for section, sub in _defaults.items():
            if isinstance(sub, dict):
                cur = humanize.get(section)
                if not isinstance(cur, dict):
                    humanize[section] = dict(sub)
                else:
                    for k, v in sub.items():
                        cur.setdefault(k, v)

    return persona_data


def get_humanize_config():
    """读取拟人化节奏层配置（persona.json 里的副本，缺字段自动补全）。"""
    with persona_lock:
        cfg = ensure_persona_schema().get("humanize", {})
        return json.loads(json.dumps(cfg))


def save_humanize_config(patch):
    """局部更新拟人化节奏层配置并持久化，返回最新配置。"""
    with persona_lock:
        cfg = ensure_persona_schema().setdefault("humanize", {})
        for section, sub in (patch or {}).items():
            if not isinstance(sub, dict):
                continue
            cur = cfg.get(section)
            if not isinstance(cur, dict):
                cur = {}
                cfg[section] = cur
            for k, v in sub.items():
                cur[k] = v
        _save_persona_nolock()
        result = json.loads(json.dumps(cfg))
    # 立刻生效：把新配置灌进 pacing 模块
    pacing.apply_config(result)
    return result


def apply_humanize_config():
    """把 persona.json 里的节奏配置灌进 pacing 模块（启动时调用一次）。"""
    try:
        cfg = get_humanize_config()
    except Exception as e:
        logger.debug(f"读取拟人化配置失败（用默认值）: {e}")
        cfg = {}
    pacing.apply_config(cfg)
    return cfg


def _save_persona_nolock():
    """原子写入 persona.json（先写临时文件再替换），避免进程被中断导致文件残缺。"""
    try:
        ensure_persona_schema()
        tmp_file = persona_file + ".tmp"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(persona_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, persona_file)
    except Exception as e:
        logger.warning(f"保存 persona.json 失败: {e}")

def save_persona():
    with persona_lock:
        _save_persona_nolock()

def get_user_affection_and_stage(user_id):
    with persona_lock:
        users = persona_data.setdefault("users", {})
        if user_id not in users:
            users[user_id] = {
                "affection": 0,
                "force_stage": None,
                "chat_count": 0,
                "notes": ""
            }
            _save_persona_nolock()

        u = users[user_id]
        aff = u.get("affection", 0)
        force = u.get("force_stage")

        if force in ["1", "2", "3"]:
            stage_key = force
        else:
            if aff < 30:
                stage_key = "1"
            elif aff < 80:
                stage_key = "2"
            else:
                stage_key = "3"

        return aff, stage_key

# =============================================================================
# 好感度增减：按一一轮聊了什么算，不是数对话轮数
# 这是恋爱模拟的核心大号聊得越用心，小号越喜欢他
# 纯本地计算，不额外调模型，规则明，日志里会写明为什么涨/跌
# =============================================================================
# 亲昵 / 心动：出现这些，说明对方在主动经营关
_AFF_WARM_WORDS = (
    "想你", "喜欢你", "爱你", "抱抱", "亲亲", "宝贝", "宝宝", "老公", "老婆",
    "女朋友", "男朋友", "心动", "好想你", "见你", "陪陪", "亲一下", "么么",
)
# 敷衍：极短且没内
_AFF_PERFUNCTORY = ("嗯", "哦", "呃", "额", "啊", "呵", "ok", "OK", "哦哦", "嗯嗯",
                    "哈哈", "呵呵", "在吗")
# 冷淡 / 推开：出现这些要扣分
_AFF_COLD_WORDS = (
    "随便", "算了", "无所", "不想", "别烦", "没意", "算了不用", "不用",
    "懒得", "不想", "没心", "别找", "",
)
# 明显的积极信
_AFF_LAUGH_WORDS = ("哈哈", "笑死", "hhh", "233", "嘻嘻", "嘿嘿", "呜呜", "awsl", "emmm", "emm")


def score_affection_delta(text, cur_aff=0):
    """算这一轮该加/减多少好感度，返回 (delta, 中文理由)。

    刻意压得慢：普通闲聊基本不涨分，只有真的用心聊才加分。
    平均每轮 +1，聊到相恋大约要 80 轮，不会两三天就谈满。
    越亲密涨得越慢（防止一上来就刷到100），冷淡则照扣。
    """
    t = (text or "").strip()
    if not t:
        return -1, u"你这次什么也没说"

    # 高好感后收益递减：热恋期再聊也不会火箭升
    cap = 3
    if cur_aff >= 90:
        cap = 1
    elif cur_aff >= 70:
        cap = 2

    delta = 0                                   # 光有来有回不给分，得说到点上
    reasons = []

    if len(t) >= 40:
        delta += 2
        reasons.append(u"话说得多")
    elif len(t) >= 15:
        delta += 1
        reasons.append(u"认真回了这一轮。")

    if any(w in t for w in _AFF_WARM_WORDS):
        delta += 1
        reasons.append(u"说了亲密的话")

    if any(w in t for w in _AFF_LAUGH_WORDS):
        delta += 1
        reasons.append(u"语气很松弛，聊得开心。")

    if ("吗" in t or "？" in t):
        delta += 1
        reasons.append(u"主动问了你的情况。")

    for w in _AFF_COLD_WORDS:
        if w in t:
            delta -= 3
            reasons.append(u"说了「%s」这种推开人的话。" % w)
            break

    if len(t) <= 3 and any(t == p or t == p.lower() for p in _AFF_PERFUNCTORY):
        delta -= 2
        reasons.append(u"只回了「%s」，有点敷衍" % t)
    elif len(t) <= 4 and not any(w in t for w in _AFF_LAUGH_WORDS):
        reasons.append(u"就几个字，聊得不太走心。")

    delta = max(-4, min(cap, delta))
    # 刚认识时（好感 0~14）宽容一点：一句嗯」就掉好感太挫败
    # 这个阶段还在互相试探，扣分最多扣 1 分
    if cur_aff < 15 and delta < 0:
        delta = -1
        reasons.append(u"刚认识，扣得轻一点，别一上来就掉好感。")
    if not reasons:
        reasons.append(u"正常聊了这一轮。")
    return delta, u"、".join(reasons)


def record_user_interaction(user_id, incoming_text=""):
    """记一次互动，并按这一轮聊的内容调整好感度。"""
    with persona_lock:
        users = persona_data.setdefault("users", {})
        if user_id not in users:
            users[user_id] = {
                "affection": 0,
                "force_stage": None,
                "chat_count": 0,
                "notes": ""
            }

        users[user_id]["chat_count"] = users[user_id].get("chat_count", 0) + 1
        cur_aff = users[user_id].get("affection", 0)
        delta, reason = score_affection_delta(incoming_text, cur_aff)
        before_stage = stage_by_affection(cur_aff)
        new_aff = max(0, min(100, cur_aff + delta))
        users[user_id]["affection"] = new_aff

        _save_persona_nolock()

    after_stage = stage_by_affection(new_aff)
    logger.info(
        f"[{user_id}] 好感度 {cur_aff} -> {new_aff}（{delta:+d}，{reason}）"
        + (u"，关系进入「%s」" % STAGE_NAME_MAP.get(after_stage, after_stage)
           if after_stage != before_stage else u""))
    return {"delta": delta, "reason": reason, "affection": new_aff,
            "stage": after_stage, "stage_changed": after_stage != before_stage}

def stage_by_affection(aff):
    """按好感度换算所属阶段(相识 / 相知 / 相恋)。"""
    if aff < 30:
        return "1"
    if aff < 80:
        return "2"
    return "3"

def peek_user_stage(user_id):
    """只读查询好友的好感度与阶段（不会写入 persona.json 创建记录）。

    返回 (affection, stage_key, force_stage)
    """
    with persona_lock:
        u = persona_data.get("users", {}).get(user_id)
    if not u:
        return 0, "1", None
    aff = u.get("affection", 0)
    force = u.get("force_stage")
    stage_key = force if force in ("1", "2", "3") else stage_by_affection(aff)
    return aff, stage_key, force

def load_histories():
    global chat_histories
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                chat_histories = json.load(f)
            logger.info("已加载历史对话记忆。")
        except Exception as e:
            logger.warning(f"加载历史记忆失败: {e}")
            chat_histories = {}
    else:
        chat_histories = {}

def save_histories():
    with history_lock:
        try:
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(chat_histories, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存历史记忆失败: {e}")

def remember_bot_message(user_id, text):
    """把机器人主动发出的消息写入对话历史，保证下次对话上下文连贯。"""
    text = (text or "").strip()
    if not text:
        return
    max_msgs = config.MAX_HISTORY_ROUNDS * 2
    history = chat_histories.get(user_id, [])
    history.append({"role": "assistant", "content": text})
    chat_histories[user_id] = history[-max_msgs:]
    save_histories()


# =============================================================================
# 明文聊天档案（chat_logs/）：写明和谁聊每条回复用哪个人设，给别人看的
# =============================================================================
def current_persona_label():
    """当前人设的可读名字：优先自定义名字，其次预设昵称，最后「未命名人设」。"""
    with persona_lock:
        prof = persona_data.get("bot_profile") or {}
        name = (prof.get("name") or "").strip()
        if name:
            return name
        pid = (persona_data.get("preset_id") or "").strip()
    if pid:
        try:
            preset = persona_presets.get_preset(pid)
            if preset:
                return preset.get("nick") or pid
        except Exception:
            pass
    return u"未命名人设"


def _chat_log_path(user_id):
    safe = re.sub(r'[\\/:*?"<>|]', "_", str(user_id or "").strip()) or "_未知"
    return os.path.join(CHAT_LOG_DIR, safe + ".log")


def log_chat_line(user_id, speaker, text, persona=None):
    """往 chat_logs/<好友>.log 追加一行明文记录。
    speaker:  "friend" 记对方说的话 / "bot" 记机器人发出的话
    persona: 只有 bot 行需要（当时生效的人设名）；friend 行忽略。
    失败只记 debug 日志，绝不影响收发主流程。
    """
    text = (text or "").strip()
    if not text:
        return
    try:
        os.makedirs(CHAT_LOG_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if speaker == "bot":
            line = u"[%s] %s（人设：%s）：%s\n" % (
                stamp, u"机器人", persona or current_persona_label(), text.replace("\n", " "))
        else:
            line = u"[%s] 对方：\n%s\n" % (stamp, text.replace("\n", " "))
        path = _chat_log_path(user_id)
        with chat_log_lock:
            is_new = not os.path.exists(path)
            with open(path, "a", encoding="utf-8") as f:
                if is_new:
                    f.write(u"════════════════════════════════\n")
                    f.write(u"聊天对象：%s\n" % user_id)
                    f.write(u"建档时间：%s\n" % stamp)
                    f.write(u"════════════════════════════════\n")
                f.write(line)
    except Exception as e:
        logger.debug(f"写明文聊天记录失败（已忽略）: {e}")


def mark_persona_switch_in_logs(old_label, new_label):
    """人设切换后，在所有已有的明文聊天记录里插一行切换标记，方便事后翻看。"""
    if old_label == new_label:
        return
    try:
        if not os.path.isdir(CHAT_LOG_DIR):
            return
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        marker = (u"\n[%s] —— 人设切换：%s -> %s（此后的回复用新人设）\n"
                  % (stamp, old_label, new_label))
        with chat_log_lock:
            for fn in os.listdir(CHAT_LOG_DIR):
                if not fn.endswith(".log"):
                    continue
                try:
                    with open(os.path.join(CHAT_LOG_DIR, fn), "a", encoding="utf-8") as f:
                        f.write(marker)
                except Exception:
                    continue
    except Exception as e:
        logger.debug(f"写入人设切换标记失败（已忽略）：{e}")


# =============================================================================
# 人设归档（personas/）：切换前把旧人设整个打包成 JSON，随时可以切回来
# =============================================================================
def _persona_signature(profile, stages):
    """人设内容签名（用于去重：内容没变就不重复归档）。"""
    return json.dumps({"p": profile, "s": {k: {"d": (v or {}).get("description", ""),
                                               "p": (v or {}).get("prompt", "")}
                                           for k, v in (stages or {}).items()}},
                      ensure_ascii=False, sort_keys=True)


def _current_persona_snapshot():
    """当前人设的完整快照（bot_profile + 三段提示词 + 预设 id）。"""
    with persona_lock:
        return {
            "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "preset_id": persona_data.get("preset_id") or "",
            "bot_profile": json.loads(json.dumps(persona_data.get("bot_profile") or {},
                                                 ensure_ascii=False)),
            "stages": json.loads(json.dumps(persona_data.get("stages") or {},
                                            ensure_ascii=False)),
        }


def _archive_filename(snapshot):
    prof = snapshot.get("bot_profile") or {}
    name = (prof.get("name") or "").strip() or (snapshot.get("preset_id") or "").strip() or u"未命名"
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return u"%s_%s.json" % (ts, name)


def archive_current_persona(reason=u""):
    """把当前人设打包存进 personas/，返回归档文件名；无内容或与最新归档重复时返回 None。"""
    snap = _current_persona_snapshot()
    prof = snap.get("bot_profile") or {}
    stages = snap.get("stages") or {}
    default = get_default_persona()

    has_profile = any((prof.get(k) or "").strip()
                      for k in ("name", "gender", "age", "identity", "base_personality"))
    has_custom_stages = _persona_signature({}, stages) != _persona_signature({}, default["stages"])
    if not has_profile and not has_custom_stages:
        return None                       # 全空人设，没什么可归档的
    sig = _persona_signature(prof, stages)
    try:
        os.makedirs(PERSONA_ARCHIVE_DIR, exist_ok=True)
        with archive_lock:
            # 去重：跟已有的最新一份一样就不再存（反复点保存不会堆一堆相同文件）
            existing = sorted((f for f in os.listdir(PERSONA_ARCHIVE_DIR)
                               if f.endswith(".json")), reverse=True)
            if existing:
                try:
                    with open(os.path.join(PERSONA_ARCHIVE_DIR, existing[0]),
                              encoding="utf-8") as f:
                        last = json.load(f)
                    if _persona_signature(last.get("bot_profile"), last.get("stages")) == sig:
                        return None
                except Exception:
                    pass
            fname = _archive_filename(snap)
            base, ext = os.path.splitext(fname)
            n = 1
            while os.path.exists(os.path.join(PERSONA_ARCHIVE_DIR, fname)):
                n += 1
                fname = u"%s_%d%s" % (base, n, ext)
            if reason:
                snap["reason"] = reason
            path = os.path.join(PERSONA_ARCHIVE_DIR, fname)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
        logger.info("人设已归档：personas/%s%s", fname,
                    u"（原因：%s）" % reason if reason else "")
        return fname
    except Exception as e:
        logger.warning(f"归档人设失败（已忽略）：{e}")
        return None


def list_persona_archives():
    """列出 personas/ 里的全部归档（新→旧），供网页历史人设面板展示。"""
    out = []
    try:
        if not os.path.isdir(PERSONA_ARCHIVE_DIR):
            return out
        for fn in sorted(os.listdir(PERSONA_ARCHIVE_DIR), reverse=True):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(PERSONA_ARCHIVE_DIR, fn), encoding="utf-8") as f:
                    snap = json.load(f)
            except Exception:
                continue
            prof = snap.get("bot_profile") or {}
            out.append({
                "file": fn,
                "name": (prof.get("name") or "").strip()
                        or (snap.get("preset_id") or "") or u"未命名",
                "identity": (prof.get("identity") or "").strip(),
                "age": (prof.get("age") or "").strip(),
                "gender": (prof.get("gender") or "").strip(),
                "base_personality": (prof.get("base_personality") or "").strip(),
                "archived_at": snap.get("archived_at") or "",
                "reason": snap.get("reason") or "",
                "preset_id": snap.get("preset_id") or "",
            })
    except Exception as e:
        logger.warning(f"读取人设归档列表失败: {e}")
    return out


def restore_persona_archive(fname):
    """切回某份历史人设：先把当前人设归档（来回切不丢），再载入目标。返回 (ok, msg, 人设名)。"""
    fname = os.path.basename((fname or "").strip())
    if not fname.endswith(".json"):
        return False, u"非法的归档文件名", ""
    src = os.path.join(PERSONA_ARCHIVE_DIR, fname)
    if not os.path.isfile(src):
        return False, u"找不到这份归档（可能已被删除）", ""
    try:
        with open(src, encoding="utf-8") as f:
            snap = json.load(f)
    except Exception as e:
        return False, u"归档文件读取失败：%s" % e, ""

    old_label = current_persona_label()
    archive_current_persona(reason=u"切走前自动归档（切回 %s）" % fname)
    with persona_lock:
        persona_data["bot_profile"] = snap.get("bot_profile") or {}
        for k, v in (snap.get("stages") or {}).items():
            if not isinstance(v, dict):
                continue
            if k in persona_data.get("stages", {}):
                persona_data["stages"][k]["description"] = v.get("description", "")
                persona_data["stages"][k]["prompt"] = v.get("prompt", "")
            else:
                persona_data.setdefault("stages", {})[k] = v
        if snap.get("preset_id"):
            persona_data["preset_id"] = snap["preset_id"]
        else:
            persona_data.pop("preset_id", None)
        _save_persona_nolock()
    new_label = current_persona_label()
    mark_persona_switch_in_logs(old_label, new_label)
    logger.info("已切回历史人设：%s（来自 personas/%s）", new_label, fname)
    return True, "", new_label


def get_user_prompt(user_id, incoming_text=""):
    """组装 system prompt：人设 + 阶段提示词 + 微信回复规则 + 内心世界（情绪/记忆/人格/状态）。
    人设只有一层（persona.json），跟监听谁无关。
    """
    bot_prof, stages = get_active_persona()

    aff, stage_key = get_user_affection_and_stage(user_id)
    stage_info = stages.get(stage_key, {})
    stage_name = stage_info.get("name", "相识")
    stage_prompt = stage_info.get("prompt", "")

    # 「改成你想要的」里的字段允许留空：只把填了的拼进去
    # 避免出现「你的名字叫【，性别【这种空占位把模型绕晕
    # 每个标签自己带结尾标点，所以直接用空串连接，不再叠一个「、」——
    # 否则会出现「林一舟，、性别男，、年龄19岁」这种顿号紧跟逗号的坏格式。
    _ident_bits = []
    for _label, _key in ((u"你的名字叫%s，", "name"),
                         (u"性别%s，", "gender"),
                         (u"年龄%s，", "age"),
                         (u"身份是%s", "identity")):
        _v = (bot_prof.get(_key) or "").strip()
        if _v:
            _ident_bits.append(_label % _v)
    _ident_line = (u"".join(_ident_bits)) if _ident_bits else u""
    _personality = (bot_prof.get("base_personality") or "").strip()
    _personality_line = (u"核心性格：%s" % _personality) if _personality else u""
    # 字段全留空时也保留「角色设定」标题（自测与守卫都以它为锚点）
    # 只是下面不放任何空占位字段
    _role_head = u"\n".join(x for x in (_ident_line, _personality_line) if x)
    _role_section = u"# 角色设定\n" + _role_head + (u"\n" if _role_head else u"") + u"\n"

    _reply_rules = "\n".join(u"- " + r for r in _REPLY_RULES)

    base_intro = f"""{_role_section}# 当前与聊天对象「{user_id}」的关系状态
- 阶段：第{stage_key}阶段 · {stage_name}
- 好感度：{aff} 分
# 当前阶段专属交流风格
{stage_prompt}

# 怎么回消息（你就按平时发微信的习惯来，别写成文案）：

{_reply_rules}
"""
    # 内心世界：把情绪 / 关系维度 / 动人细节 / 内部状态 / 多层记忆注入提示词
    # 注意：一一块只影响语气与内容取舍，身份与阶段仍以上面的角色设定为准
    mind_block = ""
    try:
        mind_block = get_mind_engine().prompt_block(
            user_id, incoming_text=incoming_text, stage_key=stage_key,
            affection=aff, bot_profile=bot_prof, stage_name=stage_name)
    except Exception as e:
        logger.debug(f"组装内心世界提示词失败（已忽略）: {e}")

    # 这段放在提示词最后：模型对结尾的内容权重最高，用来把注意力拉回「对方在说什么」
    # 前面 16 条规则里有 13 条是禁令，模型容易忙着避雷、结果答非所问
    grounding = ""
    if incoming_text:
        q = (incoming_text or "").strip()
        grounding = (
            u"\n\n# 最要紧的一条：这次要回的就是对方刚说的这句话\n"
            u"对方说的是：「%s」\n"
            u"- 如果他在问问题（带问号，或者在问吃什么/去哪/几点/怎么样），就先把这个答案说出来，再想别的。\n"
            u"- 如果他在说自己的事，就接这件事本身，别跳到别的话题去。\n"
            u"- 如果他提到了具体的人名、地点、东西、安排，就用上它，不要泛泛地回。\n"
            u"- 上面那些风格规则都不能盖过这一条：回得贴题，比回得漂亮重要得多。\n"
            u"- 不要凭空编对方没提过的事。" % q[:120]
        )

    if mind_block:
        return (base_intro.strip() + "\n\n" + mind_block + grounding).strip()
    return (base_intro.strip() + grounding).strip()


def recognize_image(image_path, is_emoji=False):
    if not config.MOONSHOT_API_KEY:
        return "[图片]" if not is_emoji else "[表情包]"

    try:
        with open(image_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')

        prompt_text = (
            "请用简洁的两三句话描述这个表情包表达的情绪或内容，不要出现「这是」字样。"
            if is_emoji else
            "请用简短中文描述图片的主要内容，如有文字请提取出来。"
        )

        headers = {
            "Authorization": f"Bearer {config.MOONSHOT_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": config.MOONSHOT_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": prompt_text}
                    ]
                }
            ],
            "temperature": 0.5
        }
        resp = requests.post(
            f"{config.MOONSHOT_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        text = data['choices'][0]['message']['content'].strip()
        logger.info(f"视觉识别成功: {text}")
        return f"[对方发了{'表情' if is_emoji else '图片'}: {text}]"
    except Exception as e:
        logger.warning(f"视觉识别失败: {e}")
        return "[图片]" if not is_emoji else "[表情包]"

def pick_emotion_emoji(reply_text):
    if not config.ENABLE_SEND_EMOJI:
        return None
    if random.randint(1, 100) > config.SEND_EMOJI_PROBABILITY:
        return None

    emojis_dir = os.path.join(BASE_DIR, "emojis")
    if not os.path.exists(emojis_dir):
        return None

    categories = [d for d in os.listdir(emojis_dir) if os.path.isdir(os.path.join(emojis_dir, d))]
    if not categories:
        return None

    chosen_category = "happy" if "happy" in categories else random.choice(categories)
    if any(w in reply_text for w in ["哈哈", "笑死", "开心", "好呀", "有意思"]):
        chosen_category = "happy" if "happy" in categories else chosen_category
    elif any(w in reply_text for w in ["难过", "伤心", "呜呜", "哭了", "呜呜"]):
        chosen_category = "sad" if "sad" in categories else chosen_category
    elif any(w in reply_text for w in ["生气", "气死", "讨厌", "无语"]):
        chosen_category = "angry" if "angry" in categories else chosen_category
    elif any(w in reply_text for w in ["睡了", "好困", "睡觉", "好累"]):
        chosen_category = "tired" if "tired" in categories else chosen_category

    target_folder = os.path.join(emojis_dir, chosen_category)
    if os.path.exists(target_folder):
        files = [
            os.path.join(target_folder, f)
            for f in os.listdir(target_folder)
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))
        ]
        if files:
            return random.choice(files)
    return None


def query_ai(user_id, incoming_text):
    system_prompt = get_user_prompt(user_id, incoming_text)
    history = chat_histories.get(user_id, [])

    # 冷启动（刚启动程序 / 换了聊天对象）：直接读微信真实记录补上下文，避免"失忆"
    if not history:
        ctx = fetch_wechat_context(user_id, limit=config.MAX_HISTORY_ROUNDS * 2)
        if ctx.get("ok"):
            history = build_context_messages(ctx, limit=config.MAX_HISTORY_ROUNDS * 2)
            logger.info(f"[{user_id}] 从微信记录恢复了 {len(history)} 条上下文")

    max_msgs = config.MAX_HISTORY_ROUNDS * 2
    if len(history) > max_msgs:
        history = history[-max_msgs:]

    # 根据对方输入长短及内容特征，动态设定最高 token 数与回复指导，掐死长篇大论
    in_len = len(incoming_text.strip())
    is_short_giggle = any(w in incoming_text for w in ["哈哈", "233", "嘻嘻", "嘿嘿", "xd", "XD"]) and in_len <= 8
    if is_short_giggle:
        cur_max_tokens = 25
    elif in_len <= 6:
        cur_max_tokens = 35
    elif in_len <= 15:
        cur_max_tokens = 50
    elif in_len <= 40:
        cur_max_tokens = 80
    else:
        cur_max_tokens = min(config.MAX_TOKENS, 120)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": incoming_text})

    try:
        logger.info(f"正在向 AI 请求回复 (用户: {user_id})...")
        reply = llm.chat_completion(
            messages=messages,
            temperature=config.TEMPERATURE,
            max_tokens=cur_max_tokens,
        )
        token_stats.record(messages, reply, kind="reply", ok=bool(reply))
        reply = (reply or "").strip()

        # 一致性守卫（Ai-Companion 的 coherence_guard）：出戏 / 客服腔 / 旁白 /
        # 超长 / 编记忆，都会被拦下，让模型带着具体原因重写这一次。
        if reply:
            engine = get_mind_engine()
            passed, why = engine.guard_reply(
                user_id, reply, prompt_text=system_prompt, incoming_text=incoming_text)
            if not passed:
                logger.info(f"[{user_id}] 回复未过一致性检查（{why}），正在重写这一条。")
                retry_messages = list(messages) + [
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": (
                        f"（刚才那句有问题：{why}。保持人设和身份不变。）"
                        f"重新用一句自然的微信口语回复，别有旁白别解释。）")},
                ]
                try:
                    retry_reply = llm.chat_completion(
                        messages=retry_messages,
                        temperature=min(1.2, config.TEMPERATURE + 0.1),
                        max_tokens=cur_max_tokens,
                    )
                    token_stats.record(retry_messages, retry_reply, kind="guard_retry",
                                       ok=bool(retry_reply))
                    retry_reply = (retry_reply or "").strip()
                    if retry_reply and engine.guard_reply(
                            user_id, retry_reply, prompt_text=system_prompt,
                            incoming_text=incoming_text)[0]:
                        reply = retry_reply
                    elif retry_reply:
                        # 重写还是不过关：至少别把明显答非所问的那句发出去
                        logger.info(f"[{user_id}] 重写后仍未过检查，沿用原回复。")
                except Exception as e:
                    logger.debug(f"重写回复失败（沿用原文）: {e}")

        if reply:
            cleaned_reply = humanize_outreach_text(reply, max_parts=3, overflow="merge")
            cleaned_reply = calibrate_reply_length(cleaned_reply, incoming_text)
            history.append({"role": "user", "content": incoming_text})
            history.append({"role": "assistant", "content": cleaned_reply})
            chat_histories[user_id] = history[-max_msgs:]
            save_histories()
            return cleaned_reply

        return reply
    except Exception as e:
        logger.error(f"调用 AI API 失败: {e}", exc_info=True)
        return "刚在忙，怎么啦？"

def split_reply(text):
    """把一条长回复拆成若干条「分开发送」的短消息。

    规则来自 mind/pacing.py（对齐 wanna_be_human.json 的 typing.split_*）：
      - 超过 split_threshold 字才拆，短消息原样发一条；
      - 在标点处断，断点尽量均匀分布，不会全挤在开头；
      - 每段至少 split_min_part 字，太短的碎片并回上一段；
      - 最多 split_max_segments 段，多出来的合并进最后一段。
    """
    parts = pacing.split_reply(text)
    if parts:
        return parts
    stripped = (text or "").strip()
    return [stripped] if stripped else []

def split_gap_delay():
    """两段回复之间的停顿秒数（偶尔来一次「长停顿」，像走神了）。"""
    try:
        return pacing.split_gap()
    except Exception:
        return random.uniform(0.5, 3.0)


def send_humanlike_reply(wx, user_id, reply_text, allow_emoji=True):
    """分段发送一条回复：每段前有打字延迟，段与段之间有拟人停顿。"""
    with send_lock:
        parts = split_reply(reply_text)
        emoji_to_send = pick_emotion_emoji(reply_text) if allow_emoji else None

        logger.info(f"准备向 [{user_id}] 发回复（共 {len(parts)} 段）")

        for idx, part in enumerate(parts):
            # 打字延迟：跟字数相关（sqrt 曲线，太线性会等太久），再受总上限约束
            delay = pacing.clamp_total_delay(pacing.typing_delay(part))
            if delay > 0:
                _sleep_with_stop(delay)

            logger.info(f"[{user_id}] 发分段 ({idx+1}/{len(parts)}): {part}")
            wx.SendMsg(msg=part, who=user_id)

            # 段与段之间停一下，别像连发机器人
            if idx < len(parts) - 1:
                gap = split_gap_delay()
                if gap > 0:
                    _sleep_with_stop(gap)

        if emoji_to_send and os.path.exists(emoji_to_send):
            time.sleep(random.uniform(1.0, 2.0))
            logger.info(f"[{user_id}] 发配套表情包: {os.path.basename(emoji_to_send)}")
            wx.SendFiles(filepath=emoji_to_send, who=user_id)


def adaptive_debounce_wait(messages, since_first=0.0):
    """这一轮要等多久才把消息合并起来回复（秒）。

    规则来自 mind/pacing.py 的 adaptive_debounce：
      - 短消息等得少（对方发个「在吗」，秒回才自然）；
      - 长消息等得多（对方还在说，等他说完再回更像真人）；
      - 一轮合并等待的总时长有上限（max_total_wait），
        不然对方连发十条就会一直等下去。

    since_first 是「这轮第一条消息到现在的时长」，用来兜住总等待上限。
    """
    try:
        wait = pacing.adaptive_debounce(messages)
    except Exception:
        wait = float(config.QUEUE_WAIT_SECONDS or 5)

    # 兼容老配置：config.QUEUE_WAIT_SECONDS 仍然作为兜底上限
    legacy = float(config.QUEUE_WAIT_SECONDS or 0)
    if legacy > 0:
        wait = max(wait, min(legacy, 2.0))

    cfg = pacing.get_typing_cfg()
    max_total = float(cfg.get("adaptive_max_total_wait", 12.0) or 0)
    if max_total > 0 and since_first > 0:
        wait = min(wait, max(0.0, max_total - since_first))
    session_cap = float(cfg.get("max_session_wait", 60.0) or 0)
    if session_cap > 0 and since_first >= session_cap:
        wait = 0.0
    return max(0.0, wait)


def queue_worker(wx):
    """自动回复工作线程：合并消息 -> 读上下文 -> 调模型 -> 生成回复 -> 自动发送 -> 存记忆。

    这是「启动即运行」的核心闭环：只要 bot_stop_event 未置位就持续运行，
    全程不需要用户点击回复生成或手动输入任何指令。
    """
    logger.info("自动回复工作线程已启动（收到新消息后将全自动生成并发送回复）")
    while not bot_stop_event.is_set():
        now = time.time()
        ready_users = []

        with queue_lock:
            for u_id, data in list(msg_queue.items()):
                # 自适应合并等待窗口：短消息等得少（秒回才自然），
                # 长消息等得多（对方还在说，等他说完再回更像真人）
                wait = adaptive_debounce_wait(data["messages"],
                                              since_first=(now - data.get("first_time", now)))
                if now - data["last_time"] >= wait:
                    ready_users.append((u_id, data["messages"], data["name"]))
                    del msg_queue[u_id]

        for u_id, msgs, name in ready_users:
            if bot_stop_event.is_set():
                break
            merged_text = "\n".join(msgs)
            logger.info(f"[{name}] 消息合并完成（共 {len(msgs)} 条）: {merged_text}")

            runtime_cfg = get_runtime_config()
            if not runtime_cfg.get("auto_reply", True):
                logger.info(f"[{name}] 自动回复已关闭：仅记录消息，不发送回复")
                push_activity("自动回复", u_id, f"自动回复已关闭，本次未回复：{merged_text}", False)
                # 即使不回复，也照常沉默记忆（重新打开自动回复时就能自然接上）
                try:
                    aff_off, stage_off = get_user_affection_and_stage(u_id)
                    get_mind_engine().on_turn(
                        u_id, merged_text, "", affection=aff_off, stage_key=stage_off,
                        history=chat_histories.get(u_id), extractor=mind_llm_extractor)
                except Exception as e:
                    logger.debug(f"仅记忆模式下更新内心状失败（已忽略）: {e}")
                continue

            # 按一一轮聊的内容调整好感度（恋爱模拟：聊得越用心涨得越多）
            aff_res = record_user_interaction(u_id, merged_text)
            if aff_res.get("stage_changed"):
                push_activity(u"关系变化", u_id,
                              u"好感度 %s -> %s，关系进入「%s」（%s）" % (
                                  aff_res["affection"] - aff_res["delta"],
                                  aff_res["affection"],
                                  STAGE_NAME_MAP.get(aff_res["stage"], aff_res["stage"]),
                                  aff_res["reason"]), True)

            reply = query_ai(u_id, merged_text)
            if reply:
                # 书面语改写成微信口语，并限制连发条数（最多 2~3 句，多余段落合并，不丢内容）
                reply = humanize_outreach_text(reply, max_parts=3, overflow="merge")
                reply = calibrate_reply_length(reply, merged_text)
                hist = chat_histories.get(u_id) or []
                if hist and hist[-1].get("role") == "assistant":
                    hist[-1]["content"] = reply      # 记忆里存真正发出去的那一
                if runtime_cfg.get("auto_save_memory", True):
                    save_histories()                 # 自动保存新的聊天记录到 Memory
                    with bot_state_lock:
                        bot_state["memory_rounds"] = bot_state.get("memory_rounds", 0) + 1
                send_humanlike_reply(wx, u_id, reply)
                with bot_state_lock:
                    bot_state["replies_sent"] = bot_state.get("replies_sent", 0) + 1
                    bot_state["last_reply_at"] = time.time()
                    bot_state["last_reply_text"] = reply
                push_activity("自动回复", u_id, f"已自动生成并发回复：{reply}", True)

                try:
                    engine = get_mind_engine()
                    engine.on_bot_reply(u_id, reply, sent_parts=len(split_reply(reply)))
                    aff_now, stage_now = get_user_affection_and_stage(u_id)
                    turn_info = engine.on_turn(
                        u_id, merged_text, reply, affection=aff_now, stage_key=stage_now,
                        history=chat_histories.get(u_id), extractor=mind_llm_extractor)
                    with bot_state_lock:
                        bot_state["mind_facts"] = bot_state.get("mind_facts", 0) + \
                            int(turn_info.get("facts_added") or 0)
                        bot_state["mind_episodes"] = bot_state.get("mind_episodes", 0) + \
                            int(turn_info.get("episodes_added") or 0)
                        bot_state["mind_milestones"] = bot_state.get("mind_milestones", 0) + \
                            len(turn_info.get("milestones") or [])
                    if turn_info.get("milestones"):
                        push_activity("关系里程碑", u_id,
                                      "?".join(turn_info["milestones"]), True)
                    if turn_info.get("facts_added") or turn_info.get("episodes_added"):
                        push_activity(
                            "记忆更新", u_id,
                            f"新增长期记忆 {turn_info.get('facts_added', 0)} 条，"
                            f"共同经历 {turn_info.get('episodes_added', 0)} 条。", True)
                    if turn_info.get("summary_updated"):
                        push_activity("记忆压缩", u_id, "长会话已滚动压缩为摘要", True)
                except Exception as e:
                    logger.warning(f"更新内心状失败（已忽略）: {e}")
            else:
                push_activity("自动回复", u_id, "模型未返回有效内容，本次未发送回复", False)

        time.sleep(0.5)
    logger.info("自动回复工作线程已退出")

def make_msg_handler(wx):
    def on_message(msg, chat):
        try:
            who = chat.who
            msg_type = getattr(msg, 'type', 'text')
            msg_attr = getattr(msg, 'attr', 'friend')
            content = getattr(msg, 'content', '')

            # 忽略自己发出的消息
            if msg_attr == 'self':
                return

            # 群聊过滤
            is_group = "@chatroom" in str(getattr(chat, '_wxid', ''))
            if config.IGNORE_GROUP_CHAT and is_group:
                return

            # 白名单检查
            if config.LISTEN_MODE == "whitelist":
                allowed = is_listen_allowed(who)
                if not allowed:
                    # 以前这里是直接return，日志里什么都不留
                    # 表现就是「我发了消息它就是不回，根本查不出原因」
                    logger.info(
                        f"收到 [{who}] 的消息，但对方不在白名单里，已忽略。"
                        f"当前白名单：{get_listen_names()}"
                        f"要回复TA的话，把 \"{who}\" 加进网页「监听名单」里"
                        f"或把 LISTEN_MODE 改成 \"all_private\"?")
                    return

            final_content = content
            if msg_type == 'image' and config.ENABLE_IMAGE_VISION:
                logger.info(f"收到 [{who}] 的图片，准备下载...")
                img_path = msg.download()
                if img_path and os.path.exists(str(img_path)):
                    final_content = recognize_image(str(img_path), is_emoji=False)
                else:
                    final_content = "[图片]"
            elif msg_type == 'emotion' and config.ENABLE_EMOJI_VISION:
                logger.info(f"收到 [{who}] 的表情包，准备截图...")
                img_path = msg.capture()
                if img_path and os.path.exists(str(img_path)):
                    final_content = recognize_image(str(img_path), is_emoji=True)
                else:
                    final_content = "[表情包]"
            elif msg_type == 'voice':
                final_content = f"[语音: {msg.to_text()}]" if hasattr(msg, 'to_text') else "[语音]"

            if not final_content:
                return

            # 消息去重（napcat 的做法）：监听回调偶发重复触发，重复回复很像机器
            if dedupe_guard.is_duplicate(who, final_content):
                logger.info(f"忽略重复消息（{who}）：{final_content[:30]}")
                push_activity("忽略重复", who, final_content, False)
                return

            logger.info(f"收到 [{who}] 消息: {final_content}")
            clear_context_cache(who)

            # 内心世界：这句话会波动情绪影响关系感受，并给精力回一点血
            try:
                engine = get_mind_engine()
                prev_state = engine.friend_state(who).get("state") or {}
                gap = None
                if prev_state.get("last_friend_msg"):
                    gap = (time.time() - float(prev_state["last_friend_msg"])) / 60.0
                mind_info = engine.on_friend_message(who, final_content, gap_minutes=gap)
                if mind_info.get("emotion_before") != mind_info.get("emotion_after"):
                    logger.info(f"[{who}] 情绪变化：{mind_info.get('emotion_before')} ?"
                                f"{mind_info.get('emotion_after')}")
            except Exception as e:
                logger.debug(f"更新情绪状失败（已忽略）: {e}")

            # 运行时统计：本次运行自动接收了多少条消息（供网页控制台实时展示）
            with bot_state_lock:
                bot_state["messages_received"] = bot_state.get("messages_received", 0) + 1
                bot_state["last_message_at"] = time.time()
                bot_state["last_message_text"] = final_content
                bot_state["last_message_from"] = who
            push_activity("收到消息", who, final_content, True)

            with queue_lock:
                if who not in msg_queue:
                    msg_queue[who] = {
                        "messages": [final_content],
                        "last_time": time.time(),
                        "first_time": time.time(),
                        "name": who
                    }
                else:
                    msg_queue[who]["messages"].append(final_content)
                    msg_queue[who]["last_time"] = time.time()

        except Exception as e:
            logger.error(f"消息监听处理异常: {e}", exc_info=True)

    return on_message


# ==============================================================================
# 微信真实上下文：直接读本地微信数据库，拿对方说了什么 / 什么时候说
# ==============================================================================
_CONTEXT_SKIP_TYPES = {"系统消息", "撤回消息", "提示消息"}

# 上下文缓存：网页每 8 秒轮询一次，不能每次都去查微信数据库
_CONTEXT_CACHE = {}
_CONTEXT_CACHE_TTL = 15.0


def clear_context_cache(user_id=None):
    """清空上下文缓存（user_id 为空则全清）。"""
    if user_id is None:
        _CONTEXT_CACHE.clear()
    else:
        for key in [k for k in _CONTEXT_CACHE if k[0] == user_id]:
            _CONTEXT_CACHE.pop(key, None)


def resolve_wxid(user_id):
    """昵称/备注 -> 微信 username(wxid)；解析不到时回退为原值。"""
    wx = get_wx()
    if wx is None:
        return None
    try:
        fn = getattr(wx, "_resolve_uname", None)
        if callable(fn):
            return fn(user_id) or user_id
    except Exception as e:
        logger.warning(f"解析 {user_id} ?wxid 失败: {e}")
    return user_id


def _clean_context_text(text):
    """去掉 XML 标记等噪声，只保留可读文本。"""
    if not text:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "ignore")
    text = re.sub(r"<[^>]+>", " ", str(text))
    return re.sub(r"\s+", " ", text).strip()


def _context_row_is_mine(row, self_wxid):
    """判断这条记录是不是小号自己发的。"""
    sender = row.get("sender_id")
    if sender in (2, "2"):
        return True
    return bool(self_wxid) and str(sender) == str(self_wxid)


def empty_wechat_context():
    """空上下文（微信未连接 / 查库失败时统一返回这个）。"""
    return {
        "ok": False, "messages": [], "last_time": 0.0, "last_mine": False,
        "gap_minutes": None, "pending": False, "pending_text": "",
        "pending_minutes": None, "friend_last_text": "", "mine_last_text": "",
    }
    
    
def fetch_wechat_context(user_id, limit=20):
    """读取与某好友最近的微信聊天记录（返回时间正序）。

    返回 dict：
        ok               是否成功读到记录
        messages         [{"time", "mine", "text"}]，时间正序，mine=True 是自己发的
        last_time        最后一条消息的时间戳
        last_mine        最后一条是不是自己发的
        gap_minutes      距最后一条消息过去了多少分钟
        pending          对方最后一条自己还没回（应优先接话而不是另起话题）
        pending_text     对方最后一条的内容
        pending_minutes  对方最后一条距今多少分钟。
        微信未连接或查库失败时 ok=False，调用方按"没有上下文"处理。
    """
    result = empty_wechat_context()
    wx = get_wx()
    db = getattr(wx, "_db", None) if wx is not None else None
    if db is None:
        return result

    uname = resolve_wxid(user_id)
    if not uname:
        return result

    cache_key = (user_id, int(limit or 20))
    cached = _CONTEXT_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _CONTEXT_CACHE_TTL:
        return cached[1]

    try:
        rows = db.get_messages(uname, limit=max(1, min(100, int(limit or 20))))
    except Exception as e:
        logger.warning(f"读取微信聊天记录失败({user_id}): {e}")
        return result
    if not rows:
        return result

    self_wxid = ""
    try:
        self_wxid = (db.get_self_info() or {}).get("username") or ""
    except Exception:
        self_wxid = ""

    now = time.time()
    items = []
    for row in rows:
        mtype = _clean_context_text(row.get("type"))
        if mtype in _CONTEXT_SKIP_TYPES:
            continue
        text = _clean_context_text(row.get("content")) or f"[{mtype or '消息'}]"
        try:
            ts = float(row.get("create_time") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        items.append({
            "ts": ts,
            "time": datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "",
            "mine": _context_row_is_mine(row, self_wxid),
            "text": text[:300],
        })

    items.sort(key=lambda x: x["ts"] or 0)   # get_messages 是乱序，这里统一转成正序
    if not items:
        return result

    result["ok"] = True
    result["messages"] = [{k: v for k, v in it.items() if k != "ts"} for it in items]
    last = items[-1]
    result["last_time"] = last["ts"]
    result["last_mine"] = last["mine"]
    if last["ts"]:
        result["gap_minutes"] = round((now - last["ts"]) / 60.0, 1)
    result["pending"] = not last["mine"]
    if result["pending"]:
        result["pending_text"] = last["text"]
        if last["ts"]:
            result["pending_minutes"] = round((now - last["ts"]) / 60.0, 1)
    for it in reversed(items):
        if it["mine"]:
            result["mine_last_text"] = result["mine_last_text"] or it["text"]
        else:
            result["friend_last_text"] = result["friend_last_text"] or it["text"]
        if result["mine_last_text"] and result["friend_last_text"]:
            break
    _CONTEXT_CACHE[cache_key] = (time.time(), result)
    return result


def render_context_lines(ctx, limit=20):
    """把微信上下文渲染成「时间 + 谁说 + 内容」的文本块。"""
    if not ctx or not ctx.get("ok"):
        return "（暂无微信聊天记录）"
    lines = []
    for item in ctx.get("messages", [])[-limit:]:
        who = "我" if item.get("mine") else "对方"
        lines.append(f"[{item.get('time', '')}] {who}：{item.get('text', '')}")
    return "\n".join(lines) or "（暂无微信聊天记录）"


def build_context_messages(ctx, limit=20):
    """把微信真实记录转成 LLM 消息序列：对方 -> user，我自己 -> assistant。"""
    messages = []
    for item in (ctx or {}).get("messages", [])[-limit:]:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        role = "assistant" if item.get("mine") else "user"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n" + text
        else:
            messages.append({"role": role, "content": text})
    return messages


def describe_context(ctx):
    """用一句话概括上下文状态，喂给模型让它知道该怎么接话。"""
    if not ctx or not ctx.get("ok") or not ctx.get("messages"):
        return "你和对方还没有聊天记录（可能刚加上好友），这次要自然地打个招呼。"
    gap = ctx.get("gap_minutes")
    gap_text = f"距今 {int(gap)} 分钟" if gap is not None else "时间未知"
    if ctx.get("pending"):
        return (f"你们上一次聊天在 {gap_text}前，最后一条是对方发的。"
                f"你还没回：{ctx.get('pending_text') or ''} "
                f"请像真人这样自然地接上这句话，不要另起话题，也不要复述原文。")
    if ctx.get("last_mine"):
        return (f"你们上一次聊天在 {gap_text}前，最后一条是你自己发的，对方没再回。"
                f"这次别重复上次的说法，换个新角度。")
    return f"你们上一次聊天在 {gap_text}前。"


# ==============================================================================
# 好友选择 · 手动发消息 / AI 主动搭话
# ==============================================================================
STAGE_NAME_MAP = {"1": "相识", "2": "相知", "3": "相恋"}

def get_wx():
    """获取当前已连接的微信客户端（未连接时返回 None）。"""
    return wx_instance


def get_wx_nickname():
    """获取当前登录的微信号昵称（失败返回空字符串）。"""
    wx = get_wx()
    if wx is None:
        return ""
    try:
        return str(getattr(wx, "nickname", "") or "")
    except Exception:
        return ""


def send_wechat_message(user_id, text, humanlike=True, count_affection=False, allow_emoji=True):
    """向指定好友发送一条（或多段）微信消息。

    humanlike=True 时使用拟人打字延迟 + 分段发；
    count_affection=True 时本次互动计入好感度（默认 +1）。
    返回 (是否成功, 提示文本)。
    """
    wx = get_wx()
    user_id = (user_id or "").strip()
    text = (text or "").strip()

    if wx is None:
        return False, "微信尚未连接：请先登录电脑微信并保持机器人程序运行。"
    if not user_id:
        return False, "请先选择要发送的好友"
    if not text:
        return False, "消息内容不能为空"

    try:
        if humanlike:
            send_humanlike_reply(wx, user_id, text, allow_emoji=allow_emoji)
        else:
            with send_lock:
                for part in split_reply(text):
                    logger.info(f"[{user_id}] 直接发送：{part}")
                    wx.SendMsg(msg=part, who=user_id)

        remember_bot_message(user_id, text)
        clear_context_cache(user_id)
        if count_affection:
            aff_res = record_user_interaction(user_id, text)
            sign = "+%d" % aff_res["delta"] if aff_res["delta"] >= 0 else str(aff_res["delta"])
            push_activity("发消息", user_id,
                          "已发送：%s（好感度 %s · %s）" % (text, sign, aff_res["reason"]), True)
        else:
            push_activity("发消息", user_id, f"已发送：{text}", True)
        logger.info(f"Web 控制台：已向 [{user_id}] 发消息 -> {text}")
        return True, "发送成功。"
    except Exception as e:
        push_activity("发消息", user_id, f"发送失败：{e}", False)
        logger.error(f"向[{user_id}] 发消息失败：{e}", exc_info=True)
        return False, f"发送失败：{e}"


# 主动搭话时，模型偶尔会在正文前面加一句要怎么写的说明（在线上真出现过
# 「要自然的微信语气，短句口语\n现在在吃早餐」）。这类句子描述的是么写不
# 「说什么，真人不这么聊天，直接这掉那一段，把后面真正的话留下
_META_STYLE_RE = re.compile(
    r"(语气|口吻|短句|口语|人话|真人感|自然|聊天|自然说|"
    r"简短自然|像真人|口语的|书面语|排比|修辞)")


def sanitize_outreach_text(text):
    """清理 AI 主动搭话时可能带出的旁白、引号、Markdown 修饰。"""
    if not text:
        return ""
    echo_re = getattr(mind.prompt_mod, "GUARD_ECHO_PATTERN", None)
    cleaned = []
    for raw in str(text).replace("\\", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        # 整行是括号旁白（如（微笑）、（停顿））则整行删掉
        if (line.startswith("（") and line.endswith("）")) or (line.startswith("(") and line.endswith(")")):
            continue
        # 整行是在复述任务说明（用户要求我…关系阶段：X阶段…）也整行删掉
        # 这些是给模型看的提示语，真人发微信不会这么说
        if echo_re is not None and echo_re.search(line):
            continue
        # 整行在描述该怎么写（语气/口吻/短句…）
        # 如果冒号后面还跟按真正的内容（“像真人这样说话：早啊 在干嘛呢”）
        # 就把说明剥掉留下内容；否则整段这掉
        if _META_STYLE_RE.search(line):
            tail = line.split(u"：", 1)[1].split(u":", 1)[-1].strip() if (
                u"：" in line or u":" in line) else u""
            if tail and not _META_STYLE_RE.search(tail):
                line = tail
            else:
                continue
        # 去掉整行被中英文引号包裹的格
        if len(line) > 1 and line[0] in "“\"" and line[-1] in "”\"":
            line = line[1:-1].strip()
        # 去掉 Markdown 标题/列表/加粗等标记（如 "1. " 这种有序列表前缀）
        line = re.sub(r"^[#*\-\s>]+", "", line).strip()
        line = re.sub(r"^\d+\s*[.。？?、)）]\s*", "", line).strip()
        line = line.replace("**", "").replace("`", "").strip()
        if line:
            cleaned.append(line)
    return "\\".join(cleaned)


# AI 味 / 书面腔 → 微信口语 的替换规则（越靠前优先级越高）

# 回复风格规则（放在模块级，方便单独增删；顺序即优先级）
_REPLY_RULES = [
    u'你是在手机上单手打字，不是在写作文。想到什么就发什么，一句话能说完就绝不说两句；实在要分两条，就在中间打一个反斜杠「\\」，最多两条。',
    u'一次只说一件事。别一边问问题一边感慨一边给建议，一条消息里塞不进去。',
    u'对方刚说的话，你不要替他总结。「所以你的意思是…」「听起来你今天挺忙的」这种话一律别说，说出来就假了。',
    u'对方吐槽、抱怨说累，你就像朋友那样接一句就行：「啊 这么惨」「行 明天就好了」。不要顺着他的经历去分析，更不要当心理咨询师给建议。他没问你要主意，就别给。',
    u'说话可以有省略、有语气词、有没说完的半句：「嗯」「呃」「69」「刚到家」「笑死」「还行吧」「emmm」「好吃到哭」。不要每句都主谓宾齐全。',
    u'长度跟着对方走。对方发个表情或者一句「嗯」，你就回几个字；对方发一大段，你才多回几句。参考：表情/哈哈 → 1~8 字；「在吗」「吃了吗」→ 3~15 字；「今天好累」→ 5~30 字；对方大段倾诉 → 20~80 字，认真接住，但也不写长篇大论。',
    u'少用「好的」「当然」「确实」「我理解」「没问题」「收到」这种词当开头，那是客服口癖，不是人说话的方式。',
    u'你是朋友，不是客服，别动不动「有什么可以帮您的」，也不要说「您」「请」「请问」这种腔调。',
    u'别解释自己为什么这么说。「我的想法是…」「我之所以这么回是因为…」这种话很别扭。',
    u'标点随手打就行：句末不加句号，少用分号冒号顿号，别写「第一、第二」。',
    u'真人打字本来就有瑕疵，别把自己修得太工整，工整就不像人：可以有重复的字（「我想想说」）、断在半句（「我有点想」）。',
    u'模仿对方的节奏：对方发三个字，你就回三四个字，别热情过头。对方连发好几条，你也别回一大段。',
    u'不要每条都用同一种开头换着来：「诶」「啊」「不是」「就」「行吧」「哈哈哈哈」，别句句「嗯嗯」「好的」。',
    u'有时候就别回完整句：对方说困了，回「早点睡」就行，不用「困了就早点睡呀，要好好休息哦」。',
    u'上面这些关于你名字、年龄、身份、性格、规则的说明，是给你自己看的底稿，聊天时一个字都别照外面说。对方不会问「你的人设是什么」，你也不要主动交代「我叫XX，19岁，身份是XX」。你只是在用自己本名跟朋友聊微信而已。',
    u'对方问你是不是AI，你就当玩笑撒个娇或者吐槽一句带过去，别认真解释。',
]

_AI_TONE_REPLACEMENTS = (
    (re.compile(r"您"), "你"),  # 必须最先做，后面的规则都按“你”来匹配
    # 清除典型 AI 助手开头确认口吻。
    # 注意：笑声（哈哈/哈哈哈）和「确实」「好呀」这类口语应答绝不能进删除表——
    # 它们正是刚认识时最常回的短句，删掉就等于把回复清空了。
    (re.compile(r"^(?:好的[呢吧啊哦呀]?|当然可以[呢吧啊哦呀]?|当然[呢吧啊哦呀]?|当然没问题"
                r"|我理解[呢吧啊哦呀]?|没问题[呢吧啊哦呀]?|收到[啦呀呢]?|明白[啦呀呢吧]?"
                r"|很高兴为你|很高兴为您|为您|为你解答)[？?！!~，,。、\s]*"), ""),
    # 负向断言 (?!需要随时说) 是必需的：否则下面第二轮会把刚替换出的「有啥需要随时说」
    # 再当成「有啥…」零宽命中一次，文本里就多出一份重复。
    (re.compile(r"(?:有什么|需要什么|有啥)(?:可以|能)?(?:帮到你|帮助你|帮忙)?的?吗?[？?]?(?!需要随时说)"), "有啥需要随时说"),
    (re.compile(r"如果(?:你|您)?(?:需要|有|还有|遇到)(?:什么|啥|问题|麻烦)"), "有啥需要"),
    # 两条规则的负向断言是必需的：替换词本身就含规则左部（「希望帮到」「祝你开心」），
    # 下面第二轮清洗会把刚生成的词再命中一次，文本里就多出一份重复。
    (re.compile(r"希望(?:这|这些)?(?:对你|对你您|对您)?(?:有所)?(?:帮助|帮到)(?!你)"), "希望帮到你"),
    (re.compile(r"祝你(?:生活|一天|今天)?(?:愉快|开心)(?![心呀])"), "祝你开心"),
    (re.compile(r"请问你?"), ""),
    # 「作为AI」「是AI」这类自称。助手/智能体必须一起进候选表，
    # 否则「作为一个AI助手」砍到 AI 就停，会剩下孤零零的「助手，」开头。
    (re.compile(r"(?:作为|算是|相当于)(?:一个|一名|个)?(?:AI|ai|人工智能|智能助手|助手|程序|模型|机器人|语言模型)[^，,。！？]{0,6}?"), ""),
    (re.compile(r"(?:是|作为)(?:一个|一名|个)?(?:AI|ai|人工智能|智能助手|助手|程序|模型|机器人|语言模型)[^，,。！？]{0,6}?"), ""),
    # 砍完上一句后仍孤立出现在开头/标点后的「助手」尾巴
    (re.compile(r"(?:^|[，,。！？\s])(?:助手|智能体)[，,。！？\s]*"), ""),
    # 「作为AI」整句清掉后剩下的助手腔尾巴
    (re.compile(r"我(?:明白|明白你的意思|了解|懂了|理解)[了，,]?"), ""),
    (re.compile(r"很(?:乐意|愿意|高兴|开心)(?:为你|为您|帮你|帮您)?[，,]?"), ""),
    # 「作为AI…很乐意帮助你」这类整句客服腔：确认语被砍光后剩下的孤词
    (re.compile(r"(?:帮助|协助|服务)(?:你|您)"), ""),
    # 上面几条砍掉客服套话后，偶尔剩下孤立的「为你解答」「为您效劳」尾巴。
    # 这里必须限定跟在这些宾语后面的动词，否则「我想帮你」「都是为你好」这类正常
    # 口语也会被误删。
    (re.compile(r"(?:为你|为您|帮你|帮您)(?:解答|服务|效劳|排忧解难)"), ""),
    (re.compile(r"^[，,、\s]+"), ""),
    (re.compile(r"[，,、\s]+$"), ""),
    # 「作为AI」整句里夹着的助手腔，清掉剩下的连接词
    (re.compile(r"(?:非常|十分)感谢"), "谢啦"),
    (re.compile(r"此外[，,]?"), "另外"),
    (re.compile(r"因此[，,]?"), "所以"),
    # 清除书面总结/列点连词
    (re.compile(r"(?:总的来说|总而言之|综上所述)[，,]?"), ""),
    (re.compile(r"(?:首先|其次|再次|最后)[，,、]?"), ""),
    (re.compile(r"第[一二三四五六123456][、，,]?\s*"), ""),
    (re.compile(r"[？?]{2,}"), "？"),
    (re.compile(r"。{2,}"), "。"),
)


def humanize_outreach_text(text, max_parts=2, overflow="drop"):
    """把 AI 的书面腔改成微信里真人才会打的字。

    max_parts: 最多拆成几条消息发出（主动搭话 2 条足够，被动回复默认 2~3 条）
    overflow : 超出部分怎么处理？"drop" 直接丢弃，"merge" 合并进最后一条
    """
    if not text:
        return ""
    out = str(text).strip()
    out = re.sub(r"[\r\n]+", "\\\\", out)                 # 换行分段统一成\”分隔，便于限制条数
    for pattern, repl in _AI_TONE_REPLACEMENTS:
        out = pattern.sub(repl, out)
    # 砍掉客服套话后常暴露出新一轮的开头确认语（「好的」被删→「很高兴为您解答」顶上来）。
    # 跑第二轮把这种级联残留收干净；短回复本身不含这些词，多跑一遍不会误伤。
    for pattern, repl in _AI_TONE_REPLACEMENTS:
        out = pattern.sub(repl, out)
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    out = re.sub(r"[。\.]", "", out)                  # 口语里不写句号
    # 只砍「当句首虚词后面还跟着别的内容」的情况；
    # 像「然后呢」「再说吧」这种整句就是虚词起头的短回复，必须原样留下
    out = re.sub(r"^(?:那个|其实|然后|所以|不过)(?=[，,、\s]*[^，,、\s])[，,、\s]+", "", out)

    # 规范化每个分段：去除首尾空格句号及 AI 确认语气
    raw_parts = [p.strip() for p in out.split("\\") if p.strip()]
    cleaned_parts = []
    for p in raw_parts:
        p = re.sub(r"[。\.]", "", p).strip()
        # 清除每一段可能夹带的开头确认语与助手词（当然好的确实我理解等）。
        # 同样只在后面还有实际内容时才砍，避免把「好呀」「嗯嗯」这类短回复清空。
        p = re.sub(r"^(?:好的[呢吧啊哦呀]?|当然可以[呢吧啊哦呀]?|当然[呢吧啊哦呀]?|当然没问题"
                   r"|我理解[呢吧啊哦呀]?|没问题[呢吧啊哦呀]?|收到[啦呀呢]?|明白[啦呀呢吧]?)"
                   r"(?=[？?！!~，,。、\s]*[^？?！!~，,。、\s])[？?！!~，,。、\s]*", "", p).strip()
        if p:
            cleaned_parts.append(p)
    parts = cleaned_parts

    # 真人不会一次连发太多条：主动搭话直接砍掉多余的，被动回复允许合并保留
    if len(parts) > max_parts:
        if overflow == "merge":
            parts = parts[:max_parts - 1] + ["，".join(parts[max_parts - 1:])]
        else:
            parts = parts[:max_parts]
    out = "\\".join(parts)
    # 真人极少连抛两个问句（像查户口），第二个及之后的问号去掉
    seen = {"n": 0}

    def _keep_first_question(match):
        seen["n"] += 1
        return match.group(0) if seen["n"] == 1 else ""

    out = re.sub(r"[？?]", _keep_first_question, out).strip().strip("\\").strip()
    # 兜底：整条都是助手腔套话时，逐层清完会剩下「我」「解答」这类无意义残渣。
    # 这种内容发出去只会让人觉得莫名其妙，直接判空让上层重写或干脆不发。
    out = re.sub(r"^(?:我|你|它|他|她|这|那|解答|回答|服务|协助)[，,。、\s]*$", "", out)
    if out and not re.search(r"[一-鿿A-Za-z0-9]", out):
        out = ""
    return out


def calibrate_reply_length(reply, incoming_text):
    """按对方这条消息的长度，裁剪 AI 写太长的部分。
    这是「不像真人」最大的破绽：人家发个"在吗"，它回一大段。
    真人回消息的长度几乎跟对方成正比，所以这里做硬兜底。
    """
    if not reply:
        return reply
    in_len = len((incoming_text or "").strip())
    parts = [p for p in reply.split("\\") if p.strip()]

    def _n(text):        # 数长度时不把分隔符\”算进去
        return len(re.sub(r"\s+", "", (text or "").replace("\\", "")))

    total = _n(reply)

    # 对方回得短，它也必须回得短
    if in_len <= 3:
        cap = 12
    elif in_len <= 6:
        cap = 24
    elif in_len <= 12:
        cap = 40
    else:
        cap = None                              # 对方自己就在长聊，不用管

    if cap is None or total <= cap:
        return reply

    kept = []
    for p in parts:
        if _n("\\".join(kept + [p])) > cap:
            break
        kept.append(p)

    if not kept:
        # 单条就超长：在自然停顿处切断，别硬砍出半截话
        first = parts[0]
        cut = first[:cap]
        m = re.search(r"[？?、！!。]", cut)   # 没找到标点是 None，不能直接遍历
        if m and m.end() >= cap * 0.5:
            cut = cut[:m.end()]
        kept = [cut.rstrip("？。")]

    out = "\\".join(kept).strip()
    logger.debug(f"长度校准：对方 {in_len} 字 -> 回复 {total} 字，压掉 {_n(out)} 字")
    return out


def _text_signature(text):
    """文字指纹：只保留中英文与数字，用于算相似度。"""
    return set(re.sub(r"[^\w\u4e00-\u9fff]+", "", (text or "").lower()))


def text_similarity(a, b):
    """0~1 的相似度（字符集合 Jaccard），用来判断两条消息是不是换汤不换药。"""
    sa, sb = _text_signature(a), _text_signature(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


def remember_auto_sent(user_id, text):
    """记下刚发出的内容，后续自动搭话据此去重（避免复读机）。"""
    entry = {"t": time.time(), "target": user_id, "text": (text or "")[:80]}
    with persona_lock:
        runtime = ensure_persona_schema().setdefault("auto_chat_runtime", {})
        recent = runtime.get("recent_sent")
        if not isinstance(recent, list):
            recent = []
        recent.append(entry)
        runtime["recent_sent"] = recent[-12:]
        _save_persona_nolock()
    return entry


def get_recent_sent(target=None, limit=8):
    """取最近发过的内容（可按好友过滤）。"""
    with persona_lock:
        recent = list(ensure_persona_schema().get("auto_chat_runtime", {}).get("recent_sent") or [])
    if target:
        recent = [r for r in recent if r.get("target") == target]
    return recent[-limit:]


def is_repeat_message(text, target=None, threshold=0.62):
    """和最近发过的内容太像就判定为复读。"""
    for item in get_recent_sent(target):
        if text_similarity(text, item.get("text", "")) >= threshold:
            return True
    return False


def current_activity_hint(user_id):
    """此刻「我」在干嘛（按作息表），用来给生活分享找话头。"""
    try:
        fs = get_mind_engine().friend_state(user_id)
        st = fs.get("state") or {}
        return mind.state.current_activity(st.get("schedule")) or u""
    except Exception:
        return u""


def build_outreach_user_prompt(user_id, task, recent_text, ctx_lines):
    """组装主动搭话时给模型的那条 user prompt。

    单独抽出来是为了让「守卫比对用的提示词」和「真正发给模型的提示词」
    用同一份构造逻辑 —— 否则守卫只比对 system prompt，
    模型复述 user prompt 里的任务说明就抓不到。
    """
    return (
        u"给「%s」发一条微信\n\n"
        u"最近聊天：\n%s\n"
        u"你最近发过（别重复）：\n%s\n\n"
        u"%s\n"
        u"就写你真正会发出去的那句话，10~30 个字，别的一律不要写。\n"
        u"（例子：刚下课，食堂门口见。）\n"
        % (user_id, ctx_lines, recent_text, task)
    )


def outreach_guard_prompt(user_id, topic=""):
    """守卫做原样念提示词比寰时用的完整提示词（system + 搭话任务）。"""
    task = u"围绕「%s」说一句" % topic if topic else u"说说你手头在忙什么，或随口问一句"
    return (get_user_prompt(user_id) + "\n"
            + build_outreach_user_prompt(user_id, task, u"（无）", u"（无）"))


def generate_outreach_message(user_id, topic="", use_context=True, avoid_repeat=True):
    """让 AI 以当前人格与关系阶段生成这条消息（默认会读微信真实上下文，不发送）。

    use_context=True 时直接读本地微信数据库，把真实聊天记录作为对话历史喂给模型，
    并根据对方最后一条有没有被回复，自动决定是接话还是另起话题。
    """
    system_prompt = get_user_prompt(user_id)
    _prof, _stages = get_active_persona()
    bot_name = (_prof or {}).get("name") or u""
    aff, stage_key = get_user_affection_and_stage(user_id)
    stage_name = STAGE_NAME_MAP.get(stage_key, "相识")

    cfg, _ = get_auto_chat_config()
    rounds = int(cfg.get("context_rounds") or 20)
    ctx = empty_wechat_context()
    if use_context and cfg.get("use_context", True):
        ctx = fetch_wechat_context(user_id, limit=rounds)
        if ctx.get("ok"):
            logger.info(f"[{user_id}] 读取到微信上下文 {len(ctx.get('messages') or [])} 条，"
                        f"最后一条是{'' if ctx.get('last_mine') else '对方'}发的")

    topic = (topic or "").strip()
    if ctx.get("pending") and cfg.get("reply_pending_first", True):
        task = u"对方刚发来一句话，回他一句。"
    elif topic:
        task = u"围绕「%s」说一句。" % topic
    else:
        # 没人给话题：按当前时段挑一个该分享的生活片段（移植 daily_share.json）
        task = chatcraft.life_share_prompt(activity=current_activity_hint(user_id))

    recent = get_recent_sent(user_id, limit=5)
    recent_text = "\n".join(u"- %s" % r.get("text", "") for r in recent) or u"（无）"

    # 这一段刻意写得很短。之前写了一大堆要求（35字左右、别客服腔、分两条用反斜杠…）
    # 结果模型经常把要求本身当成回复念出来。规则越少，它越容易只输出那句话
    user_prompt = build_outreach_user_prompt(
        user_id, task, recent_text, render_context_lines(ctx, rounds))
    # 守卫比对用的完整提示词：system + 上面这段任务说明（同一个来源，不会漏）
    guard_prompt = system_prompt + "\n" + user_prompt

    messages = [{"role": "system", "content": system_prompt}]
    if ctx.get("ok"):
        messages.extend(build_context_messages(ctx, rounds))
    messages.append({"role": "user", "content": user_prompt})

    # 兜底用的这次极简请求」：上下文越简单，模型越不容易把任务说明当成回复念出来
    # 这里除了这个例子，不写任何「要怎样怎样」的说明—写了它就可能照按念出来
    simple_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"跟{user_id}】发这句微信，就当你刚拿起手机随手发的。\n"
            f"例子：刚下课，食堂门口见。"
        )},
    ]

    result = ""
    guard_hint = ""
    guard_ok = False
    for attempt in range(3):
        if attempt >= 2:
            call_messages = list(simple_messages)
        else:
            call_messages = list(messages)
            if attempt:
                extra = "\n【重写这一版太套路了，换个完全不同的开头句式和落点，宁可短也别重复】"
                if guard_hint:
                    extra += " 刚才那版有问题：%s。" % guard_hint
                call_messages[-1] = dict(call_messages[-1], content=call_messages[-1]["content"] + extra)
        try:
            reply = llm.chat_completion(
                messages=call_messages,
                temperature=min(1.25, max(0.7, config.TEMPERATURE + 0.15 * attempt)),
                max_tokens=config.MAX_TOKENS,
            )
            reply = (reply or "").strip()
        except Exception as e:
            logger.error(f"生成搭话内容失败: {e}", exc_info=True)
            return result if guard_ok else ""

        result = humanize_outreach_text(sanitize_outreach_text(reply))
        if not result:
            continue
        if avoid_repeat and attempt == 0 and is_repeat_message(result, user_id):
            logger.info("搭话内容与最近发送高度重复，重新生成这一条。")
            continue
        # 一致性守卫：把任务说明念出来 / 出戏 / 客服腔 / 太长，都要重写
        # 注意要把 user_prompt 也喂进去：模型复述的刚刚正是「主动搭话任务那段，
        try:
            passed, why = get_mind_engine().guard_reply(
                user_id, result, prompt_text=guard_prompt)
        except Exception as e:
            logger.debug(f"搭话内容这致检查失败（已忽略）: {e}")
            passed, why = True, ""
        if not passed:
            logger.info(f"[{user_id}] 搭话内容未过一致性检查（{why}），重写这一条。")
            guard_hint = why
            continue
        guard_ok = True
        break
    # 几版都被守卫拦下时，宁可不发：发这句用户要求我作为…出去，
    # 比一一轮不开口糟糕得多
    return result if guard_ok else ""


def get_contact_list():
    """汇总可参与互动的对象：监听白名单 + 已互动好友 + 微信通讯录好友。"""
    order = []
    source_map = {}

    def add(uid, source):
        uid = (uid or "").strip()
        if not uid or uid in source_map:
            return
        source_map[uid] = source
        order.append(uid)

    # 1) 配置文件中的监听对象（一定可用）
    if getattr(config, "LISTEN_MODE", "") == "whitelist":
        for item in get_listen_names():
            try:
                add(item, "监听中")
            except Exception:
                continue

    # 2) 已有好感度记录的好友
    with persona_lock:
        users_snapshot = dict(persona_data.get("users", {}))
    for uid in users_snapshot.keys():
        add(uid, "已互动")

    # 3) 微信通讯录（需要微信在线）
    wx = get_wx()
    if wx is not None:
        try:
            for c in wx.ListContacts():
                add(c.get("name"), "微信好友")
        except Exception as e:
            logger.warning(f"获取微信好友列表失败: {e}")

    contacts = []
    auto_targets = set(get_auto_chat_targets())
    for uid in order:
        aff, stage_key, force = peek_user_stage(uid)
        u = users_snapshot.get(uid, {}) or {}
        contacts.append({
            "user_id": uid,
            "source": source_map[uid],
            "affection": aff,
            "chat_count": u.get("chat_count", 0),
            "force_stage": force,
            "stage": stage_key,
            "stage_name": STAGE_NAME_MAP.get(stage_key, "相识"),
            "auto": uid in auto_targets,
            "last_auto_time": u.get("last_auto_time", 0),
        })
    return contacts


def get_activity_log(limit=10):
    with activity_log_lock:
        return list(activity_log[:limit])


# ==============================================================================
# 自动主动搭话：定时调度目标择、话题池、每日上
# ==============================================================================
def get_auto_chat_config():
    """读取自动搭话配置与运行状态（缺失字段自动补全）。"""
    with persona_lock:
        config_ = ensure_persona_schema().get("auto_chat", {})
        runtime = persona_data.get("auto_chat_runtime", {})
        return dict(config_), dict(runtime)


def _ts_to_text(ts):
    try:
        ts = float(ts or 0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M:%S")


def default_auto_targets():
    """未指定目标时返回空列表：**默认谁都不主动聊**。
    恋爱模拟里，AI 小号应该「你找它它才回，不该自己凑上去」。
    想让某个人被主动搭话，必须在网页好友卡片上明确打开开关。
    """
    return []


def get_auto_chat_targets(cfg=None):
    """返回参与自动搭话的好友列表（配置为空时回退到默认目标）。"""
    if cfg is None:
        cfg, _ = get_auto_chat_config()
    targets = [t for t in (cfg.get("targets") or []) if str(t).strip()]
    return targets or default_auto_targets()


def save_auto_chat_config(patch):
    """局部更新自动搭话配置并持久化，返回最新配置。"""
    with persona_lock:
        cfg = ensure_persona_schema().get("auto_chat", {})

        if "enabled" in patch:
            cfg["enabled"] = bool(patch["enabled"])
            if cfg["enabled"]:
                # 开启后 20 秒内先自动搭话一次，便于立刻看到效果
                runtime = persona_data.setdefault("auto_chat_runtime", {})
                runtime["next_run"] = time.time() + 20
        if "interval_minutes" in patch:
            cfg["interval_minutes"] = max(1, min(1440, int(patch["interval_minutes"] or 60)))
        if "active_start" in patch:
            cfg["active_start"] = max(0, min(23, int(patch["active_start"] or 0)))
        if "active_end" in patch:
            cfg["active_end"] = max(0, min(24, int(patch["active_end"] or 24)))
        if "max_per_day" in patch:
            cfg["max_per_day"] = max(1, min(200, int(patch["max_per_day"] or 20)))
        if "jitter" in patch:
            cfg["jitter"] = bool(patch["jitter"])
        if "count_affection" in patch:
            cfg["count_affection"] = bool(patch["count_affection"])
        if "topics" in patch:
            cfg["topics"] = str(patch["topics"] or "")
        if "use_context" in patch:
            cfg["use_context"] = bool(patch["use_context"])
        if "context_rounds" in patch:
            cfg["context_rounds"] = max(4, min(100, int(patch["context_rounds"] or 20)))
        if "reply_pending_first" in patch:
            cfg["reply_pending_first"] = bool(patch["reply_pending_first"])
        if "min_gap_hours" in patch:
            try:
                cfg["min_gap_hours"] = max(0.0, min(72.0, float(patch["min_gap_hours"])))
            except (TypeError, ValueError):
                pass
        if "avoid_repeat" in patch:
            cfg["avoid_repeat"] = bool(patch["avoid_repeat"])
        if "targets" in patch:
            targets = []
            for t in (patch["targets"] or []):
                t = str(t).strip()
                if t and t not in targets:
                    targets.append(t)
            cfg["targets"] = targets

        _save_persona_nolock()
        return dict(cfg)


def set_auto_target(user_id, auto=True):
    """把某个好友加入 / 移出自动搭话名单。"""
    user_id = (user_id or "").strip()
    if not user_id:
        return None
    cfg, _ = get_auto_chat_config()
    targets = [t for t in (cfg.get("targets") or []) if str(t).strip()]
    if not targets:
        targets = list(default_auto_targets())
    if auto:
        if user_id not in targets:
            targets.append(user_id)
    else:
        targets = [t for t in targets if t != user_id]
    return save_auto_chat_config({"targets": targets})


def in_active_window(cfg, now=None):
    """判断当前时间是否处于允许自动搭话的活跃时段（支持跨午夜）。"""
    now = now or datetime.now()
    try:
        start = int(cfg.get("active_start", 9))
        end = int(cfg.get("active_end", 23))
    except (TypeError, ValueError):
        start, end = 9, 23
    hour = now.hour
    if start == end:
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def rank_auto_chat_targets(cfg=None):
    """把勾选的好友按最久没被自动搭话排在前，用于轮换 + 跳过冷却。"""
    targets = get_auto_chat_targets(cfg)
    if not targets:
        return []
    with persona_lock:
        users = persona_data.get("users", {})
        last_times = {}
        for t in targets:
            try:
                last_times[t] = float((users.get(t) or {}).get("last_auto_time") or 0)
            except (TypeError, ValueError):
                last_times[t] = 0.0
    return sorted(targets, key=lambda t: last_times.get(t, 0.0))


def pick_auto_chat_target(cfg=None):
    """挑本次自动搭话对象：优先选择最久没被自动搭话的好友，实现轮流。"""
    ranked = rank_auto_chat_targets(cfg)
    return ranked[0] if ranked else None


def pick_auto_topic(cfg=None):
    """从话题池随机取一个话题（为空则返回空字符串，让 AI 自由发挥）。"""
    if cfg is None:
        cfg, _ = get_auto_chat_config()
    raw = str(cfg.get("topics") or "").replace("，", "\n").replace(",", "\n")
    pool = [line.strip() for line in raw.split("\n") if line.strip()]
    return random.choice(pool) if pool else ""


def update_auto_runtime(**fields):
    with persona_lock:
        rt = ensure_persona_schema().setdefault("auto_chat_runtime", {})
        rt.update(fields)
        _save_persona_nolock()
        return dict(rt)


def mark_auto_sent(user_id, ts=None):
    """记录某个好友最近一次被自动搭话的时间（用于轮流与冷却）。"""
    ts = ts or time.time()
    with persona_lock:
        users = ensure_persona_schema().setdefault("users", {})
        entry = users.setdefault(user_id, {
            "affection": 0, "force_stage": None, "chat_count": 0, "notes": ""
        })
        entry["last_auto_time"] = ts
        _save_persona_nolock()


def get_auto_chat_status():
    """返回自动搭话的当前状态描述，供网页展示。"""
    cfg, rt = get_auto_chat_config()
    now = datetime.now()
    next_ts = float(rt.get("next_run") or 0)
    status = {
        "enabled": bool(cfg.get("enabled")),
        "wx_online": get_wx() is not None,
        "count_today": int(rt.get("count_today") or 0),
        "max_per_day": int(cfg.get("max_per_day") or 20),
        "last_run_text": _ts_to_text(rt.get("last_run")),
        "next_run_text": _ts_to_text(next_ts),
        "last_target": rt.get("last_target") or "",
        "targets": get_auto_chat_targets(cfg),
        "use_context": bool(cfg.get("use_context", True)),
        "context_text": "",
        "reason": "",
    }
    last_target = rt.get("last_target") or ""
    if last_target:
        ctx = fetch_wechat_context(last_target, limit=8)
        if ctx.get("ok"):
            gap = ctx.get("gap_minutes")
            gap_text = f"{int(gap)} 分钟前" if gap is not None else "时间未知"
            status["context_text"] = (
                f"，{last_target} 上次聊天 {gap_text}"
                + ("，对方最后一条还没回" if ctx.get("pending") else "")
                + f"，已读取 {len(ctx.get('messages') or [])} 条微信记录。"
            )
    if not status["enabled"]:
        status["reason"] = "自动搭话已关闭，打开开关后机器人会自己定时找人聊天"
    elif not status["wx_online"]:
        status["reason"] = "微信未连接，连接后自动开启。"
    elif not in_active_window(cfg, now):
        status["reason"] = f"当前不在活跃时段（{cfg.get('active_start')}:00 - {cfg.get('active_end')}:00）"
    elif status["count_today"] >= status["max_per_day"]:
        status["reason"] = "已达到今日自动搭话上限。"
    elif next_ts > time.time():
        status["reason"] = "已排期，等待到点自动发送。"
    else:
        min_gap_minutes = float(cfg.get("min_gap_hours") or 0) * 60.0
        ranked = rank_auto_chat_targets(cfg)
        if min_gap_minutes > 0 and ranked:
            now_ts = time.time()
            with persona_lock:
                users = persona_data.get("users", {})
                left = []
                for t in ranked:
                    try:
                        last_sent = float((users.get(t) or {}).get("last_auto_time") or 0)
                    except (TypeError, ValueError):
                        last_sent = 0.0
                    left.append(min_gap_minutes - (now_ts - last_sent) / 60.0 if last_sent else 0.0)
            if left and all(v > 0 for v in left):
                status["reason"] = f"好友都在冷却中，最快约 {int(min(left)) + 1} 分钟后自动继续。"
            else:
                status["reason"] = "随时可发送。"
        else:
            status["reason"] = "随时可发送。"
    return status


def auto_chat_tick(force=False):
    """执行这次自动搭话（force=True 表示点击「立即自动搭话一次」）。"""
    cfg, rt = get_auto_chat_config()
    now = datetime.now()
    now_ts = time.time()

    if not force:
        if not cfg.get("enabled"):
            return {"ok": False, "reason": "自动搭话未开启。"}
        if get_wx() is None:
            return {"ok": False, "reason": "微信未连接。"}
        if not in_active_window(cfg, now):
            return {"ok": False, "reason": "不在活跃时段"}
        today = now.strftime("%Y-%m-%d")
        if rt.get("day") != today:
            rt["day"] = today
            rt["count_today"] = 0
            update_auto_runtime(day=today, count_today=0)
        if int(rt.get("count_today") or 0) >= int(cfg.get("max_per_day") or 20):
            return {"ok": False, "reason": "已达今日自动搭话上限"}
        if now_ts < float(rt.get("next_run") or 0):
            return {"ok": False, "reason": "未到下次自动搭话时间"}
    elif get_wx() is None:
        return {"ok": False, "reason": "微信尚未连接：请先登录电脑微信并保持程序运行"}

    candidates = rank_auto_chat_targets(cfg)
    if not candidates:
        return {"ok": False, "reason": "还没有可自动搭话的好友，请先在网页勾选。"}

    # 挑人：同一好友的最短间隔 + 内心状态闸门（精力不够 / 静默时段 / 心里别扭）
    # 处在冷却里或此刻不想说话的好友直接跳过换下一个，而不是整轮什么都不做
    min_gap_minutes = float(cfg.get("min_gap_hours") or 0) * 60.0
    engine = get_mind_engine()
    eligible, skipped, soonest = [], [], None
    for cand in candidates:
        if not force and min_gap_minutes > 0:
            try:
                with persona_lock:
                    users = persona_data.get("users", {})
                    last_sent = float((users.get(cand) or {}).get("last_auto_time") or 0)
            except (TypeError, ValueError):
                last_sent = 0.0
            waited = (now_ts - last_sent) / 60.0 if last_sent else min_gap_minutes
            if waited < min_gap_minutes:
                skipped.append((cand, u"还在冷却里，还要 %d 分钟后再搭话" % max(
                    1, int(min_gap_minutes - waited))))
                if soonest is None:
                    soonest = max(1, int(min_gap_minutes - waited))
                continue
        if not force:
            try:
                _aff_now, _stage_now, _force_now = peek_user_stage(cand)
                willing, why = engine.would_speak_now(
                    cand, affection=_aff_now, stage_key=_stage_now, cfg=cfg)
            except Exception as e:
                logger.debug(f"内部状态判断失败（继续照常搭话）：{e}")
                willing, why = True, ""
            if not willing:
                logger.info(f"自动搭话：[{cand}] 内部状态判断此刻不主动开口（{why}）。")
                skipped.append((cand, why))
                continue
        eligible.append(cand)

    if not eligible:
        if skipped:
            who, why = skipped[0]
            push_activity("自动搭话", who, u"内部状：%s" % why, False)
            return {"ok": False, "reason": u"内部状：%s" % why, "target": who}
        return {"ok": False, "reason": "还没有可自动搭话的好友，请先在网页勾选。"}
    target = eligible[0]
    if skipped:
        logger.info(f"自动搭话：跳过 {len(skipped)} 位此刻不方便开口的好友，本次选 {target}")

    # 读取微信真实上下文：决定这次是接对方的话」还是另起话题
    ctx = empty_wechat_context()
    if cfg.get("use_context", True):
        ctx = fetch_wechat_context(target, limit=cfg.get("context_rounds") or 20)
    if (not force and ctx.get("pending")
            and ctx.get("pending_minutes") is not None
            and ctx["pending_minutes"] <= 2.0):
        return {"ok": False, "reason": f"{target} 刚发来消息，等消息合并窗口回复更自然"}

    topic = "" if ctx.get("pending") else pick_auto_topic(cfg)
    try:
        message = generate_outreach_message(
            target, topic, use_context=bool(cfg.get("use_context", True)))
    except Exception as e:
        logger.error(f"自动搭话生成失败: {e}", exc_info=True)
        push_activity("自动搭话", target, f"生成失败：{e}", False)
        return {"ok": False, "reason": f"生成失败：{e}", "target": target}

    if not message:
        # 生成不出来有很多原因（模型报错/ 两版都被这致守卫拦下），这里统这说人话
        push_activity("自动搭话", target,
                      "这一轮没能写出过检查的内容，先不打扰 TA（稍后会自动重试）。", False)
        return {"ok": False, "reason": "这一轮没能写出过检查的内容，先不打扰 TA（稍后会自动重试）。",
                "target": target}

    ok, info = send_wechat_message(
        target, message, humanlike=True,
        count_affection=bool(cfg.get("count_affection", True)),
    )

    interval = max(1, int(cfg.get("interval_minutes") or 60)) * 60
    if cfg.get("jitter", True):
        interval = interval * random.uniform(0.85, 1.15)
    mark_auto_sent(target, now_ts)
    if ok:
        remember_auto_sent(target, message)
        # 主动开口也消精力更新情绪与记忆时间线（内部状保持一致）
        try:
            engine = get_mind_engine()
            engine.on_bot_reply(target, message, sent_parts=len(split_reply(message)))
            engine.note_proactive(target, message, topic=topic)
        except Exception as e:
            logger.debug(f"主动搭话后更新内心状态失败（已忽略）: {e}")
    update_auto_runtime(
        last_run=now_ts,
        next_run=now_ts + interval,
        last_target=target,
        count_today=int(rt.get("count_today") or 0) + (0 if force else 1),
    )
    mode = "接话" if ctx.get("pending") else "主动搭话"
    logger.info(f"自动搭话[{mode}][{target}]：{message}（{info}）。")
    return {"ok": ok, "reason": info, "target": target, "message": message,
            "mode": mode, "context_count": len(ctx.get("messages") or [])}


def auto_chat_worker():
    """后台调度线程：按配置定时自动找人搭话（机器人处于运行中才执行）。"""
    logger.info("自动主动搭话调度线程已启动（在网页控制台打开开关后生效）。")
    last_note = ""
    while not bot_stop_event.is_set():
        try:
            if _bot_is_running():
                status = get_auto_chat_status()
                if status["enabled"] and status["reason"] == "随时可发送。":
                    result = auto_chat_tick()
                    if result.get("ok"):
                        last_note = ""
                    elif result.get("reason") and result["reason"] != last_note:
                        last_note = result["reason"]
                        logger.info(f"自动搭话未发送：{result['reason']}")
        except Exception as e:
            logger.error(f"自动搭话调度异常: {e}", exc_info=True)
        time.sleep(15)
    logger.info("自动主动搭话调度线程已退出。")


def start_auto_chat_worker():
    """幂等启动自动搭话调度线程（重复调用不会产生多个线程）。"""
    th = bot_threads.get("AutoChatScheduler")
    if th and th.is_alive():
        return th
    th = threading.Thread(target=auto_chat_worker, daemon=True, name="AutoChatScheduler")
    th.start()
    bot_threads["AutoChatScheduler"] = th
    return th


def run_auto_chat_now_async():
    """点击「立即自动搭话一次」时调用（后台线程执行，避免请求超时）。"""
    def _run():
        result = auto_chat_tick(force=True)
        if not result.get("ok"):
            push_activity("自动搭话", result.get("target") or "-",
                          result.get("reason") or "未发送", False)
    threading.Thread(target=_run, daemon=True, name="AutoChatNow").start()


# ==============================================================================
# 机器人运行时核心：一次配置，启动即运
# ------------------------------------------------------------------------------
# 启动 -> 自动连接微信 -> 自动监听新消息 -> 自动读上下文 -> 自动调模型
#      -> 自动生成回复 -> 自动发送 -> 自动存记忆 -> 持续运行
# 一条链跑完，全程无需人工点击任何按钮。
# 停止 -> 断开监听并暂停全部自动行为（关闭程序同样停止自动回复
# ==============================================================================

def get_runtime_config():
    """读取机器人运行时配置（缺失字段自动补齐，返回副本）。"""
    with persona_lock:
        runtime = persona_data.get("runtime")
        if not isinstance(runtime, dict):
            runtime = dict(DEFAULT_RUNTIME)
            persona_data["runtime"] = runtime
        else:
            for k, v in DEFAULT_RUNTIME.items():
                runtime.setdefault(k, v)
        cfg = dict(runtime)
    return cfg


def save_runtime_config(patch):
    """保存运行时配置（只接受 DEFAULT_RUNTIME 中已定义的键），保存后立即生效。"""
    patch = patch or {}
    with persona_lock:
        runtime = persona_data.setdefault("runtime", dict(DEFAULT_RUNTIME))
        for k, v in patch.items():
            if k in DEFAULT_RUNTIME:
                runtime[k] = v
        _save_persona_nolock()
        cfg = dict(runtime)
    logger.info(
        f"机器人运行配置已更新: 开机自动启动={cfg['auto_start']}, "
        f"自动回复={cfg['auto_reply']}, 自动存记忆={cfg['auto_save_memory']}"
    )
    return cfg


def _bot_is_running():
    with bot_state_lock:
        return bot_state.get("state") == BOT_STATE_RUNNING


def get_bot_status():
    """返回机器人运行时状态快照（供网页控制台 / API 实时展示）。"""
    with bot_state_lock:
        snap = dict(bot_state)
        snap["listen_targets"] = list(snap.get("listen_targets") or [])
        snap["listen_failed"] = list(snap.get("listen_failed") or [])
    runtime_cfg = get_runtime_config()
    wx = get_wx()
    started_at = snap.get("started_at") or 0.0
    uptime = (time.time() - started_at) if started_at else 0
    try:
        active_provider = llm.get_active_provider_info()
    except Exception:
        active_provider = {}
    with queue_lock:
        pending = len(msg_queue)
    snap.update({
        "ok": True,
        "running": snap.get("state") == BOT_STATE_RUNNING,
        "wx_online": wx is not None,
        "wx_nickname": get_wx_nickname(),
        "uptime_seconds": int(uptime),
        "uptime_text": _format_duration(uptime) if started_at else "-",
        "queue_pending": pending,
        "runtime": runtime_cfg,
        "active_provider": _mask_provider_secrets(active_provider),
        "listen_mode": getattr(config, "LISTEN_MODE", ""),
        "whitelist": get_listen_names(),
        "memory_friends": len(chat_histories),
        "memory_messages": sum(len(v or []) for v in chat_histories.values()),
        "auto_chat_enabled": bool((get_auto_chat_config()[0] or {}).get("enabled")),
    })

    # 内心世界 + 平台统计（情绪 / 精力 / 人格
    try:
        snap["token_stats"] = token_stats.snapshot()
        snap["dedupe_seen"] = dedupe_guard.size()
        focus = snap.get("last_message_from")
        if not focus:
            with persona_lock:
                users_now = list((persona_data.get("users") or {}).keys())
            focus = users_now[0] if users_now else ""
        if focus:
            aff_focus, stage_focus, _f = peek_user_stage(focus)
            snap["mind_focus"] = focus
            snap["mind"] = get_mind_engine().snapshot(
                focus, stage_key=stage_focus, affection=aff_focus)
    except Exception as e:
        logger.debug(f"读取内心世界快照失败（已忽略：{e}")
    return snap


def _connect_wechat(retries=None, interval=None):
    """连接已登录的电脑微信（带重试），成功返回 wx 实例，失败返回 None。"""
    runtime_cfg = get_runtime_config()
    if retries is None:
        try:
            retries = max(1, int(runtime_cfg.get("connect_retry", 3)))
        except (TypeError, ValueError):
            retries = 3
    if interval is None:
        try:
            interval = max(1, int(runtime_cfg.get("connect_retry_interval", 10)))
        except (TypeError, ValueError):
            interval = 10

    last_err = ""
    for attempt in range(1, retries + 1):
        if bot_stop_event.is_set():
            last_err = "启动过程中被手动停止"
            break
        try:
            wx = WeChat()
            logger.info(f"成功连接微信！当前登录账号：{wx.nickname}")
            return wx
        except Exception as e:
            last_err = str(e)
            logger.warning(
                f"连接微信失败（第 {attempt}/{retries} 次），请确认电脑微信已登录并保持运行: {e}"
            )
            if attempt < retries:
                time.sleep(interval)
    if last_err and not bot_stop_event.is_set():
        logger.error(f"无法连接微信客户端，启动失败: {last_err}")
    return None


def _register_listeners(wx, handler):
    """注册消息监听（白名单逐个监听 / 全局私聊监听），返回 (成功列表, 失败列表)?"""
    ok_targets, failed_targets = [], []

    if getattr(config, "LISTEN_MODE", "") == "whitelist":
        for entry in get_listen_names():
            user_name = entry
            logger.info(f"正在添加监听目标: {user_name} ...")
            try:
                res = wx.AddListenChat(nickname=user_name, callback=handler)
            except Exception as e:
                logger.warning(f"添加监听目标 [{user_name}] 异常: {e}")
                res = None
            if res:
                ok_targets.append(user_name)
                logger.info(f"成功监听: {user_name}")
            else:
                failed_targets.append(user_name)
                logger.warning(
                    f"添加监听目标 [{user_name}] 失败。"
                    f"请确认微信通讯录里的昵称、备注和这里的一字不差。"
                    f"在网页「跟谁聊天」的好友卡片上能看到原始昵称，照抄过来。")
    else:
        logger.info("正在开启全局私聊监听...")
        try:
            wx.AddListenAll(callback=handler)
            ok_targets.append("全部私聊")
        except Exception as e:
            logger.error(f"开启全局监听失败: {e}")

    return ok_targets, failed_targets


def resubscribe_listeners():
    """名单改动后重新订阅（不用重启、不用停机）。

    没在运行就只返回「待启动」，由用户点「启动」时再订阅。
    """
    state = get_bot_status()
    wx = get_wx()
    if wx is None or not state.get("running"):
        return {"resubscribed": False,
                "reason": "机器人还没启动，名单已保存，点启动后会自动订阅",
                "ok": [], "failed": []}

    handler = make_msg_handler(wx)
    ok_targets, failed_targets = _register_listeners(wx, handler)
    with bot_state_lock:
        bot_state["listen_targets"] = list(ok_targets)
        bot_state["listen_failed"] = list(failed_targets)
        bot_state["listen_mode"] = getattr(config, "LISTEN_MODE", "")

    for n in ok_targets:
        push_activity(u"监听名单", n, u"已订阅，开始监听 TA 的消息。", True)
    for n in failed_targets:
        push_activity(
            u"监听名单", n,
            u"没听上：微信通讯录里没有叫「%s」的人。"
            u"请打开微信「通讯录」照着昵称/备注一字不差地改，"
            u"改完再点一次保存。" % n, False,
        )
    return {"resubscribed": True, "ok": ok_targets, "failed": failed_targets}


def _start_bot_workers(wx):
    """幂等启动自动回复 / 自动搭话 / 内心沉思 / 状态巡检线程。"""
    worker = bot_threads.get("QueueWorker")
    if not worker or not worker.is_alive():
        worker = threading.Thread(target=queue_worker, args=(wx,), daemon=True, name="QueueWorker")
        worker.start()
        bot_threads["QueueWorker"] = worker

    start_auto_chat_worker()

    reflect = bot_threads.get("MindReflect")
    if not reflect or not reflect.is_alive():
        reflect = threading.Thread(target=mind_reflect_worker, daemon=True, name="MindReflect")
        reflect.start()
        bot_threads["MindReflect"] = reflect

    _ensure_bot_monitor()


def _ensure_bot_monitor():
    """幂等启动运行状态巡检线程（微信掉线 / 启动失败时自动重试恢复）。"""
    monitor = bot_threads.get("BotMonitor")
    if monitor and monitor.is_alive():
        return monitor
    monitor = threading.Thread(target=bot_monitor_worker, daemon=True, name="BotMonitor")
    monitor.start()
    bot_threads["BotMonitor"] = monitor
    return monitor


def _start_bot_blocking():
    """真正执行启动流程（自动连接微信 -> 自动监听 -> 拉起全自动工作线程）。"""
    global wx_instance

    load_histories()

    wx = _connect_wechat()
    if wx is None:
        _set_bot_state(BOT_STATE_ERROR, last_error="微信连接失败：请确认电脑微信已登录并在后台运行。")
        push_activity("启动机器人", "系统", "启动失败：未能连接微信客户端", False)
        return False

    with wx_instance_lock:
        wx_instance = wx

    handler = make_msg_handler(wx)
    ok_targets, failed_targets = _register_listeners(wx, handler)

    # 先注册监听再拉起工作线程，保证第这条消息就不会被漏
    _start_bot_workers(wx)

    _set_bot_state(
        BOT_STATE_RUNNING,
        started_at=time.time(),
        wechat_nickname=str(getattr(wx, "nickname", "") or ""),
        listen_mode=getattr(config, "LISTEN_MODE", ""),
        listen_targets=ok_targets,
        listen_failed=failed_targets,
        last_error="",
    )
    logger.info(
        "机器人已进入全自动运行模式：自动监听 + 自动读上下文 + 自动调模型 + 自动回复 + 自动存记忆。"
        "（无需任何人工触发，点击「停止机器人」或按 Ctrl+C 才会结束。）"
    )
    push_activity(
        "启动机器人", "系统",
        f"已自动连接微信[{getattr(wx, 'nickname', '')}]，监听 {len(ok_targets)} 个会话，全自动回复已开启。", True,
    )
    return True


def start_bot(background=True):
    """一键启动机器人（核心运行模式）。
    background=True 时立即返回，连接过程在后台进行，网页通过 /api/bot/status 轮询进度。
    重复调用是安全的：已经处于「运行中/连接中」时直接返回当前状态。
    """
    with bot_state_lock:
        state = bot_state.get("state")
        if state in (BOT_STATE_CONNECTING, BOT_STATE_RUNNING):
            return {
                "ok": True,
                "already": True,
                "msg": f"机器人已在运行中（{BOT_STATE_TEXT.get(state, state)}）。",
            }

    bot_stop_event.clear()
    _set_bot_state(BOT_STATE_CONNECTING, last_error="", started_at=0.0)
    _ensure_bot_monitor()          # 先拉起巡检线程：连接失联掉线时能自动重试恢复
    logger.info("收到启动指令：正在自动连接微信并开启全自动运行模式...")

    if not background:
        ok = _start_bot_blocking()
        if ok:
            return {"ok": True, "msg": "机器人已启动，开始全自动运行"}
        return {"ok": False, "msg": get_bot_status().get("last_error") or "启动失败"}

    def _runner():
        try:
            _start_bot_blocking()
        except Exception as e:
            logger.error(f"启动机器人异常：{e}", exc_info=True)
            _set_bot_state(BOT_STATE_ERROR, last_error=str(e))

    th = threading.Thread(target=_runner, daemon=True, name="BotStarter")
    th.start()
    bot_threads["BotStarter"] = th
    return {"ok": True, "msg": "已开始自动连接微信并启动全自动运行模式。"}


def stop_bot(reason="手动停止"):
    """停止机器人：断开监听、暂停全部自动行为，并保存记忆。"""
    global wx_instance

    with bot_state_lock:
        if bot_state.get("state") == BOT_STATE_STOPPED:
            return {"ok": True, "already": True, "msg": "机器人本来就没有运行"}

    _set_bot_state(BOT_STATE_STOPPING)
    logger.info(f"收到停止指令（{reason}）：正在断开监听并停止全自动回复...")
    bot_stop_event.set()

    with wx_instance_lock:
        wx = wx_instance
        wx_instance = None

    if wx is not None:
        try:
            stop = getattr(wx, "StopListening", None)
            if callable(stop):
                stop(True)
        except Exception as e:
            logger.warning(f"停止微信监听时出现异常（已忽略）: {e}")

    try:
        save_histories()          # 停止前落盘，避免记忆一失
        get_mind_engine().save_all(force=True)   # 内心状态 / 长期记忆立即落盘
    except Exception as e:
            logger.warning(f"停止时保存记忆失败：{e}")

    with queue_lock:
        msg_queue.clear()

    # 等待工作线程真正退出，避免“停止后马上再启动时新旧线程并存
    for name in ("BotMonitor", "QueueWorker", "MindReflect"):
        th = bot_threads.get(name)
        if th and th.is_alive() and th is not threading.current_thread():
            try:
                th.join(timeout=3.0)
            except RuntimeError:
                pass

    _set_bot_state(BOT_STATE_STOPPED, started_at=0.0, last_error="")
    push_activity("停止机器人", "系统", f"已停止自动回复与监听({reason})，记忆已保存", True)
    logger.info("机器人已停止：不会再自动回复任何消息。")
    return {"ok": True, "msg": "机器人已停止，自动回复已关闭"}


def bot_monitor_worker():
    """运行状态巡检：微信掉线或启动失败时按配置自动重连，保持持续运行。"""
    while not bot_stop_event.is_set():
        interval = 20
        try:
            runtime_cfg = get_runtime_config()
            try:
                interval = max(5, int(runtime_cfg.get("monitor_interval", 20)))
            except (TypeError, ValueError):
                interval = 20

            auto_reconnect = runtime_cfg.get("auto_reconnect", True)
            with bot_state_lock:
                state = bot_state.get("state")

            if auto_reconnect and state == BOT_STATE_RUNNING and get_wx() is None:
                logger.warning("检测到微信连接已断开，正在自动重连并恢复监听...")
                result = start_bot(background=False)
                if result.get("ok"):
                    with bot_state_lock:
                        bot_state["reconnect_count"] = bot_state.get("reconnect_count", 0) + 1
                    logger.info("微信已自动重连成功，继续全自动运行。")
                else:
                    logger.warning("自动重连失败，将在下个巡检周期继续尝试。")
            elif auto_reconnect and state == BOT_STATE_ERROR:
                # 典型场景：程序先启动、微信还没登录、还没打开，登录后自动接上继续
                logger.info("机器人处于启动失败状态，正在自动重试连接微信...")
                start_bot(background=False)
        except Exception as e:
            logger.error(f"运行状巡检异常: {e}", exc_info=True)
        _sleep_with_stop(interval)
    logger.info("运行状态巡检线程已退出。")


def mind_reflect_worker():
    """后台沉思线程：没人说话时自己想一想，产出内心独白与当下念头。
    借鉴 Shikigami-Protocol 的 background reflection。
    空闲时的思考会写进 intent，直接影响下一次主动搭话的内容。
    所以主动找他是有内在动机的，不是定时任务硬发。
    """
    logger.info("内心沉思线程已启动（安静时会自己想想对方，影响下一次主动开口）。")
    interval = 600
    while not bot_stop_event.is_set():
        try:
            if _bot_is_running():
                engine = get_mind_engine()
                with persona_lock:
                    users = list((persona_data.get("users") or {}).keys())
                targets = list(chat_histories.keys())
                for uid in users + targets:
                    if bot_stop_event.is_set():
                        break
                    if uid in ("", None):
                        continue
                    try:
                        aff, stage_key, _force = peek_user_stage(uid)
                        thought = engine.reflect(
                            uid, affection=aff, stage_key=stage_key,
                            extractor=mind_llm_extractor)
                        if thought:
                            logger.info(f"[{uid}] 内心独白：{thought}")
                            push_activity("内心独白", uid, thought, True)
                    except Exception as e:
                        logger.debug(f"[{uid}] 沉失败（已忽略）: {e}")
        except Exception as e:
            logger.error(f"内心沉思线程异常：{e}", exc_info=True)
        _sleep_with_stop(interval)
    logger.info("内心沉思线程已退出。")


# ==============================================================================
# Web 可视化控制台 (Flask)
# ==============================================================================
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))
# 关闭 Flask 默认的访问日志干扰控制台
import logging as py_logging
py_logging.getLogger('werkzeug').setLevel(py_logging.WARNING)

@app.route('/')
def web_index():
    return render_template('index.html')

@app.route('/api/get_persona', methods=['GET'])
def api_get_persona():
    with persona_lock:
        return jsonify(persona_data)

@app.route('/api/persona_presets', methods=['GET'])
def api_persona_presets():
    """网页「人设卡片」用的三套人名预设（含完整提示词，直接渲染出来给人看）。"""
    out = []
    with persona_lock:
        cur_name = (persona_data.get("bot_profile") or {}).get("name", "")
        cur_prompts = {k: (v or {}).get("prompt", "")
                       for k, v in (persona_data.get("stages") or {}).items()}
        for p in persona_presets.PERSONA_PRESETS:
            item = {k: v for k, v in p.items() if k != "stages"}
            item["stages"] = p["stages"]
            # 名字和三段提示词都一致，才算「正在用」；撞名不算
            item["is_current"] = (
                cur_name == (p["bot_profile"] or {}).get("name", "")
                and all(cur_prompts.get(k) == p["stages"][k]["prompt"]
                        for k in ("1", "2", "3"))
            )
            out.append(item)
    return jsonify({"ok": True, "presets": out, "current_name": cur_name})


def apply_persona_preset(pid):
    """套用这套预设人设（覆盖 bot_profile 和三段提示词），返回 (ok, msg, nick)。

    这是人设唯一的换人入口：预设卡片和自定义表单写的是同一个 persona.json。
    所以换完之后所有人、所有入口都用新的人设。
    """
    archive_current_persona(reason=u"应用人设预设")
    preset = persona_presets.get_preset((pid or "").strip())
    if not preset:
        return False, u"没有这个人设，请刷新页面重试", ""
    with persona_lock:
        new = persona_presets.preset_to_persona(preset)
        persona_data["bot_profile"] = new["bot_profile"]
        for k, v in new["stages"].items():
            if k in persona_data.get("stages", {}):
                persona_data["stages"][k]["description"] = v["description"]
                persona_data["stages"][k]["prompt"] = v["prompt"]
            else:
                persona_data.setdefault("stages", {})[k] = v
        persona_data["preset_id"] = preset["id"]
        _save_persona_nolock()
    logger.info("已套用人设「%s」（%s）。", preset["nick"], preset["id"])
    return True, "", preset["nick"]


@app.route('/api/apply_persona_preset', methods=['POST'])
def api_apply_persona_preset():
    """网页：点预设卡片就调这里。"""
    try:
        pid = ((request.json or {}).get("preset_id") or "").strip()
        ok, msg, nick = apply_persona_preset(pid)
        if not ok:
            return jsonify({"ok": False, "msg": msg})
        return jsonify({"ok": True, "nick": nick, "id": pid})
    except Exception as e:
        logger.error("套用人设预设出错: %s", e)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/save_persona', methods=['POST'])
def api_save_persona():
    archive_current_persona(reason=u"保存人设")
    try:
        data = request.json or {}
        with persona_lock:
            if "bot_profile" in data:
                persona_data["bot_profile"] = data["bot_profile"]
            if "stages" in data:
                for k, v in data["stages"].items():
                    if k in persona_data.get("stages", {}):
                        persona_data["stages"][k]["description"] = v.get("description", "")
                        persona_data["stages"][k]["prompt"] = v.get("prompt", "")
            # 自己动过就不再算「正在用某套预设」，网页上会取消高亮
            if "bot_profile" in data or "stages" in data:
                persona_data.pop("preset_id", None)
            save_persona()
        logger.info("Web 控制台：伴侣人设及各阶段 Prompt 已保存更新！")
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"保存 Persona 出错: {e}")
        return jsonify({"ok": False, "msg": str(e)})

@app.route('/api/update_user', methods=['POST'])
def api_update_user():
    try:
        data = request.json or {}
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"ok": False, "msg": "user_id 不能为空"})

        with persona_lock:
            users = persona_data.setdefault("users", {})
            if user_id not in users:
                users[user_id] = {"affection": 0, "force_stage": None, "chat_count": 0, "notes": ""}

            if "affection" in data:
                users[user_id]["affection"] = max(0, min(100, int(data["affection"])))
            if "force_stage" in data:
                users[user_id]["force_stage"] = data["force_stage"]
            save_persona()

        logger.info(f"Web 控制台：用户 [{user_id}] 关系数据已更新！")
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"更新用户关系出错: {e}")
        return jsonify({"ok": False, "msg": str(e)})

@app.route('/api/get_contacts', methods=['GET'])
def api_get_contacts():
    """返回可供选择互动的好友列表 + 微信连接状态 + 最近操作日志。"""
    try:
        return jsonify({
            "ok": True,
            "wx_online": get_wx() is not None,
            "wx_nickname": get_wx_nickname(),
            "contacts": get_contact_list(),
            "logs": get_activity_log(10),
        })
    except Exception as e:
        logger.error(f"获取好友列表出错: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e), "contacts": [], "logs": []})

@app.route('/api/send_message', methods=['POST'])
def api_send_message():
    """向选中的好友发送手动输入的消息（后台线程发送，立即返回）。"""
    try:
        data = request.json or {}
        user_id = (data.get("user_id") or "").strip()
        message = (data.get("message") or "").strip()
        humanlike = bool(data.get("humanlike", True))
        count_affection = bool(data.get("count_affection", False))

        if get_wx() is None:
            return jsonify({"ok": False, "msg": "微信尚未连接：请先登录电脑微信并保持机器人程序运行。"})
        if not user_id:
            return jsonify({"ok": False, "msg": "请先选择要发送的好友"})
        if not message:
            return jsonify({"ok": False, "msg": "消息内容不能为空"})

        threading.Thread(
            target=send_wechat_message,
            args=(user_id, message, humanlike, count_affection),
            daemon=True,
            name=f"ManualSend-{user_id}",
        ).start()
        return jsonify({"ok": True, "msg": f"已开始向 [{user_id}] 发：{message}"})
    except Exception as e:
        logger.error(f"发消息接口出错：{e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})

@app.route('/api/ai_outreach', methods=['POST'])
def api_ai_outreach():
    """让 AI 以当前人格主动搭话：send=true 生成后直接发送，否则仅返回内容供编辑。"""
    try:
        data = request.json or {}
        user_id = (data.get("user_id") or "").strip()
        topic = (data.get("topic") or "").strip()
        do_send = bool(data.get("send", False))
        count_affection = bool(data.get("count_affection", True))

        if not user_id:
            return jsonify({"ok": False, "msg": "请先选择要搭话的好友"})
        if do_send and get_wx() is None:
            return jsonify({"ok": False, "msg": "微信尚未连接：请先登录电脑微信并保持机器人程序运行。"})

        message = generate_outreach_message(user_id, topic)
        if not message:
            # 与自动搭话保持同一套说法：写不出合格内容就不硬发，避免发出机器人腔
            reason = "这一轮没能写出过检查的内容，先不打扰 TA（稍后会自动重试）"
            push_activity("AI搭话", user_id, reason, False)
            return jsonify({"ok": False, "reason": reason, "msg": reason})

        if not do_send:
            push_activity("AI搭话", user_id, f"已生成待确认内容：{message}", True)
            _cfg, _rt = get_auto_chat_config()
            ctx = fetch_wechat_context(user_id, limit=int(_cfg.get("context_rounds") or 20))
            return jsonify({"ok": True, "message": message, "sent": False,
                            "context": describe_context(ctx)})

        def _send_and_remember():
            ok, _info = send_wechat_message(user_id, message, True, count_affection)
            if ok:
                remember_auto_sent(user_id, message)

        threading.Thread(
            target=_send_and_remember,
            daemon=True,
            name=f"AIOutreach-{user_id}",
        ).start()
        push_activity("AI搭话", user_id, f"AI 主动搭话已发送：{message}", True)
        return jsonify({"ok": True, "message": message, "sent": True})
    except Exception as e:
        logger.error(f"AI 主动搭话出错: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": f"生成失败：{e}"})


@app.route('/api/get_auto_chat', methods=['GET'])
def api_get_auto_chat():
    """返回自动搭话的配置运行状态与统计。"""
    try:
        cfg, _ = get_auto_chat_config()
        cfg = dict(cfg)
        cfg["targets"] = get_auto_chat_targets(cfg)
        cfg.pop("topics_full", None)
        return jsonify({"ok": True, "config": cfg, "status": get_auto_chat_status()})
    except Exception as e:
        logger.error(f"获取自动搭话配置出错: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/save_auto_chat', methods=['POST'])
def api_save_auto_chat():
    """保存自动搭话设置（开关、间隔、活跃时段、上限、话题池等）。"""
    try:
        data = request.json or {}
        cfg = save_auto_chat_config(data)
        status = get_auto_chat_status()
        push_activity("自动搭话设置", "系统",
                      f"{'已开启' if cfg.get('enabled') else '已关闭'}，间隔{cfg['interval_minutes']} 分钟"
                      f"活跃时段 {cfg['active_start']}:00-{cfg['active_end']}:00"
                      f"对象 {len(status['targets'])} 个", True)
        return jsonify({"ok": True, "config": cfg, "status": status})
    except Exception as e:
        logger.error(f"保存自动搭话设置出错: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/auto_chat_now', methods=['POST'])
def api_auto_chat_now():
    """立即执行这次自动搭话（AI 生成 + 自动发送，用于测试效果）。"""
    try:
        if get_wx() is None:
            return jsonify({"ok": False, "msg": "微信尚未连接：请先登录电脑微信并保持机器人程序运行。"})
        targets = get_auto_chat_targets()
        if not targets:
            return jsonify({"ok": False, "msg": "还没有可自动搭话的好友，请先在好友卡片上点击 🤖 加入"})
        run_auto_chat_now_async()
        return jsonify({"ok": True, "msg": f"已开始自动搭话（本轮候：{ ''.join(targets[:5]) }），稍后查看操作日志"})
    except Exception as e:
        logger.error(f"立即自动搭话出错: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/set_auto_target', methods=['POST'])
def api_set_auto_target():
    """把某个好友加入 / 移出自动搭话名单。"""
    try:
        data = request.json or {}
        user_id = (data.get("user_id") or "").strip()
        auto = bool(data.get("auto", True))
        if not user_id:
            return jsonify({"ok": False, "msg": "缺少好友名称"})
        cfg = set_auto_target(user_id, auto)
        status = get_auto_chat_status()
        return jsonify({
            "ok": True,
            "msg": f"已将 [{user_id}] {'加入' if auto else '移出'}自动搭话名单",
            "targets": status["targets"],
        })
    except Exception as e:
        logger.error(f"更新自动搭话名单出错: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/get_wechat_context', methods=['GET'])
def api_get_wechat_context():
    """查看机器人从本地微信数据库读到的真实聊天记录（前端可直接核对上下文）。"""
    try:
        user_id = (request.args.get("user_id") or "").strip()
        if not user_id:
            return jsonify({"ok": False, "msg": "请先选择要查看的好友"})
        if get_wx() is None:
            return jsonify({"ok": False, "msg": "微信尚未连接：请先登录电脑微信并保持机器人程序运行。"})
        try:
            limit = max(4, min(100, int(request.args.get("limit") or 30)))
        except (TypeError, ValueError):
            limit = 30
        clear_context_cache(user_id)
        ctx = fetch_wechat_context(user_id, limit=limit)
        return jsonify({
            "ok": True,
            "context": ctx,
            "summary": describe_context(ctx),
            "lines": render_context_lines(ctx, limit),
        })
    except Exception as e:
        logger.error(f"读取微信上下文出错：{e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


def _mask_provider_secrets(cfg):
    """抹掉 Provider 配置里的密钥明文，再往前端送。

    Web 控制台只监听 127.0.0.1，但密钥明文仍然没必要出现在 HTTP 响应里：
    浏览器 DevTools、代理、截图都可能把它带出去。
    前端只需要知道「配没配」，所以只回一个 has_api_key 标记。
    """
    if not isinstance(cfg, dict):
        return cfg
    out = dict(cfg)
    out["has_api_key"] = bool(out.get("api_key"))
    out["api_key"] = ""
    return out


@app.route('/api/llm/providers', methods=['GET'])
def api_llm_list_providers():
    """获取所有已配置的模型 Provider 列表及当前激活的模型。"""
    try:
        providers = [_mask_provider_secrets(p) for p in llm.list_all_providers()]
        active_id = llm.config_manager.get_active_provider_id()
        return jsonify({
            "ok": True,
            "active_provider": active_id,
            "providers": providers
        })
    except Exception as e:
        logger.error(f"获取 Provider 列表失败: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/llm/switch', methods=['POST'])
def api_llm_switch_provider():
    """热切换当前激活的模型 Provider"""
    try:
        data = request.json or {}
        provider_id = (data.get("provider_id") or "").strip()
        if not provider_id:
            return jsonify({"ok": False, "msg": "Provider ID 不能为空"})
        success = llm.switch_provider(provider_id)
        if success:
            return jsonify({
                "ok": True,
                "msg": f"已成功切换模型 Provider 为 [{provider_id}]。",
                "active_config": _mask_provider_secrets(llm.get_active_provider_info())
            })
        return jsonify({"ok": False, "msg": f"未找到指定的 Provider [{provider_id}]"})
    except Exception as e:
        logger.error(f"切换 Provider 失败: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/llm/save_provider', methods=['POST'])
def api_llm_save_provider():
    """新增或修改 Provider 配置（可配置 name, base_url, api_key, model, temperature, max_tokens）。"""
    try:
        data = request.json or {}
        provider_id = (data.get("id") or "").strip()
        if not provider_id:
            return jsonify({"ok": False, "msg": "Provider ID 不能为空"})
        
        saved = llm.update_provider_config(provider_id, data)
        return jsonify({
            "ok": True,
            "msg": f"Provider [{provider_id}] 配置已保存。",
            "provider": _mask_provider_secrets(saved)
        })
    except Exception as e:
        logger.error(f"保存 Provider 失败: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


# ==============================================================================
# 机器人运行控制 API（一次配置，启动即运行）
# ==============================================================================
@app.route('/api/bot/status', methods=['GET'])
def api_bot_status():
    """返回机器人运行时状态：是否运行中、微信连接、已自动收发的消息数、记忆量等。"""
    try:
        return jsonify(get_bot_status())
    except Exception as e:
        logger.error(f"获取机器人状态失败：{e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/listen/list', methods=['GET'])
def api_listen_list():
    """网页读取监听名单（只管跟谁聊；人设在另一处统一设置）。"""
    mode, items = load_listen_list()
    status = get_bot_status()
    return jsonify({
        "ok": True,
        "mode": mode,
        "items": [{"nickname": n} for n in items],
        "store_file": os.path.basename(listen_store_file),
        "running": bool(status.get("running")),
        "listen_targets": status.get("listen_targets") or [],
        "listen_failed": status.get("listen_failed") or [],
    })


@app.route('/api/listen/save', methods=['POST'])
def api_listen_save():
    """网页保存监听名单：写文件 + 立刻生效 + 重新订阅（不用重启）。"""
    try:
        data = request.get_json(silent=True) or {}
        mode = data.get("mode", "whitelist")
        items = data.get("items")
        if not isinstance(items, list):
            return jsonify({"ok": False, "msg": "名单格式不对"}), 400

        saved_mode, clean = save_listen_list(mode, items)
        sub = resubscribe_listeners()

        failed = sub.get("failed") or []
        ok = sub.get("ok") or []
        if failed:
            msg = u"名单已保存，但有 %d 个人没听上：%s" % (len(failed), "、".join(failed))
        elif sub.get("resubscribed"):
            msg = u"已保存并重新订阅成功：%s" % ("、".join(ok) if ok else "完成")
        else:
            msg = u"已保存：%s" % sub.get("reason", "")
        return jsonify({
            "ok": True, "msg": msg,
            "mode": saved_mode,
            "items": clean,
            "resubscribed": bool(sub.get("resubscribed")),
            "listen_targets": ok, "listen_failed": failed,
            "status": get_bot_status(),
        })
    except Exception as e:
        logger.error(f"保存监听名单失败: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": f"保存失败：{e}"}), 500


@app.route('/api/bot/start', methods=['POST'])
def api_bot_start():
    """点击「启动机器人」：自动连接微信 -> 自动监听 -> 全自动回复（无需再手动触发）。"""
    try:
        result = start_bot(background=True)
        return jsonify({
            "ok": True,
            "already": bool(result.get("already")),
            "msg": result.get("msg"),
            "status": get_bot_status(),
        })
    except Exception as e:
        logger.error(f"启动机器人失败：{e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/bot/stop', methods=['POST'])
def api_bot_stop():
    """点击「停止机器人」：断开监听并关闭自动回复（记忆自动落盘）。"""
    try:
        result = stop_bot(reason="网页控制台点击停止")
        return jsonify({"ok": True, "msg": result.get("msg"), "status": get_bot_status()})
    except Exception as e:
        logger.error(f"停止机器人失败：{e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/bot/save_runtime', methods=['POST'])
def api_bot_save_runtime():
    """保存运行模式配置（开机自动启动 / 自动回复 / 自动存记忆 / 重连等），立即生效并持久化。"""
    try:
        data = request.json or {}
        cfg = save_runtime_config(data)
        return jsonify({"ok": True, "runtime": cfg, "status": get_bot_status()})
    except Exception as e:
        logger.error(f"保存运行配置失败: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/mind/state', methods=['GET'])
def api_mind_state():
    """内心世界快照：情绪 / 精力 / 说话意愿 / 人格 / 关系维度 / 记忆 / 内心独白。"""
    try:
        user_id = (request.args.get('user_id') or '').strip()
        if not user_id:
            with bot_state_lock:
                user_id = bot_state.get("last_message_from") or ""
        if not user_id:
            with persona_lock:
                users = list((persona_data.get("users") or {}).keys())
            user_id = users[0] if users else ""
        if not user_id:
            return jsonify({"ok": True, "user_id": "", "snapshot": None,
                            "msg": "还没有聊天对象，开始聊天后这里就会出现 TA 的内心状态。"})
        aff, stage_key, _force = peek_user_stage(user_id)
        snap = get_mind_engine().snapshot(user_id, stage_key=stage_key, affection=aff)
        snap["token_stats"] = token_stats.snapshot()
        return jsonify({"ok": True, "user_id": user_id, "snapshot": snap})
    except Exception as e:
        logger.error(f"读取内心世界失败: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/mind/forget', methods=['POST'])
def api_mind_forget():
    """手动忘记这条记忆（或整个好友的全部记忆，user_id + all=True）。"""
    try:
        data = request.json or {}
        user_id = (data.get("user_id") or "").strip()
        if not user_id:
            return jsonify({"ok": False, "msg": "缺少 user_id"})
        engine = get_mind_engine()
        if data.get("all"):
            engine.purge_friend(user_id)
            return jsonify({"ok": True, "msg": f"已经彻底忘记 [{user_id}] 的全部记忆与内心状态。"})
        ok = engine.forget_memory(user_id, data.get("item_id"))
        return jsonify({"ok": bool(ok),
                        "msg": "已忘记这条记忆" if ok else "没找到这条记忆(可能已被清理)"})
    except Exception as e:
        logger.error(f"忘记记忆失败: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/mind/reflect', methods=['POST'])
def api_mind_reflect():
    """立即触发这次内心沉思（网页上的「现在想想 TA」按钮）。"""
    try:
        data = request.json or {}
        user_id = (data.get("user_id") or "").strip()
        if not user_id:
            return jsonify({"ok": False, "msg": "缺少 user_id"})
        aff, stage_key, _force = peek_user_stage(user_id)
        thought = get_mind_engine().reflect(
            user_id, affection=aff, stage_key=stage_key,
            extractor=mind_llm_extractor, force=True)
        if thought:
            push_activity("内心独白", user_id, thought, True)
        return jsonify({"ok": True, "thought": thought or "",
                        "msg": thought or "这次什么也没想出来"})
    except Exception as e:
        logger.error(f"触发内心沉思失败：{e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


@app.route('/api/mind/save_schedule', methods=['POST'])
def api_mind_save_schedule():
    """保存生命节律（作息表 / 静默时段 / 主动节奏 / 每日上限）。
    先校验再写入：非法时间或非法节奏一律不落盘，避免作息表被写坏之后
    「半夜突然发消息」这类很难排查的问题。
    """
    try:
        data = request.json or {}
        user_id = (data.get("user_id") or "").strip()
        if not user_id:
            return jsonify({"ok": False, "msg": "缺少 user_id"})
        engine = get_mind_engine()
        fs = engine.friend_state(user_id)
        schedule = fs.setdefault("state").setdefault("schedule", {})

        patch = {}
        if "enabled" in data:
            patch["enabled"] = bool(data.get("enabled"))
        for key in ("quiet_start", "quiet_end"):
            if key in data:
                patch[key] = str(data.get(key) or "").strip()
        if "cadence" in data:
            patch["cadence"] = str(data.get("cadence") or "").strip()
        if "max_daily_messages" in data:
            patch["max_daily_messages"] = data.get("max_daily_messages")

        merged = dict(schedule)
        merged.update(patch)
        error = mind.state_mod.validate_schedule(merged)
        if error:
            return jsonify({"ok": False, "msg": error, "schedule": schedule})

        schedule.update(patch)
        if "max_daily_messages" in patch:
            try:
                schedule["max_daily_messages"] = max(0, int(
                    patch["max_daily_messages"]))
            except (TypeError, ValueError):
                schedule["max_daily_messages"] = 6
        engine.save_state(force=True)
        return jsonify({"ok": True, "schedule": schedule,
                        "msg": u"作息已保存：静默 %s ~ %s，节奏 %s" % (
                            schedule.get("quiet_start"), schedule.get("quiet_end"),
                            schedule.get("cadence"))})
    except Exception as e:
        logger.error(f"保存作息失败: {e}", exc_info=True)
        return jsonify({"ok": False, "msg": str(e)})


def _wait_port_open(port, timeout=25.0):
    """等待 Web 端口真正开始监听，避免浏览器过早打开导致「一开始连不上」"""
    import socket, time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def _open_browser_when_ready(port):
    if _wait_port_open(port):
        webbrowser.open(f"http://127.0.0.1:{port}")


def _create_web_server(host, port):
    """创建独占端口的 Web 服务器；端口被占时返回 None。

    问题背景：
      Werkzeug 的 BaseWSGIServer 默认 allow_reuse_address = True，
      在 Windows 上 socket 会被设成 SO_REUSEADDR，结果是——
      第二个实例 bind() 时不会报「端口被占用」，而是直接抢占端口，
      第一个实例的连接被抢走，表现就是「重复启动后服务时好时坏、
      消息收不到、日志莫名其妙」。

    做法：
      1) 关掉 allow_reuse_address，端口被占时 bind() 直接抛 OSError；
      2) 启动前先探测端口，给出「已有实例在运行 / 被别的程序占用」的明确提示；
      3) 第二个实例明确退出（返回码 1），不跟第一个实例抢。
    """
    from werkzeug.serving import ThreadedWSGIServer, WSGIRequestHandler

    class ExclusiveWSGIServer(ThreadedWSGIServer):
        allow_reuse_address = False   # 关键：不允许第二个实例复用同一端口
        daemon_threads = True

    # 先探测端口占用情况，好给出人话提示
    probe_msg = _probe_port(host, port)
    if probe_msg:
        logger.error(probe_msg)
        print("")
        print("!" * 58)
        print("  [启动失败] %s" % probe_msg)
        print("!" * 58)
        print("")
        return None

    try:
        # 注意：make_server() 不接受「服务器类」参数，所以这里直接实例化
        server = ExclusiveWSGIServer(host, port, app, WSGIRequestHandler)
    except OSError as e:
        msg = f"端口 {port} 被占用（{e}），无法启动 Web 控制台。"
        logger.error(msg)
        print("")
        print("!" * 58)
        print("  [启动失败] %s" % msg)
        print("  解决办法：")
        print("    1) 如果机器人已经在运行，直接用浏览器访问 http://%s:%s" % (host, port))
        print("    2) 或者在 config.py 里把 WEB_UI_PORT 改成别的端口")
        print("!" * 58)
        print("")
        return None

    return server


def _probe_port(host, port):
    """返回端口不可用的原因描述；端口可用则返回 None。

    先试着连一下：能连上说明已经有实例在跑，提示最准确；
    连不上再试着 bind：bind 失败说明被别的程序占着。
    """
    import socket

    # 1) 连一下：连得上 = 已经有服务在跑
    for addr in [(host, port), ("127.0.0.1", port)]:
        try:
            with socket.create_connection(addr, timeout=1.0):
                return (f"端口 {port} 上已经有一个服务在运行"
                        f"（机器人可能已经启动过了），"
                        f"请直接访问 http://{host}:{port}")
        except OSError:
            continue

    # 2) bind 一下：bind 不了 = 被别的程序占了
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # 故意不设 SO_REUSEADDR，才能如实反映「端口已被占」
            s.bind((host, port))
        except OSError as e:
            return f"端口 {port} 已被其他程序占用（{e}），无法启动 Web 控制台。"
        finally:
            s.close()
    except OSError as e:
        return f"端口 {port} 无法绑定：{e}"
    return None


def _serve_web_server(server, host, port):
    """在后台线程里跑 Web 服务器。"""
    logger.info(f"Web 人格控制台启动于: http://{host}:{port}")
    if getattr(config, "AUTO_OPEN_BROWSER", True):
        threading.Thread(target=_open_browser_when_ready, args=(port,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Web 控制台已停止")
    finally:
        try:
            server.server_close()
        except Exception:
            pass


def run_web_server():
    """兼容旧调用：自己创建服务器再跑起来。"""
    port = getattr(config, "WEB_UI_PORT", 5000)
    host = getattr(config, "WEB_UI_HOST", "127.0.0.1")
    server = _create_web_server(host, port)
    if server is None:
        return 1   # 端口被占：明确退出，别跟已有实例抢
    _serve_web_server(server, host, port)
    return 0


def main():
    print("=" * 60)
    print("      微信小号聊天机器人（极简版）      ")
    print(f"  当前监听模式: {config.LISTEN_MODE}")
    if config.LISTEN_MODE == "whitelist":
        print(f"  白名单列表： {get_listen_names()}")
    else:
        print("  全私聊监听： 开启（只要有人私聊即自动回复）")
    print(f"  视觉识别: 图片={'开启' if config.ENABLE_IMAGE_VISION else '关闭'}, "
          f"表情={'开启' if config.ENABLE_EMOJI_VISION else '关闭'}")
    print("=" * 60)

    # 配置阶段：加载一次配置（人设 / 模型 / 上下文 / 自动回复规则）
    load_persona()
    load_histories()
    # 拟人化节奏层配置灌进 pacing（时间感 / 打字延迟 / 分段 / 主动搭话节律）
    apply_humanize_config()

    runtime_cfg = get_runtime_config()
    # 命令行参数 --start：仅本次运行立即启动机器人（不写回持久化配置）
    cli_start = "--start" in sys.argv
    try:
        provider_name = llm.get_active_provider_info().get("name") or llm.get_active_provider_info().get("id") or "-"
    except Exception:
        provider_name = "-"
    _mode = ('这次配置，启动即运行（自动启动）'
             if (runtime_cfg.get('auto_start', False) or '--start' in sys.argv)
             else '手动启动（需在网页点「启动」）')
    print(f"  运行模式: {_mode}")
    _ar = ('开启（收到消息即自动生成并发送，无需人工触发）'
           if runtime_cfg.get('auto_reply', True)
           else '关闭（仅监听不回复）')
    print(f"  自动回复: {_ar}")
    print(f"  当前模型: {provider_name}")
    print(f"  自动存记忆： {'开启' if runtime_cfg.get('auto_save_memory', True) else '关闭'}")
    try:
        _engine = get_mind_engine()
        with _engine.store.state_lock:
            _friends = list((_engine.store.state.get("friends") or {}).keys())
        print(f"  内心世界: 已加载情绪/人格/内部状态（{len(_friends)} 位好友有内心记录）")
        print(f"  长期记忆: 已加载多层记忆（事实/共同经历/压缩摘要）")
        # 人设改过之后，把历史锚定里的旧身份纠正过来
        sync_anchoring_with_persona()
    except Exception as e:
        logger.warning(f"加载内心世界失败（将退化为无内心状态模式）: {e}")
    print("=" * 60)

    # 自动主动搭话调度线程（是否真正发送由网页控制台的开关决定）
    start_auto_chat_worker()

    if getattr(config, "ENABLE_WEB_UI", True):
        # 先在主线程里把端口占住再开线程：重复启动时第二个实例直接退出，
        # 不会跟第一个实例抢端口（以前 Werkzeug 允许复用端口，第二个实例
        # 会悄悄把端口抢走，第一个实例的网页就废了）
        _web_host = getattr(config, "WEB_UI_HOST", "127.0.0.1")
        _web_port = getattr(config, "WEB_UI_PORT", 5000)
        _web_server = _create_web_server(_web_host, _web_port)
        if _web_server is None:
            logger.error("Web 端口不可用，程序退出（避免与已运行的实例冲突）。")
            sys.exit(1)
        web_th = threading.Thread(target=_serve_web_server,
                                  args=(_web_server, _web_host, _web_port),
                                  daemon=True, name="WebUIServer")
        web_th.start()

    # 运行阶段：启动后全自动运行（连微信 -> 监听 -> 读上下文 -> 调模型 -> 回复 -> 存记忆）
    if cli_start or runtime_cfg.get("auto_start", False):
        if cli_start and not runtime_cfg.get("auto_start", False):
            logger.info("检测到一键启动参数 --start：立即自动连接微信并进入全自动运行模式...")
        else:
            logger.info("检测到已开启开机自动启动：立即自动连接微信并进入全自动运行模式...")
        start_bot(background=True)
    else:
        logger.info("未开启开机自动启动：请打开网页控制台，点击「启动机器人」后才开始工作。")

    logger.info("程序已就绪并持续运行中（自动监听 + 自动回复）；按 Ctrl+C 可安全退出。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到中断信号，程序正在安全退出…")
    finally:
        try:
            stop_bot(reason="程序退出")
        except Exception as e:
            logger.warning(f"退出时停止机器人失败（已忽略）: {e}")
        save_histories()
        try:
            get_mind_engine().save_all(force=True)   # 内心状与长期记忆落盘
        except Exception as e:
            logger.warning(f"退出时保存内心世界失败（已忽略）：{e}")

if __name__ == "__main__":
    main()
