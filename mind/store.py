# -*- coding: utf-8 -*-
"""mind 包的持久化层：原子写 JSON + 线程安全，零第三方依赖。

借鉴 YuanYeYouTao/Yuki-QQbot 的做法——「身份、记忆和关系由自己的数据库保存，
更换模型、账号或网关时不丢」；本项目用两个 JSON 文件承载：

    mind_state.json  {"friends": {"<好友>": {emotion/relationship/personality/state/...}}}
    mind_bank.json   {"friends": {"<好友>": {facts/episodes/summaries/archive}}}
"""
import copy
import json
import logging
import os
import tempfile
import threading
import time

logger = logging.getLogger("SimpleWeChatBot.Mind")

DEFAULT_STATE_FILE = "mind_state.json"
DEFAULT_BANK_FILE = "mind_bank.json"
STATE_VERSION = 1
BANK_VERSION = 1


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def deep_merge(base, patch):
    """把 patch 深合并进 base（base 会被就地修改并返回）。"""
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def load_json(path, default):
    if not os.path.exists(path):
        return copy.deepcopy(default)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return copy.deepcopy(default)
        return data
    except Exception as e:
        logger.warning("读取 %s 失败: %s", os.path.basename(path), e)
        return copy.deepcopy(default)


def save_json_atomic(path, data):
    """先写临时文件再替换，避免写入中断导致 JSON 损坏。"""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".mind_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        logger.warning("写入 %s 失败: %s", os.path.basename(path), e)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False
    return True


class MindStore(object):
    """带节流的持久化容器。

    对话很频繁，每次都落盘会拖慢回复，因此写入带最小间隔（默认 2 秒），
    同时提供 force=True 立即落盘（停止机器人 / 关程序时使用）。
    """

    def __init__(self, base_dir=None, flush_interval=2.0):
        self.base_dir = base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.state_file = os.path.join(self.base_dir, DEFAULT_STATE_FILE)
        self.bank_file = os.path.join(self.base_dir, DEFAULT_BANK_FILE)
        self.flush_interval = max(0.0, float(flush_interval))
        self.state_lock = threading.RLock()
        self.bank_lock = threading.RLock()
        self._io_lock = threading.RLock()
        self._last_flush = 0.0
        self.state = self._empty_state()
        self.bank = self._empty_bank()
        self.load()

    # ---------------- 结构 ----------------

    @staticmethod
    def _empty_state():
        return {"version": STATE_VERSION, "updated_at": 0.0, "friends": {}}

    @staticmethod
    def _empty_bank():
        return {"version": BANK_VERSION, "updated_at": 0.0, "friends": {}}

    # ---------------- 读写 ----------------

    def load(self):
        with self.state_lock:
            self.state = load_json(self.state_file, self._empty_state())
            self.state.setdefault("version", STATE_VERSION)
            if not isinstance(self.state.get("friends"), dict):
                self.state["friends"] = {}
        with self.bank_lock:
            self.bank = load_json(self.bank_file, self._empty_bank())
            self.bank.setdefault("version", BANK_VERSION)
            if not isinstance(self.bank.get("friends"), dict):
                self.bank["friends"] = {}
        return self

    def save_state(self, force=False):
        return self._flush(self.state_file, self.state, self.state_lock, force)

    def save_bank(self, force=False):
        return self._flush(self.bank_file, self.bank, self.bank_lock, force)

    def save_all(self, force=True):
        ok = self.save_state(force=force)
        ok = self.save_bank(force=force) and ok
        return ok

    def _flush(self, path, data, lock, force):
        now = time.time()
        with self._io_lock:
            if not force and (now - self._last_flush) < self.flush_interval:
                return False
            with lock:
                data["updated_at"] = now
                payload = copy.deepcopy(data)
            save_json_atomic(path, payload)
            self._last_flush = now
        return True
