from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat, ImageLimits
from src.domain.ocr import OcrError, TextRegionStatus
from src.infrastructure.ocr_profiles import OcrProfile
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.infrastructure.rapidocr_adapter import RapidOcrAdapter, RapidOcrModelFiles


def _document() -> ImageDocument:
    width, height = 240, 120
    return ImageDocument(
        ImageAsset(Path("fixture.png"), width, height, 1, ImageFileFormat.PNG, False, False),
        "RGB",
        bytes([255]) * width * height * 3,
    )


class FakeEngine:
    def __init__(self, inconsistent: bool = False) -> None:
        self.inconsistent = inconsistent

    def __call__(self, image: np.ndarray, **_options: object) -> SimpleNamespace:
        assert image.shape == (120, 240, 3)
        return SimpleNamespace(
            boxes=np.array([[[10, 10], [110, 10], [110, 40], [10, 40]]], dtype=float),
            txts=["  PRODUCT 2026  "],
            scores=[] if self.inconsistent else [0.42],
        )


def test_adapter_normalizes_result_and_caches_profile_engine() -> None:
    created: list[OcrProfile] = []

    def factory(profile: OcrProfile) -> FakeEngine:
        created.append(profile)
        return FakeEngine()

    adapter = RapidOcrAdapter(confidence_threshold=0.5, engine_factory=factory)
    first = adapter.recognize(_document(), "en")
    second = adapter.recognize(_document(), "zh-Hans")
    assert len(created) == 1
    assert first.regions[0].text == "PRODUCT 2026"
    assert first.regions[0].status is TextRegionStatus.LOW_CONFIDENCE
    assert second.model_id == first.model_id
    assert first.regions[0].polygon[0].x == 10


def test_adapter_reports_unavailable_language_and_inconsistent_runtime() -> None:
    adapter = RapidOcrAdapter(engine_factory=lambda _profile: FakeEngine(inconsistent=True))
    with pytest.raises(OcrError) as unavailable:
        adapter.recognize(_document(), "bn")
    assert unavailable.value.code == "model_unavailable"
    with pytest.raises(OcrError) as inconsistent:
        adapter.recognize(_document(), "en")
    assert inconsistent.value.code == "invalid_runtime_result"


def _font_path() -> Path | None:
    candidates = (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    return next((path for path in candidates if path.is_file()), None)


def test_real_rapidocr_minimal_english_call(tmp_path: Path) -> None:
    font_path = _font_path()
    if font_path is None:
        pytest.skip("No cross-platform test font available")
    source = tmp_path / "rapidocr-input.png"
    image = Image.new("RGB", (1000, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.text((45, 55), "PRODUCT 2026", font=ImageFont.truetype(str(font_path), 96), fill="black")
    image.save(source)
    document = PillowImageCodec().load(source, ImageLimits())
    result = RapidOcrAdapter(confidence_threshold=0.3).recognize(document, "en")
    assert result.model_id == "ppocrv6-common-small"
    assert result.elapsed_ms >= 0
    assert result.regions
    assert any("PRODUCT" in region.text.upper() for region in result.regions)


def test_adapter_passes_installed_model_paths_to_rapidocr(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_paths = []
    for name in ("det.onnx", "cls.onnx", "rec.onnx"):
        path = tmp_path / name
        path.write_bytes(b"fixture")
        model_paths.append(path)
    captured = {}

    class _EmptyEngine:
        def __call__(self, image, **options):
            del image, options
            return SimpleNamespace(boxes=None, txts=None, scores=None)

    def create_engine(*, params):
        captured["params"] = params
        return _EmptyEngine()

    monkeypatch.setattr("rapidocr.RapidOCR", create_engine)
    adapter = RapidOcrAdapter(
        model_resolver=lambda profile: RapidOcrModelFiles(*model_paths)
    )
    result = adapter.recognize(_document(), "en")

    assert result.regions == ()
    assert captured["params"]["Det.model_path"] == str(model_paths[0])
    assert captured["params"]["Cls.model_path"] == str(model_paths[1])
    assert captured["params"]["Rec.model_path"] == str(model_paths[2])


def test_short_cjk_region_can_recover_missing_edge_character() -> None:
    class _RefiningEngine:
        def __init__(self) -> None:
            self.calls = []

        def __call__(self, image, **options):
            self.calls.append((image.shape, options))
            if options["use_det"]:
                return SimpleNamespace(
                    boxes=np.array(
                        [[[84, 40], [177, 40], [177, 74], [84, 74]]],
                        dtype=float,
                    ),
                    txts=["家直销"],
                    scores=[0.9998],
                )
            return SimpleNamespace(
                boxes=None,
                txts=["厂家直销"],
                scores=[0.9999],
            )

    engine = _RefiningEngine()
    result = RapidOcrAdapter(engine_factory=lambda _profile: engine).recognize(
        _document(),
        "zh-Hans",
    )

    assert result.regions[0].text == "厂家直销"
    assert min(point.x for point in result.regions[0].polygon) < 60
    assert engine.calls[1][1] == {
        "use_det": False,
        "use_cls": True,
        "use_rec": True,
    }


def test_refinement_does_not_borrow_characters_from_adjacent_region() -> None:
    class _AdjacentEngine:
        def __init__(self) -> None:
            self.recognition_call = 0

        def __call__(self, image, **options):
            del image
            if options["use_det"]:
                return SimpleNamespace(
                    boxes=np.array(
                        [
                            [[0, 20], [80, 20], [80, 50], [0, 50]],
                            [[90, 20], [170, 20], [170, 50], [90, 50]],
                        ],
                        dtype=float,
                    ),
                    txts=["枪灰款", "1个装"],
                    scores=[0.9998, 0.9998],
                )
            self.recognition_call += 1
            return SimpleNamespace(
                boxes=None,
                txts=["枪灰款" if self.recognition_call == 1 else "款1个装"],
                scores=[0.9999],
            )

    result = RapidOcrAdapter(
        engine_factory=lambda _profile: _AdjacentEngine()
    ).recognize(_document(), "zh-Hans")

    assert [region.text for region in result.regions] == ["枪灰款", "1个装"]
