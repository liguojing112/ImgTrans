"""商品详情生成 — 服务端代理 LLM 适配器。

客户端不再持有大模型密钥：调用服务端 /v1/llm/chat，
服务端持客户配置的 GLM 密钥调大模型，费用由客户承担。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json

from src.infrastructure.llm_adapter import LLMAdapter, LLMError
from src.infrastructure.llm_config import LLMConfig

_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
TokenSource = str | Callable[[], str | None]


class ServerLLMAdapter(LLMAdapter):
    """与 LLMAdapter 同接口，但 LLM 请求转发到服务端代理。"""

    def __init__(
        self,
        backend_url: str,
        access_token: TokenSource,
        timeout_seconds: float = 120.0,
    ) -> None:
        # provider 非 glm 以避免旧模型的 1024 max_tokens 截断限制；
        # glm-4.6v 等付费模型支持更高输出
        super().__init__(LLMConfig(provider="custom", max_tokens=4096))
        self._backend_url = backend_url.rstrip("/")
        self._token_source = access_token
        self._timeout_seconds = timeout_seconds

    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        return self._server_chat(messages, model, max_tokens, temperature)

    def chat_with_image(
        self,
        image_path: Path,
        prompt: str,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        # 压缩图片再上传，避免大图导致 GLM 视觉处理超时
        image_b64, media_type = self._encode_compressed_image(image_path)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_b64}",
                        },
                    },
                ],
            }
        ]
        return self._server_chat(messages, model, max_tokens)

    @staticmethod
    def _encode_compressed_image(
        path: Path, max_side: int = 1024, quality: int = 82
    ) -> tuple[str, str]:
        """缩放图片最长边到 max_side 并 JPEG 压缩，返回 (base64, media_type)。"""
        from PIL import Image
        import base64
        import io

        with Image.open(path) as image:
            image = image.convert("RGB")
            width, height = image.size
            longest = max(width, height)
            if longest > max_side:
                scale = max_side / longest
                image = image.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    Image.Resampling.LANCZOS,
                )
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return encoded, "image/jpeg"

    def _server_chat(
        self,
        messages: list[dict],
        model: str | None,
        max_tokens: int | None,
        temperature: float | None = None,
    ) -> str:
        token = self._resolve_token()
        body: dict = {
            "messages": messages,
            "max_tokens": self._clamp_max_tokens(
                max_tokens or self._config.max_tokens
            ),
        }
        if model:
            body["model"] = model
        if temperature is not None:
            body["temperature"] = temperature
        encoded = json.dumps(
            body, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        request = Request(
            self._backend_url + "/v1/llm/chat",
            data=encoded,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=UTF-8",
                "Authorization": f"Bearer {token}",
                "User-Agent": "ImgTrans/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise LLMError(
                _backend_error_message(error.code), error.code
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise LLMError("无法连接商品详情生成服务", None) from error
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise LLMError("商品详情服务响应过大", None)
        try:
            text = json.loads(payload.decode("utf-8"))["text"]
        except (UnicodeDecodeError, ValueError, TypeError, KeyError) as error:
            raise LLMError("商品详情服务返回无效结果", None) from error
        if not isinstance(text, str) or not text:
            raise LLMError("商品详情服务未返回内容", None)
        return text

    def _resolve_token(self) -> str:
        value = (
            self._token_source()
            if callable(self._token_source)
            else self._token_source
        )
        if not isinstance(value, str) or len(value) < 16:
            raise LLMError("请先激活应用后再使用商品详情生成", None)
        return value


def _backend_error_message(status: int) -> str:
    if status == 401:
        return "未激活或授权已失效，请先在账户中激活"
    if status == 503:
        return "商品详情生成服务未配置，请联系供应商"
    if status == 502:
        return "大模型服务调用失败，请联系供应商"
    return f"商品详情生成服务请求失败（HTTP {status}）"
