from __future__ import annotations

from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, sleep
from types import SimpleNamespace

from src.application.batch import RunBatch
from src.application.translation import TranslateRegions
from src.domain.batch import BatchItemStatus, BatchStatus
from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.job import ImageStage, JobCancelled
from src.domain.ocr import (
    HighRecallOcrOptions,
    OcrMode,
    OcrResult,
    Point,
    RingBand,
    TextRegion,
    order_quad,
)
from src.domain.protection import ProtectionEngine
from src.domain.terminology import TerminologyCatalog, TerminologyEntry
from src.domain.translation import TranslationAdapterItem
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


class _UnusedTranslationAdapter:
    adapter_id = "unused"

    def __init__(self) -> None:
        self.calls = []

    def translate(self, texts, source_language, target_language):
        self.calls.append((texts, source_language, target_language))
        return tuple(
            TranslationAdapterItem(translated_text=f"translated:{text}")
            for text in texts
        )


class _TerminologyWorkflow:
    def __init__(self, translate: TranslateRegions) -> None:
        self._translate = translate
        self.results = []

    def execute(self, document, ocr_language, selection, brand_terms=(), on_stage=None):
        del ocr_language, on_stage
        ocr = OcrResult(
            (
                TextRegion(
                    "term",
                    order_quad(((0, 0), (5, 0), (5, 1), (0, 1))),
                    "Clamp",
                    0.99,
                    "en",
                    "fixture",
                ),
            ),
            "en",
            "fixture",
            0,
        )
        translation = self._translate.execute(ocr, selection, brand_terms)
        self.results.append(translation)
        return SimpleNamespace(document=document, translation=translation)

    def cancel(self) -> None:
        pass


class _ProtectionOptionsWorkflow:
    def __init__(self) -> None:
        self.preserve_numbers_values: list[bool] = []
        self.ocr_modes: list[OcrMode] = []
        self.high_recall_options: list[HighRecallOcrOptions | None] = []

    def execute(
        self,
        document,
        ocr_language,
        selection,
        brand_terms=(),
        on_stage=None,
        **options,
    ):
        del ocr_language, selection, brand_terms, on_stage
        self.preserve_numbers_values.append(options["preserve_numbers"])
        self.ocr_modes.append(options.get("ocr_mode", OcrMode.STANDARD))
        self.high_recall_options.append(options.get("high_recall_options"))
        return SimpleNamespace(document=document)

    def cancel(self) -> None:
        pass


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


def test_first_visible_snapshot_marks_scheduled_items_as_running() -> None:
    importer = _TrackingImporter()
    workflow = _TrackingWorkflow()
    scheduler = RunBatch(importer, workflow, _ReleasingStore(importer), 2)
    snapshots = []
    scheduler.execute(
        (Path("one.png"), Path("two.png")),
        "en",
        _selection(),
        on_update=snapshots.append,
    )
    assert snapshots
    assert all(
        item.status is BatchItemStatus.RUNNING
        for item in snapshots[0].items
    )


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


def test_pause_finishes_scheduled_items_and_resume_does_not_repeat_work() -> None:
    importer = _TrackingImporter()
    workflow = _TrackingWorkflow(block=True)
    scheduler = RunBatch(importer, workflow, _ReleasingStore(importer), 2)
    paused = Event()
    snapshots = []
    holder = []

    def on_update(snapshot) -> None:
        snapshots.append(snapshot)
        if snapshot.status is BatchStatus.PAUSED:
            paused.set()

    thread = Thread(
        target=lambda: holder.append(
            scheduler.execute(
                tuple(Path(f"{index}.png") for index in range(5)),
                "en",
                _selection(),
                on_update=on_update,
            )
        )
    )
    thread.start()
    assert workflow.started.wait(1)
    scheduler.pause()
    workflow.block = False
    assert paused.wait(2)
    paused_snapshot = snapshots[-1]
    assert paused_snapshot.status is BatchStatus.PAUSED
    assert paused_snapshot.completed_count <= 2
    imported_before_resume = tuple(importer.imported)
    assert len(imported_before_resume) <= 2

    scheduler.resume()
    thread.join(3)
    assert not thread.is_alive()
    result = holder[0]
    assert result.status is BatchStatus.COMPLETED
    assert result.completed_count == 5
    assert len(importer.imported) == 5
    assert len(set(importer.imported)) == 5


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


def test_single_and_batch_workflows_use_the_same_exact_terminology() -> None:
    catalog = TerminologyCatalog(
        (TerminologyEntry("en", "zh-Hans", "Clamp", "卡箍"),)
    )
    adapter = _UnusedTranslationAdapter()
    workflow = _TerminologyWorkflow(
        TranslateRegions(
            adapter,
            ProtectionEngine(),
            terminology_catalog=catalog,
        )
    )
    selection = _selection()
    single_importer = _TrackingImporter(pixel_bytes=30)
    single = workflow.execute(
        single_importer.execute(Path("single.png")),
        "en",
        selection,
    )
    batch_importer = _TrackingImporter(pixel_bytes=30)
    batch = RunBatch(
        batch_importer,
        workflow,
        _ReleasingStore(batch_importer),
        1,
    ).execute((Path("batch.png"),), "en", selection)

    assert single.translation.units[0].translated_text == "卡箍"
    assert workflow.results[-1].units[0].translated_text == "卡箍"
    assert batch.completed_count == 1
    assert adapter.calls == []


def test_batch_forwards_disabled_number_protection_to_workflow() -> None:
    importer = _TrackingImporter(pixel_bytes=30)
    workflow = _ProtectionOptionsWorkflow()
    result = RunBatch(
        importer,
        workflow,
        _ReleasingStore(importer),
        1,
    ).execute(
        (Path("batch.png"),),
        "en",
        _selection(),
        preserve_numbers=False,
    )
    assert result.completed_count == 1
    assert workflow.preserve_numbers_values == [False]


def test_batch_forwards_high_recall_mode_and_geometry_to_workflow() -> None:
    importer = _TrackingImporter(pixel_bytes=30)
    workflow = _ProtectionOptionsWorkflow()
    options = HighRecallOcrOptions(
        center=Point(100, 80),
        ring_bands=(RingBand(30, 70),),
    )
    result = RunBatch(
        importer,
        workflow,
        _ReleasingStore(importer),
        1,
    ).execute(
        (Path("ring.png"),),
        "en",
        _selection(),
        ocr_mode=OcrMode.HIGH_RECALL,
        high_recall_options=options,
    )
    assert result.completed_count == 1
    assert workflow.ocr_modes == [OcrMode.HIGH_RECALL]
    assert workflow.high_recall_options == [options]
