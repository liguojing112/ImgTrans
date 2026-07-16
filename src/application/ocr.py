from __future__ import annotations

from src.application.ports import OcrAdapter
from src.domain.image import ImageDocument
from src.domain.ocr import OcrError, OcrResult


class RecognizeText:
    def __init__(self, adapter: OcrAdapter) -> None:
        self._adapter = adapter

    @property
    def language_codes(self) -> tuple[str, ...]:
        return self._adapter.language_codes

    def execute(self, document: ImageDocument, language_code: str) -> OcrResult:
        if language_code not in self._adapter.language_codes:
            raise OcrError("unsupported_language", f"OCR 不支持语言代码：{language_code}")
        return self._adapter.recognize(document, language_code)
