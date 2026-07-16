from __future__ import annotations

from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, sleep
from types import SimpleNamespace

from src.application.batch import RunBatch
from src.domain.batch import BatchStatus
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.job import ImageStage, JobCancelled
from src.domain.translation import TranslationMode, TranslationSelection


class _TrackingImporter:
    def __init__(self, pixel_bytes: int = 120 * 80 * 3) -> None:
        self.pixel_bytes = pixel_bytes
        self.imported: list[Path] = []
        self.live = 0
        self.peak_live = 0
        self._lock = Lock()

    def execute(self, source: Path) -> ImageDocument:
        with self._lock:
            self.imported.append(source)
            self.live += 1
            self.peak_live = max(self.peak_live, self.live)
        width = self.pixel_bytes // 3
        asset = ImageAsset(source, width, 1, 1, ImageFileFormat.PNG, False, False)
        value = len(source.stem) % 255
        return ImageDocument(asset, "RGB", bytes([value]) * self.pixel_bytes)

    def release(self) -> None:
        with self._lock:
            self.live -= 1


class _TrackingWorkflow:
    def __init__(self, fail_name: str | None = None, block: bool = False) -> None:
        self.fail_name = fail_name
        self.block = block
        self.started = Event()
        self.cancelled = Event()
        self.active = 0
        self.peak_active = 0
        self._lock = Lock()

    def execute(self, document, ocr_language, selection, brand_terms=(), on_stage=None):
        del ocr_language, selection, brand_terms
        with self._lock:
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
        self.started.set()
        try:
            if on_stage is not None:
                on_stage(ImageStage.OCR)
            if document.asset.source_path.name == self.fail_name:
                raise RuntimeError("fixture failure")
            while self.block and not self.cancelled.wait(0.01):
                pass
            if self.cancelled.is_set():
                raise JobCancelled("cancelled")
            sleep(0.002)
            return SimpleNamespace(document=document)
        finally:
            with self._lock:
                self.active -= 1

    def cancel(self) -> None:
        self.cancelled.set()


class _ReleasingStore:
    def __init__(self, importer: _TrackingImporter) -> None:
        self.importer = importer
        self.refs: set[str] = set()

    def save(self, batch_id: str, item_id: str, document: ImageDocument) -> str:
        del document
        result_ref = f"{batch_id}/{item_id}.png"
        self.refs.add(result_ref)
        self.importer.release()
        return result_ref

    def load(self, result_ref: str) -> ImageDocument:
        raise NotImplementedError(result_ref)

    def clear(self, batch_id: str) -> None:
        self.refs = {value for value in self.refs if not value.startswith(batch_id)}


def _selection() -> TranslationSelection:
    return TranslationSelection(TranslationMode.ALL, "zh-Hans")


def test_single_failure_does_not_stop_batch_and_heavy_work_is_serial() -> None:
    importer = _TrackingImporter()
    workflow = _TrackingWorkflow("bad.png")
    scheduler = RunBatch(importer, workflow, _ReleasingStore(importer), 2)
    result = scheduler.execute(
        tuple(Path(name) for name in ("1.png", "bad.png", "2.png", "3.png")),
        "en",
        _selection(),
    )
    assert result.status is BatchStatus.COMPLETED
    assert result.completed_count == 3
    assert result.failed_count == 1
    assert result.items[1].error == "fixture failure"
    assert workflow.peak_active == 1


def test_cancel_stops_queue_and_marks_unstarted_items_without_waiting_one_second() -> None:
    importer = _TrackingImporter()
    workflow = _TrackingWorkflow(block=True)
    scheduler = RunBatch(importer, workflow, _ReleasingStore(importer), 2)
    holder = []
    thread = Thread(
        target=lambda: holder.append(
            scheduler.execute(
                tuple(Path(f"{index}.png") for index in range(100)),
                "en",
                _selection(),
            )
        )
    )
    thread.start()
    assert workflow.started.wait(1)
    started = monotonic()
    scheduler.cancel()
    thread.join(1)
    assert not thread.is_alive()
    assert monotonic() - started < 1
    result = holder[0]
    assert result.status is BatchStatus.CANCELLED
    assert result.completed_count == 0
    assert result.cancelled_count == 100
    assert len(importer.imported) <= 2


def test_50_and_100_items_keep_the_same_bounded_active_image_count() -> None:
    peaks = []
    for count in (50, 100):
        importer = _TrackingImporter(512 * 1024 * 3)
        workflow = _TrackingWorkflow()
        scheduler = RunBatch(importer, workflow, _ReleasingStore(importer), 2)
        result = scheduler.execute(
            tuple(Path(f"{index}.png") for index in range(count)),
            "en",
            _selection(),
        )
        assert result.completed_count == count
        peaks.append(importer.peak_live)
    assert peaks == [2, 2]
