from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace
import secrets
import sys

import httpx

from server.app import create_app
from server.config import ServerSettings, ServerSettingsError
from server.domain.translation import SUPPORTED_LANGUAGE_CODES
from server.infrastructure.microsoft_translator import MicrosoftTranslatorAdapter


@dataclass(frozen=True, slots=True)
class LiveTranslationCheckResult:
    provider_id: str
    item_count: int


async def execute_live_check(
    settings: ServerSettings,
    texts: tuple[str, ...],
    source_language: str | None,
    target_language: str,
    *,
    provider=None,
) -> LiveTranslationCheckResult:
    if not texts or any(not text.strip() for text in texts):
        raise ValueError("Live translation check texts cannot be empty")
    if provider is None:
        if settings.translator_key is None:
            raise ServerSettingsError("Microsoft Translator is not configured")
        provider = MicrosoftTranslatorAdapter(
            settings.translator_endpoint,
            settings.translator_key,
            settings.translator_region,
            settings.translator_timeout_seconds,
        )
    client_token = secrets.token_urlsafe(32)
    isolated_settings = replace(
        settings,
        environment="integration",
        database_url="sqlite+pysqlite:///:memory:",
        client_api_token=client_token,
        docs_enabled=False,
    )
    app = create_app(isolated_settings, translation_provider=provider)
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://live-check.local",
            timeout=settings.translator_timeout_seconds + 5,
        ) as client:
            response = await client.post(
                "/v1/translations",
                headers={
                    "Authorization": f"Bearer {client_token}",
                    "X-Correlation-ID": secrets.token_hex(16),
                },
                json={
                    "source_language": source_language,
                    "target_language": target_language,
                    "items": [
                        {"item_id": f"check-{index}", "text": text}
                        for index, text in enumerate(texts)
                    ],
                },
            )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items")
        if payload.get("provider") != provider.provider_id:
            raise RuntimeError("Translation proxy reported an unexpected provider")
        if not isinstance(items, list) or len(items) != len(texts):
            raise RuntimeError("Translation proxy returned an invalid item count")
        failures = [item.get("error_code") for item in items if item.get("status") != "translated"]
        if failures:
            code = next((value for value in failures if isinstance(value, str)), "unknown")
            raise RuntimeError(f"Translation provider check failed: {code}")
        return LiveTranslationCheckResult(provider.provider_id, len(items))
    finally:
        app.state.database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an opt-in live check through the ImgTrans translation proxy",
    )
    parser.add_argument(
        "--source-language",
        choices=("auto", *SUPPORTED_LANGUAGE_CODES),
        default="auto",
    )
    parser.add_argument(
        "--target-language",
        choices=SUPPORTED_LANGUAGE_CODES,
        default="zh-Hans",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        settings = ServerSettings.from_env()
        result = asyncio.run(
            execute_live_check(
                settings,
                ("Hello", "Summer sale"),
                None if arguments.source_language == "auto" else arguments.source_language,
                arguments.target_language,
            )
        )
    except (ServerSettingsError, httpx.HTTPError, RuntimeError, ValueError) as error:
        print(f"live_translation_check_failed: {error}", file=sys.stderr)
        return 1
    print(
        "live_translation_check_ok "
        f"provider={result.provider_id} items={result.item_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
