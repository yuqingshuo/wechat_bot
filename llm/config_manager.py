# -*- coding: utf-8 -*-
"""
LLM 配置管理中心：负责加载、持久化 models_config.json 并提供热切换
"""
import os
import json
import logging
import threading
from typing import Dict, Any, Optional, List

from llm.base import LLMConfig
import config as legacy_config

logger = logging.getLogger("SimpleWeChatBot.LLM.ConfigManager")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_CONFIG_FILE = os.path.join(BASE_DIR, "models_config.json")

_config_lock = threading.Lock()


def get_default_models_config() -> Dict[str, Any]:
    legacy_api_key = getattr(legacy_config, "API_KEY", "")
    legacy_base_url = getattr(legacy_config, "BASE_URL", "https://api.deepseek.com/v1")
    legacy_model = getattr(legacy_config, "MODEL", "deepseek-chat")
    legacy_temp = float(getattr(legacy_config, "TEMPERATURE", 0.8))
    legacy_max_tokens = int(getattr(legacy_config, "MAX_TOKENS", 120))

    return {
        "active_provider": "default_cloud",
        "providers": {
            "default_cloud": {
                "id": "default_cloud",
                "name": "云端大模型 (默认)",
                "provider_type": "openai",
                "base_url": legacy_base_url,
                "api_key": legacy_api_key,
                "model": legacy_model,
                "temperature": legacy_temp,
                "max_tokens": legacy_max_tokens,
                "timeout": 45.0,
                "max_retries": 2,
                "extra": {}
            },
            "local_ollama": {
                "id": "local_ollama",
                "name": "本地 Ollama",
                "provider_type": "ollama",
                "base_url": "http://127.0.0.1:11434",
                "api_key": "",
                "model": "qwen2.5:7b",
                "temperature": 0.8,
                "max_tokens": 120,
                "timeout": 60.0,
                "max_retries": 1,
                "extra": {}
            },
            "local_llamacpp": {
                "id": "local_llamacpp",
                "name": "本地 llama.cpp Server",
                "provider_type": "llamacpp",
                "base_url": "http://127.0.0.1:8080/v1",
                "api_key": "",
                "model": "default",
                "temperature": 0.7,
                "max_tokens": 120,
                "timeout": 60.0,
                "max_retries": 1,
                "extra": {}
            }
        }
    }

class LLMConfigManager:
    """管理模型配置文件的增删改查与持久化"""

    def __init__(self, filepath: str = MODELS_CONFIG_FILE):
        self.filepath = filepath
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> Dict[str, Any]:
        with _config_lock:
            if not os.path.exists(self.filepath):
                self._data = get_default_models_config()
                self._save_nolock()
            else:
                try:
                    with open(self.filepath, "r", encoding="utf-8") as f:
                        self._data = json.load(f)
                except Exception as e:
                    logger.error(f"加载 models_config.json 异常，使用默认配置: {e}")
                    self._data = get_default_models_config()

            if "active_provider" not in self._data:
                self._data["active_provider"] = "default_cloud"
            if "providers" not in self._data or not self._data["providers"]:
                self._data["providers"] = get_default_models_config()["providers"]

            return self._data

    def _save_nolock(self):
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.filepath)

    def save(self):
        with _config_lock:
            self._save_nolock()

    def get_raw_data(self) -> Dict[str, Any]:
        with _config_lock:
            return json.loads(json.dumps(self._data))

    def get_active_provider_id(self) -> str:
        with _config_lock:
            return self._data.get("active_provider", "default_cloud")

    def set_active_provider(self, provider_id: str) -> bool:
        with _config_lock:
            if provider_id not in self._data.get("providers", {}):
                logger.warning(f"切换失败：未找到 Provider ID '{provider_id}'")
                return False
            self._data["active_provider"] = provider_id
            self._save_nolock()
            logger.info(f"已切换当前活跃大模型 Provider 为: {provider_id}")
            return True

    def get_active_config(self) -> LLMConfig:
        with _config_lock:
            act_id = self._data.get("active_provider", "default_cloud")
            providers = self._data.get("providers", {})
            p_data = providers.get(act_id)
            if not p_data:
                if providers:
                    act_id = next(iter(providers.keys()))
                    p_data = providers[act_id]
                else:
                    return LLMConfig.from_dict(get_default_models_config()["providers"]["default_cloud"])

            p_data["id"] = act_id
            return LLMConfig.from_dict(p_data)

    def list_providers(self) -> List[Dict[str, Any]]:
        with _config_lock:
            act_id = self._data.get("active_provider", "default_cloud")
            res = []
            for pid, cfg in self._data.get("providers", {}).items():
                item = dict(cfg)
                item["id"] = pid
                item["is_active"] = (pid == act_id)
                # 不把密钥明文吐给前端：只告诉前端「有没有配」，
                # 真正的密钥留在服务端，保存时空值即表示「沿用原来的」。
                item["has_api_key"] = bool(cfg.get("api_key"))
                item["api_key"] = ""
                res.append(item)
            return res

    def save_provider(self, provider_id: str, data: Dict[str, Any]) -> LLMConfig:
        with _config_lock:
            data = dict(data or {})
            data["id"] = provider_id
            # 前端传来的 api_key 为空 = 用户没改密钥，沿用已保存的那个
            if not (data.get("api_key") or "").strip():
                old = self._data.get("providers", {}).get(provider_id) or {}
                data["api_key"] = old.get("api_key", "")
            cfg = LLMConfig.from_dict(data)
            self._data.setdefault("providers", {})[provider_id] = cfg.to_dict()
            self._save_nolock()
            return cfg

    def delete_provider(self, provider_id: str) -> bool:
        with _config_lock:
            providers = self._data.setdefault("providers", {})
            if provider_id not in providers:
                return False
            del providers[provider_id]
            if self._data.get("active_provider") == provider_id:
                self._data["active_provider"] = next(iter(providers.keys())) if providers else "default_cloud"
            self._save_nolock()
            return True


# 单例配置管理器
config_manager = LLMConfigManager()

