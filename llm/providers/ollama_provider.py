# -*- coding: utf-8 -*-
"""
本地 Ollama Provider (支持原生 /api/chat 与 /v1 兼容格式)
"""
import json
import logging
import time
from typing import List, Dict, Any, Optional, Iterator
import requests

from llm.base import BaseLLMProvider, LLMConfig, LLMResponse

logger = logging.getLogger("SimpleWeChatBot.LLM.Ollama")


class OllamaProvider(BaseLLMProvider):
    """适配 Ollama 本地运行模型"""

    def _get_chat_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        # 支持用户配置 http://localhost:11434 或 http://localhost:11434/api
        if base.endswith("/api/chat"):
            return base
        if base.endswith("/api"):
            return f"{base}/chat"
        return f"{base}/api/chat"

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def chat_complete(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        url = self._get_chat_url()
        headers = self._get_headers()

        # 映射 Ollama options
        options = {
            "temperature": self.config.temperature if temperature is None else temperature,
        }
        tokens = self.config.max_tokens if max_tokens is None else max_tokens
        if tokens:
            options["num_predict"] = tokens

        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        if self.config.extra:
            payload.update(self.config.extra)
        payload.update(kwargs)

        retries = max(0, self.config.max_retries)
        last_err = None

        for attempt in range(retries + 1):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.config.timeout,
                )
                resp.raise_for_status()
                data = resp.json()

                message = data.get("message", {})
                content = message.get("content") or ""
                content = self.clean_text(content)

                prompt_tokens = data.get("prompt_eval_count", 0)
                completion_tokens = data.get("eval_count", 0)

                return LLMResponse(
                    content=content,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                    model=data.get("model", self.config.model),
                    raw=data,
                )
            except Exception as e:
                last_err = e
                logger.warning(
                    f"[Ollama:{self.config.model}] 请求失败 (尝试 {attempt + 1}/{retries + 1}): {e}"
                )
                if attempt < retries:
                    time.sleep(1.0 * (attempt + 1))

        logger.error(f"[Ollama:{self.config.model}] 重试耗尽，最终失败: {last_err}", exc_info=True)
        raise RuntimeError(f"Ollama Provider 调用失败: {last_err}") from last_err

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Iterator[str]:
        url = self._get_chat_url()
        headers = self._get_headers()

        options = {
            "temperature": self.config.temperature if temperature is None else temperature,
        }
        tokens = self.config.max_tokens if max_tokens is None else max_tokens
        if tokens:
            options["num_predict"] = tokens

        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
            "options": options,
        }
        if self.config.extra:
            payload.update(self.config.extra)
        payload.update(kwargs)

        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.config.timeout,
            stream=True,
        )
        resp.raise_for_status()

        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                data = json.loads(line)
                piece = data.get("message", {}).get("content") or ""
                if piece:
                    yield piece
                if data.get("done"):
                    break
            except Exception:
                continue
