import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat
from src.domain.inpainting import (
    EraseMask,
    InpaintingError,
    InpaintingRequest,
    InpaintingResult,
)
from src.infrastructure.fallback_inpaint_adapter import (
    FallbackInpaintAdapter,
    _is_text_shaped_mask,
    _should_fill_with_background,
    _text_on_solid_background_mask,
)
from src.infrastructure.inpainting_process import ProcessLamaAdapter
from src.infrastructure.lama_onnx_adapter import LamaOnnxAdapter
from src.infrastructure.opencv_inpaint_adapter import OpenCvInpaintAdapter
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer


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


class _MaskCapturingSession(_SolidSession):
    def __init__(self) -> None:
        self.mask: np.ndarray | None = None

    def run(self, outputs: object, inputs: object) -> list[np.ndarray]:
        self.mask = inputs["mask"].copy()
        return super().run(outputs, inputs)


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


def test_lama_binarizes_antialiased_mask_before_inference(tmp_path: Path) -> None:
    model = tmp_path / "model.onnx"
    model.write_bytes(b"contract-model")
    expected = hashlib.sha256(model.read_bytes()).hexdigest()
    session = _MaskCapturingSession()
    adapter = LamaOnnxAdapter(
        model,
        expected,
        session_factory=lambda path, threads: session,
    )
    base = _request("RGB")
    mask = np.frombuffer(base.erase_mask.pixels, dtype=np.uint8).reshape(40, 48).copy()
    mask[11, 15] = 1
    mask[11, 16] = 127
    request = InpaintingRequest(
        base.document,
        EraseMask(48, 40, mask.tobytes()),
        base.context_pixels,
    )

    adapter.inpaint(request)

    assert session.mask is not None
    assert set(np.unique(session.mask)) <= {0.0, 1.0}
    assert np.any(session.mask == 1.0)


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


def test_short_text_on_solid_colored_label_uses_background_fill() -> None:
    width, height = 400, 200
    image = Image.new("RGB", (width, height), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([40, 110, 360, 170], radius=30, fill=(232, 96, 140))
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    draw.text((75, 118), "SALE OFF", font=font, fill=(255, 255, 255))
    pixels = np.asarray(image).copy()
    document = ImageDocument(
        ImageAsset(
            Path("pink-label.png"),
            width,
            height,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )
    polygon = ((75, 112), (330, 112), (330, 168), (75, 168))
    mask = PillowMaskRasterizer().rasterize_text(document, (polygon,), 2)
    mask_pixels = np.frombuffer(mask.pixels, dtype=np.uint8).reshape(height, width)

    assert _should_fill_with_background(
        InpaintingRequest(document, mask, context_pixels=96)
    )
    result = FallbackInpaintAdapter(
        _UnavailableAdapter(),
        _UnavailableAdapter(),
    ).inpaint(InpaintingRequest(document, mask, context_pixels=96))
    repaired = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        height,
        width,
        3,
    )

    assert result.backend_id == "opencv-text-fill"
    assert np.allclose(repaired[mask_pixels > 0], (232, 96, 140), atol=12)
    assert np.array_equal(repaired[mask_pixels == 0], pixels[mask_pixels == 0])


def test_solid_box_mask_on_uniform_background_uses_lama() -> None:
    request = _request("RGB")
    assert not _should_fill_with_background(request)
    assert not _is_text_shaped_mask(request)
    assert not _text_on_solid_background_mask(request)


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


def test_textured_fill_restores_grain_instead_of_leaving_flat_patch() -> None:
    """有颗粒的背景擦除后必须补回噪点，不能留一块过于平滑的色斑。

    实测 0901 水印图：纯平滑填充的擦除区噪点只有 3.4（周边 5.7），
    色差 6.0，用户能在新数字背后看到旧字的淡蓝色轮廓。
    """
    width, height = 240, 120
    rng = np.random.default_rng(7)
    # 全图同一种底色 + 均匀颗粒，避免上下区域本身就存在色偏
    pixels = np.full((height, width, 3), (40, 68, 170), dtype=np.int16)
    pixels = np.clip(
        pixels + rng.integers(-16, 17, size=(height, width, 3)), 0, 255
    ).astype(np.uint8)

    # 必须像文字：细笔画 + L 形拐角，连通块填充率低于 0.93 才会走背景填充
    mask = np.zeros((height, width), dtype=np.uint8)
    for left in (60, 82, 104, 126, 148):
        mask[42:78, left : left + 5] = 255
        mask[73:78, left : left + 16] = 255
    pixels[mask > 0] = (245, 248, 255)

    document = ImageDocument(
        ImageAsset(
            Path("grain.png"), width, height, 1, ImageFileFormat.PNG, False, False
        ),
        "RGB",
        pixels.tobytes(),
    )
    request = InpaintingRequest(
        document, EraseMask(width, height, mask.tobytes())
    )

    result = FallbackInpaintAdapter(
        _UnavailableAdapter(), _UnavailableAdapter()
    ).inpaint(request)
    repaired = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        height, width, 3
    )

    def grain_of(window: np.ndarray) -> float:
        gray = cv2.cvtColor(window, cv2.COLOR_RGB2GRAY).astype(np.float32)
        return float((gray - cv2.GaussianBlur(gray, (0, 0), 1.4)).std())

    filled_grain = grain_of(repaired[42:78, 60:164])
    surrounding_grain = grain_of(repaired[0:38, 0:width])
    # 填充区不能是光滑色斑：噪点要接近周边（允许明显偏差但仍需有颗粒）
    assert filled_grain > surrounding_grain * 0.4

    # 颜色要对齐周边，不能留下可见色差
    filled_mean = repaired[42:78, 60:164].astype(np.float32).mean(axis=(0, 1))
    surrounding_mean = repaired[0:38, 0:width].astype(np.float32).mean(axis=(0, 1))
    assert float(np.linalg.norm(filled_mean - surrounding_mean)) < 12.0


def test_flat_background_fill_does_not_add_grain() -> None:
    """纯色背景本来就没有噪点，补噪点反而会弄脏。"""
    width, height = 120, 60
    pixels = np.full((height, width, 3), (200, 205, 210), dtype=np.uint8)
    mask = np.zeros((height, width), dtype=np.uint8)
    for left in (30, 46, 62, 78, 94):
        mask[22:38, left : left + 4] = 255
        mask[34:38, left : left + 11] = 255
    pixels[mask > 0] = (60, 60, 60)

    document = ImageDocument(
        ImageAsset(
            Path("flat.png"), width, height, 1, ImageFileFormat.PNG, False, False
        ),
        "RGB",
        pixels.tobytes(),
    )
    result = FallbackInpaintAdapter(
        _UnavailableAdapter(), _UnavailableAdapter()
    ).inpaint(InpaintingRequest(document, EraseMask(width, height, mask.tobytes())))
    repaired = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        height, width, 3
    )

    assert np.max(
        np.abs(
            repaired[mask > 0].astype(np.int16)
            - np.asarray((200, 205, 210), dtype=np.int16)
        )
    ) <= 1


def test_uniform_background_is_replaced_by_a_real_background_patch() -> None:
    """纯色/颗粒底上的文字擦除后必须无痕，哪怕蒙版把笔画围成的圈一并盖住。

    实测 0901 水印图：合成填充无论如何调参，旧数字的轮廓都会留下一层
    淡蓝影子（多尺度高通差 -1.5~-3.5）。改为从图里另找一块同款无字背景
    整块覆盖后，残影降到 -0.05——底色、颗粒、明暗过渡都是原图自己的。
    这里用一整片带颗粒的纯色底复现，要求覆盖后与原底色的统计完全一致。
    """
    width, height = 320, 180
    rng = np.random.default_rng(31)
    base = np.array((38, 62, 172), dtype=np.int16)
    pixels = np.clip(
        base + rng.integers(-13, 14, size=(height, width, 3)), 0, 255
    ).astype(np.uint8)

    mask = np.zeros((height, width), dtype=np.uint8)
    for left in (70, 96, 122, 148, 174):
        mask[74:112, left : left + 6] = 255
        mask[106:112, left : left + 20] = 255
    pixels[mask > 0] = (246, 248, 252)

    document = ImageDocument(
        ImageAsset(
            Path("patch-bg.png"), width, height, 1, ImageFileFormat.PNG, False, False
        ),
        "RGB",
        pixels.tobytes(),
    )
    result = FallbackInpaintAdapter(
        _UnavailableAdapter(), _UnavailableAdapter()
    ).inpaint(InpaintingRequest(document, EraseMask(width, height, mask.tobytes())))
    repaired = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        height, width, 3
    )

    gray_before = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gray_after = cv2.cvtColor(repaired, cv2.COLOR_RGB2GRAY).astype(np.float32)
    was_text = (mask > 0) & (gray_before > 200)
    untouched = (mask == 0) & (gray_before < 150)
    assert int(was_text.sum()) > 400
    assert int(untouched.sum()) > 5000

    # 原字位置与未动区域的亮度分布必须一致
    delta = float(gray_after[was_text].mean() - gray_after[untouched].mean())
    assert abs(delta) < 3.0, f"旧字位置亮度偏差 {delta:+.1f}，说明覆盖没生效"

    # 颗粒也必须一致：覆盖的是原图自己的背景，噪点强度应与周边相同
    def grain(window: np.ndarray) -> float:
        blur = cv2.GaussianBlur(window, (0, 0), 1.4)
        return float((window - blur).std())

    assert abs(grain(gray_after[was_text]) - grain(gray_after[untouched])) < 2.0


def test_text_fill_does_not_imprint_neighbourhood_structure_into_glyphs() -> None:
    """填充区里不能残留「旧字轮廓」：底色必须与周边统计一致。

    实测 0901 水印图：曾经把邻区纹理整块平移进蒙版，邻区的明暗结构
    在蒙版内不是零均值，沿笔画轮廓叠出一圈网纹，旧数字仍然隐约可见。
    这里在周边铺一块固定图案，填充后原字位置不能比原背景位置更亮/更暗。
    """
    width, height = 260, 130
    rng = np.random.default_rng(11)
    pixels = np.full((height, width, 3), (38, 66, 172), dtype=np.int16)
    pixels = np.clip(
        pixels + rng.integers(-14, 15, size=(height, width, 3)), 0, 255
    ).astype(np.uint8)
    # 一段有空间结构的邻区（左明右暗），整块平移进来就会印出结构
    pixels[:, :40] = np.clip(pixels[:, :40].astype(np.int16) + 26, 0, 255)

    mask = np.zeros((height, width), dtype=np.uint8)
    for left in (60, 84, 108, 132, 156):
        mask[47:83, left : left + 5] = 255
        mask[78:83, left : left + 18] = 255
    pixels[mask > 0] = (245, 248, 255)

    document = ImageDocument(
        ImageAsset(
            Path("structure.png"),
            width,
            height,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        pixels.tobytes(),
    )
    result = FallbackInpaintAdapter(
        _UnavailableAdapter(), _UnavailableAdapter()
    ).inpaint(InpaintingRequest(document, EraseMask(width, height, mask.tobytes())))
    repaired = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        height, width, 3
    )

    gray = cv2.cvtColor(repaired, cv2.COLOR_RGB2GRAY).astype(np.float32)
    # 原字位置 vs 蒙版外一圈紧邻环带：两者底色相同，填充正确时统计一致
    was_text = (mask > 0) & (
        cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY) > 150
    )
    ring = (
        cv2.dilate((mask > 0).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    ) & ~(mask > 0)
    ring[:, :45] = False  # 排除左半的加亮结构，只跟同底的右半比
    assert int(was_text.sum()) > 200
    assert int(ring.sum()) > 200

    # 原字位置不应系统性地比周边亮或暗（|差| < 2 个亮度级）
    delta = float(gray[was_text].mean() - gray[ring].mean())
    assert abs(delta) < 2.0, f"旧字轮廓残影 delta={delta:.2f}"


def test_text_fill_does_not_copy_glyph_antialiasing_as_background() -> None:
    """笔画边缘的抗锯齿亮边不能被当成底色填进蒙版。

    实测 0901 水印图：白字外圈 1~4px 是亮度 170~245 的抗锯齿边缘。
    最近邻取样若采到这些像素，填充区里就会出现孤立亮斑——客户圈出来的
    「旧数字 9 的圈里有块偏白的斑」就是它。取样源必须离开蒙版至少几像素。
    """
    width, height = 200, 110
    base = (36, 60, 170)
    # 带颗粒的底色，才会走「噪点回填」路径（纯色底会直接按主色填平）
    rng = np.random.default_rng(23)
    pixels = np.full((height, width, 3), base, dtype=np.int16)
    pixels = np.clip(
        pixels + rng.integers(-14, 15, size=(height, width, 3)), 0, 255
    ).astype(np.uint8)

    mask = np.zeros((height, width), dtype=np.uint8)
    for left in (52, 74, 96, 118, 140):
        mask[40:72, left : left + 5] = 255
        mask[67:72, left : left + 15] = 255
    # 白字外圈 1px 是抗锯齿亮边（实测 0901 水印确实只有 1~2px），
    # 再往外就是真实底色
    halo = (cv2.dilate(mask, np.ones((3, 3), np.uint8)) > 0) & (mask == 0)
    pixels[halo] = (110, 135, 200)
    pixels[mask > 0] = (245, 248, 255)

    document = ImageDocument(
        ImageAsset(
            Path("halo.png"), width, height, 1, ImageFileFormat.PNG, False, False
        ),
        "RGB",
        pixels.tobytes(),
    )
    result = FallbackInpaintAdapter(
        _UnavailableAdapter(), _UnavailableAdapter()
    ).inpaint(InpaintingRequest(document, EraseMask(width, height, mask.tobytes())))
    repaired = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        height, width, 3
    )

    # 蒙版内任何一个连通块都不能明显亮于真实底色
    gray = cv2.cvtColor(repaired, cv2.COLOR_RGB2GRAY).astype(np.float32)
    base_gray = float(
        cv2.cvtColor(np.array([[base]], dtype=np.uint8), cv2.COLOR_RGB2GRAY)[0, 0]
    )
    count, labels = cv2.connectedComponents(mask, 8)
    for component_id in range(1, count):
        component = labels == component_id
        if int(component.sum()) < 40:
            continue
        mean = float(gray[component].mean())
        assert mean - base_gray < 8.0, (
            f"笔画块 {component_id} 被抗锯齿亮边污染：均值 {mean:.1f}，"
            f"真实底色 {base_gray:.1f}"
        )


def test_text_fill_preserves_colored_label_gradient() -> None:
    """彩色标签的渐变底不能被填成单一块状色。

    实测电商图黄标签：左上 [225,165,44] 渐变到右下 [203,138,46]。
    用「就近取最近背景色」时，远处深色被搬到近处浅色区，整块渐变被
    抹成一块块深黄斑（dE 35~60，客户看到三块橙色污渍）。填充必须
    延续渐变：左右两侧各自接近本侧的底色，且块内方差要小。
    """
    width, height = 240, 90
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    # 横向渐变：左浅右深
    for x in range(width):
        t = x / (width - 1)
        pixels[:, x] = (
            int(225 - 22 * t),
            int(165 - 27 * t),
            int(44 + 2 * t),
        )

    mask = np.zeros((height, width), dtype=np.uint8)
    for left in (60, 88, 116, 144, 172):
        mask[30:60, left : left + 6] = 255
        mask[54:60, left : left + 18] = 255
    pixels[mask > 0] = (250, 250, 252)

    document = ImageDocument(
        ImageAsset(
            Path("gradient.png"), width, height, 1, ImageFileFormat.PNG, False, False
        ),
        "RGB",
        pixels.tobytes(),
    )
    result = FallbackInpaintAdapter(
        _UnavailableAdapter(), _UnavailableAdapter()
    ).inpaint(InpaintingRequest(document, EraseMask(width, height, mask.tobytes())))
    repaired = np.frombuffer(result.document.pixels, dtype=np.uint8).reshape(
        height, width, 3
    )

    left_band = mask[:, 60:120] > 0
    right_band = mask[:, 150:210] > 0
    assert int(left_band.sum()) > 100
    assert int(right_band.sum()) > 100

    left_fill = repaired[:, 60:120][left_band[:, :60]].astype(np.float32).mean(axis=0)
    right_fill = repaired[:, 150:210][right_band[:, :60]].astype(np.float32).mean(axis=0)
    left_ref = pixels[5, 60:120].astype(np.float32).mean(axis=0)
    right_ref = pixels[5, 150:210].astype(np.float32).mean(axis=0)

    assert float(np.linalg.norm(left_fill - left_ref)) < 14.0, (
        f"左侧浅色区填充偏差过大：{left_fill.round(0)} vs {left_ref.round(0)}"
    )
    assert float(np.linalg.norm(right_fill - right_ref)) < 14.0, (
        f"右侧深色区填充偏差过大：{right_fill.round(0)} vs {right_ref.round(0)}"
    )
    # 左右两侧必须仍有明显色差（渐变没被抹平）
    assert float(np.linalg.norm(left_fill - right_fill)) > 8.0


def _ocr_for_polygon(polygon):
    from src.domain.ocr import OcrResult, TextRegion, order_quad

    region = TextRegion(
        "region-0001",
        order_quad(polygon),
        "TEST",
        0.99,
        "en",
        "fixture",
    )
    return OcrResult((region,), "en", "fixture", 0)


def _translation_for_region():
    from src.domain.translation import (
        TranslationMode,
        TranslationResult,
        TranslationSelection,
        TranslationStatus,
        TranslationUnit,
    )

    return TranslationResult(
        (
            TranslationUnit(
                region_id="region-0001",
                source_text="TEST",
                translated_text="TEST",
                source_language="en",
                target_language="en",
                status=TranslationStatus.TRANSLATED,
            ),
        ),
        TranslationSelection(TranslationMode.ALL, "en"),
        "fixture",
        0,
    )


def _mask_document(arr: np.ndarray) -> ImageDocument:
    height, width = arr.shape[:2]
    return ImageDocument(
        ImageAsset(Path("m.png"), width, height, 1, ImageFileFormat.PNG, False, False),
        "RGB",
        arr.astype(np.uint8).tobytes(),
    )


def test_erase_mask_keeps_colored_label_background() -> None:
    """彩色标签上的白字只擦笔画，不能整框擦掉标签底色。

    客户电商图（黄底 / 紫底标签）整框擦除后，补全模型不知道原底色，
    标签被补成灰白碎块。高对比场景必须走字形蒙版。
    """
    from src.application.inpainting import BuildEraseMask

    height, width = 200, 400
    for base, text in (((240, 185, 45), (255, 255, 255)), ((110, 50, 160), (255, 255, 255))):
        arr = np.full((height, width, 3), base, np.uint8)
        # 模拟真实文字笔画（不是整块色块）：几条竖笔画 + 横笔画
        for x in range(70, 330, 40):
            arr[75:125, x : x + 14] = text
            arr[75:85, x : x + 34] = text
        document = _mask_document(arr)
        mask = BuildEraseMask(PillowMaskRasterizer()).execute(
            document,
            _ocr_for_polygon(((40, 60), (360, 60), (360, 140), (40, 140))),
            _translation_for_region(),
        )
        pixels = np.frombuffer(mask.pixels, np.uint8).reshape(height, width) > 0
        box_area = 320 * 80
        covered = float(np.count_nonzero(pixels)) / box_area
        assert covered < 0.7, (
            f"底色 {base} 的标签被整框擦掉了（覆盖 {covered:.0%}），应保留标签底色"
        )
        # 标签四角必须没被擦
        assert not pixels[62, 42], "标签角落不应被擦除"
        assert not pixels[138, 358], "标签角落不应被擦除"


def test_erase_mask_uses_whole_box_for_low_contrast_text() -> None:
    """低对比（半透明底）文字整框遮挡，避免笔画缝隙透出旧字轮廓。"""
    from src.application.inpainting import BuildEraseMask

    height, width = 200, 400
    arr = np.full((height, width, 3), (90, 110, 180), np.uint8)
    arr[70:130, 60:340] = (105, 125, 190)
    document = _mask_document(arr)
    mask = BuildEraseMask(PillowMaskRasterizer()).execute(
        document,
        _ocr_for_polygon(((40, 60), (360, 60), (360, 140), (40, 140))),
        _translation_for_region(),
    )
    pixels = np.frombuffer(mask.pixels, np.uint8).reshape(height, width) > 0
    covered = float(np.count_nonzero(pixels)) / (320 * 80)
    assert covered > 0.8, f"低对比区域应整框遮挡，实际覆盖仅 {covered:.0%}"


def _wide_label_document() -> ImageDocument:
    """横排黄色胶囊标签 + 白色文字（客户电商图场景）。"""
    height, width = 100, 360
    arr = np.zeros((height, width, 3), np.uint8)
    # 对角渐变黄底
    for y in range(height):
        for x in range(width):
            arr[y, x] = (
                248 - min(40, x // 12),
                190 - min(55, y // 2),
                70 - min(35, x // 10),
            )
    for x in range(30, 330, 40):
        arr[30:70, x : x + 16] = (255, 255, 255)
    return _mask_document(arr)


def test_wide_colored_label_is_not_erased_as_a_whole() -> None:
    """横排彩色标签只擦文字，不能把整块标签底色当成文字擦掉。

    客户电商图：黄底白字的胶囊标签，整框膨胀后标签被擦成碎块，
    补全模型补出一片深黄污渍。
    """
    height, width = 100, 360
    document = _wide_label_document()
    rasterizer = PillowMaskRasterizer()
    polygon = ((15, 20), (345, 20), (345, 80), (15, 80))

    whole = np.frombuffer(
        rasterizer.rasterize_text(
            document, (polygon,), 2, allow_wide_label=False
        ).pixels,
        np.uint8,
    ).reshape(height, width)
    refined = np.frombuffer(
        rasterizer.rasterize_text(
            document, (polygon,), 2, allow_wide_label=True
        ).pixels,
        np.uint8,
    ).reshape(height, width)

    # 放开横排分支后必须只擦笔画，标签底色保留
    assert refined[20:80, 15:345].mean() / 255 < 0.45, (
        "横排标签应只擦文字笔画，保住标签底色"
    )
    # 且不能比默认路径擦得更多
    assert refined.sum() <= whole.sum()


def test_build_erase_mask_keeps_wide_label_background() -> None:
    """翻译流程对高对比横排标签使用字形蒙版，保住底色。"""
    from src.application.inpainting import BuildEraseMask

    height, width = 100, 360
    document = _wide_label_document()
    mask = BuildEraseMask(PillowMaskRasterizer()).execute(
        document,
        _ocr_for_polygon(((15, 20), (345, 20), (345, 80), (15, 80))),
        _translation_for_region(),
    )
    pixels = np.frombuffer(mask.pixels, np.uint8).reshape(height, width) > 0
    covered = float(np.count_nonzero(pixels[20:80, 15:345])) / (330 * 60)
    assert covered < 0.45, f"标签底色被整块擦掉了（覆盖 {covered:.0%}）"


def test_dark_colored_text_on_label_is_mostly_erased() -> None:
    """彩色标签上的深色字也要擦到（深紫/深红 chroma 落在中性色与饱和色之间）。"""
    height, width = 120, 400
    arr = np.full((height, width, 3), (243, 174, 255), np.uint8)
    # 深紫近黑的文字笔画
    for x in range(60, 340, 40):
        arr[40:90, x : x + 14] = (61, 32, 32)
        arr[40:50, x : x + 34] = (61, 32, 32)
    document = _mask_document(arr)
    mask = PillowMaskRasterizer().rasterize_text(
        document,
        (((40, 30), (360, 30), (360, 100), (40, 100)),),
        2,
        allow_wide_label=True,
    )
    pixels = np.frombuffer(mask.pixels, np.uint8).reshape(height, width) > 0
    dark = arr.astype(int).sum(axis=2) < 330
    covered = float(np.count_nonzero(dark & pixels)) / max(1, np.count_nonzero(dark))
    assert covered >= 0.95, f"深色字漏擦（仅覆盖 {covered:.0%}），会留旧字轮廓"


def test_light_background_outside_label_is_not_erased() -> None:
    """标签框四角露出框外浅色底时，不能把框外背景当成文字擦掉。"""
    height, width = 120, 400
    arr = np.full((height, width, 3), (190, 206, 249), np.uint8)
    # 圆角标签只占中间一块
    arr[35:95, 55:345] = (240, 185, 45)
    for x in range(90, 310, 40):
        arr[50:80, x : x + 14] = (255, 255, 255)
    document = _mask_document(arr)
    mask = PillowMaskRasterizer().rasterize_text(
        document,
        (((55, 35), (345, 35), (345, 95), (55, 95)),),
        2,
        allow_wide_label=True,
    )
    pixels = np.frombuffer(mask.pixels, np.uint8).reshape(height, width) > 0
    covered = float(np.count_nonzero(pixels)) / ((345 - 55) * (95 - 35))
    assert covered < 0.55, f"标签底色被大面积擦除（覆盖 {covered:.0%}）"


def test_light_background_with_dark_colored_heading_is_not_inverted() -> None:
    """浅色底上的大号彩色标题：不能把字当底色、把底当字（会漏掉整块标题）。

    客户主图「毛绒玩具定制」是深紫大字压在浅蓝渐变上，最大饱和连通域
    其实是文字本身，旧逻辑据此判定"彩色标签"，结果抠出的是背景。
    """
    height, width = 90, 340
    arr = np.zeros((height, width, 3), np.uint8)
    for y in range(height):
        arr[y, :] = (200 + y // 6, 215 + y // 8, 245)
    # 三块深紫大字
    for x in range(30, 300, 110):
        arr[25:70, x : x + 70] = (60, 16, 120)
    document = _mask_document(arr)
    mask = PillowMaskRasterizer().rasterize_text(
        document,
        (((20, 15), (320, 15), (320, 78), (20, 78)),),
        2,
        allow_wide_label=True,
    )
    pixels = np.frombuffer(mask.pixels, np.uint8).reshape(height, width) > 0
    dark = arr.astype(int).sum(axis=2) < 330
    covered = float(np.count_nonzero(dark & pixels)) / max(1, np.count_nonzero(dark))
    assert covered >= 0.95, f"标题字漏擦（仅覆盖 {covered:.0%}）"
    # 底色不能被当成文字大面积擦掉
    ratio = float(np.count_nonzero(pixels[15:78, 20:320])) / (300 * 63)
    assert ratio < 0.70, f"底色被误擦（{ratio:.0%}）"


def test_mixed_row_with_light_and_dark_text_is_fully_erased() -> None:
    """一行里中英文混排、字号差异大时，整行文字都要擦掉。

    客户主图「Plush toy customization 毛绒玩具定制」被 OCR 成一个大框，
    旧逻辑只按最大饱和连通域抠字，实测只擦到前三个中文字，
    右半行整段残留。
    """
    height, width = 120, 780
    arr = np.zeros((height, width, 3), np.uint8)
    for y in range(height):
        arr[y, :] = (205 + y // 10, 218 + y // 12, 246)
    # 左半：细笔画的深紫英文（模拟 Plush toy ...）
    for x in range(25, 350, 22):
        arr[40:95, x : x + 6] = (60, 16, 120)
        arr[40:50, x : x + 18] = (60, 16, 120)
    # 右半：粗笔画的深紫中文（模拟 毛绒玩具定制）
    for x in range(400, 760, 90):
        arr[35:100, x : x + 62] = (60, 16, 120)
    document = _mask_document(arr)

    mask = PillowMaskRasterizer().rasterize_text(
        document,
        (((15, 30), (770, 30), (770, 108), (15, 108)),),
        2,
        allow_wide_label=True,
    )
    pixels = np.frombuffer(mask.pixels, np.uint8).reshape(height, width) > 0
    dark = arr.astype(int).sum(axis=2) < 330

    covered = float(np.count_nonzero(dark & pixels)) / max(1, np.count_nonzero(dark))
    assert covered >= 0.95, f"混排行漏擦（仅覆盖 {covered:.0%}），右半行会残留"

    # 左右两半都必须覆盖到
    left = dark[:, :380]
    right = dark[:, 380:]
    assert (left & pixels[:, :380]).sum() / max(1, left.sum()) >= 0.95
    assert (right & pixels[:, 380:]).sum() / max(1, right.sum()) >= 0.95
