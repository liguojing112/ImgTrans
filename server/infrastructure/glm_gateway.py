"""GLM（智谱）网关 — 服务端代理商品详情生成的 LLM 调用。

配置通过 config_provider 动态读取（优先数据库后台配置，其次环境变量），
客户端不再持有大模型密钥，由客户在后台统一配置。
"""

from __future__ import annotations

from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import time

_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_RETRYABLE_HTTP = {429, 500, 502, 503, 504}
# 智谱业务错误码：访问量过大（限流）
_RATE_LIMIT_CODES = {"1305", "rate_limit", "429"}


class GlmError(RuntimeError):
    pass


class GlmNotConfigured(GlmError):
    pass


class GlmGateway:
    """OpenAI 兼容协议的 GLM 调用器（base_url 为智谱 paas/v4）。"""

    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
    CHAT_PATH = "/chat/completions"

    def __init__(
        self,
        config_provider: Callable[[], dict | None],
        timeout_seconds: float = 30.0,
        max_attempts: int = 4,
        sleeper=time.sleep,
    ) -> None:
        self._provider = config_provider
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleeper = sleeper

    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        config = self._provider()
        if not config or not config.get("api_key"):
            raise GlmNotConfigured("GLM 未配置，请在后台第三方配置填写 API 密钥")
        base_url = (config.get("base_url") or self.DEFAULT_BASE_URL).rstrip("/")
        body: dict = {
            "model": model or config.get("model") or "glm-4.6v-flash",
            "messages": messages,
            "max_tokens": max_tokens or 4096,
        }
        if temperature is not None:
            body["temperature"] = temperature
        encoded = json.dumps(
            body, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        request = Request(
            base_url + self.CHAT_PATH,
            data=encoded,
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "Accept": "application/json",
                "Authorization": f"Bearer {config['api_key']}",
            },
            method="POST",
        )
        for attempt in range(self._max_attempts):
            retryable = attempt + 1 < self._max_attempts
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:
                    payload = response.read(_MAX_RESPONSE_BYTES + 1)
            except HTTPError as error:
                if error.code in _RETRYABLE_HTTP and retryable:
                    self._sleeper(0.5 * (attempt + 1))
                    continue
                raise GlmError(f"GLM 服务返回 HTTP {error.code}") from error
            except (URLError, TimeoutError, OSError) as error:
                if retryable:
                    self._sleeper(0.5 * (attempt + 1))
                    continue
                raise GlmError("无法连接 GLM 服务") from error
            if len(payload) > _MAX_RESPONSE_BYTES:
                raise GlmError("GLM 服务响应过大")
            if _is_rate_limited(payload):
                if retryable:
                    self._sleeper(0.8 * (attempt + 1))
                    continue
                raise GlmError("GLM 服务当前访问量过大，请稍后再试")
            return _extract_text(payload)
        raise GlmError("GLM 服务当前访问量过大，请稍后再试")


def _is_rate_limited(payload: bytes) -> bool:
    """判断 GLM 响应是否为限流（HTTP 200 但业务错误码为 1305 等）。"""
    try:
        data = json.loads(payload.decode("utf-8"))
        error = data.get("error") or {}
        code = error.get("code")
    except (UnicodeDecodeError, ValueError, TypeError, AttributeError):
        return False
    return isinstance(code, str) and code in _RATE_LIMIT_CODES


def _extract_text(payload: bytes) -> str:
    try:
        data = json.loads(payload.decode("utf-8"))
        choices = data["choices"]
        if not choices:
            raise GlmError("GLM 服务未返回内容")
        content = choices[0].get("message", {}).get("content")
    except (UnicodeDecodeError, ValueError, TypeError, KeyError) as error:
        raise GlmError("GLM 服务返回无效结果") from error
    if not isinstance(content, str) or not content:
        raise GlmError("GLM 服务未返回内容")
    return content
