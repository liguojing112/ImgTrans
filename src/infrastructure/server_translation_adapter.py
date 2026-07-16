from __future__ import annotations

from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4
import json

from src.domain.translation import (
    TranslationAdapterItem,
    TranslationError,
)


_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
TokenSource = str | Callable[[], str | None]


class ServerTranslationAdapter:
    adapter_id = "imgtrans-server"

    def __init__(
        self,
        base_url: str,
        api_token: TokenSource,
        timeout_seconds: float = 15.0,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Backend URL must use HTTP or HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Backend URL cannot contain credentials, query or fragment")
        if isinstance(api_token, str) and len(api_token) < 16:
            raise ValueError("Backend API token must contain at least 16 characters")
        if not isinstance(api_token, str) and not callable(api_token):
            raise TypeError("Backend API token must be a string or callable")
        if timeout_seconds <= 0:
            raise ValueError("Translation timeout must be positive")
        self._url = f"{base_url.rstrip('/')}/v1/translations"
        self._token_source = api_token
        self._timeout_seconds = timeout_seconds

    def translate(
        self,
        texts: tuple[str, ...],
        source_language: str | None,
        target_language: str,
    ) -> tuple[TranslationAdapterItem, ...]:
        api_token = self._resolve_token()
        item_ids = tuple(f"item-{index}" for index in range(len(texts)))
        encoded = json.dumps(
            {
                "source_language": source_language,
                "target_language": target_language,
                "items": [
                    {"item_id": item_id, "text": text}
                    for item_id, text in zip(item_ids, texts, strict=True)
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self._url,
            data=encoded,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=UTF-8",
                "Authorization": f"Bearer {api_token}",
                "X-Correlation-ID": uuid4().hex,
                "User-Agent": "ImgTrans/0.1",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise TranslationError(
                _backend_error_code(error.code),
                "翻译服务端请求失败",
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise TranslationError(
                "backend_unavailable",
                "无法连接翻译服务端",
            ) from error
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise TranslationError(
                "invalid_backend_response",
                "翻译服务端响应过大",
            )
        return _parse_response(payload, item_ids)

    def _resolve_token(self) -> str:
        value = (
            self._token_source()
            if callable(self._token_source)
            else self._token_source
        )
        if not isinstance(value, str) or len(value) < 16:
            raise TranslationError(
                "backend_authentication_required",
                "请先激活应用后再使用服务端翻译",
            )
        return value


def _parse_response(
    encoded: bytes,
    expected_ids: tuple[str, ...],
) -> tuple[TranslationAdapterItem, ...]:
    try:
        payload = json.loads(encoded.decode("utf-8"))
        items = payload["items"]
        if not isinstance(items, list) or len(items) != len(expected_ids):
            raise ValueError
        results = []
        for expected_id, item in zip(expected_ids, items, strict=True):
            if item["item_id"] != expected_id:
                raise ValueError
            if item["status"] == "translated":
                text = item["translated_text"]
                if not isinstance(text, str) or not text:
                    raise ValueError
                results.append(TranslationAdapterItem(translated_text=text))
            elif item["status"] == "failed":
                code = item["error_code"]
                message = item["error_message"]
                if not isinstance(code, str) or not isinstance(message, str):
                    raise ValueError
                results.append(
                    TranslationAdapterItem(
                        error_code=code,
                        error_message=message,
                    )
                )
            else:
                raise ValueError
        return tuple(results)
    except (UnicodeDecodeError, ValueError, TypeError, KeyError) as error:
        raise TranslationError(
            "invalid_backend_response",
            "翻译服务端返回了无效结果",
        ) from error


def _backend_error_code(status: int) -> str:
    if status == 401:
        return "backend_authentication_failed"
    if status == 429:
        return "backend_rate_limited"
    if status in {408, 500, 502, 503, 504}:
        return "backend_unavailable"
    if status in {400, 413, 422}:
        return "backend_rejected_request"
    return "backend_failed"
