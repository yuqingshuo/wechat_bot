# -*- coding: utf-8 -*-
"""模型对比测试：同人设 + 同一段多轮上文，测「前后搭不搭」。

场景：上文里用户提到猫生病，隔了几轮之后问「它怎么样了」。
能接住「猫」的模型才配做聊天大脑；接不住的就会前后不搭。

🔐 本文件会提交到 Git，不含任何密钥。
密钥读取顺序（与 config.py 约定一致）：
  1) 环境变量 WECHATBOT_API_KEY / WECHATBOT_BASE_URL
  2) config_local.py 里的 API_KEY / BASE_URL（该文件不进 Git）
  3) models_config.json 当前生效 provider 的 api_key / base_url（该文件不进 Git，
     即网页控制台「🧠 AI 大脑」里填的那把）
"""
import json
import os
import urllib.request

BASE = "https://docode.cc/v1"
KEY = ""


def _load_credentials():
    """按优先级取 (BASE_URL, API_KEY)，取不到就返回 ("", "")。"""
    base = os.environ.get("WECHATBOT_BASE_URL", "")
    key = os.environ.get("WECHATBOT_API_KEY", "")

    if not (base and key):
        try:
            import config_local  # noqa: F401  本地私有配置，不进 Git
            base = base or getattr(config_local, "BASE_URL", "")
            key = key or getattr(config_local, "API_KEY", "")
        except Exception:
            pass

    if not (base and key):
        try:
            with open("models_config.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
            prov = cfg["providers"][cfg.get("active_provider", "default_cloud")]
            base = base or prov.get("base_url", "")
            key = key or prov.get("api_key", "")
        except Exception:
            pass

    return base, key


BASE, KEY = _load_credentials()

SYSTEM = (
    u"你叫苏晚，19岁，高职电商专业二班学生，人缘好，说话有点拽但心地好。"
    u"用微信聊天的口吻回复，短句、口语，一次只说一件事。"
)

MESSAGES = [
    {"role": "user", "content": u"哎 我家猫昨天吐了"},
    {"role": "assistant", "content": u"啊 严重吗 带去看了没"},
    {"role": "user", "content": u"去了 医生说吃太急 开了点药"},
    {"role": "assistant", "content": u"那就行 吓我一跳 你以后别一次喂那么多了"},
    {"role": "user", "content": u"嗯 今天加班到现在 累瘫"},
    {"role": "assistant", "content": u"辛苦 早点回 别硬扛"},
    {"role": "user", "content": u"它怎么样了"},
]


def chat(model, temperature):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}] + MESSAGES,
        "temperature": temperature,
        "max_tokens": 80,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=60) as resp:
        d = json.load(resp)
    return d["choices"][0]["message"]["content"].strip()


def main():
    global BASE, KEY
    BASE, KEY = _load_credentials()
    if not KEY:
        print(u"没找到 API Key。三种填法任选一：")
        print(u"  1) 环境变量：set WECHATBOT_API_KEY=sk-xxx  (Linux/Mac: export ...)")
        print(u"  2) config_local.py 里写 API_KEY = \"sk-xxx\"")
        print(u"  3) 启动机器人，在网页「🧠 AI 大脑」里填一次（存进 models_config.json）")
        return

    for model in ("kimi-k3", "glm-5.3-flash", "deepseek-v4.1-flash"):
        try:
            reply = chat(model, 0.5)
        except Exception as e:
            print("【%s】调用失败: %s\n" % (model, e))
            continue
        hit = (u"猫" in reply or u"吐" in reply or u"药" in reply)
        print("【%s】%s" % (model, u"✅ 接住了猫" if hit else u"❌ 没接住"))
        print("   %s\n" % reply.replace("\n", " / "))


if __name__ == "__main__":
    main()
