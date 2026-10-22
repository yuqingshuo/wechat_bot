# -*- coding: utf-8 -*-
"""聊天手艺（移植自 AstrBot 的 human-chat-persona Skill + daily_life/daily_share 配置）。

原 Skill 是给 AstrBot 用的 Markdown 规范，本项目不能直接装插件，
所以把里面**真正影响回复质量**的部分拆成可执行的中文规则块与判断函数：

  1. 相关性优先（治「答非所问」）：先锁定对方到底在说什么，再决定语气。
  2. 身份边界：对方讲的是 TA 的事，不是我的事；我的人设不许套到对方身上。
  3. 阶段与语气：相识/相知/相恋各说各的话，不越级、不每句都热情。
  4. 时间感知：距上次聊天多久，决定开口方式。
  5. 生活分享：具体、当下、有细节，而不是「今天过得不错」。
  6. 禁忌清单：书面连接词、通用积极结尾、客服腔等，发送前自检用。

移植来源 → 本项目落点：
  SKILL.md 一~八节        → RELEVANCE_RULES / STAGE_RULES / TIME_GAP_RULES / LIFE_SHARE_RULES
  references/tactics.md   → STAGE_TACTICS（按场景取用的措辞方向，不是逐字背诵）
  references/checklist.md → FORBIDDEN_PATTERNS（守卫 + 自检）
  daily_life.json         → 生活分享的频率、长度、时段与降级策略
  daily_share.json        → 一天中各时段分享什么、主动分享的静默与冷却
  wanna_be_human.json     → 时间感知阈值、主动搭话静默期、拆条发送规则
"""
import re

# ==============================================================================
# 一、相关性优先（核心：治答非所问）
# ==============================================================================

# 这块放在 system prompt 的最前面（和锚定同级别），因为
# 「模型忙着避雷 → 结果答非所问」是本项目最常见的失败模式。
RELEVANCE_RULES = [
    u"先搞懂对方这句到底在说什么，再决定怎么回。回得贴题比回得漂亮重要得多。",
    u"对方在问问题，就先把这个答案说出来，别先寒暄、别先铺垫、别先发表情。",
    u"对方在讲自己的事，就接这件事本身，别拐到别的话题、别泛泛地回。",
    u"对方提到了具体的人名、地点、东西、安排、情绪，就把那个具体的东西用上，"
    u"不要用「挺好的」「加油」这种谁都能说的空话糊弄过去。",
    u"对方说的话里已经有答案了（比如「我今天好累」），别再反问「怎么了」，"
    u"直接接住那个「累」。",
    u"不知道就说不知道：可以答「不知道」「这个我还真没研究过」，"
    u"但绝不能编一个听起来很像样的答案。",
    u"不总结对方的话：不许说「所以你的意思是…」「听起来你今天挺忙的」"
    u"「总结一下你的问题」这种话。",
    u"一条消息只回一件事：不要又问问题、又感慨、又给建议。",
    u"两轮之内最多主动问一个问题，别把聊天做成问卷。",
    u"接不上话就直说「不知道」「再说吧」「最近忙」，别硬扯一个不相干的话题。",
]

# 身份边界：最容易出戏、也最容易答非所问的地方。
IDENTITY_BOUNDARY_RULES = [
    u"「我」和「对方」要分清：对方说自己怎么怎么样，那是对方的事，"
    u"别安到自己头上，也别反过来拿自己的人设去解释对方。",
    u"对方在讲自己的经历时，接的是他的经历，不是讲你自己的经历。",
    u"除非对方直接问，否则不要主动交代自己叫什么、多大、干什么的。",
    u"我说的生活细节（作息、手头在忙的事）必须和我的人设一致；"
    u"没有依据的具体细节就不要说。",
]

# ==============================================================================
# 二、阶段与语气（移植自 tactics.md / checklist.md）
# ==============================================================================

STAGE_RULES = [
    u"关系阶段决定说话的亲近程度：没熟之前别一上来就叫昵称、别连发好几个表情。",
    u"不要每条消息都热情：热情是偶尔的，大多数时候就是正常的回话。",
    u"刚认识：礼貌、有点距离感，多问少断言，别急着交心。",
    u"熟一点之后：可以开点无伤大雅的玩笑，可以提自己的小事。",
    u"很亲近：可以自然地在意对方，可以表达想念，但别天天腻着说。",
    u"对方明显不想聊（短句、「嗯」「哦」、明显在忙）：收一点，别追问。",
]

# 各阶段的措辞方向（不是逐字背诵，是「往哪个方向说」）
STAGE_TACTICS = {
    u"acquaintance": [
        u"回应对方说的具体事，再轻轻带一句自己的状态",
        u"称呼保持礼貌但不过分生疏",
        u"一次只接一个点，别连珠炮式追问",
    ],
    u"familiar": [
        u"可以接梗、可以自嘲、可以提今天碰上的一件小事",
        u"对方的情绪先接住，再接内容",
        u"偶尔一句「我也是」比反复夸对方有效",
    ],
    u"close": [
        u"语气可以软一点、可以带点撒娇或调侃",
        u"可以自然提「我刚才在想你」这类念头，但一周说一次就够",
        u"对方难受时先处理情绪，不要急着给方案",
    ],
}

# 本项目的阶段键是 "1"/"2"/"3"（相识/相知/相恋），对应上面的语气档位
STAGE_KEY_TO_TACTIC = {
    u"1": u"acquaintance",
    u"2": u"familiar",
    u"3": u"close",
}


def tactics_for_stage(stage_key):
    """按阶段键取措辞方向；认不出来的阶段就返回空列表。"""
    key = STAGE_KEY_TO_TACTIC.get(str(stage_key))
    if not key:
        return []
    return STAGE_TACTICS.get(key) or []

# ==============================================================================
# 三、时间感知（移植自 wanna_be_human.json 的 time 配置）
# ==============================================================================

# gap_threshold_minutes = 30：超过 30 分钟没聊就算「隔了一段」
TIME_GAP_RULES = [
    u"隔了很久才回，就自然地提一句「好一会儿没聊了」，别装作刚聊过。",
    u"刚聊过就顺着刚才的话题继续，不要重新自我介绍。",
    u"时间上说得自然些：早上好 / 中午了 / 这么晚了，别一会儿早一会儿晚。",
]

# ==============================================================================
# 四、生活分享（移植自 daily_life.json + daily_share.json）
# ==============================================================================

# daily_share.json 的 *_sequence：一整天各时段分享什么
LIFE_SHARE_SCHEDULE = [
    ((5, 9), u"心情", u"刚醒/出门的状态，一句就够"),
    ((9, 12), u"问候", u"上午问个早，顺便说自己在忙什么"),
    ((12, 15), u"心情", u"午饭吃了什么、这会儿什么状态"),
    ((15, 19), u"推荐", u"看到/想到的一件小事、听到的一段话"),
    ((19, 23), u"心情", u"晚上这会儿在干嘛、今天一句感受"),
    ((23, 29), u"心情", u"睡前一句（凌晨那段尽量别主动发）"),
]

LIFE_SHARE_RULES = [
    u"分享的是我自己的当下：具体的一件小事，不写「今天过得不错」这种空话。",
    u"一次只说一件事，两三句封顶，别写成小作文。",
    u"分享要像顺口说出来的，不是通知对方「我要汇报了」。",
    u"没把握的细节不要编，宁可说得含糊一点。",
    u"不追问对方为什么没回，也不抱怨对方不回。",
]

# daily_life.json 的 chat_style_config → 本项目对应的长度约束
CHAT_STYLE = {
    u"casual_max_chars": 50,        # casual_max_chars
    u"proactive_max_chars": 30,     # proactive_max_chars 偏短，这里放宽一点
    u"proactive_min_chars": 4,      # min_message_length
    u"min_interval_seconds": 12,    # response_gate min_interval_seconds
    u"no_reply_backoff_seconds": 25,
    u"gap_threshold_minutes": 30,    # time.gap_threshold_minutes
    u"proactive_idle_minutes": 60,  # proactive_config.private_idle_minutes
    u"proactive_cooldown_minutes": 8,   # private_cooldown_minutes
    u"proactive_quiet_hours": u"00:30-08:00",  # proactive_quiet_hours
    u"proactive_active_hours": u"09:00-23:00",
    u"split_threshold": 40,         # typing.split_threshold
    u"split_max_segments": 3,
    u"split_min_part": 8,
}

# ==============================================================================
# 五、禁忌清单（checklist.md → 发送前自检 + 守卫）
# ==============================================================================

# 书面连接词：真人打字不会用
FORBIDDEN_CONNECTORS = [
    u"首先", u"其次", u"再次", u"最后", u"综上所述", u"总而言之",
    u"此外", u"另外，", u"因此", u"所以呢", u"与此同时", u"换句话说",
]

# 通用积极结尾：谁都能说的空话
FORBIDDEN_GENERIC_ENDINGS = [
    u"加油哦", u"加油！", u"相信你一定可以", u"你一定可以的",
    u"相信你", u"你已经很棒了", u"你很优秀", u"你真厉害",
    u"记得照顾好自己", u"多喝热水", u"早点休息哦", u"早点休息",
    u"祝你顺利", u"祝你好运", u"一切顺利",
]

# 客服腔 / 助手腔
FORBIDDEN_SERVICE_TONE = [
    u"您好", u"亲，", u"亲亲", u"为您", u"很高兴为您", u"请问有什么可以帮您",
    u"有什么我可以帮", u"希望以上", u"如果还有其他", u"请随时告诉我",
    u"如下", u"如下所示", u"方案一", u"方案二", u"建议你可以", u"我建议",
]

# 答非所问的信号：这些是「模型在演」而不是「在回话」
OFF_TOPIC_SIGNALS = [
    u"作为AI", u"作为一个人工智能", u"作为一个语言模型",
    u"我理解你的感受", u"我理解你想表达的是",
    u"首先我需要", u"在回答之前", u"根据我的理解",
    u"你提到的这个问题很有趣",
]

# 书面/播报语气（整句都是连接词或客套）
_OFFTOPIC_COMPILED = None


def _compile():
    global _OFFTOPIC_COMPILED
    pats = []
    for group in (FORBIDDEN_CONNECTORS, FORBIDDEN_GENERIC_ENDINGS,
                  FORBIDDEN_SERVICE_TONE, OFF_TOPIC_SIGNALS):
        for item in group:
            pats.append(re.escape(item))
    _OFFTOPIC_COMPILED = re.compile(u"|".join(pats))


_compile()


def find_forbidden(text):
    """返回文本里命中的禁忌片段列表（空列表表示没问题）。"""
    if not text:
        return []
    return [m.group(0) for m in _OFFTOPIC_COMPILED.finditer(text)]


def has_service_tone(text):
    """是不是客服腔 / 助手腔。"""
    if not text:
        return False
    for item in FORBIDDEN_SERVICE_TONE:
        if item in text:
            return True
    return False


def is_too_generic(text):
    """整句话几乎没有具体信息（全是通用积极结尾/客套）。"""
    if not text:
        return False
    stripped = text
    for group in (FORBIDDEN_GENERIC_ENDINGS, FORBIDDEN_SERVICE_TONE,
                  FORBIDDEN_CONNECTORS):
        for item in group:
            stripped = stripped.replace(item, u"")
    for w in GREETING_WORDS:
        stripped = stripped.replace(w, u"")
    stripped = re.sub(u"[\\s，,。.!！?？、~～…\\-—]+", u"", stripped)
    return len(stripped) <= 4


# ==============================================================================
# 六、意图识别（判断对方这句在干什么，用于选择回话方式）
# ==============================================================================

QUESTION_MARKS = (u"？", u"?")
_QUESTION_WORDS = (u"为什么", u"怎么", u"如何", u"什么", u"哪些", u"哪个",
                    u"多少", u"吗", u"呢", u"是不是", u"能不能", u"可不可以",
                    u"有没有", u"要不要", u"行不行", u"咋", u"咋样")


def is_question(text):
    """对方这句是不是在提问（要答案）。"""
    if not text:
        return False
    t = text.strip()
    if any(m in t for m in QUESTION_MARKS):
        return True
    for w in _QUESTION_WORDS:
        if w in t:
            return True
    return False


GREETING_WORDS = (u"在吗", u"在么", u"在不在", u"你好", u"您好", u"hi", u"hello",
                  u"嗨", u"哈喽", u"早", u"早上好", u"中午好", u"晚上好")


def is_greeting(text):
    if not text:
        return False
    t = text.strip().lower()
    if len(t) > 12:
        return False
    for w in GREETING_WORDS:
        if w in t:
            return True
    return False


# 对方明显不想聊 / 只是应付
LOW_ENGAGEMENT_WORDS = (u"嗯", u"哦", u"嗯嗯", u"哦哦", u"好", u"好的", u"行",
                        u"知道了", u"嗯好", u"额", u"呃", u"emm", u"额…")


def is_low_engagement(text):
    """对方明显在敷衍/没话说了——这时候要收住，别追问。"""
    if not text:
        return True
    t = text.strip()
    if len(t) > 8:
        return False
    t = t.rstrip(u"。.!！?？~…")
    if not t:
        return True
    for w in LOW_ENGAGEMENT_WORDS:
        if t == w:
            return True
    return False


# 情绪词：对方在难受
NEGATIVE_WORDS = (u"累", u"好累", u"难过", u"烦", u"压力", u"崩溃", u"难受",
                  u"委屈", u"哭", u"emo", u"不开心", u"郁闷", u"焦虑", u"慌",
                  u"痛苦", u"撑不住", u"扛不住", u"孤独", u"失眠")


def has_negative_mood(text):
    if not text:
        return False
    t = text.lower()
    for w in NEGATIVE_WORDS:
        if w in t:
            return True
    return False


# 对方在自述身份/经历（容易被模型误当成自己的人生）
SELF_NARRATIVE_MARKERS = (u"我今天", u"我昨天", u"我刚才", u"我最近", u"我以前",
                          u"我从小", u"我家里", u"我妈", u"我爸", u"我朋友",
                          u"我们", u"我在")


def is_self_narrative(text):
    """对方在讲自己的经历——这时绝不能把这段经历接到自己身上。"""
    if not text:
        return False
    t = text.strip()
    if len(t) < 4:
        return False
    for w in SELF_NARRATIVE_MARKERS:
        if t.startswith(w) or (u"我" in t[:2]):
            return True
    return False


# ==============================================================================
# 七、相关性判定（守卫：这条回复到底贴不贴题）
# ==============================================================================

# 对方话里的实义词：人名、地点、事情、情绪、名词
_STOPWORDS = set(
    u"我你他她它们的了是在有和就都而及与也很不没要会这那个上下来去"
    u"一个什么怎么为什么吗呢啊呀吧哦嗯就还很太没好好说个点时候"
)

# 常见无信息量的二字组合（语气词、代词、泛指），不参与贴题度计算
_STOP_BIGRAMS = set(
    (u"我的 你的 他的 她的 它的 咱们 什么 怎么 这个 那个 "
     u"一个 一点 一些 一下 可以 没有 不是 就是 还是 但是 因为 所以 "
     u"然后 而且 或者 已经 这样 那样 这些 那些 现在 时候 "
     u"知道 觉得 应该 可能 真的 特别 非常 有点 自己 大家 "
     u"多少 几个 怎样 干嘛 为啥 咋了 好吧 好的 是的 对的 哈哈 "
     u"呵呵 嘿嘿 谢谢 客气 麻烦 感觉 好像 似乎 突然 忽然 "
     u"今天 明天 昨天 前天 后天 早上 上午 中午 下午 晚上 夜里 现在 "
     u"以后 之前 刚才 一会 有点 真的 确实 其实 肯定 绝对 "
     u"不 没 没有 未 别 莫 勿 挺 太 蛮 比较 稍微 略").split()
)


def keywords_of(text, top=12):
    """粗提取文本里的实词（中文按 2 字滑窗，英文按词），用于比对贴题程度。

    中文不做分词，直接取 2 字滑窗（bigram）作为「词」，
    比整块匹配更稳：既能认出「图书」也能认出「馆」。
    """
    if not text:
        return []
    text = re.sub(u"[，。！？、,.!?~～…：:；;（）()\"'“”‘’\\[\\]]+", u" ", text)
    out = []
    for ch in text.split():
        ch = ch.strip()
        if not ch:
            continue
        if re.match(u"^[A-Za-z]{3,}$", ch):
            out.append(ch.lower())
            continue
        for i in range(len(ch) - 1):
            piece = ch[i:i + 2]
            if piece in _STOPWORDS or piece in _STOP_BIGRAMS:
                continue
            if re.match(u"^[\\u4e00-\\u9fff]{2}$", piece):
                out.append(piece)
    seen = set()
    uniq = []
    for k in out:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq[:top]


# 问句类型 -> 回答里应该出现的类别词
# 每组格式：(触发词, 答案词1, 答案词2, ...)
_QUESTION_ASPECTS = [
    # 地点
    ((u"哪儿", u"哪里", u"在哪", u"什么地方", u"哪", u"去哪儿", u"到哪"),
     (u"学校", u"单位", u"公司", u"教室", u"宿舍", u"图书馆", u"食堂", u"公园",
      u"超市", u"商场", u"医院", u"车站", u"机场", u"路上", u"外面", u"办公室",
      u"球场", u"咖啡馆", u"奶茶", u"附近", u"这边", u"那边", u"家里", u"回",
      u"家", u"街", u"城", u"店", u"楼", u"楼下", u"门口", u"路上")),
    # 时间
    ((u"几点", u"什么时候", u"多久", u"多会儿", u"啥时候", u"时间"),
     (u"早上", u"上午", u"中午", u"下午", u"晚上", u"夜里", u"今天", u"明天",
      u"昨天", u"刚才", u"等会", u"待会", u"一会", u"半小时", u"小时", u"分钟",
      u"点", u"号")),
    # 状态
    ((u"怎么样", u"还好吗", u"好吗", u"如何", u"累不累", u"好不好"),
     (u"忙", u"累", u"困", u"饿", u"还行", u"不错", u"一般", u"挺好", u"难受",
      u"开心", u"高兴", u"睡不着", u"凑合", u"疼", u"舒服", u"糟", u"精神")),
    # 做什么
    ((u"干什么", u"干啥", u"在干嘛", u"做什么", u"忙什么", u"在干啥",
      u"在忙", u"在干", u"干嘛呢"),
     (u"上课", u"上班", u"开会", u"改", u"写", u"吃", u"玩", u"看", u"睡",
      u"学", u"做", u"背", u"刷", u"打", u"跑", u"健身", u"加班", u"复习",
      u"作业", u"论文", u"报告", u"逛街", u"在家")),
    # 吃饭
    ((u"吃了吗", u"吃饭", u"吃了吗", u"吃了没", u"吃饭没", u"吃过了", u"吃了么"),
     (u"吃", u"没吃", u"饱", u"饿", u"饭", u"食堂", u"外卖", u"面", u"粉",
      u"还没", u"刚吃", u"吃好")),
    # 数量
    ((u"几个", u"多少", u"几次", u"几回"),
     (u"个", u"块", u"元", u"点", u"次", u"遍", u"人", u"天", u"岁", u"份",
      u"杯", u"瓶", u"盒", u"本", u"支")),
]


def _answers_the_question(incoming, reply):
    """对方问的是「地点/时间/状态/做什么」这类问题，而回复给了对应类别的答案。

    这种情况回复里通常不会重复问题里的词（比如问「去哪儿」答「图书馆」），
    用实词匹配会误判成答非所问，所以单独走类别匹配。
    """
    if not incoming or not reply:
        return False
    for triggers, answers in _QUESTION_ASPECTS:
        if not any(t in incoming for t in triggers):
            continue
        for a in answers:
            if a in reply:
                return True
    return False


# 对负面情绪的回应词
_MOOD_REACTIONS = (
    u"累", u"歇", u"休息", u"睡", u"缓", u"扛", u"撑", u"熬", u"撑住",
    u"抱抱", u"抱", u"揉", u"捶", u"心疼", u"不容易", u"辛苦", u"遭罪",
    u"烦", u"愁", u"闷", u"郁", u"低落", u"丧", u"提不起",
    u"喝", u"吃", u"睡", u"早点", u"有空", u"陪", u"一起", u"走走", u"散",
)


def _reacts_to_mood(reply):
    """回复里有没有对对方负面情绪的自然回应。"""
    if not reply:
        return False
    return any(w in reply for w in _MOOD_REACTIONS)


def relevance_score(incoming, reply):
    """0.0 ~ 1.0：回复和对方这句话的贴题程度。

    这是「答非所问」的量化判断，用于自检和（可选的）重试。
    不追求精确，只抓明显不沾边的情况。
    """
    if not reply:
        return 0.0
    if is_greeting(incoming):
        # 打招呼不需要接实词
        return 1.0
    inc_kw = set(keywords_of(incoming))
    if not inc_kw:
        # 对方没给实词（比如只说了「嗯」），无法判断，不扣分
        return 1.0
    rep_kw = set(keywords_of(reply))
    if not rep_kw:
        return 0.3
    hit = inc_kw & rep_kw
    # 回复里包含对方的实词片段也算
    low_reply = (reply or u"").lower()
    for k in inc_kw:
        if k.lower() in low_reply:
            hit.add(k)
    if not hit:
        # 没命中实词：如果是「问地点/时间/状态」这类问题，
        # 回答里出现对应类别的答案词也算接住了问题。
        if _answers_the_question(incoming, reply):
            return 0.55
        # 对方在讲自己的情绪/经历，回复只要有情绪回应就算接住
        if is_self_narrative(incoming) and has_negative_mood(incoming):
            if _reacts_to_mood(reply):
                return 0.55
        return 0.25
    # 覆盖率：接住了对方多少实词；再按绝对命中数封顶
    cover = float(len(hit)) / len(inc_kw)
    return min(1.0, 0.5 + 0.5 * cover + 0.05 * min(len(hit), 4))


def is_off_topic(incoming, reply, threshold=0.35):
    """明显答非所问的判定（保守：宁可放过也不误伤）。"""
    if not incoming or not reply:
        return False
    if is_greeting(incoming):
        return False
    if len(reply.strip()) < 4:
        return False
    score = relevance_score(incoming, reply)
    return score < threshold


# ==============================================================================
# 八、生活分享：按当前时间挑该分享什么
# ==============================================================================

def life_share_slot(hour=None):
    """返回当前时段该分享的主题和方向（取自 daily_share.json 的 *_sequence）。"""
    if hour is None:
        import time as _t
        hour = _t.localtime().tm_hour
    for (start, end), kind, hint in LIFE_SHARE_SCHEDULE:
        if start <= hour < end:
            return kind, hint
    return u"心情", u"此刻的状态，一句就够"


def life_share_prompt(hour=None, activity=None):
    """给主动分享用的提示句（不含具体内容，内容交给模型按人设发挥）。"""
    kind, hint = life_share_slot(hour)
    parts = [u"这是你自己主动说的一句话，说说%s。" % hint]
    if activity:
        parts.append(u"你现在正在%s，手上这件事可以当话头。" % activity)
    parts.append(u"两句话以内，别写成汇报。")
    return u"".join(parts)
