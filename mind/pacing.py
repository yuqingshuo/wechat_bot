# -*- coding: utf-8 -*-
"""拟人化「节奏层」：真实时间感、打字延迟节奏、分段发送、去抖等待、主动搭话节律。

对照 AstrBot 的 `wanna_be_human.json` 配置，把里面跟「时间 / 打字 / 主动搭话」
有关的规则补齐到这个项目里。原先这些行为散落在 main.py 的几个硬编码常量中
（固定 5 秒合并窗口、固定 35 字分段、固定 2 小时间隔），这里统一收口成
可配置、可单测的一层。

参考配置对照：
    time.enable_gap / gap_threshold_minutes -> gap_minutes()
    time.include_wall_clock / include_calendar -> wall_clock_line() / calendar_line()
    time.rhythm_* -> rhythm_delay()
    time.include_last_chat -> last_chat_hint()
    typing.delay_min / delay_max -> typing_delay()
    typing.split_* -> split_reply()
    typing.debounce_* / adaptive_* -> adaptive_debounce()
    typing.total_delay_cap -> TOTAL_DELAY_CAP
    proactive.silence_after_minutes / fluctuation -> silence_minutes()
    proactive.silence_scale_* -> scaled_silence_minutes()
    proactive.topic_mode / weights -> pick_topic()
    proactive.topic_repeat_cooldown_days -> topic_cooldown_ok()
    proactive.pout_on_unanswered / max_unanswered -> pout_state()
    parrot.* -> parrot_decision()
"""
import random
import time
from datetime import datetime, timedelta

# ==============================================================================
# 一、配置（默认值与 wanna_be_human.json 对齐）
# ==============================================================================

TIME_CFG = {
    "enable_gap": True,
    "gap_threshold_minutes": 30,      # 超过多久算「隔了一段」
    "include_wall_clock": True,       # 提示词里带真实钟点
    "include_calendar": True,         # 提示词里带日期/星期
    "include_last_chat": True,        # 提示词里带「上次聊天是什么时候」
    "rhythm_enable": True,            # 冷热节奏（热=秒回，冷=隔一会儿才回）
    "rhythm_hot_ratio": 0.2,          # 20% 的消息走「热」节奏
    "rhythm_cold_ratio": 0.667,
    "rhythm_delay_hot_min": 1.5,
    "rhythm_delay_hot_max": 4.0,
    "rhythm_delay_cold_min": 10.0,
    "rhythm_delay_cold_max": 25.0,
}

TYPING_CFG = {
    "enable": True,
    "delay_min": 0.0,                 # 附加随机延迟下限（秒）
    "delay_max": 0.0,
    "total_delay_cap": 90.0,          # 单条消息总等待上限（秒）
    "split_enable": True,
    "split_threshold": 40,            # 超过多少字才拆成多条
    "split_max_segments": 3,
    "split_min_part": 8,              # 每段至少多少字，太短就并回上一段
    "split_gap_min": 0.5,             # 段与段之间的停顿（秒）
    "split_gap_max": 3.0,
    "split_gap_long_prob": 0.2,       # 概率触发「长停顿」（像走神了）
    "split_gap_long_min": 4.0,
    "split_gap_long_max": 8.0,
    "debounce_enable": True,
    "enable_adaptive_debounce": True,
    "adaptive_min_wait": 1.0,         # 短消息等得少
    "adaptive_max_wait": 6.0,         # 长消息等得多
    "adaptive_max_total_wait": 12.0,  # 一轮合并等待的总上限
    "adaptive_short_message_threshold": 10,  # 短于这个字数的算「短消息」
    "max_session_wait": 60.0,
}

PROACTIVE_CFG = {
    "silence_after_minutes": 45,      # 对方静默多久之后才考虑主动开口
    "silence_fluctuation_minutes": 15,  # 静默阈值的随机浮动
    "silence_scale_enable": True,     # 越久不聊越难主动开口
    "silence_scale_step": 0.3,
    "silence_scale_cap_minutes": 240,
    "pout_on_unanswered": True,       # 对方一直不回就赌气
    "max_unanswered": 6,
    "topic_mode": "mixed",            # mixed / random / history / life / preset
    "topic_weights": "history=4,life=3,preset=3",
    "topic_repeat_cooldown_days": 7,  # 同一个话题 N 天内不重复
    "followup_enable": False,         # 主动发完没回，追问一句
    "followup_prob": 0.6,
    "followup_delay_min_minutes": 12,
    "followup_delay_max_minutes": 20,
    "followup_max_unanswered": 2,
}

PARROT_CFG = {
    "enabled": True,
    "judge_threshold": 7,             # 短于这个长度不复读
    "prob": 0.06,
    "prob_normal": 0.0,
    "cooldown_turns": 8,              # 隔多少轮才复读一次
    "max_per_day": 3,
    "min_len": 1,
    "max_len": 24,
    "allow_groups": False,
}

# 中文星期
_WEEKDAYS = [u"周一", u"周二", u"周三", u"周四", u"周五", u"周六", u"周日"]

# 一天里大致的人话（用来把钟点翻译成「早上好/这么晚了」）
_DAY_PERIODS = (
    (0, 5, u"凌晨"),
    (5, 9, u"早上"),
    (9, 12, u"上午"),
    (12, 14, u"中午"),
    (14, 18, u"下午"),
    (18, 23, u"晚上"),
    (23, 24, u"半夜"),
)


def _now_dt(now=None):
    if isinstance(now, datetime):
        return now
    return datetime.now()


def _f(cfg, key, default=None):
    """从配置字典里取值，容错（配置可能来自网页 JSON，类型不稳）。"""
    try:
        val = (cfg or {}).get(key, default)
    except AttributeError:
        val = default
    if val is None:
        val = default
    return val


def apply_config(cfg):
    """把外部配置（config.HUMANIZE 或网页保存的副本）合并进本模块的默认值。

    只覆盖出现过的键，所以缺字段不会把默认值抹掉。
    返回合并后的四份配置。
    """
    if not isinstance(cfg, dict):
        return (TIME_CFG, TYPING_CFG, PROACTIVE_CFG, PARROT_CFG)
    for section, target in (("time", TIME_CFG), ("typing", TYPING_CFG),
                            ("proactive", PROACTIVE_CFG), ("parrot", PARROT_CFG)):
        sub = cfg.get(section)
        if isinstance(sub, dict):
            for k, v in sub.items():
                if isinstance(v, dict):
                    continue
                target[k] = v
    return (TIME_CFG, TYPING_CFG, PROACTIVE_CFG, PARROT_CFG)


def get_time_cfg():
    return TIME_CFG


def get_typing_cfg():
    return TYPING_CFG


def get_proactive_cfg():
    return PROACTIVE_CFG


def get_parrot_cfg():
    return PARROT_CFG


def day_period(now=None):
    """返回当前时段的人话标签（凌晨/早上/上午/中午/下午/晚上/半夜）。"""
    hour = _now_dt(now).hour
    for lo, hi, label in _DAY_PERIODS:
        if lo <= hour < hi:
            return label
    return u"白天"


def wall_clock_line(now=None):
    """真实钟点，例如「现在是 14:35」。给提示词用，让模型不会把时间说错。"""
    if not _f(TIME_CFG, "include_wall_clock", True):
        return ""
    dt = _now_dt(now)
    return u"现在是 %02d:%02d（%s）" % (dt.hour, dt.minute, day_period(dt))


def calendar_line(now=None):
    """真实日期，例如「今天是 2026年10月21日 周三」。"""
    if not _f(TIME_CFG, "include_calendar", True):
        return ""
    dt = _now_dt(now)
    return u"今天是 %d年%d月%d日 %s" % (
        dt.year, dt.month, dt.day, _WEEKDAYS[dt.weekday()])


def format_last_chat(ts, now=None):
    """把「上次聊天时间戳」翻译成一句人话。"""
    try:
        ts = float(ts or 0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    now_ts = now.timestamp() if isinstance(now, datetime) else time.time()
    diff = now_ts - ts
    if diff < 0:
        diff = 0.0
    minutes = int(diff / 60.0)
    if minutes < 1:
        return u"刚刚才聊过"
    if minutes < 60:
        return u"上次聊天是 %d 分钟前" % minutes
    hours = minutes / 60.0
    if hours < 24:
        return u"上次聊天是 %.1f 小时前" % hours
    days = hours / 24.0
    if days < 30:
        return u"上次聊天是 %.1f 天前" % days
    return u"上次聊天是 %.0f 天前" % days


def gap_minutes_since(last_ts, now=None):
    """距上次聊天过了多少分钟（没有记录返回 None）。"""
    try:
        last_ts = float(last_ts or 0)
    except (TypeError, ValueError):
        return None
    if last_ts <= 0:
        return None
    now_ts = now.timestamp() if isinstance(now, datetime) else time.time()
    return max(0.0, (now_ts - last_ts) / 60.0)


# ==============================================================================
# 二、节奏与打字延迟
# ==============================================================================

def rhythm_pick(now=None):
    """决定这一轮走「热」还是「冷」节奏。

    热 = 对方刚说完就秒回（微信里最常见的形态）；
    冷 = 隔了一小会儿才回，像刚看到消息。
    """
    if not _f(TIME_CFG, "rhythm_enable", True):
        return "hot"
    roll = random.random()
    hot_ratio = float(_f(TIME_CFG, "rhythm_hot_ratio", 0.2) or 0)
    cold_ratio = float(_f(TIME_CFG, "rhythm_cold_ratio", 0.667) or 0)
    if roll < hot_ratio:
        return "hot"
    if roll < hot_ratio + cold_ratio:
        return "cold"
    return "mid"


def rhythm_delay(now=None, cfg=None):
    """返回本轮「发第一条之前的等待秒数」（冷热节奏）。"""
    cfg = cfg or TIME_CFG
    if not _f(cfg, "rhythm_enable", True):
        return 0.0
    mode = rhythm_pick(now)
    if mode == "hot":
        lo = float(_f(cfg, "rhythm_delay_hot_min", 1.5) or 0)
        hi = float(_f(cfg, "rhythm_delay_hot_max", 4.0) or 0)
    elif mode == "cold":
        lo = float(_f(cfg, "rhythm_delay_cold_min", 10.0) or 0)
        hi = float(_f(cfg, "rhythm_delay_cold_max", 25.0) or 0)
    else:
        hot_hi = float(_f(cfg, "rhythm_delay_hot_max", 4.0) or 0)
        cold_lo = float(_f(cfg, "rhythm_delay_cold_min", 10.0) or 0)
        lo = hot_hi
        hi = max(lo, cold_lo)
    if hi <= lo:
        return max(0.0, lo)
    return random.uniform(lo, hi)


def typing_delay(text, cfg=None):
    """单条消息的「正在输入」延迟（秒）。

    真人打字速度大致跟字数成正比，但长消息开头会慢一点，
    所以这里用 sqrt 而不是线性——线性会让 60 字的消息等 7 秒，太假。
    """
    cfg = cfg or TYPING_CFG
    if not _f(cfg, "enable", True):
        return 0.0
    try:
        n = len((text or "").strip())
    except Exception:
        n = 0
    base = min(6.0, 0.35 * (n ** 0.55))
    extra_min = float(_f(cfg, "delay_min", 0.0) or 0)
    extra_max = float(_f(cfg, "delay_max", 0.0) or 0)
    if extra_max > extra_min:
        base += random.uniform(extra_min, extra_max)
    else:
        base += extra_min
    return max(0.0, base)


def clamp_total_delay(delay, cfg=None):
    """把单条延迟压到 total_delay_cap 以内（别让对方等太久）。"""
    cfg = cfg or TYPING_CFG
    cap = float(_f(cfg, "total_delay_cap", 90.0) or 0)
    if cap <= 0:
        return max(0.0, delay)
    return max(0.0, min(delay, cap))




def split_gap(cfg=None, rng=None):
    """两段之间的停顿（秒）：偶尔来一次「长停顿」，像走神了。"""
    cfg = cfg or TYPING_CFG
    rng = rng or random
    lo = float(_f(cfg, "split_gap_min", 0.5) or 0)
    hi = float(_f(cfg, "split_gap_max", 3.0) or 0)
    if hi <= lo:
        gap = lo
    else:
        gap = rng.uniform(lo, hi)
    prob = float(_f(cfg, "split_gap_long_prob", 0.2) or 0)
    if prob > 0 and rng.random() < prob:
        lmin = float(_f(cfg, "split_gap_long_min", 4.0) or 0)
        lmax = float(_f(cfg, "split_gap_long_max", 8.0) or 0)
        if lmax > lmin:
            gap = max(gap, rng.uniform(lmin, lmax))
    return max(0.0, gap)


def _split_points(text):
    """找出可以断句的位置：逗号、句号、顿号、问号、感叹号、空格。"""
    points = []
    for i, ch in enumerate(text):
        if ch in u"，。！？；、,.!?; ":
            points.append(i)
    return points


def _cap_segments(parts, max_segments):
    if len(parts) <= max_segments:
        return parts
    head = parts[:max_segments - 1]
    tail = u"，".join(parts[max_segments - 1:])
    return head + [tail]



def split_reply(text, cfg=None):
    """把一条长回复拆成若干条「分开发送」的短消息。

    规则（对齐 wanna_be_human.json 的 typing.split_*）：
      - 超过 split_threshold 字才拆，短消息原样发一条；
      - 在标点处断，且断点尽量均匀分布，不会全挤在开头；
      - 每段至少 split_min_part 字，太短的碎片并回上一段；
      - 最多 split_max_segments 段，多出来的合并进最后一段。
    """
    cfg = cfg or TYPING_CFG
    raw = (text or "").strip()
    if not raw:
        return []
    if not _f(cfg, "split_enable", True):
        return [raw]

    threshold = int(_f(cfg, "split_threshold", 40) or 40)
    max_segments = max(1, int(_f(cfg, "split_max_segments", 3) or 3))
    min_part = max(0, int(_f(cfg, "split_min_part", 8) or 0))

    # 先按已有换行切
    lines = [ln.strip() for ln in raw.replace(u"\\", u"\n").split(u"\n") if ln.strip()]
    if len(lines) > 1:
        return _cap_segments(lines, max_segments)

    if len(raw) <= threshold:
        return [raw]

    points = _split_points(raw)
    if not points:
        return _cap_segments([raw], max_segments)

    target = len(raw) / float(max_segments)
    cuts, used = [], set()
    for seg_idx in range(1, max_segments):
        ideal = target * seg_idx
        best = None
        for p in points:
            if p in used or p <= 0 or p >= len(raw):
                continue
            if p - (cuts[-1] if cuts else 0) < min_part:
                continue
            if len(raw) - p < min_part:
                continue
            dist = abs(p - ideal)
            if best is None or dist < best[0]:
                best = (dist, p)
        if best:
            used.add(best[1])
            cuts.append(best[1])
    cuts.sort()

    parts, prev = [], 0
    for c in cuts:
        piece = raw[prev:c].strip(u"，。！？；、,.!?; ")
        if piece:
            parts.append(piece)
        prev = c
    tail = raw[prev:].strip(u"，。！？；、,.!?; ")
    if tail:
        parts.append(tail)

    # 合并过短的碎片
    merged = []
    for piece in parts:
        if merged and len(piece) < min_part:
            merged[-1] = merged[-1] + u"，" + piece
        else:
            merged.append(piece)
    if merged and len(merged[-1]) < min_part and len(merged) > 1:
        merged[-2] = merged[-2] + u"，" + merged.pop()

    return _cap_segments(merged, max_segments) if merged else [raw]



def adaptive_debounce(messages, cfg=None):
    """自适应合并等待窗口（秒）：对方连发多条时等多久再一起回。

    短消息等得少（对方面无表情，秒回才自然）；
    长消息等得多（对方还在说，等他说完再回更像真人）。
    """
    cfg = cfg or TYPING_CFG
    if not _f(cfg, "debounce_enable", True):
        return float(_f(cfg, "adaptive_min_wait", 1.0) or 1.0)
    if not _f(cfg, "enable_adaptive_debounce", True):
        return float(_f(cfg, "adaptive_max_wait", 6.0) or 6.0)
    total_len = sum(len(m or "") for m in (messages or []))
    threshold = int(_f(cfg, "adaptive_short_message_threshold", 10) or 10)
    lo = float(_f(cfg, "adaptive_min_wait", 1.0) or 0)
    hi = float(_f(cfg, "adaptive_max_wait", 6.0) or 0)
    max_total = float(_f(cfg, "adaptive_max_total_wait", 12.0) or 0)
    if total_len <= threshold:
        wait = lo
    else:
        ratio = min(1.0, (total_len - threshold) / 40.0)
        wait = lo + (hi - lo) * ratio
    if max_total > 0:
        wait = min(wait, max_total)
    return max(0.0, wait)


def silence_minutes(cfg=None, rng=None):
    """对方静默多久之后才考虑主动开口（分钟，含随机浮动）。"""
    cfg = cfg or PROACTIVE_CFG
    rng = rng or random
    base = float(_f(cfg, "silence_after_minutes", 45) or 0)
    fluct = float(_f(cfg, "silence_fluctuation_minutes", 15) or 0)
    if fluct <= 0:
        return max(0.0, base)
    return max(0.0, base + rng.uniform(-fluct, fluct))


def scaled_silence_minutes(silent_minutes, cfg=None):
    """按「已经多久没聊」把静默阈值放大：越久不聊，越不容易主动开口。

    这样避免了「一整天没说话，一上来就问在吗」的那种机器人感。
    """
    cfg = cfg or PROACTIVE_CFG
    if not _f(cfg, "silence_scale_enable", True):
        return silence_minutes(cfg)
    try:
        silent = float(silent_minutes or 0)
    except (TypeError, ValueError):
        silent = 0.0
    step = float(_f(cfg, "silence_scale_step", 0.3) or 0)
    cap = float(_f(cfg, "silence_scale_cap_minutes", 240) or 0)
    base = silence_minutes(cfg)
    if step <= 0:
        return base
    scaled = base * (1.0 + step * (silent / 60.0))
    if cap > 0:
        scaled = min(scaled, cap)
    return max(base, scaled)


# ==============================================================================
# 三、主动搭话：话题选择 / 冷却 / 赌气 / 复读
# ==============================================================================

def parse_topic_weights(raw):
    """把 "history=4,life=3,preset=3" 解析成 {来源: 权重}。"""
    weights = {}
    for item in str(raw or "").replace(u"，", u",").split(u","):
        item = item.strip()
        if not item or u"=" not in item:
            continue
        name, _, val = item.partition(u"=")
        try:
            weights[name.strip()] = max(0.0, float(val))
        except (TypeError, ValueError):
            continue
    return weights


def pick_topic_source(cfg=None, rng=None):
    """按权重挑一个话题来源。

    来源：history（从最近聊过的内容找话头）/ life（自己的日常）/
    preset（预设话题池）/ random（纯随机）。
    """
    cfg = cfg or PROACTIVE_CFG
    rng = rng or random
    mode = str(_f(cfg, "topic_mode", "mixed") or "mixed").strip().lower()
    if mode == "random":
        return "random"
    if mode in ("history", "life", "preset"):
        return mode
    weights = parse_topic_weights(_f(cfg, "topic_weights", "history=4,life=3,preset=3"))
    weights = {k: v for k, v in weights.items() if v > 0}
    if not weights:
        return "random"
    total = sum(weights.values())
    roll = rng.random() * total
    acc = 0.0
    for name in sorted(weights):
        acc += weights[name]
        if roll <= acc:
            return name
    return sorted(weights)[-1]


def topic_cooldown_ok(topic, recent_topics, cfg=None, now=None):
    """同一话题在冷却期内不再重复（避免天天问同一句）。

    recent_topics: [{"topic": "...", "at": 时间戳}] 之类
    """
    cfg = cfg or PROACTIVE_CFG
    days = float(_f(cfg, "topic_repeat_cooldown_days", 7) or 0)
    if days <= 0:
        return True
    topic = (topic or "").strip()
    if not topic:
        return True
    now_ts = now.timestamp() if isinstance(now, datetime) else time.time()
    cutoff = now_ts - days * 86400.0
    for item in (recent_topics or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("topic") or "").strip() != topic:
            continue
        try:
            at = float(item.get("at") or 0)
        except (TypeError, ValueError):
            at = 0.0
        if at >= cutoff:
            return False
    return True


def filter_topics_by_cooldown(topics, recent_topics, cfg=None, now=None):
    """把冷却期内用过的话题从候选里剔掉（全部被剔就返回空列表）。"""
    out = []
    for t in (topics or []):
        if topic_cooldown_ok(t, recent_topics, cfg=cfg, now=now):
            out.append(t)
    return out


def pout_state(unanswered, cfg=None):
    """对方一直不回时会不会赌气。

    返回 (是否赌气: bool, 剩余机会: int)
    """
    cfg = cfg or PROACTIVE_CFG
    if not _f(cfg, "pout_on_unanswered", True):
        return False, 0
    try:
        n = int(unanswered or 0)
    except (TypeError, ValueError):
        n = 0
    max_unanswered = int(_f(cfg, "max_unanswered", 6) or 0)
    if max_unanswered <= 0:
        return False, 0
    return (n >= max_unanswered, max(0, max_unanswered - n))


def followup_delay_minutes(cfg=None, rng=None):
    """主动发完没回之后，隔多久追问一句（分钟）。"""
    cfg = cfg or PROACTIVE_CFG
    rng = rng or random
    lo = float(_f(cfg, "followup_delay_min_minutes", 12) or 0)
    hi = float(_f(cfg, "followup_delay_max_minutes", 20) or 0)
    if hi <= lo:
        return max(0.0, lo)
    return rng.uniform(lo, hi)


def parrot_decision(text, turns_since_last, today_count=0, cfg=None, rng=None):
    """要不要复读（parrot）对方刚说的话。

    真人在群里偶尔会原样重复一句（表示惊讶或确认），但很少见——
    所以概率很低，且有冷却和每日上限。
    """
    cfg = cfg or PARROT_CFG
    rng = rng or random
    if not _f(cfg, "enabled", True):
        return False
    raw = (text or "").strip()
    min_len = int(_f(cfg, "min_len", 1) or 1)
    max_len = int(_f(cfg, "max_len", 24) or 24)
    threshold = int(_f(cfg, "judge_threshold", 7) or 0)
    if len(raw) < min_len or len(raw) > max_len:
        return False
    if threshold and len(raw) > threshold:
        return False
    cooldown = int(_f(cfg, "cooldown_turns", 8) or 0)
    if cooldown and int(turns_since_last or 0) < cooldown:
        return False
    max_per_day = int(_f(cfg, "max_per_day", 3) or 0)
    if max_per_day and int(today_count or 0) >= max_per_day:
        return False
    prob = float(_f(cfg, "prob", 0.06) or 0)
    return rng.random() < prob

