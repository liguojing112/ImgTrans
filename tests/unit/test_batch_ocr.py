from __future__ import annotations

from pathlib import Path

from PIL import Image

from src.application.batch import BatchOcrState, RunBatch
from src.application.image_io import ImportImage
from src.application.ocr import BatchOcrWorkflow, OcrOnlyResult, RecognizeText
from src.domain.image import ImageLimits
from src.domain.job import JobCancelled
from src.domain.ocr import OcrMode, OcrResult, TextRegion, order_quad
from src.domain.translation import TranslationMode, TranslationSelection
from src.infrastructure.batch_result_store import PngBatchResultStore
from src.infrastructure.pillow_image_codec import PillowImageCodec


class _FakeAdapter:
    language_codes = ("en",)

    def __init__(self, on_recognize=None) -> None:
        self.calls: list = []
        self._on_recognize = on_recognize

    def recognize(self, document, language_code, fast: bool = False):
        self.calls.append((language_code, fast))
        if self._on_recognize is not None:
            self._on_recognize()
        region = TextRegion(
            "r1",
            order_quad(((2, 2), (18, 2), (18, 12), (2, 12))),
            "HELLO",
            0.93,
            "en",
            "fixture",
        )
        return OcrResult((region,), language_code, "fixture", 3.0)


def _fake_adapter(**kwargs) -> _FakeAdapter:
    return _FakeAdapter(**kwargs)


def test_batch_ocr_workflow_returns_ocr_without_touching_pixels() -> None:
    adapter = _fake_adapter()
    workflow = BatchOcrWorkflow(RecognizeText(adapter))
    from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat

    asset = ImageAsset(Path("a.png"), 24, 16, 1, ImageFileFormat.PNG, False, False)
    image = ImageDocument(asset, "RGB", bytes((9, 9, 9)) * 24 * 16)
    stages: list = []

    result = workflow.execute(
        image,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
        (),
        stages.append,
        ocr_mode=OcrMode.STANDARD,
    )

    assert isinstance(result, OcrOnlyResult)
    assert result.document is image  # 只识别，不改像素
    assert [region.text for region in result.ocr.regions] == ["HELLO"]
    assert adapter.calls == [("en", False)]
    assert len(stages) == 1


def test_batch_ocr_workflow_cancel_aborts_run() -> None:
    holder: dict = {}

    def cancel_during_ocr() -> None:
        holder["workflow"].cancel()

    adapter = _fake_adapter(on_recognize=cancel_during_ocr)
    workflow = BatchOcrWorkflow(RecognizeText(adapter))
    holder["workflow"] = workflow

    from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat

    asset = ImageAsset(Path("a.png"), 8, 8, 1, ImageFileFormat.PNG, False, False)
    image = ImageDocument(asset, "RGB", bytes((0, 0, 0)) * 8 * 8)
    try:
        workflow.execute(image, "en", object())
    except JobCancelled:
        pass
    else:  # pragma: no cover - 取消必须中断
        raise AssertionError("cancel 未中断批量识别")


def test_run_batch_persists_ocr_state_for_ocr_mode(tmp_path: Path) -> None:
    source = tmp_path / "one.png"
    Image.new("RGB", (32, 24), (120, 140, 160)).save(source)
    codec = PillowImageCodec()
    store = PngBatchResultStore(tmp_path / "cache", codec)
    batch = RunBatch(
        ImportImage(codec, ImageLimits(min_width=1, min_height=1)),
        BatchOcrWorkflow(RecognizeText(_fake_adapter())),
        store,
        max_active_items=1,
    )

    snapshot = batch.execute(
        (source,),
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )

    assert snapshot.completed_count == 1
    result_ref = snapshot.items[0].result_ref
    assert result_ref is not None
    state = store.load_editable(result_ref)
    assert isinstance(state, BatchOcrState)
    assert [region.text for region in state.ocr.regions] == ["HELLO"]
