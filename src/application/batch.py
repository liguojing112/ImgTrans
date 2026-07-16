from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock
from typing import Protocol
from uuid import uuid4

from src.application.image_io import ImportImage
from src.application.ports import BatchResultStore
from src.application.translate_image import TranslateImageResult
from src.domain.batch import (
    BatchItemSnapshot,
    BatchItemStatus,
    BatchSnapshot,
    BatchStatus,
)
from src.domain.image import ImageDocument
from src.domain.job import ImageStage, JobCancelled
from src.domain.translation import TranslationSelection


class BatchWorkflow(Protocol):
    def execute(
        self,
        document: ImageDocument,
        ocr_language: str,
        selection: TranslationSelection,
        brand_terms: tuple[str, ...] = (),
        on_stage: Callable[[ImageStage], None] | None = None,
    ) -> TranslateImageResult: ...

    def cancel(self) -> None: ...


class RunBatch:
    def __init__(
        self,
        import_image: ImportImage,
        workflow: BatchWorkflow,
        result_store: BatchResultStore,
        max_active_items: int = 2,
    ) -> None:
        if max_active_items <= 0:
            raise ValueError("Maximum active batch items must be positive")
        self._import_image = import_image
        self._workflow = workflow
        self._result_store = result_store
        self._max_active_items = max_active_items
        self._processing_lock = Lock()
        self._state_lock = Lock()
        self._lifecycle_lock = Lock()
        self._cancel_event: Event | None = None
        self._running = False

    def execute(
        self,
        sources: Sequence[Path],
        ocr_language: str,
        selection: TranslationSelection,
        brand_terms: tuple[str, ...] = (),
        on_update: Callable[[BatchSnapshot], None] | None = None,
    ) -> BatchSnapshot:
        if not sources:
            raise ValueError("Batch requires at least one image")
        with self._lifecycle_lock:
            if self._running:
                raise RuntimeError("A batch is already running")
            self._running = True
            cancel_event = Event()
            self._cancel_event = cancel_event
        batch_id = f"batch-{uuid4().hex}"
        items = [
            BatchItemSnapshot(f"item-{uuid4().hex}", Path(source))
            for source in sources
        ]
        status = BatchStatus.RUNNING
        self._notify(batch_id, status, items, on_update)
        try:
            with ThreadPoolExecutor(
                max_workers=self._max_active_items,
                thread_name_prefix="imgtrans-batch",
            ) as executor:
                pending: dict[Future[BatchItemSnapshot], int] = {}
                next_index = 0
                while next_index < len(items) or pending:
                    while (
                        not cancel_event.is_set()
                        and next_index < len(items)
                        and len(pending) < self._max_active_items
                    ):
                        index = next_index
                        next_index += 1
                        items[index] = replace(
                            items[index], status=BatchItemStatus.RUNNING
                        )
                        future = executor.submit(
                            self._process_item,
                            batch_id,
                            items[index],
                            ocr_language,
                            selection,
                            brand_terms,
                            cancel_event,
                            lambda stage, item_index=index: self._stage_changed(
                                items,
                                item_index,
                                stage,
                            ),
                        )
                        pending[future] = index
                    self._notify(batch_id, status, items, on_update)
                    if cancel_event.is_set() and next_index < len(items):
                        for index in range(next_index, len(items)):
                            items[index] = replace(
                                items[index], status=BatchItemStatus.CANCELLED
                            )
                        next_index = len(items)
                    if not pending:
                        break
                    completed, _ = wait(
                        tuple(pending), timeout=0.1, return_when=FIRST_COMPLETED
                    )
                    for future in completed:
                        index = pending.pop(future)
                        with self._state_lock:
                            items[index] = future.result()
                        self._notify(batch_id, status, items, on_update)
            status = (
                BatchStatus.CANCELLED
                if cancel_event.is_set()
                else BatchStatus.COMPLETED
            )
            return self._notify(batch_id, status, items, on_update)
        finally:
            with self._lifecycle_lock:
                self._running = False
                if self._cancel_event is cancel_event:
                    self._cancel_event = None

    def cancel(self) -> None:
        with self._lifecycle_lock:
            cancel_event = self._cancel_event
        if cancel_event is not None:
            cancel_event.set()
            self._workflow.cancel()

    def _process_item(
        self,
        batch_id: str,
        item: BatchItemSnapshot,
        ocr_language: str,
        selection: TranslationSelection,
        brand_terms: tuple[str, ...],
        cancel_event: Event,
        on_stage: Callable[[ImageStage], None],
    ) -> BatchItemSnapshot:
        try:
            _throw_if_cancelled(cancel_event)
            document = self._import_image.execute(item.source)
            _throw_if_cancelled(cancel_event)
            with self._processing_lock:
                _throw_if_cancelled(cancel_event)
                result = self._workflow.execute(
                    document,
                    ocr_language,
                    selection,
                    brand_terms,
                    on_stage,
                )
            _throw_if_cancelled(cancel_event)
            result_ref = self._result_store.save(
                batch_id, item.item_id, result.document
            )
            return replace(
                item,
                status=BatchItemStatus.COMPLETED,
                current_stage=None,
                result_ref=result_ref,
            )
        except JobCancelled:
            return replace(
                item,
                status=BatchItemStatus.CANCELLED,
                current_stage=None,
            )
        except Exception as error:
            if cancel_event.is_set():
                return replace(
                    item,
                    status=BatchItemStatus.CANCELLED,
                    current_stage=None,
                )
            return replace(
                item,
                status=BatchItemStatus.FAILED,
                current_stage=None,
                error=str(error) or type(error).__name__,
            )

    def _stage_changed(
        self,
        items: list[BatchItemSnapshot],
        index: int,
        stage: ImageStage,
    ) -> None:
        with self._state_lock:
            items[index] = replace(items[index], current_stage=stage)

    def _notify(
        self,
        batch_id: str,
        status: BatchStatus,
        items: list[BatchItemSnapshot],
        on_update: Callable[[BatchSnapshot], None] | None,
    ) -> BatchSnapshot:
        with self._state_lock:
            snapshot = self._snapshot(batch_id, status, items)
        if on_update is not None:
            on_update(snapshot)
        return snapshot

    def _snapshot(
        self,
        batch_id: str,
        status: BatchStatus,
        items: list[BatchItemSnapshot],
    ) -> BatchSnapshot:
        return BatchSnapshot(
            batch_id,
            status,
            tuple(items),
            self._max_active_items,
        )


def _throw_if_cancelled(cancel_event: Event) -> None:
    if cancel_event.is_set():
        raise JobCancelled("批量图片翻译已取消")
