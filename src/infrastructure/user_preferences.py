from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from src.domain.protection import normalize_brand_terms


_MAX_PREFERENCES_BYTES = 64 * 1024


class UserPreferencesError(RuntimeError):
    pass


class JsonBrandTermsPreferences:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> tuple[str, ...]:
        if not self._path.is_file():
            return ()
        try:
            if self._path.stat().st_size > _MAX_PREFERENCES_BYTES:
                raise UserPreferencesError("User preferences file is too large")
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != 1:
                raise UserPreferencesError("Unsupported user preferences schema")
            brand_terms = payload.get("brand_terms")
            if not isinstance(brand_terms, list) or not all(
                isinstance(term, str) for term in brand_terms
            ):
                raise UserPreferencesError("Invalid brand terms preferences")
            return normalize_brand_terms(brand_terms)
        except UserPreferencesError:
            raise
        except (OSError, ValueError, TypeError, AttributeError) as error:
            raise UserPreferencesError("Unable to load user preferences") from error

    def save(self, brand_terms: tuple[str, ...]) -> None:
        payload = {
            "schema_version": 1,
            "brand_terms": list(normalize_brand_terms(brand_terms)),
        }
        encoded = json.dumps(
            payload,
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
