from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any
import unicodedata

from .contracts import ManifestSample, OCRRegion, order_quad
from .model_router import ModelRoute, RoutingError


class OCRRuntimeError(RuntimeError):
    pass


class RapidOCRAdapter:
    def __init__(
        self,
        confidence_threshold: float = 0.5,
        engine_factory: Callable[[dict[str, str]], Any] | None = None,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self._engine_factory = engine_factory or self._default_engine_factory
        self._engines: dict[str, Any] = {}
        self.load_times_ms: dict[str, float] = {}
        self.initialization_counts: dict[str, int] = {}

    @staticmethod
    def _default_engine_factory(params: dict[str, str]) -> Any:
        try:
            from rapidocr import RapidOCR
        except ImportError as exc:
            raise OCRRuntimeError(
                "RapidOCR runtime is not installed; install requirements.lock for this prototype"
            ) from exc
        return RapidOCR(params=params)

    def _engine(self, route: ModelRoute) -> Any:
        if not route.supported or route.model_id is None:
            raise RoutingError(route.reason or f"Unsupported OCR language: {route.language_code}")
        if route.model_id not in self._engines:
            started = perf_counter()
            self._engines[route.model_id] = self._engine_factory(route.engine_params())
            self.load_times_ms[route.model_id] = (perf_counter() - started) * 1000
            self.initialization_counts[route.model_id] = 1
        return self._engines[route.model_id]

    def recognize(self, image_path: Path, route: ModelRoute) -> tuple[OCRRegion, ...]:
        if not image_path.is_file():
            raise OCRRuntimeError(f"Image does not exist: {image_path}")
        engine = self._engine(route)
        try:
            result = engine(str(image_path), use_det=True, use_cls=True, use_rec=True)
        except Exception as exc:
            raise OCRRuntimeError(f"RapidOCR failed for {image_path.name}: {exc}") from exc

        boxes = getattr(result, "boxes", None)
        texts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is None:
            return ()
        if texts is None or scores is None or not (len(boxes) == len(texts) == len(scores)):
            raise OCRRuntimeError("RapidOCR returned inconsistent boxes, texts, and scores")

        regions = []
        for box, text, score in zip(boxes, texts, scores, strict=True):
            confidence = float(score)
            observed_scripts = scripts_in_text(str(text))
            status = "ok"
            if confidence < self.confidence_threshold:
                status = "low_confidence"
            elif observed_scripts and not observed_scripts.intersection(route.scripts):
                status = "script_mismatch"
            regions.append(
                OCRRegion(
                    polygon=order_quad(box),
                    text=str(text),
                    confidence=confidence,
                    language_code=route.language_code,
                    language_confidence=1.0,
                    model_id=route.model_id or "unsupported",
                    status=status,
                )
            )
        return tuple(regions)


class FixtureAdapter:
    def __init__(self) -> None:
        self.load_times_ms: dict[str, float] = {}
        self.initialization_counts: dict[str, int] = {}

    def recognize(self, sample: ManifestSample, route: ModelRoute) -> tuple[OCRRegion, ...]:
        if not route.supported or route.model_id is None:
            raise RoutingError(route.reason or f"Unsupported OCR language: {route.language_code}")
        self.initialization_counts[route.model_id] = 1
        self.load_times_ms.setdefault(route.model_id, 0.0)
        return sample.fixture_regions


def scripts_in_text(text: str) -> set[str]:
    scripts: set[str] = set()
    for character in text:
        codepoint = ord(character)
        name = unicodedata.name(character, "")
        if 0x4E00 <= codepoint <= 0x9FFF:
            scripts.add("Han")
        elif 0x3040 <= codepoint <= 0x30FF:
            scripts.add("Japanese")
        elif 0xAC00 <= codepoint <= 0xD7AF:
            scripts.add("Hangul")
        elif 0x0600 <= codepoint <= 0x06FF:
            scripts.add("Arabic")
        elif 0x0900 <= codepoint <= 0x097F:
            scripts.add("Devanagari")
        elif 0x0980 <= codepoint <= 0x09FF:
            scripts.add("Bengali")
        elif 0x0E00 <= codepoint <= 0x0E7F:
            scripts.add("Thai")
        elif "CYRILLIC" in name:
            scripts.add("Cyrillic")
        elif "LATIN" in name:
            scripts.add("Latin")
    return scripts

