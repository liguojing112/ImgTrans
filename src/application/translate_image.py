from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import TypeVar

from src.application.inpainting import RepairTranslatedRegions
from src.application.ocr import RecognizeText
from src.application.ports import TextLayoutAdapter, TextRenderer
from src.application.translation import TranslateRegions
from src.domain.image import ImageDocument
from src.domain.inpainting import RepairOutcome
from src.domain.job import CancellationToken, ImageJob, ImageStage, JobCancelled
from src.domain.layout import TextLayout
from src.domain.ocr import HighRecallOcrOptions, OcrMode, OcrResult
from src.domain.translation import TranslationResult, TranslationSelection


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class TranslateImageResult:
    document: ImageDocument
    ocr: OcrResult
    translation: TranslationResult
    repair: RepairOutcome
    layout: TextLayout
    job: ImageJob


class TranslateImage:
    def __init__(
        self,
        recognize: RecognizeText,
        translate: TranslateRegions,
        repair: RepairTranslatedRegions,
        layout: TextLayoutAdapter,
        renderer: TextRenderer,
    ) -> None:
        self._recognize = recognize
        self._translate = translate
        self._repair = repair
        self._layout = layout
        self._renderer = renderer
        self._token: CancellationToken | None = None
        self._token_lock = Lock()

    def execute(
        self,
        document: ImageDocument,
        ocr_language: str,
        selection: TranslationSelection,
        brand_terms: tuple[str, ...] = (),
        on_stage: Callable[[ImageStage], None] | None = None,
        ocr_mode: OcrMode = OcrMode.STANDARD,
        high_recall_options: HighRecallOcrOptions | None = None,
        allow_low_confidence: bool = False,
        automatic_confidence_threshold: float | None = None,
        preserve_numbers: bool = True,
    ) -> TranslateImageResult:
        token = CancellationToken()
        with self._token_lock:
            self._token = token
        job = ImageJob()
        job.start()
        try:
            ocr = self._run_stage(
                job,
                token,
                ImageStage.OCR,
                lambda: self._recognize.execute(
                    document,
                    ocr_language,
                    ocr_mode,
                    high_recall_options,
                ),
                on_stage,
            )
            translation = self._run_stage(
                job,
                token,
                ImageStage.TRANSLATION,
                lambda: self._translate.execute(
                    ocr,
                    selection,
                    brand_terms,
                    allow_low_confidence=allow_low_confidence,
                    automatic_confidence_threshold=automatic_confidence_threshold,
                    preserve_numbers=preserve_numbers,
                ),
                on_stage,
            )
            repair = self._run_stage(
                job,
                token,
                ImageStage.INPAINTING,
                lambda: self._repair.execute(document, ocr, translation),
                on_stage,
            )
            layout = self._run_stage(
                job,
                token,
                ImageStage.LAYOUT,
                lambda: self._layout.layout(document, ocr, translation),
                on_stage,
            )
            # 弧形/旋转文字（圆环、竖排、弧线）译文通常比原文长，放不下时一律
            # 渲染自适应缩小的译文，而不是恢复原文；仅普通水平文字放不下才保留
            # 原文（避免长译文挤乱直排版面）。
            overflow_region_ids = frozenset(
                layer.region_id
                for layer in layout.layers
                if layer.overflow
                and layer.path is None
                and abs(layer.box.rotation_degrees) <= 3
            )
            protected_conflict_region_ids = (
                self._repair.translated_protection_conflicts(
                    document,
                    ocr,
                    translation,
                )
            )
            preserved_region_ids = (
                overflow_region_ids | protected_conflict_region_ids
            )
            renderable_layout = (
                TextLayout(
                    tuple(
                        layer
                        for layer in layout.layers
                        if layer.region_id not in preserved_region_ids
                    )
                )
                if preserved_region_ids
                else layout
            )
            rendered = self._run_stage(
                job,
                token,
                ImageStage.RENDERING,
                lambda: self._renderer.render(
                    repair.result.document,
                    renderable_layout,
                ),
                on_stage,
            )
            rendered = self._repair.restore_automatic_protected_pixels(
                document,
                rendered,
                ocr,
                translation,
            )
            rendered = self._repair.restore_region_pixels(
                document,
                rendered,
                ocr,
                preserved_region_ids,
            )
            job.complete()
            return TranslateImageResult(rendered, ocr, translation, repair, layout, job)
        except JobCancelled:
            job.cancel()
            raise
        except Exception as error:
            job.fail(error)
            raise
        finally:
            with self._token_lock:
                if self._token is token:
                    self._token = None

    def cancel(self) -> None:
        with self._token_lock:
            token = self._token
        if token is not None:
            token.cancel()
            self._repair.cancel()

    def close(self) -> None:
        self.cancel()
        self._repair.close()

    @staticmethod
    def _run_stage(
        job: ImageJob,
        token: CancellationToken,
        stage: ImageStage,
        operation: Callable[[], T],
        on_stage: Callable[[ImageStage], None] | None,
    ) -> T:
        token.throw_if_cancelled()
        job.advance(stage)
        if on_stage is not None:
            on_stage(stage)
        token.throw_if_cancelled()
        value = operation()
        token.throw_if_cancelled()
        job.finish_stage()
        return value
