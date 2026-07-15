from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json


LANGUAGE_CODES = (
    "zh-Hans",
    "zh-Hant",
    "ru",
    "ja",
    "ko",
    "en",
    "th",
    "ar",
    "vi",
    "it",
    "de",
    "id",
    "pt-PT",
    "fil",
    "pt-BR",
    "pl",
    "ms",
    "hi",
    "es",
    "fr",
    "bn",
    "ur",
    "tr",
    "fa",
    "sw",
)


class RoutingError(ValueError):
    pass


@dataclass(frozen=True)
class ModelRoute:
    language_code: str
    supported: bool
    model_id: str | None
    detector: dict[str, str]
    recognizer: dict[str, str] | None
    scripts: tuple[str, ...]
    reason: str | None = None

    def engine_params(self) -> dict[str, str]:
        if not self.supported or self.recognizer is None:
            raise RoutingError(self.reason or f"Unsupported OCR language: {self.language_code}")
        return {
            "Global.log_level": "critical",
            **{f"Det.{key}": value for key, value in self.detector.items()},
            **{f"Rec.{key}": value for key, value in self.recognizer.items()},
        }


class ModelRouter:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._config = json.loads(config_path.read_text(encoding="utf-8"))
        self._validate()

    def _validate(self) -> None:
        configured = set(self._config.get("languages", {}))
        expected = set(LANGUAGE_CODES)
        if configured != expected:
            missing = sorted(expected - configured)
            extra = sorted(configured - expected)
            raise RoutingError(f"Language coverage mismatch; missing={missing}, extra={extra}")

        profiles = self._config.get("profiles", {})
        for language_code, value in self._config["languages"].items():
            profile = value.get("profile")
            if profile is not None and profile not in profiles:
                raise RoutingError(f"Unknown profile {profile!r} for {language_code}")
            if profile is None and not value.get("reason"):
                raise RoutingError(f"Unsupported route {language_code} must include a reason")

    @property
    def version(self) -> str:
        return str(self._config["version"])

    def route(self, language_code: str) -> ModelRoute:
        try:
            value = self._config["languages"][language_code]
        except KeyError as exc:
            raise RoutingError(f"Language is outside the 25-language baseline: {language_code}") from exc
        profile_id = value.get("profile")
        profile: dict[str, Any] | None = self._config["profiles"].get(profile_id)
        return ModelRoute(
            language_code=language_code,
            supported=profile is not None,
            model_id=profile_id,
            detector=dict(self._config["detector"]),
            recognizer=dict(profile["recognizer"]) if profile else None,
            scripts=tuple(value["scripts"]),
            reason=str(value["reason"]) if value.get("reason") else None,
        )

    def coverage_matrix(self) -> list[dict[str, Any]]:
        return [
            {
                "language_code": language_code,
                "supported": (route := self.route(language_code)).supported,
                "model_id": route.model_id,
                "scripts": list(route.scripts),
                "reason": route.reason,
            }
            for language_code in LANGUAGE_CODES
        ]

