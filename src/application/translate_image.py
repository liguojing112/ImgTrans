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
from src.domain.ocr import OcrResult
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
                lambda: self._recognize.execute(document, ocr_language),
                on_stage,
            )
            translation = self._run_stage(
                job,
                token,
                ImageStage.TRANSLATION,
                lambda: self._translate.execute(ocr, selection, brand_terms),
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
            rendered = self._run_stage(
                job,
                token,
                ImageStage.RENDERING,
                lambda: self._renderer.render(repair.result.document, layout),
                on_stage,
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
