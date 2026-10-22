# -*- coding: utf-8 -*-
"""把「内心世界」组装成注入 system prompt 的段落（借鉴 Ai-Companion 的编排管线）。

组装顺序即优先级顺序：

    1. 人格锚定 anchoring   —— 最高优先级，钉死「我是谁」
    2. 身份与恋爱关系主轴    —— 名字 / 身份 / 当前阶段（本项目的立身之本）
    3. 关系维度与情绪        —— 调味：亲密、信任、张力、当前心情
    4. 动态人格 OCEAN        —— 调味：这一刻多活泼、多敏感
    5. 内部状态              —— 调味：精力、正在干嘛、脑子里刚闪过的念头
    6. 口癖指纹              —— 调味：说话的味道
    7. 多层记忆              —— 事实 / 共同经历 / 压缩摘要

最后再补一句「主体性守恒」的收尾提醒：情绪和记忆只影响语气，不许改变身份与关系阶段。
"""
from mind import memory as memory_mod
from mind import personality as personality_mod
from mind import state as state_mod
from mind import chatcraft as chatcraft_mod

import re

GUARD_BREAK_WORDS = [u"作为AI", u"作为 AI", u"as an AI", u"人工智能", u"语言模型",
                     u"我是程序", u"我是机器人", u"我是模型", u"虚拟助手", u"AI助手",
                     u"扮演"]
GUARD_SERVICE_WORDS = [u"您好，", u"亲爱的用户", u"为您服务", u"请问有什么可以帮",
                       u"很高兴为您", u"感谢您的", u"请您稍等"]
# 「复述指令」：模型有时会把任务说明当成回复念出来，真人绝不会这么打字
GUARD_ECHO_PATTERN = re.compile(
    u"(用户要求|让我分析|当前是[^，。！？\\s]{0,8}阶段|好感度\\s*\\d|【[^】]{0,10}任务】"
    u"|作为\\s*微信好友|扮演一个|输出严格的|要求：|已读取|系统提示"
    u"|根据(人设|设定|规则|性格|要求)|人设[：:]|人设是(?!什么)|核心性格|按(照)?(人设|设定|性格)|我的设定是|身份是【"
    u"|需要[：:]|禁止输出|只输出|直接输出(微信|内容|回复|消息|要发|发给)|输出(要求|内容|格式)|不要输出"
    # 只收「在描述怎么扮演 / 在转述任务」，不收「角色」本身——聊角色是正常爱好
    u"|用户在(让|要求|说)|扮演.{0,6}角色|发消息(给|到)|给微信好友"
    u"|复述.{0,6}(任务|规则|说明|要求)|改写.{0,6}(任务|规则|说明|要求)|严禁.{0,4}(复述|改写|输出|解释)|思考过程"
    # 提示词里的「规格」被当内容发出来：8~35字、10-30个字、最多发 1~2 句、分享日常或问候
    u"|\\d+\\s*[~～\\-—]\\s*\\d+\\s*个?\\s*字|最多\\s*(发|写|用|说)?\\s*\\d+\\s*[条句]|\\d+\\s*[~～\\-—]\\s*\\d+\\s*句|分享(日常|生活)(或|和)(问候|聊天)"
    u"|写一[句子][^，。]{0,10}的话|用一句.{0,6}的话|不超过.{0,8}个?字"
    # 「照着任务说明解释自己」型复述（实测线上出现过）
    u"|看(一下|下)?(之前|上面)的?消息记录|现在要(围绕|开启)|不能重复之前发过|完全不同的开头"
    u"|句式和落点|朋友口气|自然开启对话"
    u"|我应该用.{0,10}语气|想到了几个方案|需要围绕|(想到|想出|列了)几个(想法|方案|思路)"
    # 注意：不收「让我想想」这种——那是正常人都会说的话。只收「想想…会怎么发」这种
    # 明显在自言自语「该怎么回」的元话语。
    u"|想想.{0,8}会怎么|会怎么(说|发|回|讲|写)|不能太(热情|冷淡|正式|随便|亲密)"
    # 消息后面挂一段「创作说明 / 写作思路」——真人不会给自己的消息配注解
    u"|(创作|写作|回复|输出|内容)(说明|思路|意图)[：:]|思路[：:]|写作说明"
    # 「规则要点：」这种一开口就自报小标题的写法（实测线上出现过，只有 4 个字）。
    # 只收明确属于「说明文档」的小标题；备注/提示/注意 这类词正常人也会用，不拦。
    u"|(规则要点|要点|格式|规范|写作要求|输出格式)[：:]|规则[：:]|要点[：:]"
    # 把「上下文描述」当内容发出来：「没有聊天记录，刚加上好友」
    u"|没有(聊天|对话)?记录|刚加上好友|暂无聊天记录|上下文(为空|里没有)"
    # 提示词专属词汇：这些词是写给模型看的，人跟朋友聊天不会说。
    # 刻意不收「人设」「分寸」——它们在饭圈/日常聊天里是真会出现的词，收了会误伤。
    u"|好感度|亲密度|不谄媚|谄媚|追问(人家)?隐私|保持普通朋友的分寸|当前阶段是"
    # 「在手机上随手发一条微信」——在描述「怎么发消息」，不是在发消息
    u"|(在手机上|随手|单手)(打字|发|写)|发一?条(微信|消息)|怎么发(消息|微信)"
    # 只回了一个列表项：「1. 自然打招呼」——那是在念菜单，不是在说话
    u"|^\\s*\\d+\\s*[.、)）]\\s*[^\\n]{0,12}$"
    u"|(核心)?(性格|年龄|身份|名字|姓名|爱好|性格特点)[：:]"
    # 提示词里的「写作要求」被当内容发出来（实测线上出现过）
    u"|客服腔|敬语|参考(例子|示例)|给的提示|因为是.{0,8}阶段|按照(阶段|设定|要求)"
    # 「别写/别提…」这种祈使说明被原样发出来
    u"|别写(任何)?(解释|旁白|说明)|不写任何(解释|说明|旁白)|别提(好感度|阶段|身份)|随手发的一条"
    # 「可以怎么说」「符合…→…」这种在讲解写法（实测线上出现过）
    u"|我需要(考虑|想想)|可以随口说|可以(说|问|分享)(在|自己|对方)|微信风格|符合[“\"].{0,20}[→>]|不正式"
    # 内心世界区块被念出来：「当前状态：」「阶段：相识（好感0分）」「亲密 36」
    u"|(当前状态|当前情绪|此刻状态|状态|阶段|关系阶段|好感度?)[：:]|（好感\\s*\\d+\\s*分?）"
    u"|亲密\\s*\\d|信任\\s*\\d|已聊\\s*\\d+\\s*轮|精力\\s*\\d+"
    # 内心状态区块的每一行标签（原话会被模型改写，所以按标签抓，不靠逐字比对）
    u"|精力[：:]|此刻在干嘛|心情[：:]|刚刚脑子里闪过的|当下最想做的事|说话的?劲头[：:]|因为累，回复"
    # 「小夏，女，21岁，在校大学生」这种把身份栏整段念出来的写法
    # 要求「岁」后面还有内容，避免误伤「我叫小明，男，28岁」这种正常聊天
    u"|[一-龥]{2,4}[，,][男女][，,]\\s*\\d+\\s*岁[，,])", re.I)
MAX_REPLY_CHARS = 200

# 英文思考过程 / 英文模板：中文微信用微信聊天不会这样（实测线上出现过 "Let me think about..."）
_EN_WORD = re.compile(r"[A-Za-z]{2,}")
_EN_COT = re.compile(r"^\s*(let me|i (should|will|need|can|think)|the (user|message|reply|conversation)"
                     r"|as an? (ai|assistant)|here is|here's|sure[,!]|okay[,!]|"
                     r"i (don'?t|dont) know)", re.I)


def _has_foreign_cot(text):
    """回复里是不是混进了英文思考过程 / 英文模板。"""
    if _EN_COT.search(text):
        return True
    # 英文单词太多（>=3 个，或字母总数 >=12）也不像在跟朋友聊微信
    words = _EN_WORD.findall(text)
    return len(words) >= 3 or sum(len(w) for w in words) >= 12


def chatcraft_prompt_block(incoming_text="", stage_key="1", gap_minutes=None):
    """「聊天手艺」段落：相关性优先 + 身份边界 + 阶段语气 +（看情况）时间感知。

    移植自 AstrBot 的 human-chat-persona Skill。这一段放在锚定之后、情绪之前，
    因为「先答对题」比「语气好不好」优先级更高——答非所问再热情也没用。
    """
    lines = [u"# 怎么回这一句（相关性优先，先答对再答好）"]
    for item in chatcraft_mod.RELEVANCE_RULES:
        lines.append(u"- %s" % item)
    lines.append(u"")
    lines.append(u"# 别把「我」和「对方」搞混")
    for item in chatcraft_mod.IDENTITY_BOUNDARY_RULES:
        lines.append(u"- %s" % item)
    lines.append(u"")
    lines.append(u"# 分寸")
    for item in chatcraft_mod.STAGE_RULES:
        lines.append(u"- %s" % item)
    tactics = chatcraft_mod.tactics_for_stage(stage_key)
    if tactics:
        for item in tactics:
            lines.append(u"- %s" % item)
    if gap_minutes is not None and gap_minutes >= chatcraft_mod.CHAT_STYLE.get(
            "gap_threshold_minutes", 30):
        lines.append(u"- 已经 %d 分钟没聊了，别装作刚说过" % int(gap_minutes))
    for item in chatcraft_mod.TIME_GAP_RULES:
        lines.append(u"- %s" % item)

    # 针对对方这一句的具体提示
    hint = incoming_hint(incoming_text)
    if hint:
        lines.append(u"")
        lines.append(u"# 对方这一句的重点")
        for item in hint:
            lines.append(u"- %s" % item)
    return u"\n".join(lines)


def time_awareness_block(gap_minutes=None, last_chat_ts=None, now=None):
    """真实时间感区块：让模型知道「现在几点、今天几号、上次聊是什么时候」。

    对照 wanna_be_human.json 的 time.include_wall_clock / include_calendar /
    include_last_chat / enable_gap——没有这一块，模型很容易把「早上」说成「晚上」，
    或者刚聊完半小时就问「好久不见」。
    """
    from mind import pacing
    lines = []
    cal = pacing.calendar_line(now=now)
    wall = pacing.wall_clock_line(now=now)
    if cal or wall:
        lines.append(u"# 现在的真实时间（别猜，照这个说）")
        if cal:
            lines.append(u"- %s" % cal)
        if wall:
            lines.append(u"- %s" % wall)
        lines.append(u"- 说到时间就用「早上好 / 中午了 / 这么晚了」这种说法，"
                     u"别报具体钟点，也别说错")
    if pacing.get_time_cfg().get("include_last_chat", True):
        last = pacing.format_last_chat(last_chat_ts, now=now)
        if last:
            lines.append(u"- %s" % last)
    threshold = pacing.get_time_cfg().get("gap_threshold_minutes", 30)
    if gap_minutes is not None and gap_minutes >= threshold:
        lines.append(u"- 已经 %d 分钟没跟 TA 说话了，可以自然地提一句「好一会儿没聊了」，"
                     u"别装作刚聊过，也别追问对方去哪了" % int(gap_minutes))
    return u"\n".join(lines)


def incoming_hint(incoming_text=""):
    """针对对方这一句给模型的具体提醒（据判断结果动态生成）。"""
    if not incoming_text:
        return []
    hints = []
    t = (incoming_text or "").strip()
    if chatcraft_mod.is_question(t):
        hints.append(u"对方在提问：先把答案说出来，再谈别的；"
                     u"不知道就说不知道，别编。")
    if chatcraft_mod.has_negative_mood(t):
        hints.append(u"对方情绪不太好：先接住这个情绪，别急着讲道理、"
                     u"别给方案、别灌鸡汤。")
    if chatcraft_mod.is_self_narrative(t):
        hints.append(u"对方在讲自己的经历：接的是 TA 的这段经历，"
                     u"别把它当成我自己的经历复述回去。")
    if chatcraft_mod.is_low_engagement(t):
        hints.append(u"对方在敷衍或没话说了：回得短一点、收一点，"
                     u"别追问、别连发好几条。")
    if chatcraft_mod.is_greeting(t):
        hints.append(u"对方在打招呼：自然接住就行，别一上来就长篇大论。")
    # 去重（同一段可能命中多条）
    out = []
    for h in hints:
        if h not in out:
            out.append(h)
    return out


def build_mind_block(fs, bank, user_id, incoming_text="", stage_key="1", affection=0,
                     bot_profile=None, stage_name=None, gap_minutes=None,
                     last_chat_ts=None):
    """返回可直接追加进 system prompt 的中文段落（没有任何状态时返回空串）。"""
    if not isinstance(fs, dict):
        return ""
    bot_profile = bot_profile or {}
    emo = fs.get("emotion") or {}
    rel = fs.get("relationship") or {}
    per = fs.get("personality") or {}
    st = fs.get("state") or {}
    anchoring = fs.get("anchoring") or personality_mod.default_anchoring()
    quirks = fs.get("quirks") or personality_mod.default_quirks()

    from mind import emotion as emotion_mod
    stage_cn = stage_name or emotion_mod.STAGE_CN.get(str(stage_key), u"相识")

    blocks = []
    blocks.append(personality_mod.anchoring_prompt_block(anchoring, stage_key))

    # 「怎么回这一句」放在情绪/状态之前：先答对题，再谈语气
    blocks.append(chatcraft_prompt_block(incoming_text, stage_key, gap_minutes))

    # 真实时间感：放在最前面几块，让模型对「现在几点/多久没聊」有准的认知
    try:
        _time_block = time_awareness_block(gap_minutes=gap_minutes,
                                           last_chat_ts=last_chat_ts)
    except Exception:
        _time_block = ""
    if _time_block:
        blocks.append(_time_block)

    # 身份字段可能被清空（网页「改成你想要的」允许留空）：只拼填了的，避免「我是【】，，身份是」
    name = (bot_profile.get("name") or u"").strip()
    _me_bits = []
    if name:
        _me_bits.append(u"我是【%s】" % name)
    for _v in ((bot_profile.get("gender") or u"").strip(),
               (bot_profile.get("age") or u"").strip()):
        if _v:
            _me_bits.append(_v)
    _identity = (bot_profile.get("identity") or u"").strip()
    if _identity:
        _me_bits.append(u"身份是%s" % _identity)
    if not _me_bits:
        _me_bits.append(u"我是这个微信小号本人（具体人设还没填）")
    relation_lines = [
        u"# 主体身份（本项目的主轴：你就是这个微信小号本人）",
        u"- %s" % u"，".join(_me_bits),
        u"- 我正在跟微信好友【%s】聊天，我们的关系阶段是【%s】，好感度 %s 分" % (
            user_id, stage_cn, affection),
        u"- 关系阶段只能由真实互动自然推进：情绪可以起伏，但阶段不许自己跳跃",
    ]
    blocks.append(u"\n".join(relation_lines))

    tone = emotion_mod.relationship_tone(affection, stage_key, rel)
    mood = emotion_mod.emotion_label(emo)
    emo_lines = [u"# 你此刻的情绪与关系感受",
                 u"- %s" % tone,
                 u"- 当前心情：%s" % mood]
    if float(emo.get("arousal", 0.0)) >= 0.70:
        emo_lines.append(u"- 情绪有点上头，说话可能更急、更冲一点，但绝不伤人")
    if float(emo.get("valence", 0.0)) <= -0.30:
        emo_lines.append(u"- 情绪偏低，回复会更短、更闷一点，不要忽然变得很热情")
    if float(rel.get("tension", 0.0)) >= 8:
        emo_lines.append(u"- 有点小别扭：可以先闷半句、或者轻轻刺一下，但主动接话时别冷战到底")
    blocks.append(u"\n".join(emo_lines))

    blocks.append(personality_mod.personality_prompt_block(per, stage_key))
    blocks.append(state_mod.state_prompt_block(st, emo, rel))
    blocks.append(personality_mod.quirks_prompt_block(quirks))

    memo = memory_mod.memory_prompt_block(bank, query=incoming_text, limit=6)
    if memo:
        blocks.append(memo)

    blocks.append(
        u"# 主体性守恒（最后确认一遍）\n"
        u"- 上面所有状态都只是「同一个我今天心情如何」，不是换了人。\n"
        u"- 名字、身份、性别、年龄、和对方的关系阶段，永远以主体身份那一节为准。\n"
        u"- 这一整段是写给你自己看的底稿：心情、精力、好感度、记忆条目、阶段名，"
        u"一个字都不许出现在你发给对方的消息里。你只负责把它们变成语气，"
        u"绝不念出来、绝不汇报、绝不因为数值高低而说明原因。")
    return u"\n\n".join(b for b in blocks if b)


def strip_prompt_examples(prompt_text):
    """从提示词里去掉「正例示范」行，再拿去做比对。

    提示词里写着「像这样就对了：刚下课，食堂门口见？」或
    「- 对方问「在干嘛」→「在画画呢 你呢」」，模型如果真的照着说了，
    那是完全正确的回复，不能因为「和提示词里的字一样」就当成复述指令给拦掉。
    """
    keep = []
    for line in (prompt_text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # 整行是「场景 → 例句」的示范，或者是一小节的标题，都不参与比对
        if u"→" in stripped:
            continue
        if stripped.rstrip(u"：:") in (u"你会怎么回", u"记住几条"):
            continue
        # 提示词里带「」的整行都是示范句（例句 / 该避免的反例），
        # 模型照着说那是对的，不能判成复述指令
        if u"「" in stripped or u"」" in stripped:
            continue
        if (stripped.startswith(u"像这样就对了") or stripped.startswith(u"例如")
                or stripped.startswith(u"比如") or stripped.startswith(u"例子")
                or stripped.startswith(u"（例子") or stripped.startswith(u"(例子")
                or stripped.startswith(u"✓") or stripped.startswith(u"×")):
            continue
        keep.append(line)
    return u"\n".join(keep)


def find_prompt_quotation(reply_text, prompt_text, min_run=5):
    """找出回复里「原样抄了 system prompt 某一小段」的地方。

    模型偶尔会把人设栏、阶段提示词、内心世界区块里的整句话当成回复发出来
    （例如「保持普通朋友的分寸」）。这类句子往往不含任何敏感词，靠关键词抓不到，
    但它和提示词里的原文一字不差，所以用「最长公共子串」来判定最稳。

    返回被抄出来的片段；没有则返回空串。
    """
    reply = (reply_text or "").strip()
    prompt = (prompt_text or "").strip()
    if len(reply) < min_run or not prompt:
        return u""
    # 先切掉标点与空白，只比「实词」，避免「，」「\n」之类凑出假阳性
    reply_core = re.sub(r"[\s，。！？、：；…～,.!?:;\-—～·「」【】()（）\\]+", "", reply)
    best = u""
    for line in prompt.splitlines():
        line = re.sub(r"[\s，。！？、：；…～,.!?:;\-—～·「」【】()（）\\]+", "", line)
        # 逐行找最长公共子串：短行开销小，长行按固定窗口扫
        if len(line) <= 60:
            for i in range(len(reply_core) - min_run + 1):
                for j in range(len(reply_core), i + min_run - 1, -1):
                    if reply_core[i:j] in line:
                        if len(reply_core[i:j]) > len(best):
                            best = reply_core[i:j]
                        break
        else:
            step = 2
            for i in range(len(reply_core) - min_run + 1, step):
                for j in range(len(reply_core), i + min_run - 1, -step):
                    if reply_core[i:j] in line:
                        if len(reply_core[i:j]) > len(best):
                            best = reply_core[i:j]
                        break
    return best if len(best) >= min_run else u""


def guard_reply(reply_text, bank=None, anchoring=None, prompt_text=None,
               incoming_text="", stage_key="1", strict_relevance=False):
    """回复一致性守卫：出戏 / 客服腔 / 旁白 / 超长 / 禁用表达 会被拦下。

    返回 (是否通过, 中文原因)。调用方可据此要求模型重写一次。

    incoming_text 传进来后，守卫会额外检查「答非所问」和「空话套话」。
    """
    text = (reply_text or "").strip()
    if not text:
        return False, u"回复为空"
    for word in GUARD_BREAK_WORDS:
        if word in text:
            return False, u"出戏：出现了「%s」这类非真人表述" % word
    for word in GUARD_SERVICE_WORDS:
        if word in text:
            return False, u"客服腔：出现了「%s」" % word
    echo = GUARD_ECHO_PATTERN.search(text)
    if echo:
        return False, u"复述了指令：出现了「%s」，这是我自己知道的事，不该说给对方听" % (
            echo.group(0))
    quoted = find_prompt_quotation(text, strip_prompt_examples(prompt_text))
    if quoted:
        return False, u"把提示词里的「%s」原样念出来了，这是给我自己看的底稿" % quoted
    stripped = text.lstrip()
    if stripped.startswith(u"（") or stripped.startswith("(") or stripped.startswith("*"):
        return False, u"出现了旁白/动作描述，真人微信不会这么打字"
    if len(text) > MAX_REPLY_CHARS:
        return False, u"太长了（%d 字），微信真人不会一次打这么多" % len(text)
    if _has_foreign_cot(text):
        return False, u"混进了英文思考过程（%s），中文微信聊天里不会有这种东西" % (
            text.strip()[:20])
    bank = bank or {}
    try:
        memory_mod.ensure_bank(bank)
        has_memory = bool(bank.get(memory_mod.LAYER_FACT) or bank.get(memory_mod.LAYER_EPISODE))
    except Exception:
        has_memory = False
    for cue in (u"你上次说", u"你之前提到", u"我记得你说"):
        if cue in text and not has_memory:
            return False, u"提到了「%s」但记忆库里没有对应内容，属于编造" % cue

    # ---- 移植自 AstrBot human-chat-persona 的自检项 ----
    # 1) 套话 / 模板话术：真人不会这么回
    bad = chatcraft_mod.find_forbidden(text)
    if bad:
        return False, u"套话模板：出现了「%s」，换个说法" % bad[0]
    # 2) 整句都是通用积极结尾，信息量为零
    if chatcraft_mod.is_too_generic(text) and len(text) <= 20:
        return False, u"整句都是没信息量的客套话，接住对方说的具体内容"
    # 3) 答非所问：回复里没有对方提到的任何实词
    if incoming_text:
        score = chatcraft_mod.relevance_score(incoming_text, text)
        if score < 0.35:
            return False, (u"答非所问：对方说的是「%s」，这句回复没接上（贴题度 %.2f）" % (
                incoming_text.strip()[:20], score))
        if strict_relevance and chatcraft_mod.is_off_topic(incoming_text, text):
            return False, u"答非所问：这条回复跟对方这句话对不上"
    return True, u"ok"
