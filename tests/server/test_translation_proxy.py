"""Translation proxy contract and security tests."""

import asyncio
import logging

import httpx

from server.app import create_app
from server.config import ServerSettings
from server.domain.translation import (
    MICROSOFT_LANGUAGE_CODES,
    SUPPORTED_LANGUAGE_CODES,
    TranslationProviderError,
    TranslationProviderItem,
)
from server.infrastructure.database import Database
from src.domain.language import SUPPORTED_LANGUAGE_CODES as CLIENT_LANGUAGE_CODES


CLIENT_TOKEN = "test-client-token-123456"


class _Provider:
    provider_id = "fixture-provider"

    def __init__(self, error: TranslationProviderError | None = None) -> None:
        self.error = error
        self.calls = []

    def translate(self, texts, source_language, target_language, correlation_id):
        self.calls.append((texts, source_language, target_language, correlation_id))
        if self.error is not None:
            raise self.error
        return tuple(
            TranslationProviderItem(
                error_code="fixture_failure",
                error_message="This item could not be translated",
            )
            if text == "FAIL"
            else TranslationProviderItem(
                translated_text=f"translated:{text}",
                source_language=source_language,
            )
            for text in texts
        )


def _app(provider, token: str | None = CLIENT_TOKEN):
    database = Database("sqlite+pysqlite:///:memory:")
    app = create_app(
        ServerSettings(environment="test", client_api_token=token),
        database,
        provider,
    )
    return app


def _request(app, payload, token: str | None = CLIENT_TOKEN):
    async def execute():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        headers = {"X-Correlation-ID": "translate-request-7"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/v1/translations",
                headers=headers,
                json=payload,
            )

    return asyncio.run(execute())


def _payload(texts=("SALE", "FAIL")):
    return {
        "source_language": "en",
        "target_language": "zh-Hans",
        "items": [
            {"item_id": f"region-{index}", "text": text}
            for index, text in enumerate(texts)
        ],
    }


def test_proxy_preserves_item_order_and_isolates_partial_failure(caplog) -> None:
    provider = _Provider()
    app = _app(provider)
    caplog.set_level(logging.DEBUG)
    try:
        response = _request(app, _payload())
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json() == {
            "correlation_id": "translate-request-7",
            "provider": "fixture-provider",
            "items": [
                {
                    "item_id": "region-0",
                    "status": "translated",
                    "translated_text": "translated:SALE",
                    "source_language": "en",
                    "error_code": None,
                    "error_message": None,
                },
                {
                    "item_id": "region-1",
                    "status": "failed",
                    "translated_text": None,
                    "source_language": None,
                    "error_code": "fixture_failure",
                    "error_message": "This item could not be translated",
                },
            ],
        }
        assert provider.calls == [
            (("SALE", "FAIL"), "en", "zh-Hans", "translate-request-7")
        ]
        assert "SALE" not in caplog.text
        assert "FAIL" not in caplog.text
    finally:
        app.state.database.close()


def test_provider_global_error_becomes_stable_per_item_failure() -> None:
    provider = _Provider(
        TranslationProviderError(
            "provider_rate_limited",
            "Translation provider rate limit was reached",
            retryable=True,
        )
    )
    app = _app(provider)
    try:
        response = _request(app, _payload(("one", "two")))
        assert response.status_code == 200
        assert [item["status"] for item in response.json()["items"]] == [
            "failed",
            "failed",
        ]
        assert {
            item["error_code"] for item in response.json()["items"]
        } == {"provider_rate_limited"}
    finally:
        app.state.database.close()


def test_proxy_is_closed_without_client_token_and_rejects_wrong_token() -> None:
    app = _app(_Provider(), None)
    try:
        assert _request(app, _payload(), None).status_code == 503
    finally:
        app.state.database.close()
    app = _app(_Provider())
    try:
        rejected = _request(app, _payload(), "wrong-client-token")
        assert rejected.status_code == 401
        assert rejected.headers["WWW-Authenticate"] == "Bearer"
        assert CLIENT_TOKEN not in rejected.text
    finally:
        app.state.database.close()


def test_proxy_rejects_images_extra_fields_duplicate_ids_and_oversized_text() -> None:
    app = _app(_Provider())
    try:
        with_image = {**_payload(("text",)), "image": "base64-data"}
        assert _request(app, with_image).status_code == 422
        duplicate = _payload(("one", "two"))
        duplicate["items"][1]["item_id"] = duplicate["items"][0]["item_id"]
        assert _request(app, duplicate).status_code == 422
        assert _request(app, _payload(("x" * 5001,))).status_code == 422
    finally:
        app.state.database.close()


def test_all_25_internal_languages_have_explicit_microsoft_mapping() -> None:
    assert len(SUPPORTED_LANGUAGE_CODES) == 25
    assert SUPPORTED_LANGUAGE_CODES == CLIENT_LANGUAGE_CODES
    assert set(MICROSOFT_LANGUAGE_CODES) == set(SUPPORTED_LANGUAGE_CODES)
    assert MICROSOFT_LANGUAGE_CODES["pt-BR"] == "pt"
    assert MICROSOFT_LANGUAGE_CODES["pt-PT"] == "pt-pt"
