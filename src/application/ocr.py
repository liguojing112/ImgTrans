from __future__ import annotations

from src.application.ports import OcrAdapter
from src.domain.image import ImageDocument
from src.domain.ocr import HighRecallOcrOptions, OcrError, OcrMode, OcrResult


class RecognizeText:
    def __init__(self, adapter: OcrAdapter) -> None:
        self._adapter = adapter

    @property
    def language_codes(self) -> tuple[str, ...]:
        return self._adapter.language_codes

    def execute(
        self,
        document: ImageDocument,
        language_code: str,
        mode: OcrMode = OcrMode.STANDARD,
        options: HighRecallOcrOptions | None = None,
        fast: bool = False,
    ) -> OcrResult:
        if language_code not in self._adapter.language_codes:
            raise OcrError("unsupported_language", f"OCR 不支持语言代码：{language_code}")
        if mode is OcrMode.HIGH_RECALL:
            recognize_high_recall = getattr(self._adapter, "recognize_high_recall", None)
            if not callable(recognize_high_recall):
                raise OcrError(
                    "high_recall_unavailable",
                    "当前 OCR 适配器不支持高召回模式",
                )
            return recognize_high_recall(
                document,
                language_code,
                options or HighRecallOcrOptions(),
            )
        return self._adapter.recognize(document, language_code, fast=fast)
