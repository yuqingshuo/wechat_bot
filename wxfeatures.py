# -*- coding: utf-8 -*-
"""微信平台侧的实际能力补强（借鉴 napcat-juice/napcat-ai-chatbot 的功能清单）。

这里是「机器人与微信之间」的工程层，与情感无关：

    * 消息去重    —— 监听回调偶发重复触发同一条消息，重复回复会显得像机器人
    * 好友冷却    —— 同一好友在极短时间内被反复触发时，强制等一下再回
    * Token 统计  —— 估算模型消耗，网页控制台可看（napcat 的 Token 统计图表）
    * 对话隔离    —— 记忆按「好友」隔离（微信群/多人群可换成按会话隔离）
    * 拍一拍/表情 —— 回复之后偶尔来一个轻互动，更像真人（napcat 的戳一戳/表情回应）
"""
import hashlib
import random
import threading
import time

ISOLATION_MODES = {
    "friend": u"每位好友独立记忆（推荐，恋爱关系主体性最强）",
    "shared": u"所有好友共享一份记忆",
}


def estimate_tokens(text):
    """中文场景的粗略 token 估算：中文约 1 字 1 token，英文约 4 字符 1 token。"""
    text = text or ""
    if not text:
        return 0
    cjk = sum(1 for ch in text if u"\u4e00" <= ch <= u"\u9fff")
    other = len(text) - cjk
    return int(cjk + other / 4.0) + 1


def messages_tokens(messages):
    total = 0
    for msg in messages or []:
        if isinstance(msg, dict):
            total += estimate_tokens(str(msg.get("content") or "")) + 4
    return total


class DedupeGuard(object):
    """消息去重：同一条消息（同人 + 同内容 + 同时间片）只处理一次。"""

    def __init__(self, ttl=90.0, bucket=45.0):
        self.ttl = float(ttl)
        self.bucket = float(bucket)
        self._seen = {}
        self._lock = threading.Lock()

    def fingerprint(self, who, content, ts=None):
        ts = ts or time.time()
        slot = int(ts // self.bucket)
        raw = u"%s|%s|%d" % (who or "", (content or "").strip(), slot)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def is_duplicate(self, who, content, ts=None):
        """返回 True 表示这条消息刚刚已经处理过，应当忽略。"""
        ts = ts or time.time()
        key = self.fingerprint(who, content, ts)
        with self._lock:
            self._purge(ts)
            if key in self._seen:
                return True
            self._seen[key] = (ts, who or "")
            return False

    def _purge(self, now):
        expired = [k for k, v in self._seen.items() if now - v[0] > self.ttl]
        for k in expired:
            self._seen.pop(k, None)

    def forget(self, who=None):
        with self._lock:
            if who is None:
                self._seen.clear()
            else:
                self._seen = {k: v for k, v in self._seen.items() if v[1] != who}

    def size(self):
        with self._lock:
            return len(self._seen)


class CooldownGuard(object):
    """好友级冷却：避免短时间内对同一个人连续刷回复。"""

    def __init__(self, default_seconds=6.0):
        self.default_seconds = float(default_seconds)
        self._last = {}
        self._lock = threading.Lock()

    def remaining(self, who, seconds=None, now=None):
        seconds = self.default_seconds if seconds is None else float(seconds)
        now = now or time.time()
        with self._lock:
            last = self._last.get(who, 0.0)
        return max(0.0, seconds - (now - last))

    def is_cooling(self, who, seconds=None, now=None):
        return self.remaining(who, seconds=seconds, now=now) > 0

    def mark(self, who, now=None):
        with self._lock:
            self._last[who] = now or time.time()

    def reset(self, who=None):
        with self._lock:
            if who is None:
                self._last.clear()
            else:
                self._last.pop(who, None)


class TokenStats(object):
    """运行期 Token / 调用统计（网页控制台展示用）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self.calls = 0
            self.prompt_tokens = 0
            self.completion_tokens = 0
            self.failures = 0
            self.by_kind = {}

    def record(self, messages, reply, kind="reply", ok=True):
        prompt = messages_tokens(messages)
        completion = estimate_tokens(reply)
        with self._lock:
            self.calls += 1
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            slot = self.by_kind.setdefault(
                kind, {"calls": 0, "prompt": 0, "completion": 0})
            slot["calls"] += 1
            slot["prompt"] += prompt
            slot["completion"] += completion
            if not ok:
                self.failures += 1

    def snapshot(self):
        with self._lock:
            total = self.prompt_tokens + self.completion_tokens
            return {
                "calls": self.calls,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": total,
                "failures": self.failures,
                "by_kind": {k: dict(v) for k, v in self.by_kind.items()},
                "text": u"模型调用 %d 次 · 约 %d tokens（输入 %d / 输出 %d）" % (
                    self.calls, total, self.prompt_tokens, self.completion_tokens),
            }


def should_poke(reply_text, probability=8, enabled=True):
    """偶尔「拍一拍」对方，类似 napcat 的戳一戳，用来做轻互动。"""
    if not enabled:
        return False
    if random.randint(1, 100) > max(0, min(100, int(probability))):
        return False
    text = reply_text or u""
    # 只在气氛轻松或撒娇的语境下拍，生气/沉重时不拍
    if any(w in text for w in [u"生气", u"难过", u"哭", u"算了", u"别烦"]):
        return False
    return any(w in text for w in [u"哎", u"喂", u"在吗", u"怎么", u"想", u"嘿嘿", u"哈哈"])
