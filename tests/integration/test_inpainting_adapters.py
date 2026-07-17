import hashlib
from pathlib import Path

import numpy as np
import pytest

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import (
    EraseMask,
    InpaintingError,
    InpaintingRequest,
    InpaintingResult,
)
from src.infrastructure.fallback_inpaint_adapter import FallbackInpaintAdapter
from src.infrastructure.inpainting_process import ProcessLamaAdapter
from src.infrastructure.lama_onnx_adapter import LamaOnnxAdapter
from src.infrastructure.opencv_inpaint_adapter import OpenCvInpaintAdapter


def _request(mode: str = "RGBA") -> InpaintingRequest:
    width, height = 48, 40
    channels = 4 if mode == "RGBA" else 3
    pixels = np.zeros((height, width, channels), dtype=np.uint8)
    pixels[:, :, :3] = (30, 80, 130)
    pixels[12:28, 16:32, :3] = (250, 250, 250)
    if channels == 4:
        pixels[:, :, 3] = np.arange(width, dtype=np.uint8)[None, :]
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[12:28, 16:32] = 255
    asset = ImageAsset(Path("fixture.png"), width, height, 1, ImageFileFormat.PNG, channels == 4, False)
    return InpaintingRequest(
        ImageDocument(asset, mode, pixels.tobytes()),
        EraseMask(width, height, mask.tobytes()),
        context_pixels=4,
    )


def test_opencv_changes_only_masked_rgb_and_preserves_alpha() -> None:
    request = _request()
    result = OpenCvInpaintAdapter().inpaint(request)
    source = np.frombuffer(request.document.pixels, dtype=np.uint8).reshape(40, 48, 4)
    output = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(40, 48, 4)
    mask = np.frombuffer(request.erase_mask.pixels, dtype=np.uint8).reshape(40, 48) > 0
    assert np.array_equal(output[~mask], source[~mask])
    assert np.array_equal(output[:, :, 3], source[:, :, 3])
    assert np.any(output[mask, :3] != source[mask, :3])


def test_opencv_respects_independent_protection_mask() -> None:
    base = _request("RGB")
    protected = np.zeros((40, 48), dtype=np.uint8)
    protected[16:20, 20:24] = 255
    request = InpaintingRequest(
        base.document,
        base.erase_mask,
        base.context_pixels,
        EraseMask(48, 40, protected.tobytes()),
    )
    result = OpenCvInpaintAdapter().inpaint(request)
    source = np.frombuffer(request.document.pixels, dtype=np.uint8).reshape(40, 48, 3)
    output = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(40, 48, 3)
    assert np.array_equal(output[protected > 0], source[protected > 0])


class _SolidSession:
    def run(self, outputs: object, inputs: object) -> list[np.ndarray]:
        return [np.full((1, 3, 512, 512), 7, dtype=np.float32)]


def test_lama_contract_verifies_model_and_composites_exact_mask(tmp_path: Path) -> None:
    model = tmp_path / "model.onnx"
    model.write_bytes(b"contract-model")
    expected = hashlib.sha256(model.read_bytes()).hexdigest()
    adapter = LamaOnnxAdapter(
        model,
        expected,
        session_factory=lambda path, threads: _SolidSession(),
    )
    request = _request("RGB")
    result = adapter.inpaint(request)
    source = np.frombuffer(request.document.pixels, dtype=np.uint8).reshape(40, 48, 3)
    output = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(40, 48, 3)
    mask = np.frombuffer(request.erase_mask.pixels, dtype=np.uint8).reshape(40, 48) > 0
    assert np.array_equal(output[~mask], source[~mask])
    assert np.all(output[mask] == 7)
    assert result.backend_id == "lama-onnxruntime"


class _UnavailableAdapter:
    adapter_id = "unavailable"

    def inpaint(self, request: InpaintingRequest):
        raise RuntimeError("model missing")


class _ResultAdapter:
    adapter_id = "fixture-result"

    def __init__(self, color: tuple[int, int, int]) -> None:
        self.color = color

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        height, width = request.document.asset.height, request.document.asset.width
        pixels = np.frombuffer(request.document.pixels, dtype=np.uint8).reshape(
            height, width, 3
        ).copy()
        mask = np.frombuffer(request.erase_mask.pixels, dtype=np.uint8).reshape(
            height, width
        ) > 0
        pixels[mask] = self.color
        return InpaintingResult(
            ImageDocument(request.document.asset, "RGB", pixels.tobytes()),
            self.adapter_id,
            1,
        )


def test_fallback_reports_visible_warning() -> None:
    result = FallbackInpaintAdapter(
        _UnavailableAdapter(), OpenCvInpaintAdapter()
    ).inpaint(_request("RGB"))
    assert result.backend_id == "opencv-telea"
    assert result.warning is not None
    assert "LaMa 不可用" in result.warning


def test_fallback_rejects_visible_color_shift_on_smooth_background() -> None:
    result = FallbackInpaintAdapter(
        _ResultAdapter((220, 220, 220)),
        _ResultAdapter((30, 80, 130)),
    ).inpaint(_request("RGB"))
    assert result.backend_id == "fixture-result"
    assert result.warning is not None
    assert "平滑背景边界不一致" in result.warning


def test_fallback_keeps_primary_when_smooth_background_matches_boundary() -> None:
    result = FallbackInpaintAdapter(
        _ResultAdapter((30, 80, 130)),
        _UnavailableAdapter(),
    ).inpaint(_request("RGB"))
    assert result.backend_id == "fixture-result"
    assert result.warning is None


def test_process_adapter_returns_structured_model_error(tmp_path: Path) -> None:
    adapter = ProcessLamaAdapter(tmp_path / "missing.onnx", timeout_seconds=15)
    try:
        with pytest.raises(InpaintingError) as error:
            adapter.inpaint(_request("RGB"))
        assert error.value.code == "lama_model_missing"
    finally:
        adapter.close()
