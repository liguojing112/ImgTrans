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


class UserPreferencesError(RuntimeError):
    pass


class _JsonPreferencesFile:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict:
        if not self._path.is_file():
            return {"schema_version": 1}
        try:
            if self._path.stat().st_size > _MAX_PREFERENCES_BYTES:
                raise UserPreferencesError("User preferences file is too large")
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                raise UserPreferencesError("Unsupported user preferences schema")
            return payload
        except UserPreferencesError:
            raise
        except (OSError, ValueError, TypeError, AttributeError) as error:
            raise UserPreferencesError("Unable to load user preferences") from error

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
