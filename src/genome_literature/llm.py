"""Client for OpenAI-compatible chat-completions APIs (DeepSeek by default).

Used by the AI reading assistant and the Chinese translator.  Settings come
from ``config.LLM_*`` and can be changed at runtime from the web app, which
writes them to ``config.ENV_FILE``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Iterator

import httpx

from . import config
from .net import HttpClient, get_client

logger = logging.getLogger(__name__)

PROVIDER_PRESETS = [
    {"name": "DeepSeek", "base": "https://api.deepseek.com", "model": "deepseek-chat", "reasoning_model": "deepseek-reasoner"},
    {"name": "通义千问 (Qwen)", "base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-max", "reasoning_model": ""},
    {"name": "Moonshot (Kimi)", "base": "https://api.moonshot.cn/v1", "model": "", "reasoning_model": ""},
]

_RETRY_STATUS = {429, 500, 502, 503, 504}
_json_mode_supported: dict[str, bool] = {}


class LLMError(RuntimeError):
    """The model service is not configured, unreachable, or returned an unusable answer."""


def is_configured() -> bool:
    return bool(config.LLM_API_KEY and config.LLM_API_BASE and config.LLM_MODEL)


def endpoint() -> str:
    return config.LLM_API_BASE.rstrip("/") + "/chat/completions"


def key_hint(key: str | None = None) -> str:
    key = config.LLM_API_KEY if key is None else key
    if not key:
        return ""
    return f"{key[:3]}…{key[-4:]}" if len(key) > 10 else "已设置"


def settings() -> dict[str, Any]:
    return {
        "configured": is_configured(),
        "base": config.LLM_API_BASE,
        "model": config.LLM_MODEL,
        "reasoning_model": config.LLM_REASONING_MODEL,
        "key_hint": key_hint(),
        "presets": PROVIDER_PRESETS,
    }


def save_settings(values: dict[str, str]) -> dict[str, Any]:
    """Persist the given ``LLM_*`` values to the .env file and apply them immediately."""
    from dotenv import set_key

    path = config.ENV_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")
    for name in config.LLM_SETTING_KEYS:
        if name not in values:
            continue
        value = str(values[name] or "").strip()
        set_key(str(path), name, value, quote_mode="never")
        os.environ[name] = value
    config.reload_llm_settings()
    return settings()


def model_for(deep: bool) -> str:
    return (config.LLM_REASONING_MODEL or config.LLM_MODEL) if deep else config.LLM_MODEL


def _require_config() -> None:
    if not is_configured():
        raise LLMError("未配置 AI 接口：请点击右上角“AI 设置”填写 API Key（DeepSeek 等），或在 .env 中设置 LLM_API_KEY")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {config.LLM_API_KEY}", "Content-Type": "application/json"}


def _status_error(status: int, text: str) -> LLMError:
    if status in (401, 403):
        return LLMError("AI 接口认证失败，请检查 API Key 是否正确、是否有余额")
    if status == 402:
        return LLMError("AI 接口账户余额不足（HTTP 402）")
    if status == 429:
        return LLMError("AI 接口请求过于频繁或并发超限（HTTP 429），请稍后再试")
    return LLMError(f"AI 接口返回 HTTP {status}: {text[:300]}")


def _payload(messages: list[dict[str, str]], model: str, temperature: float | None, max_tokens: int | None,
             json_mode: bool, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
    if temperature is not None and "reasoner" not in model:
        payload["temperature"] = temperature
    reasoning = model == config.LLM_REASONING_MODEL and model != config.LLM_MODEL
    payload["max_tokens"] = max_tokens or (config.LLM_REASONING_MAX_TOKENS if reasoning else config.LLM_MAX_TOKENS)
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float | None = 0.3,
    max_tokens: int | None = None,
    json_mode: bool = False,
    client: HttpClient | None = None,
) -> str:
    """Single (non-streaming) completion; returns the message content."""
    _require_config()
    client = client or get_client()
    url = endpoint()
    model = model or config.LLM_MODEL
    use_json = json_mode and _json_mode_supported.get(url, True)
    payload = _payload(messages, model, temperature, max_tokens, use_json, stream=False)
    try:
        resp = _post(url, payload, client)
    except LLMError as exc:
        cause = exc.__cause__
        if not (use_json and isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code == 400):
            raise
        logger.info("Endpoint rejected response_format; retrying without it")
        payload.pop("response_format", None)
        resp = _post(url, payload, client)
        _json_mode_supported[url] = False
    try:
        return resp.json()["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"AI 接口返回格式无法识别: {resp.text[:200]}") from exc


def _post(url: str, payload: dict[str, Any], client: HttpClient) -> httpx.Response:
    try:
        return client.post(url, json=payload, headers=_headers(), timeout=config.LLM_TIMEOUT)
    except httpx.HTTPStatusError as exc:
        raise _status_error(exc.response.status_code, exc.response.text) from exc
    except httpx.TransportError as exc:
        raise LLMError(f"无法连接 AI 接口 {config.LLM_API_BASE}: {exc}") from exc


def stream(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float | None = 0.3,
    max_tokens: int | None = None,
    client: HttpClient | None = None,
    retries: int = 2,
) -> Iterator[tuple[str, str]]:
    """Stream a completion as ``(kind, text)`` pairs.

    ``kind`` is ``"content"`` for answer text, ``"reasoning"`` for the thinking
    trace of reasoning models, and ``"finish"`` (text = finish reason) at the end.
    """
    _require_config()
    client = client or get_client()
    payload = _payload(messages, model or config.LLM_MODEL, temperature, max_tokens, json_mode=False, stream=True)
    url = endpoint()
    for attempt in range(retries + 1):
        try:
            with client.stream("POST", url, json=payload, headers=_headers(), timeout=config.LLM_TIMEOUT) as resp:
                if resp.status_code != 200:
                    body = resp.read().decode("utf-8", "replace")
                    if resp.status_code in _RETRY_STATUS and attempt < retries:
                        logger.warning("LLM stream HTTP %d; retrying", resp.status_code)
                        time.sleep(2 * (attempt + 1))
                        continue
                    raise _status_error(resp.status_code, body)
                yield from _parse_sse(resp.iter_lines())
                return
        except httpx.TransportError as exc:
            raise LLMError(f"与 AI 接口的连接中断或无法连接 {config.LLM_API_BASE}: {exc}") from exc


def _parse_sse(lines: Iterator[str]) -> Iterator[tuple[str, str]]:
    finish = ""
    for line in lines:
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        if chunk.get("error"):
            raise LLMError(f"AI 接口错误: {chunk['error']}")
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("reasoning_content"):
                yield "reasoning", delta["reasoning_content"]
            if delta.get("content"):
                yield "content", delta["content"]
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
    yield "finish", finish or "stop"


def test_connection(client: HttpClient | None = None) -> dict[str, Any]:
    started = time.monotonic()
    reply = chat([{"role": "user", "content": "请只回复：连接成功"}], temperature=0, max_tokens=20, client=client)
    return {"ok": True, "model": config.LLM_MODEL, "reply": reply.strip()[:60],
            "seconds": round(time.monotonic() - started, 1)}
