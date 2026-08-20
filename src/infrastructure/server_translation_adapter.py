from __future__ import annotations

from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4
import json
import re

from src.domain.translation import (
    TranslationAdapterItem,
    TranslationError,
)


_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
TokenSource = str | Callable[[], str | None]


_DEFAULT_ECOMMERCE_PROMPT = (
    "请将以下中文商品图片文字翻译成美国电商图片风格的英文。\n"
    "要求：\n"
    "1. 保留商品含义\n"
    "2. 不直译中文，用美国电商图片标题风格：短促名词短语、标题式大写"
    "（Title Case）、营销语调。少用机械的直译，例如用 No Additives 而"
    "不是 Additive-free，用 Dry & Wet Use 而不是 For dry & wet use；"
    "其它示例：零添加→No Additives，柔软细腻→Soft & Smooth，"
    "干湿两用→Dry & Wet Use\n"
    "3. 简洁，适合图片上的短文本，尽量简短，每条控制在 2~5 个英文单词，"
    "不要超过 8 个单词\n"
    "4. 严格按编号逐行输出，每行格式：编号. 译文（例如：1. Soft & Smooth），"
    "编号与输入一一对应，不要输出任何编号以外的说明"
)


class ServerTranslationAdapter:
    adapter_id = "imgtrans-server"
    reports_source_language = True

    def __init__(
        self,
        base_url: str,
        api_token: TokenSource,
        timeout_seconds: float = 15.0,
        llm_adapter=None,
        ecommerce: bool = True,
        ecommerce_terms: dict[str, str] | None = None,
        ecommerce_prompt: str | None = None,
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
        self._llm = llm_adapter
        self._ecommerce = bool(ecommerce and llm_adapter is not None)
        self._ecommerce_terms_override: dict[str, str] = {}
        self._ecommerce_prompt: str | None = None
        self.set_ecommerce_override(ecommerce_terms, ecommerce_prompt)

    def set_ecommerce_override(
        self,
        terms: dict[str, str] | None = None,
        prompt: str | None = None,
    ) -> None:
        """设置电商翻译的用户覆盖：词库合并到内置词库之上；提示词非空时覆盖内置。"""
        self._ecommerce_terms_override = {
            key.strip(): value.strip()
            for key, value in (terms or {}).items()
            if key.strip() and value.strip()
        }
        self._ecommerce_prompt = (
            prompt.strip() if prompt and prompt.strip() else None
        )

    def translate(
        self,
        texts: tuple[str, ...],
        source_language: str | None,
        target_language: str,
    ) -> tuple[TranslationAdapterItem, ...]:
        # 电商模式：词库整句命中优先，未命中批量走 LLM 电商翻译；
        # LLM 失败时自动降级到服务端（Azure）直译
        if self._ecommerce:
            try:
                return self._ecommerce_translate(texts, target_language)
            except TranslationError:
                raise
            except Exception:
                pass
        return self._azure_translate(texts, source_language, target_language)

    def _azure_translate(
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

    # —— 电商翻译模式（LLM 直接翻译 + 词库） ——

    def _ecommerce_translate(
        self,
        texts: tuple[str, ...],
        target_language: str,
    ) -> tuple[TranslationAdapterItem, ...]:
        from src.infrastructure.ecommerce_terms import ECOMMERCE_TERMS

        terms = {**ECOMMERCE_TERMS, **self._ecommerce_terms_override}
        results: list[TranslationAdapterItem | None] = []
        pending: list[str] = []
        pending_indexes: list[int] = []
        for index, text in enumerate(texts):
            mapped = terms.get(text.strip())
            if mapped:
                results.append(TranslationAdapterItem(translated_text=mapped))
            else:
                results.append(None)
                pending.append(text)
                pending_indexes.append(index)
        if pending:
            short_pending: list[str] = []
            short_indexes: list[int] = []
            long_pending: list[str] = []
            long_indexes: list[int] = []
            for index, text in zip(pending_indexes, pending):
                if _is_ecommerce_phrase(text):
                    short_pending.append(text)
                    short_indexes.append(index)
                else:
                    # 免责声明/长句不适合电商短词风格，走服务端直译避免错译
                    long_pending.append(text)
                    long_indexes.append(index)
            if short_pending:
                translated = self._llm_batch_ecommerce(
                    short_pending, target_language
                )
                for index, translated_text in zip(
                    short_indexes, translated
                ):
                    results[index] = TranslationAdapterItem(
                        translated_text=translated_text
                    )
            if long_pending:
                long_results = self._azure_translate(
                    tuple(long_pending),
                    None,
                    target_language,
                )
                for index, item in zip(long_indexes, long_results):
                    results[index] = item
        return tuple(
            item if item is not None else TranslationAdapterItem(
                translated_text=text
            )
            for item, text in zip(results, texts, strict=True)
        )

    def _llm_batch_ecommerce(
        self,
        texts: list[str],
        target_language: str,
    ) -> list[str]:
        """批量调 LLM 做电商风格翻译，返回与输入一一对应的英文列表。"""
        if self._llm is None:
            raise RuntimeError("电商翻译需要 LLM 适配器")
        items_text = "\n".join(
            f"{index + 1}. {text}" for index, text in enumerate(texts)
        )
        prompt = (
            self._ecommerce_prompt or _DEFAULT_ECOMMERCE_PROMPT
        )
        raw = self._llm.chat(
            [{"role": "user", "content": f"{prompt}\n\n待翻译：\n{items_text}"}],
            max_tokens=4096,
        )
        return _parse_llm_translations(raw, len(texts), texts)


def _is_ecommerce_phrase(text: str) -> bool:
    """判断文本是否适合电商短词风格翻译。

    电商 LLM 提示词要求「2~5 个英文单词的短促名词短语」，只适合短的商品
    短语（如「防臭气」「50-75管通用」）。免责声明/长句（含句号等句子标点、
    长度较长）会被 LLM 强行压缩成无关短词，应分流到服务端直译。
    """
    value = text.strip()
    if not value or len(value) > 16:
        return False
    if any(character in value for character in "。！？；，、:：\n"):
        return False
    return True


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
                source_language = item.get("source_language")
                if source_language is not None and (
                    not isinstance(source_language, str) or not source_language
                ):
                    raise ValueError
                results.append(
                    TranslationAdapterItem(
                        translated_text=text,
                        source_language=source_language,
                    )
                )
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


_NUMBERED_LINE = re.compile(r"^(\d{1,3})\s*[.、:)\]\-]\s*(.+)$")
_BULLET_PREFIX = re.compile(r"^[-*•·]\s*")


def _parse_llm_translations(
    raw: str,
    expected_count: int,
    fallbacks: list[str],
) -> list[str]:
    """解析 LLM 电商翻译输出，稳健对齐到输入条数。

    优先按「编号. 译文」逐行解析；LLM 偶尔会少发几行，缺失条目用原文兜底，
    避免渲染出空文本。完全没有可用输出时抛异常，交由上层降级到服务端直译。
    """
    numbered: dict[int, str] = {}
    plain: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _NUMBERED_LINE.match(line)
        if match:
            index = int(match.group(1)) - 1
            if 0 <= index < expected_count:
                numbered[index] = match.group(2).strip()
        else:
            cleaned = _BULLET_PREFIX.sub("", line).strip()
            if cleaned:
                plain.append(cleaned)
    if not numbered and not plain:
        raise RuntimeError("电商翻译 LLM 未返回有效内容")
    if numbered:
        return [
            numbered.get(index) or fallbacks[index]
            for index in range(expected_count)
        ]
    return [
        plain[index] if index < len(plain) else fallbacks[index]
        for index in range(expected_count)
    ]
