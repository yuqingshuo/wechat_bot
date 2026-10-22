# -*- coding: utf-8 -*-
"""多层记忆（借鉴 Yuki-QQbot 的长期记忆 + Ai-Companion 的多层记忆管线）。

六层分工（L0/L1 沿用项目已有的内存与 chat_histories.json，本模块负责 L2~L5）：

    L2 summary   会话滚动摘要   —— 长会话压缩，防止上下文无限增长
    L3 facts     长期事实       —— 「对方喜欢猫」「周六要考试」这类可长期复用的事实
    L4 episodes  共同经历/里程碑 —— 「一起去看了那部电影」「第一次说晚安」
    L5 profile   关系与情绪档案  —— 由 mind.emotion 维护，这里只做展示聚合

检索不引入向量库（保持零新依赖）：用「重要度 + 中文二元组重合度 + 新鲜度」打分，
对微信这种短句场景足够准，且完全离线可用。
"""
import re
import time

LAYER_SUMMARY = "summaries"
LAYER_FACT = "facts"
LAYER_EPISODE = "episodes"
LAYER_ARCHIVE = "archive"

MAX_FACTS = 220
MAX_EPISODES = 160
MAX_SUMMARIES = 60

# 值得记下来的信号词：命中越多的句子越像「长期有用」的信息
FACT_SIGNALS = {
    3.0: [u"我一直", u"记住", u"答应", u"约定", u"以后", u"再也不想", u"绝不"],
    2.0: [u"生日", u"纪念日", u"家人", u"老家", u"过敏", u"害怕", u"梦想", u"打算"],
    1.5: [u"喜欢", u"讨厌", u"爱吃", u"不吃", u"爱吃", u"习惯", u"擅长", u"养了",
          u"专业", u"工作", u"学校", u"住在", u"来自", u"每天", u"周末"],
}

EPISODE_SIGNALS = [
    (u"第一次", 5.0, "milestone"),
    (u"一起去", 4.0, "event"),
    (u"见面", 4.5, "event"),
    (u"生日", 4.0, "event"),
    (u"表白", 5.0, "milestone"),
    (u"吵架", 4.0, "conflict"),
    (u"和好", 4.0, "conflict"),
    (u"道歉", 4.0, "conflict"),
    (u"礼物", 3.5, "event"),
    (u"生病", 3.5, "event"),
    (u"考试", 3.0, "event"),
    (u"面试", 3.0, "event"),
    (u"约好", 4.0, "promise"),
    (u"答应", 4.0, "promise"),
    (u"晚安", 3.0, "ritual"),
    (u"早安", 2.5, "ritual"),
]

_SENT_SPLIT = re.compile(u"[。！？!?\\n\\r；;]+")
_CJK = re.compile(u"[\u4e00-\u9fff]")


def now_ts():
    return time.time()


def default_bank():
    return {
        LAYER_SUMMARY: [],
        LAYER_FACT: [],
        LAYER_EPISODE: [],
        LAYER_ARCHIVE: [],
        "counters": {LAYER_FACT: 0, LAYER_EPISODE: 0, LAYER_SUMMARY: 0},
        "created_at": now_ts(),
    }


def ensure_bank(bank):
    """补齐记忆银行结构（容忍旧数据 / 空数据）。"""
    if not isinstance(bank, dict):
        bank = {}
    for layer in (LAYER_SUMMARY, LAYER_FACT, LAYER_EPISODE, LAYER_ARCHIVE):
        if not isinstance(bank.get(layer), list):
            bank[layer] = []
    counters = bank.get("counters")
    if not isinstance(counters, dict):
        counters = {}
        bank["counters"] = counters
    for layer in (LAYER_FACT, LAYER_EPISODE, LAYER_SUMMARY):
        counters.setdefault(layer, 0)
    bank.setdefault("created_at", now_ts())
    return bank


def _new_id(bank, layer):
    counters = bank.setdefault("counters", {})
    counters[layer] = int(counters.get(layer, 0)) + 1
    prefix = {LAYER_FACT: "f", LAYER_EPISODE: "e", LAYER_SUMMARY: "s"}.get(layer, "m")
    return u"%s%d" % (prefix, counters[layer])


def _bigrams(text):
    text = re.sub(u"\\s+", u"", text or u"")
    if len(text) < 2:
        return set([text]) if text else set()
    return set(text[i:i + 2] for i in range(len(text) - 1))


def _char_set(text):
    """单个汉字集合：中文检索时的兜底信号。

    二元组太严格——「你家的猫怎么样了」和「对方喜欢猫」没有任何共同二元组，
    但真人一眼就知道这两句是同一件事。所以打分时额外看单字重合。
    """
    text = re.sub(u"\\s+", u"", text or u"")
    return set(ch for ch in text if 0x4E00 <= ord(ch) <= 0x9FFF)


def similarity(a, b):
    """中文友好的相似度（二元组 Jaccard），用于记忆去重。"""
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    return inter / float(len(ga | gb))


def _find_duplicate(items, text, threshold=0.68):
    for item in items:
        if similarity(item.get("text", ""), text) >= threshold:
            return item
    return None


def add_item(bank, layer, text, importance=2.0, kind="fact", source="chat", now=None):
    """写入一条记忆；重复内容会被合并（重要度取高、hits 累加）。"""
    ensure_bank(bank)
    text = (text or "").strip()
    if len(text) < 4:
        return False
    now = now or now_ts()
    target = bank[layer]
    dup = _find_duplicate(target, text)
    if dup is not None:
        dup["importance"] = round(max(float(dup.get("importance", 1.0)), float(importance)), 2)
        dup["hits"] = int(dup.get("hits", 0)) + 1
        dup["last_used"] = now
        return False
    item = {
        "id": _new_id(bank, layer),
        "text": text,
        "importance": round(float(importance), 2),
        "kind": kind,
        "source": source,
        "created_at": now,
        "last_used": 0.0,
        "hits": 0,
        "layer": layer,
        "state": "active",
    }
    target.append(item)
    limit = {LAYER_FACT: MAX_FACTS, LAYER_EPISODE: MAX_EPISODES,
             LAYER_SUMMARY: MAX_SUMMARIES}.get(layer, 200)
    if len(target) > limit:
        # 超上限时，把「最不重要且从没被用过」的老记忆移入归档层，而不是直接删掉
        target.sort(key=lambda x: (float(x.get("importance", 1.0)), float(x.get("last_used", 0))))
        overflow = target[:len(target) - limit]
        bank[LAYER_ARCHIVE].extend(overflow)
        bank[layer] = [x for x in target if x not in overflow]
    return True


def add_fact(bank, text, importance=2.0, kind="fact", source="chat"):
    return add_item(bank, LAYER_FACT, text, importance=importance, kind=kind, source=source)


def add_episode(bank, text, kind="event", importance=3.0):
    return add_item(bank, LAYER_EPISODE, text, importance=importance, kind=kind,
                    source="event")


# ==============================================================================
# 记忆抽取：优先让 LLM 蒸馏，失败/未配置时退回纯规则，保证永远可用
# ==============================================================================

EXTRACT_SYSTEM_PROMPT = (
    u"你是记忆提取器。从对话里提取「今后聊天真正用得上」的长期信息，只输出 JSON。"
    u"忽略寒暄、表情、语气词和一次性闲聊。"
)

EXTRACT_USER_TEMPLATE = (
    u"请从下面这段微信对话里提取记忆，输出严格的 JSON 数组，不要任何解释：\n"
    u"[{\"text\": \"一句中文陈述，主语用「对方」或「我」\", "
    u"\"importance\": 1到5, \"kind\": \"preference|life|promise|relation|other\"}]\n"
    u"要求：\n"
    u"1. 最多 4 条，只挑真的值得长期记住的；没有就输出 []。\n"
    u"2. text 必须是独立可读的完整短句，不要照抄整段对话。\n"
    u"3. importance：随口一提 1~2，明确的喜好/习惯/计划 3，约定与承诺 4，"
    u"重大的关系事件 5。\n\n"
    u"对话：\n%s"
)


def build_extraction_messages(text, max_chars=1200):
    text = (text or "").strip()[:max_chars]
    return [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": EXTRACT_USER_TEMPLATE % text},
    ]


def _parse_json_items(raw):
    """从模型输出里薅出 JSON 数组（容忍 markdown 代码块与前后废话）。"""
    if not raw:
        return []
    text = raw.strip()
    fence = re.search(r"```(?:json)?(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    text = text[start:end + 1]
    try:
        import json
        data = json.loads(text)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    items = []
    for row in data:
        if isinstance(row, str):
            row = {"text": row}
        if not isinstance(row, dict):
            continue
        content = str(row.get("text") or row.get("content") or "").strip()
        if len(content) < 4:
            continue
        try:
            importance = float(row.get("importance", 2))
        except (TypeError, ValueError):
            importance = 2.0
        items.append({
            "text": content[:120],
            "importance": max(1.0, min(5.0, importance)),
            "kind": str(row.get("kind") or "other")[:16],
        })
    return items


def _sentence_score(sentence):
    score = 0.0
    for weight, words in FACT_SIGNALS.items():
        for w in words:
            if w in sentence:
                score += weight
                break
    if _CJK.search(sentence) is None:
        return 0.0
    return score


def extract_facts(text, extractor=None, max_facts=4):
    """抽取长期事实。extractor 可用时走 LLM，否则走规则。"""
    text = (text or "").strip()
    if len(text) < 4:
        return []
    if extractor is not None:
        try:
            raw = extractor(build_extraction_messages(text), 320)
            items = _parse_json_items(raw)
            if items:
                return items[:max_facts]
        except Exception:
            pass  # 抽取失败时静默退回规则模式，绝不打断主流程

    results = []
    for sentence in _SENT_SPLIT.split(text):
        sentence = sentence.strip()
        if not (6 <= len(sentence) <= 60):
            continue
        score = _sentence_score(sentence)
        if score < 1.5:
            continue
        results.append({
            "text": sentence,
            "importance": max(1.0, min(5.0, 1.0 + score)),
            "kind": "fact",
        })
        if len(results) >= max_facts:
            break
    return results


def detect_episodes(text, affection=0, stage_key="1", max_items=3):
    """识别「共同经历 / 里程碑 / 仪式」，做成时间线记忆。"""
    text = (text or "").strip()
    if not text:
        return []
    results = []
    for sentence in _SENT_SPLIT.split(text):
        sentence = sentence.strip()
        if not (4 <= len(sentence) <= 80):
            continue
        for keyword, importance, kind in EPISODE_SIGNALS:
            if keyword in sentence:
                bonus = 0.5 if str(stage_key) == "3" else 0.0
                results.append({
                    "text": sentence,
                    "importance": min(5.0, importance + bonus),
                    "kind": kind,
                })
                break
        if len(results) >= max_items:
            break
    return results


# ==============================================================================
# 检索：不引入向量库，用「重要度 + 关键词重合 + 新鲜度」打分，离线可用
# ==============================================================================

def score_item(item, query_grams, now, layer_weight=1.0, query_chars=None):
    """给一条记忆打分：重要度 + 关键词重合（二元组 / 单字）+ 新鲜度 + 常用度。

    第二个返回值是「相关度」：二元组重合与单字重合取较大者，都为 0 说明这条记忆
    跟当前话题无关，只是被重要度顶进来的。
    """
    text = item.get("text", "")
    overlap = 0.0
    char_overlap = 0.0
    if query_grams:
        grams = _bigrams(text)
        if grams:
            overlap = len(query_grams & grams) / float(len(query_grams))
    if query_chars:
        chars = _char_set(text)
        if chars:
            char_overlap = len(query_chars & chars) / float(len(query_chars))
    relevance = max(overlap, char_overlap * 0.8)
    importance = float(item.get("importance", 1.0))
    age_days = max(0.0, (now - float(item.get("created_at") or now)) / 86400.0)
    recency = 1.0 if age_days <= 3 else (0.6 if age_days <= 14 else 0.35)
    hit_bonus = min(0.40, 0.06 * int(item.get("hits", 0)))
    score = (importance * 0.55 + overlap * 2.4 + char_overlap * 0.9
             + recency * 0.35 + hit_bonus) * layer_weight
    return score, relevance


def retrieve(bank, query="", limit=6, include_archive=False, now=None):
    """按当前消息召回最相关的长期记忆（会更新 hits / last_used 用于遗忘曲线）。"""
    ensure_bank(bank)
    now = now or now_ts()
    query_grams = _bigrams(query or "")
    query_chars = _char_set(query or "")
    pools = [(LAYER_EPISODE, 1.05), (LAYER_FACT, 1.0)]
    if include_archive:
        pools.append((LAYER_ARCHIVE, 0.45))

    scored = []
    for layer, weight in pools:
        for item in bank.get(layer, []):
            if item.get("state") == "archived":
                continue
            score, overlap = score_item(item, query_grams, now, weight,
                                        query_chars=query_chars)
            scored.append((score, overlap, item))
    scored.sort(key=lambda x: -x[0])

    picked = []
    for score, overlap, item in scored:
        # 没有任何关键词重合时，只放行「本来就很重要」的记忆，避免灌水
        if overlap <= 0.0 and float(item.get("importance", 1.0)) < 3.0:
            continue
        picked.append(item)
        if len(picked) >= limit:
            break
    for item in picked:
        item["hits"] = int(item.get("hits", 0)) + 1
        item["last_used"] = now
    return picked


def decay_and_archive(bank, affection=0, now=None):
    """遗忘曲线：长期没人引用又不重要的记忆降权并归档（不物理删除）。"""
    ensure_bank(bank)
    now = now or now_ts()
    archived = 0
    for layer in (LAYER_FACT, LAYER_EPISODE):
        kept = []
        for item in bank.get(layer, []):
            created = float(item.get("created_at") or now)
            last_used = float(item.get("last_used") or 0.0)
            idle_days = (now - (last_used or created)) / 86400.0
            if int(item.get("hits", 0)) == 0 and idle_days >= 7:
                item["importance"] = round(
                    max(0.4, float(item.get("importance", 1.0)) - 0.12 * (idle_days - 7)), 2)
            if float(item.get("importance", 1.0)) < 1.0:
                item["state"] = "archived"
                item["archived_at"] = now
                bank[LAYER_ARCHIVE].append(item)
                archived += 1
            else:
                kept.append(item)
        bank[layer] = kept
    if len(bank[LAYER_ARCHIVE]) > 400:
        bank[LAYER_ARCHIVE] = bank[LAYER_ARCHIVE][-400:]
    return archived


SUMMARY_SYSTEM_PROMPT = u"你是对话压缩器，把多轮微信聊天压成两三句要点，保留情绪走向和约定。"

SUMMARY_USER_TEMPLATE = (
    u"把下面的多轮微信聊天压缩成 2~3 句中文要点，只保留：关系走向、约定、重要情绪变化。"
    u"直接输出要点本身，不要标题、不要复述原话、不要解释。\n\n%s"
)


def _compress_history(chunk, extractor=None):
    """把一段旧对话压缩成一行摘要（有 LLM 用 LLM，没有就用规则抽重点）。"""
    lines = []
    for msg in chunk or []:
        text = (msg.get("content") or "").strip() if isinstance(msg, dict) else ""
        text = text.replace("\n", " ")
        if text:
            who = u"我" if msg.get("role") == "assistant" else u"对方"
            lines.append(u"%s：%s" % (who, text[:60]))
    if not lines:
        return ""
    joined = "\n".join(lines)
    if extractor is not None:
        try:
            out = extractor([
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": SUMMARY_USER_TEMPLATE % joined[:2000]},
            ], 220)
            out = (out or "").strip().replace("\n", " ")
            if len(out) >= 6:
                return out[:260]
        except Exception:
            pass
    # 规则兜底：挑信息量最大的几句
    ranked = sorted(lines, key=lambda s: -_sentence_score(s.split(u"：", 1)[-1]))
    picked = [s.split(u"：", 1)[-1] for s in ranked[:3]]
    return u"；".join(picked)[:200]


def rollup_summary(bank, history, extractor=None, keep_recent=16, min_extra=6):
    """长会话滚动压缩：把「最近 keep_recent 条之外」的旧对话压成摘要。

    返回是否真的新增了一条摘要。
    """
    ensure_bank(bank)
    if not isinstance(history, list) or len(history) <= keep_recent + min_extra:
        return False
    older = history[:-keep_recent]
    if not older:
        return False
    first = (older[0].get("content") or "")[:24] if isinstance(older[0], dict) else ""
    last = (older[-1].get("content") or "")[:24] if isinstance(older[-1], dict) else ""
    sig = u"%d|%s|%s" % (len(older), first, last)
    for item in bank[LAYER_SUMMARY]:
        if item.get("sig") == sig:
            return False
    text = _compress_history(older, extractor=extractor)
    if not text:
        return False
    bank[LAYER_SUMMARY].append({
        "id": _new_id(bank, LAYER_SUMMARY),
        "text": text,
        "importance": 3.0,
        "kind": "summary",
        "source": "rollup",
        "created_at": now_ts(),
        "last_used": 0.0,
        "hits": 0,
        "layer": LAYER_SUMMARY,
        "state": "active",
        "sig": sig,
        "span": len(older),
    })
    if len(bank[LAYER_SUMMARY]) > MAX_SUMMARIES:
        bank[LAYER_SUMMARY] = bank[LAYER_SUMMARY][-MAX_SUMMARIES:]
    return True


# ==============================================================================
# 注入提示词 / 网页展示
# ==============================================================================

def _fmt_item(item):
    text = (item.get("text") or "").strip()
    importance = float(item.get("importance", 1.0))
    return u"- %s（重要度 %.1f）" % (text, importance)


def _fmt_episode(item):
    created = float(item.get("created_at") or 0)
    when = time.strftime("%m-%d", time.localtime(created)) if created else u"某天"
    return u"- %s · %s" % (when, (item.get("text") or "").strip())


def memory_prompt_block(bank, query="", limit=6):
    """把多层记忆拼成一段可直接塞进 system prompt 的中文块。"""
    ensure_bank(bank)
    recalled = retrieve(bank, query=query, limit=limit)
    facts = [x for x in recalled if x.get("layer") == LAYER_FACT]
    episodes = [x for x in recalled if x.get("layer") == LAYER_EPISODE]
    if not facts and not episodes and not bank[LAYER_EPISODE] and not bank[LAYER_FACT]:
        return u""

    lines = [u"# 你真正记得的事（长期记忆 · 只能引用，不许编造）"]
    if facts:
        lines.append(u"【关于 TA 的长期事实】")
        lines.extend(_fmt_item(x) for x in facts)
    elif bank[LAYER_FACT]:
        lines.append(u"【关于 TA 的长期事实】")
        best = sorted(bank[LAYER_FACT], key=lambda x: -float(x.get("importance", 1)))[:3]
        lines.extend(_fmt_item(x) for x in best)
    if episodes:
        lines.append(u"【你们的共同经历】")
        lines.extend(_fmt_episode(x) for x in episodes)

    recent_summaries = bank[LAYER_SUMMARY][-2:]
    if recent_summaries:
        lines.append(u"【前面聊过的大概（已压缩，细节可能不准，别硬提）】")
        lines.extend(u"- %s" % (x.get("text") or "") for x in recent_summaries)

    lines.append(u"（这些是你自然记得的东西：刚好聊到就顺口提起，聊不到就别硬提，"
                 u"更不要凭空编造上面没有的细节。）")
    return u"\n".join(lines)


def bank_snapshot(bank, top=8):
    """给网页控制台用的记忆银行概览。"""
    ensure_bank(bank)

    def brief(items, n):
        rows = sorted(items, key=lambda x: -float(x.get("importance", 1.0)))[:n]
        out = []
        for it in rows:
            created = float(it.get("created_at") or 0)
            out.append({
                "id": it.get("id"),
                "text": it.get("text"),
                "importance": round(float(it.get("importance", 1.0)), 1),
                "hits": int(it.get("hits", 0)),
                "kind": it.get("kind"),
                "at": time.strftime("%m-%d %H:%M", time.localtime(created)) if created else "",
            })
        return out

    return {
        "facts": brief(bank[LAYER_FACT], top),
        "episodes": brief(bank[LAYER_EPISODE], top),
        "summaries": brief(bank[LAYER_SUMMARY], 4),
        "counts": {
            "facts": len(bank[LAYER_FACT]),
            "episodes": len(bank[LAYER_EPISODE]),
            "summaries": len(bank[LAYER_SUMMARY]),
            "archived": len(bank[LAYER_ARCHIVE]),
        },
    }


def remove_item(bank, item_id):
    """按 id 删掉一条记忆（网页「忘记这条」按钮用）。"""
    ensure_bank(bank)
    item_id = str(item_id or "").strip()
    if not item_id:
        return False
    for layer in (LAYER_FACT, LAYER_EPISODE, LAYER_SUMMARY, LAYER_ARCHIVE):
        before = len(bank[layer])
        bank[layer] = [x for x in bank[layer] if str(x.get("id")) != item_id]
        if len(bank[layer]) != before:
            return True
    return False
