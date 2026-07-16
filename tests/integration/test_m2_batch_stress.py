from __future__ import annotations

import gc
from pathlib import Path
from time import sleep
from types import SimpleNamespace

from PIL import Image

from src.application.batch import RunBatch
from src.application.image_io import ImportImage
from src.domain.image import ImageLimits
from src.domain.job import ImageStage
from src.domain.translation import TranslationMode, TranslationSelection
from src.infrastructure.batch_result_store import PngBatchResultStore
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.platform.process_memory import PeakRssSampler, process_rss_bytes


class _PassthroughWorkflow:
    def execute(self, document, ocr_language, selection, brand_terms=(), on_stage=None):
        del ocr_language, selection, brand_terms
        if on_stage is not None:
            for stage in ImageStage:
                on_stage(stage)
        return SimpleNamespace(document=document)

    def cancel(self) -> None:
        pass


def _create_mixed_images(directory: Path, count: int = 100) -> tuple[Path, ...]:
    directory.mkdir()
    sizes = ((160, 96), (240, 160), (320, 200), (480, 270), (640, 360))
    sources = []
    for index in range(count):
        size = sizes[index % len(sizes)]
        format_index = index % 3
        if format_index == 0:
            suffix, mode = ".png", "RGBA"
            color = (index % 255, 80, 160, 80 + index % 176)
        elif format_index == 1:
            suffix, mode = ".jpg", "RGB"
            color = (index % 255, 120, 40)
        else:
            suffix, mode = ".webp", "RGB"
            color = (30, index % 255, 180)
        source = directory / f"mixed-{index:03d}{suffix}"
        Image.new(mode, size, color).save(source)
        sources.append(source)
    return tuple(sources)


def _run_measured(sources: tuple[Path, ...], cache: Path):
    codec = PillowImageCodec()
    store = PngBatchResultStore(cache, codec)
    scheduler = RunBatch(
        ImportImage(codec, ImageLimits()),
        _PassthroughWorkflow(),
        store,
        max_active_items=2,
    )
    sampler = PeakRssSampler()
    sampler.start()
    result = scheduler.execute(
        sources,
        "en",
        TranslationSelection(TranslationMode.ALL, "zh-Hans"),
    )
    peak = sampler.stop()
    return result, store, peak


def test_100_mixed_images_memory_ratio_and_three_round_idle_rss(tmp_path: Path) -> None:
    sources = _create_mixed_images(tmp_path / "inputs")
    fifty, fifty_store, peak_50 = _run_measured(
        sources[:50], tmp_path / "cache-50"
    )
    assert fifty.completed_count == 50
    fifty_store.clear(fifty.batch_id)
    del fifty
    gc.collect()

    hundred, hundred_store, peak_100 = _run_measured(
        sources, tmp_path / "cache-100"
    )
    assert hundred.completed_count == 100
    assert peak_100 <= peak_50 * 1.25
    hundred_store.clear(hundred.batch_id)
    del hundred
    gc.collect()

    idle_rss = []
    for round_index in range(3):
        result, store, _ = _run_measured(
            sources, tmp_path / f"cache-round-{round_index}"
        )
        assert result.completed_count == 100
        store.clear(result.batch_id)
        del result
        gc.collect()
        sleep(0.05)
        idle_rss.append(process_rss_bytes())
    threshold = 4 * 1024 * 1024
    assert not (
        idle_rss[1] - idle_rss[0] > threshold
        and idle_rss[2] - idle_rss[1] > threshold
    ), idle_rss
