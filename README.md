# 微信小号情感陪伴聊天机器人（相识 ➔ 相知 ➔ 相恋）

一个给**微信小号 / 伴侣陪伴号**用的轻量 AI 自动聊天程序，带一个浏览器可视化人格控制台。

它不是「问一句答一句」的机器人，而是会自己记住你们聊过什么、按好感度分阶段换语气、主动找你聊天的一个「人」。

> ⚠️ 使用前请先读 [安全与隐私](#-安全与隐私) 和 [⚖️ 免责声明](#️-免责声明)。

---

## ✨ 它能做什么

| 能力 | 说明 |
| --- | --- |
| **三阶段情感轨迹** | 相识（0~29 分）→ 相知（30~79 分）→ 相恋（80+ 分）。好感度靠真实聊天自动累积，也可以在网页上拖滑块强制指定 |
| **全自动运行** | 点一次「🚀 启动机器人」，之后自动连微信 → 监听 → 调用模型 → 回复 → 存记忆 → 继续监听。不用守着点「回复」 |
| **可视化人格控制台** | 网页上改姓名、年龄、身份、性格、三阶段提示词，保存后**热更新即时生效**，不用重启 |
| **主动搭话** | 机器人定时主动找人聊天，可配频率、活跃时段、每日上限、话题池，会优先挑「最久没被搭话」的人 |
| **高拟真回复** | 仿真打字延迟、分段连发、消息合并缓冲——不秒回、不一大段糊脸 |
| **长期记忆** | 聊天记录、情绪状态、好感度、关系事件分层落盘，重启不丢上下文 |
| **多模型后端** | 云端 OpenAI 兼容 API（DeepSeek / 硅基流动 / Moonshot / 官方 OpenAI…）+ 本地 Ollama / llama.cpp，网页上一键热切换 |
| **图片理解** | 可选接入 Moonshot 视觉模型，识别好友发来的图片和表情包 |

---

## 🚀 快速开始

### 1. 环境要求

- **Python 3.9+**
- 微信 PC 版客户端，且**已登录**
- 一个 OpenAI 兼容 API 的 Key（DeepSeek 最便宜；也可以用本地 Ollama 完全免费）

### 2. 安装依赖

```bash
git clone <your-repo-url> wechat-bot
cd wechat-bot
pip install -r requirements.txt
```

### 3. 配置 API Key（三种方式，任选其一）

**方式 A：网页里填（推荐）**

启动程序后打开 `http://127.0.0.1:5000`，在「🧠 AI 大脑」面板填 Key，保存即生效。

**方式 B：本地私有文件**

```bash
copy config_local.py.example config_local.py    # Windows
# cp config_local.py.example config_local.py    # macOS / Linux
```

然后编辑 `config_local.py`：

```python
API_KEY = "sk-你的密钥"
BASE_URL = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"
```

> `config_local.py` 已在 `.gitignore` 里，**永远不会被提交**。

**方式 C：环境变量**

```powershell
$env:WECHATBOT_API_KEY = "sk-你的密钥"          # Windows PowerShell
$env:WECHATBOT_BASE_URL = "https://api.deepseek.com/v1"
$env:WECHATBOT_MODEL  = "deepseek-chat"
```

```bash
export WECHATBOT_API_KEY="sk-你的密钥"          # macOS / Linux
export WECHATBOT_BASE_URL="https://api.deepseek.com/v1"
export WECHATBOT_MODEL="deepseek-chat"
```

**取值优先级：环境变量 > `config_local.py` > `models_config.json`（网页里存的）> 空**

> 这条优先级作用于**默认大脑**（`default_cloud`，也就是程序第一次启动时用 `config.py` 播种的那一个）的
> `API_KEY` / `BASE_URL` / `MODEL` 三项，且**在运行时持续生效**——改了环境变量重启即可换密钥。
> 你在网页里**自己新建**的其他大脑（本地 Ollama、Llama.cpp 等）不受影响，只认 `models_config.json` 里存的值。
>
> 网页「🧠 AI 大脑」面板会显示当前密钥来自哪里（`env` / `config_local` / `saved`），
> 并且**永远不回显密钥明文**。当密钥来自环境变量或 `config_local.py` 时，
> 输入框里填的值不会生效（优先级更高），面板会给出提示。

### 4. 启动

**Windows**：双击 `一键启动.bat`

**跨平台**：

```bash
python boot.py
```

程序会自动打开浏览器控制台。依次完成：

1. **第 1 步 · 跟谁聊天** → 在网页上点开微信通讯录里的好友卡片，把要监听的人加进白名单
2. **第 2 步 · 挑一个人设** → 选一个预设卡（也可以自己写），改姓名、年龄、身份、性格和三阶段提示词
3. **第 3 步 · 启动** → 点「🚀 启动机器人」，之后全自动运行

---

## 📁 目录结构

```
wechat-bot/
├── boot.py                  # 启动入口（自动装依赖、打开浏览器）
├── main.py                  # Flask 主应用：Web 控制台 + 机器人运行时
├── wxbot.py                 # 微信自动化封装（收发、OCR、表情识别）
├── wxfeatures.py            # 微信侧高级功能
├── config.py                # 公共配置（不含密钥，可安全提交）
├── config_local.py.example  # 本地私有配置模板 → 复制成 config_local.py
├── models_config.example.json  # 模型配置模板（网页会生成真的那份）
├── presets.py               # 三套开箱即用的人设预设
├── selftest.py              # 自检脚本
├── llm/                     # LLM 抽象层
│   ├── base.py              #   Provider 基类、LLMConfig
│   ├── config_manager.py    #   多 Provider 配置管理
│   ├── factory.py           #   Provider 工厂
│   └── providers/           #   openai / ollama / llamacpp 实现
├── mind/                    # 「大脑」层
│   ├── personality.py       #   人格与阶段
│   ├── emotion.py           #   情绪状态
│   ├── memory.py            #   长期记忆
│   ├── pacing.py            #   拟人节奏（打字延迟等）
│   ├── prompt.py            #   提示词组装
│   ├── chatcraft.py         #   主动搭话话题
│   ├── state.py             #   状态存储
│   └── store.py             #   mind_state.json / mind_bank.json
├── templates/index.html     # Web 控制台页面
├── static/                  # CSS / JS / favicon
├── emojis/                  # 表情包资源
├── prompts/                 # 提示词示例文件
└── 使用说明.md               # 完整功能文档
```

### 运行时文件（已全部 gitignore，不要提交）

| 文件 | 内容 |
| --- | --- |
| `config_local.py` | 你的 API Key |
| `models_config.json` | 网页里配置的模型（含 Key） |
| `persona.json` | 人设、三阶段提示词、运行设置 |
| `listen_list.json` | 监听好友名单 |
| `chat_histories.json` | 聊天记录 |
| `mind_state.json` / `mind_bank.json` | 情绪状态 / 长期记忆 |
| `persona_archives/` | 人设历史归档 |
| `wechatauto_logs/` | 运行日志 |

---

## 🧪 自检

改完配置或遇到异常时，先跑一遍自检：

```bash
python selftest.py
```

它会检查模块导入、预设完整性、监听名单解析、人格读写、记忆读写、模型配置等。

---

## 🔐 安全与隐私

**这个项目会处理你的微信消息。请务必了解以下几点：**

1. **密钥绝不要提交。** `config_local.py` 和 `models_config.json` 都已在 `.gitignore` 中。仓库里提供的是 `*.example` 模板。
2. **密钥已明文出现过就要立刻轮换。** 如果你曾经把 Key 提交上去，删掉文件是没用的——**去服务商后台吊销并重新生成**才是唯一正确的做法。Git 历史里的内容也会永久留存。
3. **仓库里的 Web 控制台只监听 `127.0.0.1`。** 不要改成 `0.0.0.0` 暴露到公网。这个控制台没有登录认证，暴露出去等于把你的微信和 API Key 交出去。
4. **聊天记录是隐私。** `chat_histories.json`、`mind_*.json`、`persona_archives/` 里有你和好友的对话内容，全部 gitignore 了。发仓库给别人时用「Public archive」而不是 fork。
5. **接口返回里不包含密钥明文。** `/api/llm/providers` 和 `/api/llm/save_provider` 只返回 `has_api_key` 标记，密钥留在服务端；保存时留空表示「沿用原来的」。
6. **默认只监听白名单、忽略群聊。** 建议保持 `IGNORE_GROUP_CHAT = True`，避免在群里刷屏导致账号被限制。

---

## ⚖️ 免责声明

- 本项目仅供**个人学习与娱乐**使用。
- 请遵守微信用户协议与相关法律法规，**不得用于骚扰、诈骗、批量营销、冒充他人**等任何违法违规用途。
- 使用本项目造成的账号限制、封禁或任何损失，由使用者自行承担。
- 使用者需自行确保上传到聊天模型的内容符合其隐私政策与数据合规要求。
- 项目作者不对因使用本项目产生的任何直接或间接损失负责。

---

## 📄 许可证

MIT License

---

## 🙏 致谢

- [wechatauto](https://github.com/lich0821/wechat_auto) —— 微信自动化核心库
- [Flask](https://flask.palletsprojects.com/) —— Web 控制台
- [DeepSeek](https://www.deepseek.com/) / [Moonshot](https://platform.moonshot.cn/) —— 模型服务
