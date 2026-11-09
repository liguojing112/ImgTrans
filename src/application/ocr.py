from __future__ import annotations

from dataclasses import dataclass
from threading import Event

from src.application.ports import OcrAdapter
from src.domain.image import ImageDocument
from src.domain.job import ImageStage, JobCancelled
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


@dataclass(frozen=True, slots=True)
class OcrOnlyResult:
    """批量 OCR 结果：像素不变，只带回识别文本。"""

    document: ImageDocument
    ocr: OcrResult


class BatchOcrWorkflow:
    """批量调度器用的「仅 OCR」工作流：忽略翻译参数，只跑识别。"""

    def __init__(self, recognize: RecognizeText) -> None:
        self._recognize = recognize
        self._cancelled = Event()

    def execute(
        self,
        document: ImageDocument,
        ocr_language: str,
        selection: object,
        brand_terms: tuple[str, ...] = (),
        on_stage=None,
        **options: object,
    ) -> OcrOnlyResult:
        del selection, brand_terms
        self._cancelled.clear()
        if on_stage is not None:
            on_stage(ImageStage.OCR)
        if self._cancelled.is_set():
            raise JobCancelled("批量识别已取消")
        mode = options.get("ocr_mode")
        ocr = self._recognize.execute(
            document,
            ocr_language,
            mode if isinstance(mode, OcrMode) else OcrMode.STANDARD,
            options.get("high_recall_options")
            if isinstance(options.get("high_recall_options"), HighRecallOcrOptions)
            else None,
        )
        if self._cancelled.is_set():
            raise JobCancelled("批量识别已取消")
        return OcrOnlyResult(document, ocr)

    def cancel(self) -> None:
        self._cancelled.set()

