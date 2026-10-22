# -*- coding: utf-8 -*-
"""
本地 llama.cpp server Provider (支持 /v1/chat/completions 或 /completion)
"""
import json
import logging
import time
from typing import List, Dict, Any, Optional, Iterator
import requests

from llm.base import BaseLLMProvider, LLMConfig, LLMResponse

logger = logging.getLogger("SimpleWeChatBot.LLM.LlamaCpp")


class LlamaCppProvider(BaseLLMProvider):
    """适配 llama.cpp 的 llama-server 服务"""

    def _get_chat_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/v1/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        if base.endswith("/completion"):
            return base
        # 默认优先尝试 /v1/chat/completions
        return f"{base}/v1/chat/completions"

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

        payload = {
            "model": self.config.model or "default",
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
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

                content = ""
                # 兼容 openai 格式或 llama.cpp 原生 completion
                if "choices" in data and data["choices"]:
                    choice = data["choices"][0]
                    if "message" in choice:
                        content = choice["message"].get("content") or ""
                    elif "text" in choice:
                        content = choice.get("text") or ""
                elif "content" in data:
                    content = data.get("content") or ""

                content = self.clean_text(content)

                usage = data.get("usage", {})
                return LLMResponse(
                    content=content,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    model=data.get("model", self.config.model or "llama.cpp"),
                    raw=data,
                )
            except Exception as e:
                last_err = e
                logger.warning(
                    f"[llama.cpp:{self.config.name}] 请求失败 (尝试 {attempt + 1}/{retries + 1}): {e}"
                )
                if attempt < retries:
                    time.sleep(1.0 * (attempt + 1))

        logger.error(f"[llama.cpp:{self.config.name}] 重试耗尽，最终失败: {last_err}", exc_info=True)
        raise RuntimeError(f"llama.cpp Provider 调用失败: {last_err}") from last_err

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Iterator[str]:
        url = self._get_chat_url()
        headers = self._get_headers()

        payload = {
            "model": self.config.model or "default",
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "stream": True,
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
            line = line.strip()
            if line.startswith("data: "):
                line = line[6:].strip()
            if line == "[DONE]":
                break
            try:
                chunk = json.loads(line)
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    text_piece = delta.get("content") or ""
                    if text_piece:
                        yield text_piece
                elif "content" in chunk:
                    yield chunk["content"]
            except Exception:
                continue
