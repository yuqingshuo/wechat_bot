# -*- coding: utf-8 -*-
"""
OpenAI 兼容格式 Provider (适用于各类云端大模型 API、vLLM、LM Studio、FastChat、OneAPI 等)
"""
import json
import logging
import time
from typing import List, Dict, Any, Optional, Iterator
import requests

from llm.base import BaseLLMProvider, LLMConfig, LLMResponse

logger = logging.getLogger("SimpleWeChatBot.LLM.OpenAI")


class OpenAICompatibleProvider(BaseLLMProvider):
    """支持标准 OpenAI /v1/chat/completions 规范的提供商"""

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "WeChatBot-LLMProvider/1.0",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _get_endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def chat_complete(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        url = self._get_endpoint()
        headers = self._get_headers()

        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        # 允许传入 extra 里的自定义参数
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

                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                content = message.get("content") or ""
                reasoning = message.get("reasoning_content") or ""

                # 部分模型在思考时如果 content 为空，回退到 reasoning_content
                if not content.strip() and reasoning.strip():
                    content = reasoning.strip()

                content = self.clean_text(content)

                usage = data.get("usage", {})
                return LLMResponse(
                    content=content,
                    reasoning_content=reasoning,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    model=data.get("model", self.config.model),
                    raw=data,
                )
            except Exception as e:
                last_err = e
                logger.warning(
                    f"[{self.config.name}] 请求失败 (尝试 {attempt + 1}/{retries + 1}): {e}"
                )
                if attempt < retries:
                    time.sleep(1.0 * (attempt + 1))

        logger.error(f"[{self.config.name}] 重试耗尽，最终失败: {last_err}", exc_info=True)
        raise RuntimeError(f"OpenAI Provider 调用失败: {last_err}") from last_err

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Iterator[str]:
        url = self._get_endpoint()
        headers = self._get_headers()

        payload = {
            "model": self.config.model,
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
            except Exception:
                continue
