# -*- coding: utf-8 -*-
"""
LLM 统一抽象基类与通用数据模型
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Iterator


@dataclass
class LLMConfig:
    id: str                                  # Provider 唯一标识，例如 "default_cloud", "local_ollama"
    name: str                                # 友好显示名称，例如 "云端大模型"
    provider_type: str                       # 类型："openai" | "ollama" | "llamacpp"
    base_url: str                            # API 根路径
    api_key: str = ""                        # 密钥（本地模型可为空）
    model: str = ""                          # 模型名称
    temperature: float = 0.8                 # 采样温度
    max_tokens: int = 120                    # 最大输出 token
    timeout: float = 45.0                    # 超时时间（秒）
    max_retries: int = 2                     # 失败重试次数
    extra: Dict[str, Any] = field(default_factory=dict)  # 自定义额外扩展字段

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider_type": self.provider_type,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMConfig":
        return cls(
            id=data.get("id", "default"),
            name=data.get("name", "默认模型"),
            provider_type=data.get("provider_type", "openai"),
            base_url=data.get("base_url", "").rstrip("/"),
            api_key=data.get("api_key", ""),
            model=data.get("model", ""),
            temperature=float(data.get("temperature", 0.8)),
            max_tokens=int(data.get("max_tokens", 120)),
            timeout=float(data.get("timeout", 45.0)),
            max_retries=int(data.get("max_retries", 2)),
            extra=data.get("extra", {}) or {},
        )


@dataclass
class LLMResponse:
    content: str
    reasoning_content: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    raw: Optional[Dict[str, Any]] = None


class BaseLLMProvider(ABC):
    """所有模型 Provider 的公共基类"""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    def chat_complete(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """非流式调用，返回 LLMResponse"""
        pass

    @abstractmethod
    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Iterator[str]:
        """流式调用，返回文本片段迭代器"""
        pass

    def clean_text(self, text: str) -> str:
        """剔除 <think> 标签等通用模型思考块"""
        if not text:
            return ""
        s = text.strip()
        if "</think>" in s:
            s = s.split("</think>", 1)[1].strip()
        return s
