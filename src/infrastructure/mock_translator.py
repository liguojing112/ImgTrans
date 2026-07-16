from __future__ import annotations

import re

from src.domain.translation import TranslationAdapterItem


class MockTranslationAdapter:
    adapter_id = "mock-local"
    _PLACEHOLDER = re.compile(r'(<x id="\d+"/>)')
    _DICTIONARIES = {
        "zh-Hans": {
            "SUMMER SALE": "夏季促销",
            "PRODUCT": "商品",
            "SUMMER": "夏季",
            "SALE": "促销",
            "OFF": "优惠",
            "NEW": "新品",
        },
        "en": {
            "商品": "PRODUCT",
            "夏季促销": "SUMMER SALE",
            "夏季": "SUMMER",
            "促销": "SALE",
            "优惠": "OFF",
            "新品": "NEW",
        },
    }

    def translate(
        self,
        texts: tuple[str, ...],
        source_language: str | None,
        target_language: str,
    ) -> tuple[TranslationAdapterItem, ...]:
        del source_language
        dictionary = self._DICTIONARIES.get(target_language)
        return tuple(
            TranslationAdapterItem(
                translated_text=self._translate_text(
                    text,
                    target_language,
                    dictionary,
                )
            )
            for text in texts
        )

    def _translate_text(
        self, text: str, target_language: str, dictionary: dict[str, str] | None
    ) -> str:
        parts = self._PLACEHOLDER.split(text)
        changed = False
        for index in range(0, len(parts), 2):
            segment = parts[index]
            if dictionary:
                for source, target in sorted(dictionary.items(), key=lambda item: len(item[0]), reverse=True):
                    replaced = re.sub(rf"(?<!\w){re.escape(source)}(?!\w)", target, segment, flags=re.IGNORECASE)
                    changed = changed or replaced != segment
                    segment = replaced
            parts[index] = segment
        result = "".join(parts)
        if changed:
            return result
        return f"【模拟 {target_language}】{result}"
