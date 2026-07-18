from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import time

from server.domain.translation import (
    MICROSOFT_LANGUAGE_CODES,
    TranslationProviderError,
    TranslationProviderItem,
)


_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class MicrosoftTranslatorAdapter:
    provider_id = "microsoft-translator-v3"

    def __init__(
        self,
        endpoint: str,
        subscription_key: str,
        region: str | None = None,
        timeout_seconds: float = 10.0,
        max_attempts: int = 2,
        sleeper=time.sleep,
    ) -> None:
        if not subscription_key:
            raise ValueError("Microsoft Translator key is required")
        if timeout_seconds <= 0 or max_attempts <= 0:
            raise ValueError("Translator timeout and attempts must be positive")
        self._endpoint = endpoint
        self._subscription_key = subscription_key
        self._region = region
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._sleeper = sleeper

    def translate(
        self,
        texts: tuple[str, ...],
        source_language: str | None,
        target_language: str,
        correlation_id: str,
    ) -> tuple[TranslationProviderItem, ...]:
        source = _provider_language(source_language) if source_language else None
        target = _provider_language(target_language)
        query: list[tuple[str, str]] = [("api-version", "3.0"), ("to", target)]
        if source is not None:
            query.append(("from", source))
        url = f"{self._endpoint}?{urlencode(query)}"
        encoded = json.dumps(
            [{"Text": text} for text in texts],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json",
            "Ocp-Apim-Subscription-Key": self._subscription_key,
            "X-ClientTraceId": correlation_id,
        }
        if self._region:
            headers["Ocp-Apim-Subscription-Region"] = self._region
        for attempt in range(self._max_attempts):
            request = Request(url, data=encoded, headers=headers, method="POST")
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:
                    payload = response.read(_MAX_RESPONSE_BYTES + 1)
                if len(payload) > _MAX_RESPONSE_BYTES:
                    raise TranslationProviderError(
                        "invalid_provider_response",
                        "Translation provider response is too large",
                    )
                return _parse_response(
                    payload,
                    target,
                    len(texts),
                    source_language,
                )
            except HTTPError as error:
                mapped = _map_http_error(error)
                if mapped.retryable and attempt + 1 < self._max_attempts:
                    self._sleeper(mapped.retry_after_seconds or 0.25 * (attempt + 1))
                    continue
                raise mapped from error
            except (URLError, TimeoutError, OSError) as error:
                mapped = TranslationProviderError(
                    "provider_unavailable",
                    "Translation provider is unavailable",
                    retryable=True,
                )
                if attempt + 1 < self._max_attempts:
                    self._sleeper(0.25 * (attempt + 1))
                    continue
                raise mapped from error
        raise TranslationProviderError(
            "provider_unavailable",
            "Translation provider is unavailable",
        )


class UnavailableTranslationProvider:
    provider_id = "unconfigured"

    def translate(self, texts, source_language, target_language, correlation_id):
        del texts, source_language, target_language, correlation_id
        raise TranslationProviderError(
            "provider_not_configured",
            "Translation provider is not configured",
        )


def _provider_language(internal_code: str) -> str:
    try:
        return MICROSOFT_LANGUAGE_CODES[internal_code]
    except KeyError as error:
        raise TranslationProviderError(
            "unsupported_language",
            "Translation language is not supported",
        ) from error


def _parse_response(
    encoded: bytes,
    target_language: str,
    expected_count: int,
    requested_source_language: str | None,
) -> tuple[TranslationProviderItem, ...]:
    try:
        payload = json.loads(encoded.decode("utf-8"))
        if not isinstance(payload, list) or len(payload) != expected_count:
            raise ValueError
        results = []
        for item in payload:
            translations = item["translations"]
            translated = next(
                candidate["text"]
                for candidate in translations
                if candidate["to"].lower() == target_language.lower()
            )
            if not isinstance(translated, str) or not translated:
                raise ValueError
            source_language = requested_source_language
            if source_language is None:
                detected = item["detectedLanguage"]["language"]
                if not isinstance(detected, str) or not detected:
                    raise ValueError
                source_language = _internal_language(detected)
            results.append(
                TranslationProviderItem(
                    translated_text=translated,
                    source_language=source_language,
                )
            )
        return tuple(results)
    except (UnicodeDecodeError, ValueError, TypeError, KeyError, StopIteration) as error:
        raise TranslationProviderError(
            "invalid_provider_response",
            "Translation provider returned an invalid response",
        ) from error


def _internal_language(provider_code: str) -> str:
    normalized = provider_code.casefold()
    for internal_code, mapped_code in MICROSOFT_LANGUAGE_CODES.items():
        if mapped_code.casefold() == normalized:
            return internal_code
    return provider_code


def _map_http_error(error: HTTPError) -> TranslationProviderError:
    status = error.code
    if status in {401, 403}:
        return TranslationProviderError(
            "provider_authentication_failed",
            "Translation provider authentication failed",
        )
    if status == 429:
        return TranslationProviderError(
            "provider_rate_limited",
            "Translation provider rate limit was reached",
            retryable=True,
            retry_after_seconds=_retry_after(error),
        )
    if status in {408, 500, 503}:
        return TranslationProviderError(
            "provider_unavailable",
            "Translation provider is temporarily unavailable",
            retryable=True,
            retry_after_seconds=_retry_after(error),
        )
    if status == 400:
        return TranslationProviderError(
            "provider_rejected_request",
            "Translation provider rejected the request",
        )
    return TranslationProviderError(
        "provider_failed",
        "Translation provider request failed",
    )


def _retry_after(error: HTTPError) -> float | None:
    value = error.headers.get("Retry-After") if error.headers else None
    if value is None:
        return None
    try:
        return min(2.0, max(0.0, float(value)))
    except ValueError:
        return None
