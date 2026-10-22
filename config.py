# -*- coding: utf-8 -*-
"""
微信小号聊天机器人 - 极简配置文件

🔐 关于密钥：本文件会被提交到 Git，所以**不要在这里写死 API Key**。
三种填法（优先级从高到低）：
  1) 环境变量 WECHATBOT_API_KEY / WECHATBOT_BASE_URL / WECHATBOT_MODEL
  2) 本地私有文件 config_local.py（自动被本文件导入，已在 .gitignore 里）
  3) 直接在网页控制台「🧠 AI 大脑」里填（存进 models_config.json，同样已 gitignore）
"""
import os

# ==============================================================================
# 1. 监听范围设置
# ==============================================================================
# LISTEN_MODE 模式选择：
#   - "whitelist": 只监听和回复 WHITELIST 列表中的好友/群聊（推荐，安全可控）
#   - "all_private": 监听并回复所有发来私聊的好友（自动回复加微信的人，群聊不回）
LISTEN_MODE = "whitelist"

# 当 LISTEN_MODE = "whitelist" 时生效。
# 格式：[ ["微信昵称或备注"], ... ]   —— 只管「跟谁聊」，不管「用哪套人设」
#
# ⚠ 这里的昵称必须和微信通讯录里显示的「昵称」或「备注」**完全一致**，
#   否则 AddListenChat 订阅不上，那个人的消息根本收不到、也不会回。
#   昵称填错时，网页顶部的运行状态会显示「⚠ 这几个人没听上」。
#
# 怎么填：
#   1) 先启动机器人，打开网页，点「1. 跟谁聊天」里的好友卡片 ——
#      那里显示的就是微信通讯录里的原始昵称，照抄过来即可。
#   2) 一个人一行，想加几个加几个。
#   3) 人设在网页第 2 步「🎭 挑一个人设」里设一次就全局生效，不用在这里配。
#
# 例：下面这行的意思是——要监听「我的大号」
#     ["我的大号"],
LISTEN_LIST = [
    # 这里填你想跟它谈恋爱的账号昵称，必须和微信通讯录里的昵称/备注一字不差。
    # 也可以不填这里，直接在网页「更多设置 → 👥 监听好友」里加，更方便。
    # ["我的大号"],
]
# 「文件传输助手」没有特意列入：它是给我们自己测试用的，
# 默认不监听、不主动搭话，测试时在网页上手动选它发消息即可。

# 是否忽略群聊（小号聊天强烈建议保持 True，避免在群里刷屏或被封）
IGNORE_GROUP_CHAT = True

# 机器人自身的微信昵称（选填，用于防止自己跟自己死循环聊天）
BOT_WX_NAME = ""


# ==============================================================================
# 2. 对话大模型配置 (兼容 OpenAI 格式，默认支持 DeepSeek / 硅基流动 / 官方 API)
# ------------------------------------------------------------------------------
# 密钥不再写死在这里。取值顺序：
#   环境变量 WECHATBOT_API_KEY > config_local.py 里的 API_KEY > 空字符串
# 正常用法：网页控制台「🧠 AI 大脑」里填一次即可，会存进 models_config.json。
# ==============================================================================

def _env_or_local(name, default=""):
    """先看环境变量 WECHATBOT_<NAME>，再看 config_local.py 里的 <NAME>。

    例：_env_or_local("API_KEY") 会依次找
        环境变量 WECHATBOT_API_KEY
        config_local.py 里的 API_KEY = "sk-..."
    两者都没有时返回 default。
    """
    val = os.environ.get("WECHATBOT_" + name)
    if val:
        return val
    try:
        import config_local  # noqa: F401  本地私有配置，不进 Git
        return getattr(config_local, name, default) or default
    except Exception:
        return default


API_KEY = _env_or_local("API_KEY", "")
BASE_URL = _env_or_local("BASE_URL", "https://api.deepseek.com/v1")
MODEL = _env_or_local("MODEL", "deepseek-chat")

# 最大回复 Token 数（微信好友聊天必须简短碎句，限制在 120 tokens 避免模型长篇大论）
MAX_TOKENS = 120

# 采样温度 (0.0~2.0)，值越高越富有创造力和随性，推荐 0.8~1.1
TEMPERATURE = 1.0

# 保持对话轮数（记忆深度，例如 6 表示记住最近 6 轮往返对话）
MAX_HISTORY_ROUNDS = 6


# ==============================================================================
# 3. 多模态视觉配置 (图片/表情包识别，Moonshot 拥有赠送免费额度)
# ==============================================================================
# 是否开启图片识别（收到图片时，用视觉模型识别画面内容后回复）
ENABLE_IMAGE_VISION = True

# 是否开启表情包识别（收到表情包时，识别表情含义后回复）
ENABLE_EMOJI_VISION = True

# Moonshot 视觉 API 配置（如果不需要或额度用完，可将上面两个设为 False）
# 同样不写死：环境变量 WECHATBOT_MOONSHOT_API_KEY 或 config_local.py 里的 MOONSHOT_API_KEY
MOONSHOT_API_KEY = _env_or_local("MOONSHOT_API_KEY", "")
MOONSHOT_BASE_URL = _env_or_local("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
MOONSHOT_MODEL = _env_or_local("MOONSHOT_MODEL", "moonshot-v1-128k-vision-preview")


# ==============================================================================
# 4. 拟人化打字与消息节奏配置 (降低机器感，保护微信账号安全)
# ==============================================================================
# 平均打字速度 (秒/字)，默认 0.12 ~ 0.15 秒/字，符合真人打字习惯
TYPING_SPEED_PER_CHAR = 0.12

# 随机打字浮动时间 (秒)
TYPING_DELAY_MIN = 0.5
TYPING_DELAY_MAX = 1.5

# 消息合并缓冲等待时间 (秒)：对方连发多条消息时，等待几秒后合并一起回复
QUEUE_WAIT_SECONDS = 5

# ==============================================================================
# 4.1 拟人化「节奏层」配置（对照 AstrBot 的 wanna_be_human.json）
# ------------------------------------------------------------------------------
# 这些值会在程序启动时被 mind/pacing.py 合并进它的默认值，
# 网页控制台改的是 persona.json 里的运行时副本，这里是「出厂默认」。
# ==============================================================================
HUMANIZE = {
    # 时间感：真实钟点 / 日期 / 上次聊天 / 冷热节奏
    "time": {
        "enable_gap": True,
        "gap_threshold_minutes": 30,
        "include_wall_clock": True,
        "include_calendar": True,
        "include_last_chat": True,
        "rhythm_enable": True,
        "rhythm_hot_ratio": 0.2,
        "rhythm_cold_ratio": 0.667,
        "rhythm_delay_hot_min": 1.5,
        "rhythm_delay_hot_max": 4.0,
        "rhythm_delay_cold_min": 10.0,
        "rhythm_delay_cold_max": 25.0,
    },
    # 打字与分段：拆条阈值 / 段数 / 段间停顿 / 自适应去抖
    "typing": {
        "enable": True,
        "delay_min": 0.0,
        "delay_max": 0.0,
        "total_delay_cap": 90.0,
        "split_enable": True,
        "split_threshold": 40,
        "split_max_segments": 3,
        "split_min_part": 8,
        "split_gap_min": 0.5,
        "split_gap_max": 3.0,
        "split_gap_long_prob": 0.2,
        "split_gap_long_min": 4.0,
        "split_gap_long_max": 8.0,
        "debounce_enable": True,
        "enable_adaptive_debounce": True,
        "adaptive_min_wait": 1.0,
        "adaptive_max_wait": 6.0,
        "adaptive_max_total_wait": 12.0,
        "adaptive_short_message_threshold": 10,
        "max_session_wait": 60.0,
    },
    # 主动搭话：静默阈值 / 递增 / 话题权重与冷却 / 赌气
    "proactive": {
        "silence_after_minutes": 45,
        "silence_fluctuation_minutes": 15,
        "silence_scale_enable": True,
        "silence_scale_step": 0.3,
        "silence_scale_cap_minutes": 240,
        "pout_on_unanswered": True,
        "max_unanswered": 6,
        "topic_mode": "mixed",
        "topic_weights": "history=4,life=3,preset=3",
        "topic_repeat_cooldown_days": 7,
        "followup_enable": False,
        "followup_prob": 0.6,
        "followup_delay_min_minutes": 12,
        "followup_delay_max_minutes": 20,
        "followup_max_unanswered": 2,
    },
    # 复读：真人也偶尔原样重复一句，但很少见
    "parrot": {
        "enabled": True,
        "judge_threshold": 7,
        "prob": 0.06,
        "prob_normal": 0.0,
        "cooldown_turns": 8,
        "max_per_day": 3,
        "min_len": 1,
        "max_len": 24,
        "allow_groups": False,
    },
}

# 是否允许根据情感发送表情包（从 emojis 文件夹中选取）
ENABLE_SEND_EMOJI = True
# 发送表情包的触发概率 (0~100)
SEND_EMOJI_PROBABILITY = 30

# ==============================================================================
# 5. Web 可视化控制台配置 (浏览器调节伴侣人格、好感度、各阶段提示词)
# ==============================================================================
ENABLE_WEB_UI = True
WEB_UI_PORT = 5000
# ⚠️ 保持 127.0.0.1。这个控制台**没有登录认证**，里面能控制微信发消息、
# 改人设、读聊天记录。改成 0.0.0.0 会让同网段的人直接接管你的微信。
WEB_UI_HOST = "127.0.0.1"
AUTO_OPEN_BROWSER = True  # 一键启动后自动打开网页控制台（服务器就绪后打开，只开一次）

