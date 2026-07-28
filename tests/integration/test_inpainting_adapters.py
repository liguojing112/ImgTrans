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


class _SplitResultAdapter:
    def __init__(
        self,
        adapter_id: str,
        left_color: tuple[int, int, int],
        right_color: tuple[int, int, int],
    ) -> None:
        self.adapter_id = adapter_id
        self.left_color = left_color
        self.right_color = right_color

    def inpaint(self, request: InpaintingRequest) -> InpaintingResult:
        height, width = request.document.asset.height, request.document.asset.width
        pixels = np.frombuffer(request.document.pixels, dtype=np.uint8).reshape(
            height, width, 3
        ).copy()
        mask = np.frombuffer(request.erase_mask.pixels, dtype=np.uint8).reshape(
            height, width
        ) > 0
        columns = np.arange(width)[None, :]
        pixels[mask & (columns < width // 2)] = self.left_color
        pixels[mask & (columns >= width // 2)] = self.right_color
        return InpaintingResult(
            ImageDocument(request.document.asset, "RGB", pixels.tobytes()),
            self.adapter_id,
            1,
        )


def _mixed_background_request() -> InpaintingRequest:
    width, height = 96, 48
    pixels = np.full((height, width, 3), (30, 80, 130), dtype=np.uint8)
    checker = np.indices((height, width // 2)).sum(axis=0) % 2
    pixels[:, width // 2 :] = np.where(
        checker[:, :, None] == 0,
        np.array((25, 35, 45), dtype=np.uint8),
        np.array((210, 220, 230), dtype=np.uint8),
    )
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[14:34, 0:20] = 255
    mask[14:34, 66:86] = 255
    pixels[mask > 0] = (250, 250, 250)
    asset = ImageAsset(
        Path("mixed-background.png"),
        width,
        height,
        1,
        ImageFileFormat.PNG,
        False,
        False,
    )
    return InpaintingRequest(
        ImageDocument(asset, "RGB", pixels.tobytes()),
        EraseMask(width, height, mask.tobytes()),
        context_pixels=4,
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


def test_fallback_replaces_only_edge_touching_artifact_region() -> None:
    request = _mixed_background_request()
    result = FallbackInpaintAdapter(
        _SplitResultAdapter("primary", (220, 220, 220), (10, 190, 20)),
        _SplitResultAdapter("fallback", (30, 80, 130), (190, 10, 190)),
    ).inpaint(request)
    pixels = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        48, 96, 3
    )

    assert np.all(pixels[20, 15] == (30, 80, 130))
    assert np.all(pixels[20, 72] == (10, 190, 20))
    assert result.backend_id == "primary+fallback"
    assert result.warning is not None


def test_fallback_keeps_primary_for_large_edge_touching_mask() -> None:
    base = _request("RGB")
    mask = np.zeros((40, 48), dtype=np.uint8)
    mask[:, :24] = 255
    request = InpaintingRequest(
        base.document,
        EraseMask(48, 40, mask.tobytes()),
        context_pixels=4,
    )

    result = FallbackInpaintAdapter(
        _ResultAdapter((220, 220, 220)),
        _UnavailableAdapter(),
    ).inpaint(request)

    assert result.backend_id == "fixture-result"
    assert result.warning is None


def test_fallback_uses_smooth_local_fill_for_sparse_text_mask() -> None:
    width, height = 120, 50
    pixels = np.full((height, width, 4), (174, 38, 24, 127), dtype=np.uint8)
    mask = np.zeros((height, width), dtype=np.uint8)
    for left in (15, 35, 55, 75):
        mask[15:35, left : left + 4] = 255
        mask[31:35, left : left + 12] = 255
        pixels[mask > 0, :3] = (245, 235, 228)
    request = InpaintingRequest(
        ImageDocument(
            ImageAsset(
                Path("text-mask.png"),
                width,
                height,
                1,
                ImageFileFormat.PNG,
                True,
                False,
            ),
            "RGBA",
            pixels.tobytes(),
        ),
        EraseMask(width, height, mask.tobytes()),
    )

    result = FallbackInpaintAdapter(
        _UnavailableAdapter(),
        _UnavailableAdapter(),
    ).inpaint(request)
    repaired = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        height,
        width,
        4,
    )

    assert result.backend_id == "opencv-text-fill"
    assert np.max(
        np.abs(
            repaired[mask > 0, :3].astype(np.int16)
            - np.asarray((174, 38, 24), dtype=np.int16)
        )
    ) <= 1
    assert np.all(repaired[:, :, 3] == 127)


def test_sparse_text_fill_uses_dominant_background_in_dense_word_ring() -> None:
    width, height = 100, 50
    pixels = np.full((height, width, 3), 250, dtype=np.uint8)
    mask = np.zeros((height, width), dtype=np.uint8)
    for left in (28, 38, 48, 58):
        mask[20:30, left : left + 3] = 255
        mask[27:30, left : left + 7] = 255
        pixels[mask > 0] = 20
    pixels[17:19, 24:70] = 35
    pixels[31:33, 24:70] = 55
    request = InpaintingRequest(
        ImageDocument(
            ImageAsset(
                Path("dense-ring-text.png"),
                width,
                height,
                1,
                ImageFileFormat.PNG,
                False,
                False,
            ),
            "RGB",
            pixels.tobytes(),
        ),
        EraseMask(width, height, mask.tobytes()),
    )

    result = FallbackInpaintAdapter(
        _UnavailableAdapter(),
        _UnavailableAdapter(),
    ).inpaint(request)
    repaired = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        height,
        width,
        3,
    )

    assert result.backend_id == "opencv-text-fill"
    assert np.min(repaired[mask > 0]) >= 240


def test_large_mapped_text_mask_uses_clean_light_background_fill() -> None:
    width, height = 120, 80
    pixels = np.full((height, width, 4), (246, 246, 250, 173), dtype=np.uint8)
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[20:60, 20:100] = 255
    pixels[30:50, 28:92, :3] = (35, 35, 38)
    request = InpaintingRequest(
        ImageDocument(
            ImageAsset(
                Path("light-circular-text.png"),
                width,
                height,
                1,
                ImageFileFormat.PNG,
                True,
                False,
            ),
            "RGBA",
            pixels.tobytes(),
        ),
        EraseMask(width, height, mask.tobytes()),
    )

    result = FallbackInpaintAdapter(
        _UnavailableAdapter(),
        _UnavailableAdapter(),
    ).inpaint(request)
    repaired = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        height,
        width,
        4,
    )

    assert result.backend_id == "opencv-text-fill"
    assert np.min(repaired[mask > 0, :3]) >= 240
    assert np.all(repaired[:, :, 3] == 173)
    assert np.array_equal(repaired[mask == 0], pixels[mask == 0])


def test_fallback_clears_translated_pixels_on_transparent_background() -> None:
    width, height = 80, 40
    pixels = np.zeros((height, width, 4), dtype=np.uint8)
    pixels[12:28, 20:60] = (220, 60, 95, 255)
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[14:26, 24:56] = 255
    request = InpaintingRequest(
        ImageDocument(
            ImageAsset(
                Path("transparent-art-text.png"),
                width,
                height,
                1,
                ImageFileFormat.PNG,
                True,
                False,
            ),
            "RGBA",
            pixels.tobytes(),
        ),
        EraseMask(width, height, mask.tobytes()),
    )

    result = FallbackInpaintAdapter(
        _UnavailableAdapter(),
        _UnavailableAdapter(),
    ).inpaint(request)
    repaired = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        height,
        width,
        4,
    )

    assert result.backend_id == "transparent-text-clear"
    assert np.all(repaired[mask > 0] == 0)
    assert np.array_equal(repaired[12, 20], pixels[12, 20])


def test_process_adapter_returns_structured_model_error(tmp_path: Path) -> None:
    adapter = ProcessLamaAdapter(tmp_path / "missing.onnx", timeout_seconds=15)
    try:
        with pytest.raises(InpaintingError) as error:
            adapter.inpaint(_request("RGB"))
        assert error.value.code == "lama_model_missing"
    finally:
        adapter.close()
