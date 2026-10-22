# -*- coding: utf-8 -*-
"""
统一 LLM 门面：上层业务直接调用此模块中的方法，彻底屏蔽底层模型实现细节
"""
import logging
from typing import List, Dict, Any, Optional, Iterator

from llm.base import BaseLLMProvider, LLMConfig, LLMResponse
from llm.config_manager import config_manager
from llm.factory import create_provider

logger = logging.getLogger("SimpleWeChatBot.LLM")


def get_current_provider() -> BaseLLMProvider:
    """获取当前处于激活状态的模型 Provider 实例"""
    cfg = config_manager.get_active_config()
    return create_provider(cfg)


def chat_completion(
    messages: List[Dict[str, str]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    **kwargs
) -> str:
    """
    统一入口：执行对话生成并返回回复纯文本内容
    自动处理重试、超时、上下文传递以及思考标签剔除
    """
    provider = get_current_provider()
    resp = provider.chat_complete(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs
    )
    return resp.content


def chat_stream(
    messages: List[Dict[str, str]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    **kwargs
) -> Iterator[str]:
    """统一入口：流式对话生成器"""
    provider = get_current_provider()
    return provider.chat_stream(
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs
    )


def switch_provider(provider_id: str) -> bool:
    """热切换当前活跃模型"""
    return config_manager.set_active_provider(provider_id)


def get_active_provider_info() -> Dict[str, Any]:
    """获取当前生效的 Provider 配置详情"""
    cfg = config_manager.get_active_config()
    return cfg.to_dict()


def list_all_providers() -> List[Dict[str, Any]]:
    """列出所有已配置的 Provider"""
    return config_manager.list_providers()


def update_provider_config(provider_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """更新或添加某个 Provider 的配置"""
    cfg = config_manager.save_provider(provider_id, data)
    return cfg.to_dict()


__all__ = [
    "BaseLLMProvider",
    "LLMConfig",
    "LLMResponse",
    "config_manager",
    "get_current_provider",
    "chat_completion",
    "chat_stream",
    "switch_provider",
    "get_active_provider_info",
    "list_all_providers",
    "update_provider_config",
]
