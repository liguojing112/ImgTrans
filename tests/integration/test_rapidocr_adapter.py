from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest

from src.domain.image import ImageAsset, ImageDocument, ImageFileFormat, ImageLimits
from src.domain.ocr import (
    HighRecallOcrOptions,
    OcrError,
    OcrMode,
    OcrObservation,
    Point,
    TextRegion,
    TextRegionStatus,
    order_quad,
)
from src.infrastructure.ocr_profiles import OcrProfile
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.infrastructure.rapidocr_adapter import (
    RapidOcrAdapter,
    RapidOcrModelFiles,
    _alphabetic_token_spans,
    _map_cartesian_polygon_to_polar_strip,
    _map_polar_strip_polygon,
    _merge_high_recall_regions,
    _polar_geometry,
    _polar_ring_centers,
    _polar_token_quad,
    _polar_word_intervals,
    _recover_dense_repeated_regions,
    _rotate_image_expand,
)


def _document() -> ImageDocument:
    width, height = 240, 120
    return ImageDocument(
        ImageAsset(Path("fixture.png"), width, height, 1, ImageFileFormat.PNG, False, False),
        "RGB",
        bytes([255]) * width * height * 3,
    )


def _large_document() -> ImageDocument:
    width = height = 1254
    return ImageDocument(
        ImageAsset(
            Path("large-fixture.png"),
            width,
            height,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
        "RGB",
        bytes([255]) * width * height * 3,
    )


def _rotated_document() -> ImageDocument:
    width, height = 330, 327
    return ImageDocument(
        ImageAsset(
            Path("rotated-fixture.png"),
            width,
            height,
            1,
            ImageFileFormat.PNG,
            False,
            False,
        ),
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


def test_recognize_tags_regions_by_script_language() -> None:
    """回归：混合语言图片的区域不应统一打 OCR 所选语言标签。

    历史缺陷：所有区域共享 OCR 所选语言，导致「只翻译指定语言」
    （按 region.language_code 过滤）要么全部通过、要么全部跳过。"""
    texts = ["你好世界", "COTTON TISSUE", "Привет", "こんにちは"]
    boxes = np.array(
        [
            [[10, 10], [110, 10], [110, 35], [10, 35]],
            [[10, 40], [110, 40], [110, 65], [10, 65]],
            [[10, 70], [110, 70], [110, 95], [10, 95]],
            [[10, 100], [110, 100], [110, 118], [10, 118]],
        ],
        dtype=float,
    )

    class _MixedEngine:
        def __call__(self, image: np.ndarray, **_options: object) -> SimpleNamespace:
            return SimpleNamespace(
                boxes=boxes, txts=list(texts), scores=[0.9] * 4
            )

    adapter = RapidOcrAdapter(engine_factory=lambda _profile: _MixedEngine())
    result = adapter.recognize(_document(), "zh-Hans", fast=True)

    assert [region.language_code for region in result.regions] == [
        "zh-Hans", "en", "ru", "ja",
    ]
    # OCR 选英文时，汉字区域仍应修正为中文
    result_en = adapter.recognize(_document(), "en", fast=True)
    assert [region.language_code for region in result_en.regions] == [
        "zh-Hans", "en", "ru", "ja",
    ]


def test_fast_mode_runs_single_pass_without_enhanced_recovery() -> None:
    """fast=True 只做一次标准识别，跳过瓦片恢复/密集修复/逐区域精修。"""
    class _CountingEngine:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, image: np.ndarray, **_options: object) -> SimpleNamespace:
            self.calls += 1
            return SimpleNamespace(
                boxes=np.array(
                    [[[10, 10], [110, 10], [110, 40], [10, 40]]],
                    dtype=float,
                ),
                txts=["耐用"],
                scores=[0.9],
            )

    engine = _CountingEngine()
    adapter = RapidOcrAdapter(engine_factory=lambda _profile: engine)
    # 大图（1254×1254 > 960）触发瓦片恢复的阈值
    result = adapter.recognize(_large_document(), "zh-Hans", fast=True)

    assert [region.text for region in result.regions] == ["耐用"]
    assert engine.calls == 1  # 瓦片恢复/2x3x 放大/逐区域精修全部跳过


def test_non_fast_mode_keeps_enhanced_recovery() -> None:
    """默认（fast=False）保留瓦片恢复，翻译流程质量不变。"""
    class _TiledEngine:
        def __init__(self) -> None:
            self.detection_calls = 0

        def __call__(self, image, **options):
            if not options["use_det"]:
                return SimpleNamespace(boxes=None, txts=["耐用"], scores=[0.999])
            self.detection_calls += 1
            if image.shape[:2] == (1254, 1254):
                return SimpleNamespace(
                    boxes=np.array(
                        [[[1044, 87], [1147, 87], [1147, 147], [1044, 147]]],
                        dtype=float,
                    ),
                    txts=["厚实"],
                    scores=[1.0],
                )
            if self.detection_calls == 3:
                return SimpleNamespace(
                    boxes=np.array(
                        [
                            [[494, 87], [597, 87], [597, 147], [494, 147]],
                            [[494, 133], [595, 133], [595, 190], [494, 190]],
                        ],
                        dtype=float,
                    ),
                    txts=["厚实", "耐用"],
                    scores=[1.0, 0.999],
                )
            return SimpleNamespace(boxes=None, txts=None, scores=None)

    engine = _TiledEngine()
    adapter = RapidOcrAdapter(engine_factory=lambda _profile: engine)
    adapter.recognize(_large_document(), "zh-Hans")  # 默认 fast=False

    assert engine.detection_calls == 5  # 瓦片恢复照常执行


def test_high_resolution_tiles_recover_small_region_without_duplicate() -> None:
    class _TiledEngine:
        def __init__(self) -> None:
            self.detection_calls = 0

        def __call__(self, image, **options):
            if not options["use_det"]:
                return SimpleNamespace(boxes=None, txts=["耐用"], scores=[0.999])
            self.detection_calls += 1
            if image.shape[:2] == (1254, 1254):
                return SimpleNamespace(
                    boxes=np.array(
                        [[[1044, 87], [1147, 87], [1147, 147], [1044, 147]]],
                        dtype=float,
                    ),
                    txts=["厚实"],
                    scores=[1.0],
                )
            if self.detection_calls == 3:
                return SimpleNamespace(
                    boxes=np.array(
                        [
                            [[494, 87], [597, 87], [597, 147], [494, 147]],
                            [[494, 133], [595, 133], [595, 190], [494, 190]],
                        ],
                        dtype=float,
                    ),
                    txts=["厚实", "耐用"],
                    scores=[1.0, 0.999],
                )
            return SimpleNamespace(boxes=None, txts=None, scores=None)

    engine = _TiledEngine()
    result = RapidOcrAdapter(engine_factory=lambda _profile: engine).recognize(
        _large_document(),
        "zh-Hans",
    )

    assert [region.text for region in result.regions] == ["厚实", "耐用"]
    assert engine.detection_calls == 5
    assert min(point.x for point in result.regions[1].polygon) == 1044


def test_dense_repeated_word_recovers_digit_shaped_detection_at_higher_scale() -> None:
    boxes = []
    for index in range(40):
        x = (index % 8) * 40
        y = (index // 8) * 40
        boxes.append(
            np.array(
                ((x, y), (x + 24, y), (x + 24, y + 14), (x, y + 14)),
                dtype=float,
            )
        )
    canonical = "\u4e92\u52a8"
    texts = [canonical] * 5 + ["\u54c1\u8d28"] * 34 + ["4"]
    scores = [0.95] * 40
    suspicious_box = boxes[-1].copy()
    missed_box = np.array(
        ((350, 210), (378, 210), (378, 226), (350, 226)),
        dtype=float,
    )

    class _DenseScaleEngine:
        def __call__(self, image, **options):
            assert options["use_det"]
            if image.shape[:2] == (480, 800):
                return SimpleNamespace(
                    boxes=np.array([missed_box * 2], dtype=float),
                    txts=["\u54c1\u8d28"],
                    scores=[0.82],
                )
            assert image.shape[:2] == (720, 1200)
            return SimpleNamespace(
                boxes=np.array(
                    (suspicious_box * 3, missed_box * 3),
                    dtype=float,
                ),
                txts=[canonical, "\u54c1\u8d28"],
                scores=[0.9, 0.88],
            )

    recovered_boxes, recovered_texts, recovered_scores = (
        _recover_dense_repeated_regions(
            _DenseScaleEngine(),
            np.full((240, 400, 3), 255, dtype=np.uint8),
            boxes,
            texts,
            scores,
            0.5,
        )
    )

    assert recovered_texts[39] == canonical
    assert recovered_scores[39] == 0.9
    assert np.array_equal(recovered_boxes[39], suspicious_box)
    assert recovered_texts[-1] == "\u54c1\u8d28"
    assert recovered_scores[-1] == 0.82
    assert np.allclose(recovered_boxes[-1], missed_box)


def test_standard_mode_does_not_run_multi_angle_recovery() -> None:
    class _RotatedEngine:
        def __init__(self) -> None:
            self.detection_calls = 0

        def __call__(self, image, **options):
            assert options["use_det"]
            self.detection_calls += 1
            if self.detection_calls == 1:
                return SimpleNamespace(
                    boxes=np.array(
                        [
                            [[10, 20], [50, 40], [42, 56], [2, 36]],
                            [[80, 100], [100, 140], [84, 148], [64, 108]],
                        ],
                        dtype=float,
                    ),
                    txts=["One", "Two"],
                    scores=[0.99, 0.98],
                )
            if self.detection_calls == 2:
                return SimpleNamespace(
                    boxes=np.array(
                        [[[150, 150], [210, 150], [210, 170], [150, 170]]],
                        dtype=float,
                    ),
                    txts=["Three"],
                    scores=[0.97],
                )
            return SimpleNamespace(boxes=None, txts=None, scores=None)

    engine = _RotatedEngine()
    result = RapidOcrAdapter(engine_factory=lambda _profile: engine).recognize(
        _rotated_document(),
        "en",
    )

    assert [region.text for region in result.regions] == ["One", "Two"]
    assert result.mode is OcrMode.STANDARD
    assert engine.detection_calls == 1


def test_high_recall_mode_filters_single_view_rotation_noise() -> None:
    class _RotatedEngine:
        def __init__(self) -> None:
            self.detection_calls = 0

        def __call__(self, image, **options):
            assert options["use_det"]
            self.detection_calls += 1
            if self.detection_calls == 1:
                return SimpleNamespace(
                    boxes=np.array(
                        [[[10, 20], [50, 40], [42, 56], [2, 36]]],
                        dtype=float,
                    ),
                    txts=["One"],
                    scores=[0.99],
                )
            if self.detection_calls == 2:
                return SimpleNamespace(
                    boxes=np.array(
                        [[[150, 150], [210, 150], [210, 170], [150, 170]]],
                        dtype=float,
                    ),
                    txts=["Three"],
                    scores=[0.97],
                )
            return SimpleNamespace(boxes=None, txts=None, scores=None)

    engine = _RotatedEngine()
    result = RapidOcrAdapter(engine_factory=lambda _profile: engine).recognize_high_recall(
        _rotated_document(),
        "en",
        HighRecallOcrOptions(ring_bands=()),
    )

    assert result.mode is OcrMode.HIGH_RECALL
    assert [region.text for region in result.regions] == ["One"]
    assert engine.detection_calls == 5
    assert result.cleanup_summary is not None
    assert result.cleanup_summary.raw_candidate_count == 2
    assert result.cleanup_summary.unique_candidate_count == 1
    assert result.cleanup_summary.auto_confirmed_count == 1
    assert result.cleanup_summary.review_required_count == 0
    assert result.cleanup_summary.deleted_candidate_count == 1


def test_rotation_expands_canvas_and_inverse_mapping_does_not_crop() -> None:
    image = np.full((40, 100, 3), 255, dtype=np.uint8)
    image[0:4, 0:4] = 0
    rotated, matrix = _rotate_image_expand(image, 37)
    original_corners = np.asarray(
        ((0, 0), (99, 0), (99, 39), (0, 39)),
        dtype=float,
    )
    transformed = np.column_stack(
        (
            original_corners[:, 0] * matrix[0, 0]
            + original_corners[:, 1] * matrix[0, 1]
            + matrix[0, 2],
            original_corners[:, 0] * matrix[1, 0]
            + original_corners[:, 1] * matrix[1, 1]
            + matrix[1, 2],
        )
    )

    assert rotated.shape[0] > image.shape[0]
    assert rotated.shape[1] > image.shape[1]
    assert transformed[:, 0].min() >= -1
    assert transformed[:, 1].min() >= -1
    assert transformed[:, 0].max() <= rotated.shape[1] + 1
    assert transformed[:, 1].max() <= rotated.shape[0] + 1


def test_polar_mapping_round_trip_for_multiple_radii_and_angles() -> None:
    center = (120.0, 100.0)
    maximum_radius = 90.0
    angle_steps = 720
    local = np.asarray(
        ((60, 2), (180, 4), (300, 12), (540, 18)),
        dtype=float,
    )
    cartesian = _map_polar_strip_polygon(
        local,
        10,
        center,
        maximum_radius,
        angle_steps,
    )
    restored = _map_cartesian_polygon_to_polar_strip(
        cartesian,
        10,
        center,
        maximum_radius,
        angle_steps,
    )

    assert np.allclose(restored, local, atol=1e-6)


def test_multi_view_dedup_is_deterministic_and_controls_eligibility() -> None:
    polygon = order_quad(((40, 40), (90, 40), (90, 60), (40, 60)))
    standard = TextRegion("standard", polygon, "Base", 0.95, "en", "model")
    enhanced_polygon = order_quad(((140, 80), (200, 80), (200, 100), (140, 100)))
    observations = [
        OcrObservation(
            "polar",
            15,
            scale,
            confidence,
            enhanced_polygon,
            text,
            f"polar:0:scale:{scale}",
        )
        for scale, confidence, text in (
            (2, 0.91, "Strategy"),
            (3, 0.93, "Strategy"),
            (4, 0.81, "Strategv"),
        )
    ]
    observations.append(
        OcrObservation(
            "rotation",
            180,
            1,
            0.94,
            enhanced_polygon,
            "Strategy",
            "rotation:180",
        )
    )
    first = _merge_high_recall_regions(
        (standard,),
        observations,
        "en",
        "model",
        0.5,
        0.85,
        (170, 0),
    )
    second = _merge_high_recall_regions(
        (standard,),
        list(reversed(observations)),
        "en",
        "model",
        0.5,
        0.85,
        (170, 0),
    )

    assert [(region.region_id, region.text) for region in first] == [
        (region.region_id, region.text) for region in second
    ]
    enhanced = next(region for region in first if region.enhanced_only)
    assert enhanced.text == "Strategy"
    assert enhanced.auto_process_eligible
    assert len(enhanced.observations) == 4


def test_multi_view_borderline_candidate_is_kept_for_review_but_noise_is_dropped() -> None:
    polygon = order_quad(((80, 70), (140, 70), (140, 90), (80, 90)))
    observations = [
        OcrObservation(
            "polar",
            20,
            2,
            0.81,
            polygon,
            "Finance",
            "polar:0:scale:2",
        ),
        OcrObservation(
            "polar",
            20,
            3,
            0.83,
            polygon,
            "Finance",
            "polar:0:scale:3",
        ),
        OcrObservation(
            "rotation",
            90,
            1,
            0.99,
            order_quad(((200, 180), (240, 180), (240, 200), (200, 200))),
            "Noise",
            "rotation:90",
        ),
    ]

    regions = _merge_high_recall_regions(
        (),
        observations,
        "en",
        "model",
        0.5,
        0.85,
        (110, 0),
    )

    assert len(regions) == 1
    assert regions[0].text == "Finance"
    assert regions[0].enhanced_only
    assert not regions[0].auto_process_eligible


def test_polar_geometry_reports_ring_angle_width_and_tangent() -> None:
    polygon = order_quad(((80, 45), (120, 45), (120, 55), (80, 55)))
    geometry = _polar_geometry(polygon, (100, 100))

    assert 49 <= geometry.mean_radius <= 57
    assert geometry.radial_start < geometry.radial_end
    assert geometry.angle_start < geometry.angle_end
    assert 8 <= geometry.band_width <= 13
    assert abs(geometry.tangent_degrees) <= 1


def test_same_text_on_different_rings_is_never_merged() -> None:
    center = (100, 100)
    inner = order_quad(((80, 45), (120, 45), (120, 55), (80, 55)))
    outer = order_quad(((80, 25), (120, 25), (120, 35), (80, 35)))
    observations = []
    for ring, polygon in (("inner", inner), ("outer", outer)):
        for scale in (2, 3):
            observations.append(
                OcrObservation(
                    "polar",
                    0,
                    scale,
                    0.93,
                    polygon,
                    "Sales",
                    f"polar:{ring}:scale:{scale}",
                )
            )

    regions = _merge_high_recall_regions(
        (),
        observations,
        "en",
        "model",
        0.5,
        0.85,
        center,
        (200, 200),
    )

    assert len(regions) == 2
    assert all(region.auto_process_eligible for region in regions)
    radii = sorted(
        round(_polar_geometry(region.polygon, center).mean_radius)
        for region in regions
    )
    assert radii[1] - radii[0] >= 18


def test_unstable_mapping_stays_review_and_invalid_candidates_are_deleted() -> None:
    center = (100, 100)
    first = order_quad(((70, 45), (110, 45), (110, 55), (70, 55)))
    shifted = order_quad(((84, 45), (124, 45), (124, 55), (84, 55)))
    punctuation = order_quad(((140, 45), (160, 45), (160, 55), (140, 55)))
    observations = (
        OcrObservation("polar", 0, 2, 0.94, first, "Trade", "polar:0:scale:2"),
        OcrObservation("polar", 0, 3, 0.95, shifted, "Trade", "polar:0:scale:3"),
        OcrObservation("polar", 0, 2, 0.99, punctuation, "...", "polar:1:scale:2"),
        OcrObservation("polar", 0, 3, 0.99, punctuation, "...", "polar:1:scale:3"),
    )

    regions = _merge_high_recall_regions(
        (),
        list(observations),
        "en",
        "model",
        0.5,
        0.85,
        center,
        (200, 200),
    )

    assert len(regions) == 1
    assert regions[0].text == "Trade"
    assert not regions[0].auto_process_eligible


def test_matching_stable_scale_views_confirm_without_rotation() -> None:
    center = (100, 100)
    polygon = order_quad(((80, 45), (120, 45), (120, 55), (80, 55)))
    scale_observations = [
        OcrObservation(
            "polar",
            0,
            scale,
            0.94,
            polygon,
            "Sales",
            f"polar:0:scale:{scale}",
        )
        for scale in (2, 3, 4)
    ]

    confirmed_by_scales = _merge_high_recall_regions(
        (),
        scale_observations,
        "en",
        "model",
        0.5,
        0.85,
        center,
        (200, 200),
    )
    confirmed = _merge_high_recall_regions(
        (),
        [
            *scale_observations,
            OcrObservation(
                "rotation",
                0,
                1,
                0.96,
                polygon,
                "Sales",
                "rotation:0",
            ),
        ],
        "en",
        "model",
        0.5,
        0.85,
        center,
        (200, 200),
    )

    assert len(confirmed_by_scales) == 1
    assert confirmed_by_scales[0].auto_process_eligible
    assert len(confirmed) == 1
    assert confirmed[0].auto_process_eligible


def test_standard_candidate_remains_eligible_in_high_recall_mode() -> None:
    center = (100, 100)
    polygon = order_quad(((80, 45), (120, 45), (120, 55), (80, 55)))
    standard = TextRegion(
        "standard",
        polygon,
        "Sales",
        0.96,
        "en",
        "model",
    )
    rotation_zero = OcrObservation(
        "rotation",
        0,
        1,
        0.96,
        polygon,
        "Sales",
        "rotation:0",
    )
    polar = OcrObservation(
        "polar",
        0,
        2,
        0.94,
        polygon,
        "Sales",
        "polar:0:scale:2",
    )

    duplicate_view = _merge_high_recall_regions(
        (standard,),
        [rotation_zero],
        "en",
        "model",
        0.5,
        0.85,
        center,
        (200, 200),
    )
    corroborated = _merge_high_recall_regions(
        (standard,),
        [rotation_zero, polar],
        "en",
        "model",
        0.5,
        0.85,
        center,
        (200, 200),
    )

    assert duplicate_view[0].auto_process_eligible
    assert corroborated[0].auto_process_eligible


def test_cleanup_limits_polygon_width_between_neighboring_rings() -> None:
    center = (100, 100)
    inner = order_quad(((75, 42), (125, 42), (125, 58), (75, 58)))
    outer = order_quad(((75, 30), (125, 30), (125, 46), (75, 46)))
    observations = []
    for ring_index, polygon in enumerate((inner, outer)):
        for scale in (2, 3):
            observations.append(
                OcrObservation(
                    "polar",
                    0,
                    scale,
                    0.93,
                    polygon,
                    f"Ring{ring_index}",
                    f"polar:{ring_index}:scale:{scale}",
                )
            )

    regions = _merge_high_recall_regions(
        (),
        observations,
        "en",
        "model",
        0.5,
        0.85,
        center,
        (200, 200),
    )

    assert len(regions) == 2
    widths = [
        _polar_geometry(region.polygon, center).band_width
        for region in regions
    ]
    assert max(widths) < 12


def test_spatially_conflicting_dissimilar_candidates_keep_one_region() -> None:
    center = (100, 100)
    polygon = order_quad(((75, 42), (125, 42), (125, 58), (75, 58)))
    observations = []
    for text, base_confidence in (("Sales", 0.95), ("Noise", 0.83)):
        for scale in (2, 3):
            observations.append(
                OcrObservation(
                    "polar",
                    0,
                    scale,
                    base_confidence,
                    polygon,
                    text,
                    f"polar:0:scale:{scale}:{text}",
                )
            )

    regions = _merge_high_recall_regions(
        (),
        observations,
        "en",
        "model",
        0.5,
        0.85,
        center,
        (200, 200),
    )

    assert len(regions) == 1
    assert regions[0].text == "Sales"


def test_polar_helpers_find_rows_words_and_restore_tangent_geometry() -> None:
    unwrapped = np.full((100, 600, 3), 255, dtype=np.uint8)
    for y in (12, 25, 38, 51, 64):
        unwrapped[y - 3 : y + 4, 30:90] = 40
        unwrapped[y - 3 : y + 4, 130:210] = 70

    centers = _polar_ring_centers(unwrapped)
    intervals = _polar_word_intervals(unwrapped[centers[0] - 7 : centers[0] + 7])
    tokens = _alphabetic_token_spans("Import-Export Strategy")
    quad = _polar_token_quad(
        120,
        180,
        10,
        20,
        (100, 100),
        100,
        600,
    )

    assert len(centers) == 5
    assert intervals == ((30, 90), (130, 210))
    assert [token[0] for token in tokens] == ["Import", "Export", "Strategy"]
    assert quad.shape == (4, 2)
    assert np.isfinite(quad).all()
    assert abs(np.cross(quad[1] - quad[0], quad[3] - quad[0])) > 1


def test_adapter_reports_unavailable_language_and_inconsistent_runtime() -> None:
    adapter = RapidOcrAdapter(engine_factory=lambda _profile: FakeEngine(inconsistent=True))
    assert len(adapter.language_codes) == 24
    assert "bn" not in adapter.language_codes
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
