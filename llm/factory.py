# -*- coding: utf-8 -*-
"""
Provider 工厂：根据配置创建对应的 BaseLLMProvider 实例
"""
from typing import Dict, Type
from llm.base import BaseLLMProvider, LLMConfig
from llm.providers.openai_provider import OpenAICompatibleProvider
from llm.providers.ollama_provider import OllamaProvider
from llm.providers.llamacpp_provider import LlamaCppProvider

_PROVIDER_REGISTRY: Dict[str, Type[BaseLLMProvider]] = {
    "openai": OpenAICompatibleProvider,
    "ollama": OllamaProvider,
    "llamacpp": LlamaCppProvider,
}


def register_provider(type_name: str, provider_cls: Type[BaseLLMProvider]):
    """供未来三方或新模型扩展时动态注册"""
    _PROVIDER_REGISTRY[type_name.lower()] = provider_cls


def create_provider(config: LLMConfig) -> BaseLLMProvider:
    """根据 LLMConfig 的 provider_type 实例化对应的 Provider"""
    ptype = (config.provider_type or "openai").lower()
    provider_cls = _PROVIDER_REGISTRY.get(ptype)
    if not provider_cls:
        # 回退到 openai 兼容
        provider_cls = OpenAICompatibleProvider
    return provider_cls(config)
