# -*- coding: utf-8 -*-
"""情绪与关系维度（借鉴 alpaim/ashley 的情感曲线 + 关系追踪）。

两个独立的慢/快变量：
  * 情绪 emotion  —— 快变量，几分钟就消退，受一句话影响 → 决定「这一刻用什么语气」
  * 关系 relationship —— 慢变量，按天/按阶段变化 → 只做微调，绝不改阶段

主体性铁律：阶段（相识/相知/相恋）永远由 persona.json 的 affection 决定，
本模块只提供 trust（信任）/ intimacy（亲密）/ tension（委屈张力）三个「配菜」。
"""
import time

STAGE_CN = {"1": u"相识", "2": u"相知", "3": u"相爱"}

# 主导情绪字典：每种情绪给出它把愉悦度/激活度往哪推，以及触发词
EMOTION_LEXICON = {
    u"开心": {"valence": 0.55, "arousal": 0.30,
              "words": [u"哈哈", u"笑死", u"开心", u"高兴", u"太好了", u"好棒", u"棒",
                        u"嘻嘻", u"嘿嘿", u"爽", u"赞", u"不错", u"有意思"]},
    u"亲近": {"valence": 0.50, "arousal": 0.18,
              "words": [u"想你", u"抱抱", u"宝贝", u"亲爱的", u"晚安", u"早安",
                        u"么么", u"喜欢你", u"在干嘛", u"干嘛呢", u"陪我"]},
    u"害羞": {"valence": 0.40, "arousal": 0.35,
              "words": [u"害羞", u"脸红", u"不好意思", u"别夸", u"讨厌啦", u"哪有"]},
    u"思念": {"valence": -0.05, "arousal": 0.10,
              "words": [u"好久没", u"几天没", u"想我没", u"什么时候回来", u"还记得",
                        u"上次", u"以前"]},
    u"心疼": {"valence": -0.20, "arousal": 0.22,
              "words": [u"生病", u"感冒", u"发烧", u"不舒服", u"疼", u"医院",
                        u"难受", u"加班", u"熬夜", u"没吃饭"]},
    u"委屈": {"valence": -0.50, "arousal": 0.25,
              "words": [u"算了", u"随便", u"不理我", u"难过", u"伤心", u"呜呜", u"哭",
                        u"唉", u"心累", u"失望", u"委屈", u"都怪"]},
    u"吃醋": {"valence": -0.30, "arousal": 0.40,
              "words": [u"谁啊", u"哪个", u"男的女的", u"别人", u"跟谁", u"哦哦", u"是吗"]},
    u"生气": {"valence": -0.60, "arousal": 0.50,
              "words": [u"气死", u"讨厌", u"烦", u"无语", u"滚", u"别烦", u"生气",
                        u"过分", u"凭什么"]},
    u"疲惫": {"valence": -0.30, "arousal": -0.45,
              "words": [u"好累", u"太累", u"困", u"想睡", u"睡了", u"休息", u"歇会",
                        u"忙死", u"搞不动"]},
}

DOMINANT_ORDER = [u"开心", u"亲近", u"害羞", u"心疼", u"思念", u"委屈", u"吃醋",
                  u"生气", u"疲惫"]

BASELINE_VALENCE = 0.12     # 平时略带亲近感的轻微正情绪
BASELINE_AROUSAL = 0.45     # 不兴奋也不冷
VALENCE_HALF_LIFE = 1500.0  # 愉悦落差每 25 分钟衰减一半
AROUSAL_HALF_LIFE = 600.0   # 激活度每 10 分钟就平静下来

TENSION_DECAY_PER_HOUR = 1.6
TRUST_PER_POSITIVE_TURN = 0.35
INTIMACY_PER_TURN = 0.30


def now_ts():
    return time.time()


def _clamp(v, low, high):
    return max(low, min(high, v))


def default_emotion():
    return {
        "valence": BASELINE_VALENCE,
        "arousal": BASELINE_AROUSAL,
        "dominant": u"平静",
        "intensity": 0.0,
        "updated_at": now_ts(),
    }


def default_relationship():
    return {
        "trust": 10.0,
        "intimacy": 0.0,
        "tension": 0.0,
        "streak_days": 0,
        "last_talk_day": "",
        "first_seen": now_ts(),
        "days_known": 1,
        "total_messages": 0,
        "total_rounds": 0,
        "last_stage": "1",
        "stage_since": now_ts(),
    }


def _decay(current, baseline, elapsed, half_life):
    if elapsed <= 0:
        return current
    factor = 0.5 ** (elapsed / half_life)
    return baseline + (current - baseline) * factor


def emotion_decay(emo, now=None, elapsed_seconds=None):
    """情绪随时间自然回归基线（越久不聊越平静）。"""
    now = now or now_ts()
    elapsed = elapsed_seconds
    if elapsed is None:
        elapsed = max(0.0, now - float(emo.get("updated_at") or now))
    new = dict(emo)
    new["valence"] = _clamp(_decay(float(emo.get("valence", BASELINE_VALENCE)),
                                   BASELINE_VALENCE, elapsed, VALENCE_HALF_LIFE), -1.0, 1.0)
    new["arousal"] = _clamp(_decay(float(emo.get("arousal", BASELINE_AROUSAL)),
                                   BASELINE_AROUSAL, elapsed, AROUSAL_HALF_LIFE), 0.0, 1.0)
    new["intensity"] = _clamp(abs(new["valence"] - BASELINE_VALENCE) * 1.6 +
                              abs(new["arousal"] - BASELINE_AROUSAL) * 1.2, 0.0, 1.0)
    new["dominant"] = dominant_of(new["valence"], new["arousal"], emo.get("dominant"))
    new["updated_at"] = now
    return new


def dominant_of(valence, arousal, fallback=u"平静"):
    """由愉悦度/激活度反推主导情绪（用于自然衰减后重新命名）。"""
    if abs(valence - BASELINE_VALENCE) < 0.08 and abs(arousal - BASELINE_AROUSAL) < 0.10:
        return u"平静"
    if valence >= 0.30:
        return u"亲近" if arousal < 0.60 else u"开心"
    if valence <= -0.35:
        return u"生气" if arousal >= 0.60 else u"委屈"
    if valence <= -0.12:
        return u"心疼" if arousal >= 0.55 else u"思念"
    if arousal >= 0.65:
        return u"害羞"
    if arousal <= 0.22:
        return u"疲惫"
    return fallback or u"平静"


def match_emotion(text):
    """从一句话里找出最明显的那一种情绪及命中次数。"""
    text = (text or "").strip()
    best, best_score, best_hits = u"", 0.0, 0
    for name in DOMINANT_ORDER:
        spec = EMOTION_LEXICON.get(name, {})
        hits = sum(1 for w in spec.get("words", []) if w in text)
        if not hits:
            continue
        score = hits * (0.6 + 0.4 * min(3, len(text) / 20.0))
        if score > best_score:
            best, best_score, best_hits = name, score, hits
    return best, best_hits


def emotion_after_message(emo, text, from_friend=True, gap_minutes=None, now=None):
    """收到一句话后情绪如何波动（先自然衰减，再叠加这句话的刺激）。"""
    now = now or now_ts()
    emo = emotion_decay(emo, now=now)
    text = (text or "").strip()
    valence = float(emo.get("valence", BASELINE_VALENCE))
    arousal = float(emo.get("arousal", BASELINE_AROUSAL))
    dominant = emo.get("dominant") or u"平静"

    name, hits = match_emotion(text)
    if hits:
        spec = EMOTION_LEXICON.get(name, {})
        strength = _clamp(0.28 + 0.12 * hits, 0.0, 0.62)
        valence += spec.get("valence", 0.0) * strength
        arousal += spec.get("arousal", 0.0) * strength
        dominant = name

    # 标点强度：连续感叹号/问号说明对方情绪激动
    if text.count(u"！") + text.count("!") >= 2:
        arousal += 0.10
    if text.count(u"？") + text.count("?") >= 2:
        arousal += 0.08
    if u"。。。" in text:
        valence -= 0.05

    # 被冷落的失落：对方隔很久才回，而且回得很短
    if from_friend and gap_minutes is not None and gap_minutes >= 180 and len(text) <= 6:
        valence -= 0.12
        arousal -= 0.05
        dominant = u"委屈" if valence < -0.05 else u"思念"

    new = dict(emo)
    new["valence"] = round(_clamp(valence, -1.0, 1.0), 4)
    new["arousal"] = round(_clamp(arousal, 0.0, 1.0), 4)
    new["dominant"] = dominant
    new["intensity"] = round(_clamp(abs(new["valence"] - BASELINE_VALENCE) * 1.6 +
                                    abs(new["arousal"] - BASELINE_AROUSAL) * 1.2, 0.0, 1.0), 4)
    new["updated_at"] = now
    return new


def emotion_after_own_reply(emo, reply_text, now=None):
    """自己说完话之后的小幅收敛：把话说出口会略微平复情绪。"""
    now = now or now_ts()
    new = dict(emo)
    valence = float(emo.get("valence", BASELINE_VALENCE))
    arousal = float(emo.get("arousal", BASELINE_AROUSAL))
    new["valence"] = round(_clamp(valence * 0.94 + BASELINE_VALENCE * 0.06, -1.0, 1.0), 4)
    new["arousal"] = round(_clamp(arousal * 0.90 + BASELINE_AROUSAL * 0.10, 0.0, 1.0), 4)
    new["updated_at"] = now
    return new


def emotion_label(emo):
    """中文可读标签，例如「开心（强度 0.42）」。"""
    if not emo:
        return u"平静"
    name = emo.get("dominant") or u"平静"
    try:
        intensity = float(emo.get("intensity") or 0.0)
    except (TypeError, ValueError):
        intensity = 0.0
    if intensity < 0.12:
        return u"平静"
    return u"%s（强度 %.2f）" % (name, intensity)


def relationship_after_message(rel, text, from_friend=True, now=None):
    """一句话对关系慢变量的影响：只有「张力」会即时反应，其余都走得很慢。"""
    now = now or now_ts()
    new = dict(rel)
    name, hits = match_emotion(text)
    tension = float(rel.get("tension", 0.0))
    if name in (u"委屈", u"生气", u"吃醋"):
        tension += 0.9 * max(1, hits)
    elif name in (u"心疼", u"思念"):
        tension += 0.25 * max(1, hits)
    new["tension"] = round(_clamp(tension, 0.0, 100.0), 3)

    # 连续聊天天数：按自然日统计，同一天不重复累加
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    if from_friend and rel.get("last_talk_day") != day:
        yesterday = time.strftime("%Y-%m-%d", time.localtime(now - 86400))
        if rel.get("last_talk_day") == yesterday:
            new["streak_days"] = int(rel.get("streak_days", 0)) + 1
        else:
            new["streak_days"] = 1
        new["last_talk_day"] = day

    new["total_messages"] = int(rel.get("total_messages", 0)) + 1
    new["updated_at"] = now
    return new


def relationship_tick(rel, affection=0, stage_key="1", emotion=None, now=None):
    """每轮对话结束调用：按好感度与阶段推进慢变量。

    主体性保障：intimacy（亲密）以「阶段 + 好感度」为基准，tension 只做微调，
    任何情况下都不会反过来影响 stage_key —— 阶段永远由 affection 说了算。
    """
    now = now or now_ts()
    new = dict(rel)
    new["total_rounds"] = int(rel.get("total_rounds", 0)) + 1
    new["affection"] = affection

    # 认识天数
    first = float(rel.get("first_seen") or now)
    new["first_seen"] = first
    new["days_known"] = max(1, int((now - first) // 86400) + 1)

    # 信任随相处轮次缓慢上升，且永远留有上升空间（不给满分）
    trust_cap = 25.0 + 25.0 * min(1.0, max(0.0, affection) / 100.0)
    trust = float(rel.get("trust", 10.0)) + TRUST_PER_POSITIVE_TURN
    new["trust"] = round(_clamp(trust, 0.0, trust_cap), 3)

    # 亲密以阶段为基准：相识 ~6 / 相知 ~26 / 相恋 ~62，再叠加好感加成
    stage_base = {"1": 6.0, "2": 26.0, "3": 62.0}.get(str(stage_key), 6.0)
    affection_bonus = min(18.0, max(0.0, affection) * 0.18)
    intimacy = float(rel.get("intimacy", 0.0)) + INTIMACY_PER_TURN
    new["intimacy"] = round(_clamp(max(intimacy, stage_base + affection_bonus), 0.0, 100.0), 3)

    # 张力随时间自愈；气氛好时额外消解
    elapsed_hours = max(0.0, (now - float(rel.get("updated_at") or now)) / 3600.0)
    tension = max(0.0, float(rel.get("tension", 0.0)) - TENSION_DECAY_PER_HOUR * elapsed_hours)
    if emotion and float(emotion.get("valence", 0.0)) > 0.30:
        tension -= 1.2
    new["tension"] = round(_clamp(tension, 0.0, 100.0), 3)

    if str(rel.get("last_stage")) != str(stage_key):
        new["last_stage"] = str(stage_key)
        new["stage_since"] = now
    new["updated_at"] = now
    return new


def relationship_tone(affection=0, stage_key="1", rel=None):
    """把关系维度转成一句「此刻该怎么说话」的中文提示。"""
    rel = rel or {}
    tension = float(rel.get("tension", 0.0))
    intimacy = float(rel.get("intimacy", 0.0))
    trust = float(rel.get("trust", 0.0))
    stage_cn = STAGE_CN.get(str(stage_key), u"相识")
    parts = [u"阶段：%s（好感 %s 分）" % (stage_cn, affection),
             u"亲密 %.0f / 信任 %.0f" % (intimacy, trust)]
    if tension >= 12:
        parts.append(u"心里还压着一点小委屈（张力 %.0f），语气会带一点点闷，别装作没事" % tension)
    elif tension >= 4:
        parts.append(u"有一点点小别扭（张力 %.0f），语气收敛一点" % tension)
    else:
        parts.append(u"没什么隔阂，气氛是松的")
    return u"；".join(parts)


def emotion_snapshot(emo):
    emo = emotion_decay(emo)
    arousal = float(emo.get("arousal", 0.0))
    if arousal > 0.60:
        mood_word = u"有点上头"
    elif arousal < 0.30:
        mood_word = u"懒懒的"
    else:
        mood_word = u"平常心"
    return {
        "dominant": emo.get("dominant") or u"平静",
        "label": emotion_label(emo),
        "valence": round(float(emo.get("valence", 0.0)), 3),
        "arousal": round(arousal, 3),
        "intensity": round(float(emo.get("intensity", 0.0)), 3),
        "text": u"心情%s，%s" % (emotion_label(emo), mood_word),
    }


def relationship_snapshot(rel, affection=0, stage_key="1"):
    return {
        "stage": str(stage_key),
        "stage_cn": STAGE_CN.get(str(stage_key), u"相识"),
        "affection": affection,
        "trust": round(float(rel.get("trust", 0.0)), 1),
        "intimacy": round(float(rel.get("intimacy", 0.0)), 1),
        "tension": round(float(rel.get("tension", 0.0)), 1),
        "days_known": int(rel.get("days_known", 1)),
        "streak_days": int(rel.get("streak_days", 0)),
        "total_rounds": int(rel.get("total_rounds", 0)),
        "total_messages": int(rel.get("total_messages", 0)),
        "tone": relationship_tone(affection, stage_key, rel),
    }
