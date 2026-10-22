# -*- coding: utf-8 -*-
"""内部状态机（借鉴 Shikigami-Protocol 的 情绪 × 精力 × 好感 状态机 + 后台沉思，
以及 anrror/y-ai-accompany 的生命节律 daily_schedule）。

这是「真正有内部状态」的地方——不是每次被叫才运转，而是自己有一条时间线：

    energy（精力）── 聊天消耗 / 睡觉与休息恢复
    mood  （心情）── 由 mind.emotion 提供，这里负责它和精力如何共同决定行为
    affinity（好感）── 由 persona.json 的 affection 提供（恋爱关系主体，只读）
    intent（当下的念头）── 后台沉思与事件写进来，直接影响下次开口的内容
    willingness（说话意愿度）── 上三者综合出来的「此刻想不想主动找人说话」

所有状态都按好友独立保存；静默时段（作息表）内绝不主动打扰。
"""
import json
import random
import re
import time

ENERGY_MAX = 100.0
ENERGY_START = 78.0
REGEN_PER_HOUR_AWAKE = 9.0
REGEN_PER_HOUR_REST = 24.0     # 静默/睡眠时段恢复更快
REPLY_COST_BASE = 2.0
REPLY_COST_PER_CHAR = 0.02
FRIEND_CHARGE = 0.7            # 收到对方消息带来的精神回血

DEFAULT_SCHEDULE = {
    "enabled": True,
    "quiet_start": "23:30",
    "quiet_end": "07:30",
    "cadence": "medium",       # high=1h / medium=3h / low=8h 最小主动间隔
    "max_daily_messages": 6,
    "activities": [
        {"name": u"起床", "time": "07:30", "type": "transition"},
        {"name": u"早餐", "time": "08:00", "type": "meal"},
        {"name": u"上午", "time": "09:30", "type": "work"},
        {"name": u"午餐", "time": "12:00", "type": "meal"},
        {"name": u"下午", "time": "14:30", "type": "work"},
        {"name": u"傍晚放松", "time": "18:00", "type": "rest"},
        {"name": u"晚餐", "time": "19:00", "type": "meal"},
        {"name": u"晚间休息", "time": "21:30", "type": "rest"},
        {"name": u"入睡", "time": "23:30", "type": "rest"},
    ],
}
CADENCE_MINUTES = {"high": 60, "medium": 180, "low": 480}
REFLECT_MIN_GAP = 1800.0       # 两次沉思之间至少隔 30 分钟
REFLECT_AFTER_IDLE = 45.0      # 对方安静 45 分钟后才值得「想点什么」


def now_ts():
    return time.time()


def default_state():
    return {
        "energy": ENERGY_START,
        "intent": u"",
        "mood_note": u"",
        "willingness": 0.5,
        "last_active": 0.0,
        "last_friend_msg": 0.0,
        "last_own_msg": 0.0,
        "last_chat_ts": 0.0,        # 最近一次「跟 TA 说过话」的时间（不管谁先开口）
        "unanswered": 0,            # 连续几次我发了消息、TA 没回（赌气用）
        "last_reflect": 0.0,
        "reflect_count": 0,
        "last_energy_ts": now_ts(),
        "schedule": dict(DEFAULT_SCHEDULE),
        "updated_at": now_ts(),
    }


def ensure_state(st):
    if not isinstance(st, dict):
        st = {}
    base = default_state()
    for k, v in base.items():
        st.setdefault(k, v)
    if not isinstance(st.get("schedule"), dict) or not st["schedule"]:
        st["schedule"] = dict(DEFAULT_SCHEDULE)
    else:
        for k, v in DEFAULT_SCHEDULE.items():
            st["schedule"].setdefault(k, v)
    return st


def _hm_to_minutes(text, fallback):
    try:
        hh, mm = str(text).split(":")
        return int(hh) * 60 + int(mm)
    except (ValueError, AttributeError):
        return fallback


def energy_tick(st, now=None):
    """按流逝时间恢复精力（睡眠/静默时段恢复更快）。"""
    st = ensure_state(st)
    now = now or now_ts()
    last = float(st.get("last_energy_ts") or now)
    elapsed_hours = max(0.0, (now - last) / 3600.0)
    if elapsed_hours <= 0:
        return st
    rate = REGEN_PER_HOUR_REST if in_quiet_hours(st.get("schedule"), now) \
        else REGEN_PER_HOUR_AWAKE
    st["energy"] = round(min(ENERGY_MAX, float(st.get("energy", ENERGY_START)) +
                             rate * elapsed_hours), 2)
    st["last_energy_ts"] = now
    return st


def in_quiet_hours(schedule, now=None):
    """是否处于「静默时段」（作息表里的睡觉时间），跨夜也可正确判断。"""
    schedule = schedule or DEFAULT_SCHEDULE
    if not schedule.get("enabled", True):
        return False
    now = now or now_ts()
    lt = time.localtime(now)
    cur = lt.tm_hour * 60 + lt.tm_min
    start = _hm_to_minutes(schedule.get("quiet_start"), 23 * 60 + 30)
    end = _hm_to_minutes(schedule.get("quiet_end"), 7 * 60 + 30)
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


def current_activity(schedule, now=None):
    """按作息表返回此刻在干嘛（用于把「你正在做的事」写进提示词）。"""
    schedule = schedule or DEFAULT_SCHEDULE
    activities = schedule.get("activities") or []
    now = now or now_ts()
    lt = time.localtime(now)
    cur = lt.tm_hour * 60 + lt.tm_min
    best, best_min = None, -1
    for act in activities:
        if not isinstance(act, dict):
            continue
        minutes = _hm_to_minutes(act.get("time"), -1)
        if minutes < 0 or minutes > cur:
            continue
        if minutes > best_min:
            best, best_min = act, minutes
    if best:
        return best.get("name") or ""
    return activities[0].get("name") if activities and isinstance(activities[0], dict) else ""


def touch_active(st, now=None):
    st = ensure_state(st)
    st["last_active"] = now or now_ts()
    st["updated_at"] = st["last_active"]
    return st


def state_after_message(st, text, from_friend=True, now=None):
    """收到消息后的内部状态变化：精神回血 + 记录活跃时间。"""
    st = energy_tick(st, now=now)
    now = now or now_ts()
    st["last_friend_msg"] = now
    st["last_active"] = now
    st["last_chat_ts"] = now
    # TA 回话了，之前那几次「没人理我」就此作罢
    st["unanswered"] = 0
    st["energy"] = round(min(ENERGY_MAX, float(st["energy"]) + FRIEND_CHARGE), 2)
    text = (text or "").strip()
    if from_friend and len(text) >= 20:
        st["mood_note"] = u"TA 这次说得挺多，我得更认真回"
    st["updated_at"] = now
    return st


def state_after_reply(st, text, sent_parts=1, now=None):
    """发出回复后的精力消耗。"""
    st = energy_tick(st, now=now)
    now = now or now_ts()
    cost = REPLY_COST_BASE + REPLY_COST_PER_CHAR * len(text or "") + \
        0.8 * max(0, int(sent_parts) - 1)
    st["energy"] = round(max(0.0, float(st["energy"]) - cost), 2)
    st["last_own_msg"] = now
    st["last_active"] = now
    st["last_chat_ts"] = now
    st["updated_at"] = now
    return st


def state_note_unanswered(st, now=None):
    """记一笔「我发了消息但 TA 还没回」（连续未回次数 +1）。"""
    st = ensure_state(st)
    try:
        n = int(st.get("unanswered") or 0)
    except (TypeError, ValueError):
        n = 0
    st["unanswered"] = n + 1
    st["updated_at"] = now or now_ts()
    return st


def add_thought(thoughts, text, kind="reflect", limit=40):
    """把一条内心独白写进时间线（自动截断上限，避免无限增长）。"""
    text = (text or "").strip()
    if not text:
        return thoughts if isinstance(thoughts, list) else []
    if not isinstance(thoughts, list):
        thoughts = []
    thoughts.append({"text": text[:200], "kind": kind, "at": now_ts()})
    if len(thoughts) > limit:
        del thoughts[:-limit]
    return thoughts


def willingness(state, emotion=None, relationship=None, affection=0, stage_key="1",
                now=None):
    """说话意愿度 0~1：精力 × 亲密 × 心情 × 久未联系 − 别扭感。"""
    st = ensure_state(state)
    st = energy_tick(st, now=now)
    now = now or now_ts()
    rel = relationship or {}
    emo = emotion or {}
    energy = max(0.0, min(1.0, float(st.get("energy", ENERGY_START)) / ENERGY_MAX))
    intimacy = max(0.0, min(1.0, float(rel.get("intimacy", 0.0)) / 100.0))
    valence = float(emo.get("valence", 0.0))
    tension = float(rel.get("tension", 0.0))

    last_own = float(st.get("last_own_msg") or 0.0)
    silence_hours = ((now - last_own) / 3600.0) if last_own else 12.0
    silence_bonus = min(0.25, max(0.0, silence_hours) / 36.0 * 0.25)
    tension_penalty = min(0.28, tension / 60.0)
    affinity = max(0.0, min(1.0, affection / 100.0))

    score = (0.26 + 0.32 * energy + 0.20 * intimacy + 0.18 * max(0.0, valence)
             + 0.10 * affinity + silence_bonus - tension_penalty)
    if in_quiet_hours(st.get("schedule"), now):
        score = min(score, 0.05)
    return round(max(0.0, min(1.0, score)), 3)


def speaking_decision(state, emotion=None, relationship=None, affection=0, stage_key="1",
                      cfg=None, now=None):
    """此刻该不该主动开口。返回 (是否愿意, 中文原因)。

    这里刻意允许「不想说话」——赌气、累了、深夜都会让它闭嘴，
    这样主动搭话才是从内部状态长出来的，而不是定时任务硬发。
    """
    cfg = cfg or {}
    st = ensure_state(state)
    st = energy_tick(st, now=now)
    now = now or now_ts()
    rel = relationship or {}
    energy = float(st.get("energy", ENERGY_START))
    tension = float(rel.get("tension", 0.0))
    w = willingness(st, emotion, rel, affection=affection, stage_key=stage_key, now=now)
    st["willingness"] = w

    if in_quiet_hours(st.get("schedule"), now):
        return False, u"现在是静默时段（作息表里正在休息），不去打扰"
    if energy < 30:
        return False, u"精力只剩 %.0f，今天确实累了，先不主动开口" % energy
    if tension >= 25:
        return False, u"心里还压着 %.0f 的别扭，这次不想先开口" % tension

    cadence = str((st.get("schedule") or {}).get("cadence") or "medium")
    gap_minutes = CADENCE_MINUTES.get(cadence, 180)
    last_own = float(st.get("last_own_msg") or 0.0)
    if last_own and (now - last_own) < gap_minutes * 60:
        waited = int((now - last_own) / 60)
        return False, u"距离上次开口才 %d 分钟（当前节奏要求至少 %d 分钟）" % (waited, gap_minutes)

    threshold = 0.46 if str(stage_key) == "3" else (0.52 if str(stage_key) == "2" else 0.58)
    if w < threshold:
        return False, u"说话意愿度只有 %.2f（门槛 %.2f），此刻没什么想说的" % (w, threshold)

    activity = current_activity(st.get("schedule"), now)
    where = (u"（此刻我在%s）" % activity) if activity else u""
    intent = (st.get("intent") or "").strip()
    if intent:
        return True, u"想开口了%s，念头是：%s" % (where, intent)
    return True, u"想开口了%s" % where


# ==============================================================================
# 后台沉思（借鉴 Shikigami-Protocol 的 background reflection）
# ==============================================================================

REFLECT_SYSTEM_PROMPT = (
    u"你正在扮演一个真实的微信好友，现在是没人找你说话的安静时刻。"
    u"请以第一人称记录一闪而过的内心独白，只输出 JSON。"
)

REFLECT_USER_TEMPLATE = (
    u"当前状态：精力 %.0f/100；心情：%s；关系：%s；此刻在%s。\n"
    u"你记得的事：%s\n"
    u"对方上次说话是 %.0f 分钟前。\n\n"
    u"输出严格的 JSON：{\"thought\":\"20~40字的第一人称内心独白\","
    u" \"intent\":\"10字以内的当下念头，例如：想分享今天的事|想知道他在忙什么|有点想撒娇\"}\n"
    u"要求：像真人发朋友圈前的心声，口语、具体、不矫情、不总结、不提AI。"
)


def stage_index(stage_key):
    try:
        return int(stage_key)
    except (TypeError, ValueError):
        return 1


def _fallback_thought(st, emotion, relationship, affection, stage_key, idle_minutes):
    """没有模型时用模板生成独白——同样能驱动「想不想开口」。"""
    rel = relationship or {}
    emo = emotion or {}
    tension = float(rel.get("tension", 0.0))
    valence = float(emo.get("valence", 0.0))
    energy = float(st.get("energy", ENERGY_START))
    dominant = emo.get("dominant") or u"平静"
    activity = current_activity(st.get("schedule")) or u"发呆"

    if tension >= 20:
        return u"还在想刚才那句话，有点堵得慌，不太想先开口。", u"还在生闷气"
    if valence >= 0.35 and float(rel.get("intimacy", 0)) >= 20:
        return u"刚忙完手上的事，突然有点想他，想跟他说说今天的事。", u"想分享今天的事"
    if dominant == u"思念" or idle_minutes >= 360:
        return u"都大半天没动静了，也不知道他在忙什么。", u"想知道他在忙什么"
    if energy <= 35:
        return u"有点困了，不过还是想知道他到家没有。", u"想知道他到没到家"
    if stage_index(stage_key) >= 2 and valence >= 0.25:
        return (u"在%s的时候走神了一下，想起他上次说过的那个事。" % activity,
                u"想起他说过的事")
    return u"%s的时候突然想找人说说话，翻了一圈还是想找他。" % activity, u"想找他聊两句"


def _parse_reflection(raw):
    """从模型输出里取 {thought, intent}。"""
    if not raw:
        return "", ""
    text = raw.strip()
    # 模型常常把 JSON 包在 ```json ... ``` 里，先把围栏剥掉
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fence:
        text = fence.group(1).strip() or text
    try:
        hit = re.search(r"\{.*\}", text, re.S)
        if hit:
            data = json.loads(hit.group(0))
            if isinstance(data, dict):
                thought = str(data.get("thought") or data.get("content") or "").strip()
                intent = str(data.get("intent") or "").strip()
                if thought:
                    return _clean_thought(thought)[:160], intent[:30]
    except Exception:
        pass
    # JSON 解析失败（模型常在字符串里塞了未转义的引号）时，退一步只抠出 thought 的值
    loose = re.search(r'["\']?thought["\']?\s*[:：]\s*["\'](.+?)["\']\s*(?:,|$)',
                      text, re.S | re.I)
    if loose:
        intent = ""
        loose_intent = re.search(r'["\']?intent["\']?\s*[:：]\s*["\'](.+?)["\']',
                                 text, re.S | re.I)
        if loose_intent:
            intent = loose_intent.group(1).strip()[:30]
        return _clean_thought(loose.group(1))[:160], intent
    return _clean_thought(text.replace("\n", " "))[:160], ""


def _clean_thought(text):
    """把模型输出收拾成一句人话：去掉 JSON 残渣、去掉复述状态的推理过程。"""
    text = re.sub(r"```(?:json)?", " ", str(text or ""))
    text = re.sub(r"[{}\"`']", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # 模型有时会先复述一遍「精力 78/100 / 心情平静 / 关系相识」再给独白。
    # 这种复述不能当内心独白展示，只保留最后一句真正想说的话。
    parts = [p.strip() for p in re.split(r"[。！？!?\n]", text) if p.strip()]
    if len(parts) > 1 and re.search(r"(精力|心情|关系|阶段|好感|亲密|信任|我需要|根据)", parts[0]):
        tail = parts[-1]
        if 4 <= len(tail) <= 120:
            return tail
    return text[:120]


def reflect(state, emotion=None, relationship=None, bank=None, affection=0, stage_key="1",
            extractor=None, idle_minutes=None, force=False, now=None):
    """空闲时的后台沉思：产出内心独白 + 更新当下的念头 intent。

    返回 (新的 state, 本次独白文本)。未到沉思条件时独白为空串。
    """
    st = ensure_state(state)
    st = energy_tick(st, now=now)
    now = now or now_ts()
    last_reflect = float(st.get("last_reflect") or 0.0)
    if not force and last_reflect and (now - last_reflect) < REFLECT_MIN_GAP:
        return st, ""

    last_friend = float(st.get("last_friend_msg") or 0.0)
    idle = idle_minutes
    if idle is None:
        idle = ((now - last_friend) / 60.0) if last_friend else 999.0
    if not force and idle < REFLECT_AFTER_IDLE:
        return st, ""

    thought, intent = "", ""
    if extractor is not None:
        bank = bank or {}
        try:
            from mind import memory as memory_mod
            memo = memory_mod.memory_prompt_block(bank, query="", limit=4) \
                or u"（还没什么特别的记忆）"
        except Exception:
            memo = u"（还没什么特别的记忆）"
        try:
            from mind import emotion as emotion_mod
            rel_text = emotion_mod.relationship_tone(affection, stage_key, relationship)
            mood_text = emotion_mod.emotion_label(emotion)
        except Exception:
            rel_text, mood_text = u"关系正常", u"平静"
        prompt = REFLECT_USER_TEMPLATE % (
            float(st.get("energy", ENERGY_START)), mood_text, rel_text,
            current_activity(st.get("schedule")) or u"发呆", memo, idle)
        try:
            raw = extractor([
                {"role": "system", "content": REFLECT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ], 160)
            thought, intent = _parse_reflection(raw)
        except Exception:
            thought, intent = "", ""

    if not thought:
        thought, intent = _fallback_thought(st, emotion, relationship, affection,
                                            stage_key, idle)
    if intent:
        st["intent"] = intent
    st["mood_note"] = thought[:80]
    st["last_reflect"] = now
    st["reflect_count"] = int(st.get("reflect_count", 0)) + 1
    st["updated_at"] = now
    return st, thought


# ==============================================================================
# 注入提示词 / 网页展示
# ==============================================================================

def energy_word(energy):
    if energy >= 80:
        return u"精神挺好"
    if energy >= 60:
        return u"还行"
    if energy >= 42:
        return u"有点累"
    if energy >= 28:
        return u"很疲惫"
    return u"困得不行"


def state_prompt_block(state, emotion=None, relationship=None):
    """把内部状态翻译成「这一刻该怎么说话」的指导。"""
    st = ensure_state(state)
    st = energy_tick(st)
    energy = float(st.get("energy", ENERGY_START))
    activity = current_activity(st.get("schedule")) or u"闲着呢"
    w = float(st.get("willingness") or willingness(st, emotion, relationship))
    lines = [u"# 你现在的真实状态（不要把这部分内容说出来，只影响你的语气）",
             u"- 精力：%.0f/100（%s）" % (energy, energy_word(energy)),
             u"- 此刻在干嘛：%s" % activity]
    if emotion:
        lines.append(u"- 心情：%s（愉悦 %.2f / 激动 %.2f）" % (
            emotion.get("dominant") or u"平静",
            float(emotion.get("valence", 0.0)), float(emotion.get("arousal", 0.0))))
    mood_note = (st.get("mood_note") or "").strip()
    if mood_note:
        lines.append(u"- 刚刚脑子里闪过的：%s" % mood_note)
    intent = (st.get("intent") or "").strip()
    if intent:
        lines.append(u"- 当下最想做的事：%s" % intent)
    lines.append(u"- 说话的劲头：%.2f（低于 0.4 就回得更短更懒，高于 0.7 可以多说两句）" % w)
    if energy < 45:
        lines.append(u"- 因为累，回复可以更短、更口语、更懒得展开")
    return u"\n".join(lines)


def state_snapshot(state, emotion=None, relationship=None):
    st = ensure_state(state)
    st = energy_tick(st)
    energy = round(float(st.get("energy", ENERGY_START)), 1)
    w = round(float(st.get("willingness") or willingness(st, emotion, relationship)), 3)
    if w >= 0.70:
        w_text = u"很想说话"
    elif w >= 0.50:
        w_text = u"有点想聊"
    elif w < 0.35:
        w_text = u"懒得开口"
    else:
        w_text = u"一般"
    return {
        "energy": energy,
        "energy_text": u"%s（%.0f/100）" % (energy_word(energy), energy),
        "willingness": w,
        "willingness_text": w_text,
        "activity": current_activity(st.get("schedule")) or u"",
        "quiet": in_quiet_hours(st.get("schedule")),
        "intent": st.get("intent") or u"",
        "mood_note": st.get("mood_note") or u"",
        "reflect_count": int(st.get("reflect_count", 0)),
        "schedule": st.get("schedule"),
    }


def _valid_hm(text):
    try:
        hh, mm = str(text).split(":")
        return 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
    except (ValueError, AttributeError):
        return False


def validate_schedule(schedule):
    """校验作息字段，返回中文错误提示（空串表示没问题）。"""
    schedule = schedule or {}
    if not _valid_hm(schedule.get("quiet_start")):
        return u"静默开始时间格式应为 HH:MM（例如 23:30）"
    if not _valid_hm(schedule.get("quiet_end")):
        return u"静默结束时间格式应为 HH:MM（例如 07:30）"
    if str(schedule.get("cadence")) not in CADENCE_MINUTES:
        return u"主动节奏只能是 high / medium / low 之一"
    try:
        if int(schedule.get("max_daily_messages") or 0) < 0:
            return u"每日主动上限不能是负数"
    except (TypeError, ValueError):
        return u"每日主动上限必须是数字"
    return ""
