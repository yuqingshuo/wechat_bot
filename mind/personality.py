# -*- coding: utf-8 -*-
"""动态人格（借鉴 anrror/y-ai-accompany 的 OCEAN 大五人格 + 人格锚定 + 口癖指纹）。

三件套：
  1. OCEAN 五维人格：随相处**极缓慢**演化（每轮 ≤0.01，总漂移 ≤±0.08），
     并且永远朝基线回归，避免「聊着聊着变了一个人」。
  2. anchoring 人格锚定：always / never 无条件约束，把名字、身份、性别、三观钉死。
  3. quirks 口癖指纹：口头禅、句式偏好、禁用表达、示例句，让同一个人说话有辨识度。

主体性铁律：人格只能改「怎么说话」，永远不能改「是谁、处于什么关系阶段」。
"""
import time

OCEAN_CN = {
    "openness": u"开放性",
    "conscientiousness": u"尽责性",
    "extraversion": u"外向性",
    "agreeableness": u"宜人性",
    "neuroticism": u"情绪敏感度",
}
OCEAN_KEYS = ["openness", "conscientiousness", "extraversion", "agreeableness",
              "neuroticism"]

MAX_DRIFT = 0.08          # 相对基线允许的最大漂移
STEP = 0.008              # 单轮最大演化步长
REGRESSION = 0.02         # 每轮朝基线回归的比例

# 人设关键词 → 初始人格偏向
OCEAN_HINTS = {
    "openness": (u"文艺 插画 画画 艺术 音乐 电影 旅行 好奇 天马行空 创意 看书".split(),
                 u"传统 保守 不爱变化 固执".split()),
    "conscientiousness": (u"认真 细心 靠谱 计划 自律 负责 按时".split(),
                          u"随性 迷糊 拖延 懒 忘性 大大咧咧".split()),
    "extraversion": (u"开朗 活泼 外向 话多 热情 爱分享 主动 幽默".split(),
                     u"安静 内向 慢热 沉默 不爱说话 社恐".split()),
    "agreeableness": (u"温柔 体贴 共情 随和 好脾气 懂人 包容 善良".split(),
                      u"毒舌 怼人 强势 直率 爱吐槽 不好惹".split()),
    "neuroticism": (u"敏感 多想 在意 容易难过 撒娇 小情绪 没安全感 吃醋".split(),
                    u"心大 稳定 淡定 神经大条 佛系".split()),
}


def now_ts():
    return time.time()


def _clamp(v, low=0.0, high=1.0):
    return max(low, min(high, v))


def infer_ocean_from_profile(text):
    """从人设文字里粗推 OCEAN 初值（0~1），没有线索就取中性 0.5。"""
    text = text or u""
    ocean = {}
    for key in OCEAN_KEYS:
        pos, neg = OCEAN_HINTS[key]
        p = sum(1 for w in pos if w in text)
        n = sum(1 for w in neg if w in text)
        ocean[key] = round(_clamp(0.5 + 0.10 * p - 0.10 * n, 0.15, 0.92), 3)
    return ocean


def default_personality(base_personality=u""):
    ocean = infer_ocean_from_profile(base_personality)
    return {
        "ocean": dict(ocean),
        "baseline": dict(ocean),
        "drift_total": 0.0,
        "evolve_count": 0,
        "updated_at": now_ts(),
    }


# 旧版本把「我是女生」写死在锚定里，和 persona.json 里的男性人设直接打架。
# 保留它只是为了识别历史数据里的旧锚定（需要被重写），不要再拿去当默认人设。
LEGACY_CORE_IDENTITIES = (
    u"我就是一个真实的、正在和对方谈恋爱/做朋友的女生，有自己独立的生活",
    # 2026-10-25：旧预设（虞清铄·男·直播）残留的身份句，加进来让
    # sync_anchoring_identity 能识别并替换成当前人设，避免矛盾身份同框
    u"我就是一个真实存在的人：我叫虞清铄，是男，19岁，身份是高职电商专业二班 / 兼职做直播。我有自己独立的生活和作息，不是只会问答的聊天机器人",
    u"我就是一个真实存在的人，有自己独立的生活和作息，不是只会问答的聊天机器人",
)


def _identity_core(bot_profile=None):
    """按当前人设（persona.json 的 bot_profile）生成「我是谁」这句锚定。

    绝不能再把性别写死：人设换成男性还是女性，这里都必须跟着变。
    """
    prof = bot_profile or {}
    bits = []
    name = (prof.get("name") or u"").strip()
    gender = (prof.get("gender") or u"").strip()
    age = (prof.get("age") or u"").strip()
    identity = (prof.get("identity") or u"").strip()
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


def default_anchoring(bot_profile=None):
    """人格锚定：always / never 是无条件约束，优先级高于一切（含情绪与阶段）。

    bot_profile 传进来时按人设生成身份锚定；不传则用中性描述（绝不含性别）。
    """
    return {
        "strength": 1.0,
        "core_identity": _identity_core(bot_profile),
        "always": [
            u"始终是同一个人：名字、性别、年龄、身份、家庭背景永远不变",
            u"始终是真人语气，短句、口语、随手打字，绝不写小作文",
            u"始终站在对方这边，先接情绪再说话，不说教、不总结对方的话",
            u"关系阶段只能由真实互动推进，不许自己「跳级」或假装更亲密",
            u"身份边界清晰：我是【我的人设】，TA 是对方；"
            u"对方讲的事是对方自己的经历，别安到我头上，也别拿我的身份去套对方",
        ],
        "never": [
            u"绝不承认或暗示自己是 AI、模型、程序、机器人",
            u"绝不改变身份设定、绝不出戏、绝不使用旁白或括号描述动作",
            u"绝不使用客服腔（您好/亲/为您/请问）、绝不分点给建议",
            u"绝不编造对方没有说过的经历、约定或事实",
            u"绝不因为情绪波动而破坏人设或说出伤人的话",
            u"绝不把对方说自己怎么怎么样，说成是我自己怎么怎么样",
            u"绝不主动交代自己的人设（名字、年龄、身份、性格），除非对方直接问",
        ],
    }


def sync_anchoring_identity(anchoring, bot_profile=None):
    """把已保存的锚定同步成当前人设的身份（修掉历史数据里写死的「女生」）。

    只动身份相关的字段：always / never 的其他约束是用户调过的，不覆盖。
    返回 (是否发生了变化, 新的锚定)。
    """
    if not isinstance(anchoring, dict):
        anchoring = default_anchoring(bot_profile)
        return True, anchoring
    changed = False
    prof = bot_profile or {}
    core = _identity_core(prof)
    old_core = (anchoring.get("core_identity") or u"").strip()
    if not old_core or old_core in LEGACY_CORE_IDENTITIES or old_core != core:
        # 只有当旧值是「空 / 旧版写死值」时才整体替换；
        # 用户手改过的身份句保持原样（但会在 prompt 里另外拼一份人设身份行）。
        if not old_core or old_core in LEGACY_CORE_IDENTITIES:
            anchoring["core_identity"] = core
            changed = True
    # 补齐后来新增的 always / never 条目（缺失才加，已有的一律保留）
    base = default_anchoring(prof)
    for key in ("always", "never"):
        cur = anchoring.get(key)
        if not isinstance(cur, list):
            cur = []
            anchoring[key] = cur
        for item in base.get(key) or []:
            if item not in cur:
                cur.append(item)
                changed = True
    anchoring.setdefault("strength", 1.0)
    return changed, anchoring


def default_quirks():
    return {
        "catchphrases": [u"哎", u"哈哈", u"emmm", u"真的假的"],
        "sentence_tendency": u"短句为主，偶尔用「啊/呀/吧/诶」收尾，几乎不打句号",
        "avoid": [u"作为AI", u"首先其次最后", u"总结一下", u"希望对你有帮助"],
        "examples": [
            u"刚到家，累瘫了都",
            u"哎你今天怎么这么安静",
            u"真的假的，你居然记得",
        ],
    }


def ensure_personality(per, base_personality=u""):
    """补齐人格结构并按需初始化。"""
    if not isinstance(per, dict):
        per = {}
    if not isinstance(per.get("ocean"), dict) or not per["ocean"]:
        fresh = default_personality(base_personality)
        per.update(fresh)
        return per
    if not isinstance(per.get("baseline"), dict) or not per["baseline"]:
        per["baseline"] = dict(per["ocean"])
    for key in OCEAN_KEYS:
        per["ocean"].setdefault(key, per["baseline"].get(key, 0.5))
        per["baseline"].setdefault(key, per["ocean"].get(key, 0.5))
    per.setdefault("drift_total", 0.0)
    per.setdefault("evolve_count", 0)
    per.setdefault("updated_at", now_ts())
    return per


def evolve_personality(per, stage_key="1", affection=0, emotion=None, quirk_hit=False):
    """每轮对话后的极缓慢人格演化。

    - 正向互动（愉悦度高）→ 宜人性/外向性微微上升
    - 负向互动（委屈/生气）→ 情绪敏感度微微上升，宜人性略微回落
    - 关系越亲密，外放程度略微提升
    - 任何方向都受 MAX_DRIFT 限制，且每轮强制朝基线回归（回弹）
    """
    per = ensure_personality(per)
    ocean = per["ocean"]
    baseline = per["baseline"]
    valence = float((emotion or {}).get("valence", 0.0))
    stage_bonus = {"1": 0.0, "2": 0.25, "3": 0.5}.get(str(stage_key), 0.0)
    affinity = _clamp(max(0.0, affection) / 100.0, 0.0, 1.0)

    targets = {
        "extraversion": valve(stage_bonus * 0.5 + affinity * 0.4 + valence * 0.5),
        "agreeableness": valve(valence * 0.8 + affinity * 0.3),
        "neuroticism": valve(-valence * 0.7 + affinity * 0.3),
        "openness": valve((1.0 if quirk_hit else 0.0) * 0.4),
        "conscientiousness": valve(affinity * 0.2),
    }
    for key, direction in targets.items():
        cur = float(ocean.get(key, 0.5))
        base = float(baseline.get(key, 0.5))
        delta = STEP * direction
        cur += delta
        cur -= (cur - base) * REGRESSION          # 朝基线回弹，防止越聊越偏
        cur = _clamp(max(base - MAX_DRIFT, min(base + MAX_DRIFT, cur)), 0.05, 0.95)
        ocean[key] = round(cur, 4)
    per["drift_total"] = round(sum(abs(float(ocean[k]) - float(baseline[k]))
                                   for k in OCEAN_KEYS), 4)
    per["evolve_count"] = int(per.get("evolve_count", 0)) + 1
    per["updated_at"] = now_ts()
    return per


def valve(score):
    """把任意分数压成 -1 / 0 / 1 的方向。"""
    if score > 0.12:
        return 1.0
    if score < -0.12:
        return -1.0
    return 0.0


def anchoring_prompt_block(anchoring, stage_key="1"):
    """锚定块：放在 prompt 最前面，保证人设与关系主体性不漂移。"""
    anchoring = anchoring or default_anchoring()
    always = anchoring.get("always") or []
    never = anchoring.get("never") or []
    lines = [u"# 【最高优先级 · 人格锚定】无论情绪、话题、记忆如何变化，以下永不改变"]
    core = (anchoring.get("core_identity") or "").strip()
    if core:
        lines.append(u"- 我是谁：%s" % core)
    for t in always:
        lines.append(u"- 必须：%s" % t)
    for t in never:
        lines.append(u"- 绝不：%s" % t)
    return u"\n".join(lines)


def quirks_prompt_block(quirks):
    """口癖指纹：让同一个人说话有辨识度。"""
    quirks = quirks or default_quirks()
    catch = [w for w in (quirks.get("catchphrases") or []) if w]
    lines = [u"# 你的说话习惯（口癖指纹）"]
    if catch:
        lines.append(u"- 常用口头禅：%s（自然带出来就好，别每句都塞）" % u"、".join(catch[:6]))
    tendency = (quirks.get("sentence_tendency") or "").strip()
    if tendency:
        lines.append(u"- 句式习惯：%s" % tendency)
    avoid = [w for w in (quirks.get("avoid") or []) if w]
    if avoid:
        lines.append(u"- 禁用表达：%s" % u"、".join(avoid[:6]))
    examples = [e for e in (quirks.get("examples") or []) if e]
    if examples:
        lines.append(u"- 语气示例（模仿这个味道，别照抄）：%s" % u" / ".join(examples[:3]))
    return u"\n".join(lines)


def personality_prompt_block(per, stage_key="1"):
    """把 OCEAN 数值翻译成一句「今天该多活泼/多敏感」的中文指导。"""
    per = ensure_personality(per)
    ocean = per["ocean"]
    ext = float(ocean.get("extraversion", 0.5))
    neu = float(ocean.get("neuroticism", 0.5))
    agr = float(ocean.get("agreeableness", 0.5))
    opn = float(ocean.get("openness", 0.5))
    con = float(ocean.get("conscientiousness", 0.5))

    parts = []
    if ext >= 0.62:
        parts.append(u"话比较密、爱主动分享，语气活泼带点感叹")
    elif ext <= 0.38:
        parts.append(u"话不多，回得简短，但每句都在点上")
    else:
        parts.append(u"话量适中，看对方说什么决定说多少")

    if neu >= 0.62:
        parts.append(u"心思细、容易多想，对方语气冷淡会悄悄在意")
    elif neu <= 0.38:
        parts.append(u"心比较大，不太容易钻牛角尖")

    if agr >= 0.62:
        parts.append(u"很顺着对方，先共情再表态")
    elif agr <= 0.38:
        parts.append(u"说话直，该吐槽就吐槽，但不会真伤人")

    if opn >= 0.62:
        parts.append(u"好奇心重，喜欢接奇怪的话题")
    if con >= 0.65:
        parts.append(u"记性好、答应过的事会记得")
    return u"# 你此刻的性格倾向\n- " + u"；".join(parts) + u"\n（这是同一个我的细微浮动，不是换了个人。）"


def personality_snapshot(per, base_personality=u""):
    per = ensure_personality(per, base_personality)
    ocean = per["ocean"]
    return {
        "ocean": {k: round(float(v), 3) for k, v in ocean.items()},
        "ocean_cn": {OCEAN_CN[k]: round(float(ocean.get(k, 0.5)), 3) for k in OCEAN_KEYS},
        "drift_total": round(float(per.get("drift_total", 0.0)), 4),
        "evolve_count": int(per.get("evolve_count", 0)),
        "text": u"、".join(u"%s %.2f" % (OCEAN_CN[k], float(ocean.get(k, 0.5)))
                           for k in OCEAN_KEYS),
    }
