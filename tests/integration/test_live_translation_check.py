from __future__ import annotations

import asyncio

from scripts.run_live_translation_check import execute_live_check, main
from server.config import ServerSettings
from server.domain.translation import TranslationProviderItem


class _Provider:
    provider_id = "microsoft-translator-v3"

    def translate(self, texts, source_language, target_language, correlation_id):
        assert texts == ("Hello", "Summer sale")
        assert source_language is None
        assert target_language == "zh-Hans"
        assert len(correlation_id) == 32
        return tuple(
            TranslationProviderItem(translated_text=f"translated-{index}")
            for index, _ in enumerate(texts)
        )


def test_live_check_exercises_authenticated_proxy_without_persisting_text() -> None:
    result = asyncio.run(
        execute_live_check(
            ServerSettings(environment="test"),
            ("Hello", "Summer sale"),
            None,
            "zh-Hans",
            provider=_Provider(),
        )
    )
    assert result.provider_id == "microsoft-translator-v3"
    assert result.item_count == 2


def test_live_check_fails_closed_without_server_side_translator_key(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv("IMGTRANS_TRANSLATOR_KEY", raising=False)
    assert main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "live_translation_check_failed: Microsoft Translator is not configured\n"
    )
