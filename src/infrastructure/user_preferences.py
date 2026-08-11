from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from src.domain.protection import normalize_brand_terms
from src.domain.terminology import (
    TerminologyEntry,
    normalize_terminology_entries,
)


_MAX_PREFERENCES_BYTES = 64 * 1024
_CURRENT_SCHEMA_VERSION = 1
_KNOWN_FIELDS = {
    "brand_terms",
    "model_terms",
    "terminology_entries",
    "copywriting_settings",
    "ecommerce_terms",
    "ecommerce_llm_prompt",
}


class UserPreferencesError(RuntimeError):
    pass


class _JsonPreferencesFile:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict:
        if not self._path.is_file():
            return {"schema_version": _CURRENT_SCHEMA_VERSION}
        try:
            if self._path.stat().st_size > _MAX_PREFERENCES_BYTES:
                return self._recover_corrupt()
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise UserPreferencesError("Unable to read user preferences") from error
        except (ValueError, TypeError, AttributeError):
            return self._recover_corrupt()
        if not isinstance(payload, dict):
            return self._recover_corrupt()
        version = payload.get("schema_version")
        if version is not None and type(version) is not int:
            return self._recover_corrupt()
        if (version is None or version == 0) and set(payload).difference(
            {"schema_version", *_KNOWN_FIELDS}
        ) == set():
            migrated = {**payload, "schema_version": _CURRENT_SCHEMA_VERSION}
            try:
                self._validate(migrated)
            except (KeyError, TypeError, ValueError, AttributeError):
                return self._recover_corrupt()
            self.save(migrated)
            return migrated
        if version != _CURRENT_SCHEMA_VERSION:
            if isinstance(version, int) and version > _CURRENT_SCHEMA_VERSION:
                raise UserPreferencesError("Unsupported newer user preferences schema")
            return self._recover_corrupt()
        try:
            self._validate(payload)
        except (KeyError, TypeError, ValueError, AttributeError):
            return self._recover_corrupt()
        return payload

    def save(self, payload: dict) -> None:
        encoded = json.dumps(
            {**payload, "schema_version": 1},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_PREFERENCES_BYTES:
            raise UserPreferencesError("User preferences are too large")
        temporary = self._path.with_name(f".{self._path.name}.{uuid4().hex}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        except OSError as error:
            raise UserPreferencesError("Unable to save user preferences") from error
        finally:
            temporary.unlink(missing_ok=True)

    def _recover_corrupt(self) -> dict:
        backup = self._path.with_name(
            f"{self._path.name}.corrupt-{uuid4().hex}.bak"
        )
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(self._path, backup)
            payload = {"schema_version": _CURRENT_SCHEMA_VERSION}
            self.save(payload)
            return payload
        except OSError as error:
            raise UserPreferencesError(
                "Unable to preserve and recover corrupt user preferences"
            ) from error

    @staticmethod
    def _validate(payload: dict) -> None:
        brand_terms = payload.get("brand_terms", [])
        if not isinstance(brand_terms, list) or not all(
            isinstance(term, str) for term in brand_terms
        ):
            raise ValueError("Invalid brand terms preferences")
        model_terms = payload.get("model_terms", [])
        if not isinstance(model_terms, list) or not all(
            isinstance(term, str) for term in model_terms
        ):
            raise ValueError("Invalid model terms preferences")
        terminology = payload.get("terminology_entries", [])
        if not isinstance(terminology, list):
            raise ValueError("Invalid terminology preferences")
        for value in terminology:
            if not isinstance(value, dict) or not isinstance(
                value.get("enabled"), bool
            ):
                raise ValueError("Invalid terminology preferences")
            TerminologyEntry(
                source_language=value["source_language"],
                target_language=value["target_language"],
                source_text=value["source_text"],
                target_text=value["target_text"],
                enabled=value["enabled"],
            )


class JsonBrandTermsPreferences:
    def __init__(self, path: Path) -> None:
        self._file = _JsonPreferencesFile(path)

    def load(self) -> tuple[str, ...]:
        brand_terms = self._file.load().get("brand_terms", [])
        if not isinstance(brand_terms, list) or not all(
            isinstance(term, str) for term in brand_terms
        ):
            raise UserPreferencesError("Invalid brand terms preferences")
        return normalize_brand_terms(brand_terms)

    def save(self, brand_terms: tuple[str, ...]) -> None:
        payload = self._file.load()
        payload["brand_terms"] = list(normalize_brand_terms(brand_terms))
        self._file.save(payload)


class JsonModelTermsPreferences:
    def __init__(self, path: Path) -> None:
        self._file = _JsonPreferencesFile(path)

    def load(self) -> tuple[str, ...]:
        values = self._file.load().get("model_terms", [])
        if not isinstance(values, list) or not all(
            isinstance(term, str) for term in values
        ):
            raise UserPreferencesError("Invalid model terms preferences")
        return normalize_brand_terms(values)

    def save(self, model_terms: tuple[str, ...]) -> None:
        payload = self._file.load()
        payload["model_terms"] = list(normalize_brand_terms(model_terms))
        self._file.save(payload)


class JsonTerminologyPreferences:
    def __init__(self, path: Path) -> None:
        self._file = _JsonPreferencesFile(path)

    def load(self) -> tuple[TerminologyEntry, ...]:
        values = self._file.load().get("terminology_entries", [])
        if not isinstance(values, list):
            raise UserPreferencesError("Invalid terminology preferences")
        entries = []
        try:
            for value in values:
                if not isinstance(value, dict) or not isinstance(
                    value.get("enabled"), bool
                ):
                    raise ValueError
                entries.append(
                    TerminologyEntry(
                        source_language=value["source_language"],
                        target_language=value["target_language"],
                        source_text=value["source_text"],
                        target_text=value["target_text"],
                        enabled=value["enabled"],
                    )
                )
        except (KeyError, TypeError, ValueError):
            raise UserPreferencesError("Invalid terminology preferences") from None
        return normalize_terminology_entries(entries)

    def save(self, entries: tuple[TerminologyEntry, ...]) -> None:
        normalized = normalize_terminology_entries(entries)
        payload = self._file.load()
        payload["terminology_entries"] = [
            {
                "source_language": entry.source_language,
                "target_language": entry.target_language,
                "source_text": entry.source_text,
                "target_text": entry.target_text,
                "enabled": entry.enabled,
            }
            for entry in normalized
        ]
        self._file.save(payload)


class JsonCopywritingPreferences:
    """商品详情生成的习惯设置（目标语言/平台/风格/语气等）。"""

    _ALLOWED = {
        "target_language",
        "target_country",
        "platform",
        "style",
        "tone",
        "tag_count",
        "keyword_count",
        "title_count",
        "title_max_chars",
        "keep_brand",
        "keep_model",
        "banned_words",
        "custom_keywords",
        "custom_requirements",
    }

    def __init__(self, path: Path) -> None:
        self._file = _JsonPreferencesFile(path)

    def load(self) -> dict:
        values = self._file.load().get("copywriting_settings", {})
        if not isinstance(values, dict):
            return {}
        return {k: v for k, v in values.items() if k in self._ALLOWED}

    def save(self, settings: dict) -> None:
        filtered = {k: v for k, v in settings.items() if k in self._ALLOWED}
        payload = self._file.load()
        payload["copywriting_settings"] = filtered
        self._file.save(payload)


class JsonEcommercePreferences:
    """电商翻译的用户配置：词库覆盖（中文→英文）与 LLM 提示词覆盖。

    词库只保存用户自定义/覆盖的条目，内置词库作为默认兜底；提示词为空时
    使用内置提示词模板。
    """

    def __init__(self, path: Path) -> None:
        self._file = _JsonPreferencesFile(path)

    def load(self) -> tuple[dict[str, str], str | None]:
        payload = self._file.load()
        terms = payload.get("ecommerce_terms", {})
        if not isinstance(terms, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in terms.items()
        ):
            terms = {}
        prompt = payload.get("ecommerce_llm_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            prompt = None
        return {
            key.strip(): value.strip()
            for key, value in terms.items()
            if key.strip() and value.strip()
        }, prompt

    def save(self, terms: dict[str, str], prompt: str | None) -> None:
        normalized = {
            key.strip(): value.strip()
            for key, value in terms.items()
            if key.strip() and value.strip()
        }
        normalized_prompt = prompt.strip() if prompt and prompt.strip() else None
        payload = self._file.load()
        payload["ecommerce_terms"] = normalized
        payload["ecommerce_llm_prompt"] = normalized_prompt
        self._file.save(payload)
