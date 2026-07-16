from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import re


class ModelReleaseError(ValueError):
    pass


class ModelReleaseNotFound(ModelReleaseError):
    pass


class ModelReleaseConflict(ModelReleaseError):
    pass


class ModelReleaseStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"


SUPPORTED_MODEL_TARGETS = {
    ("windows", "x86_64"),
    ("macos", "arm64"),
}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ModelReleaseSpec:
    model_id: str
    version: str
    platform: str
    architecture: str
    filename: str
    object_key: str
    object_version: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.model_id, "model_id"),
            (self.version, "version"),
            (self.filename, "filename"),
        ):
            if not _SAFE_NAME.fullmatch(value):
                raise ModelReleaseError(f"Invalid {label}")
        if (
            not self.object_version
            or len(self.object_version) > 256
            or any(ord(character) < 32 for character in self.object_version)
        ):
            raise ModelReleaseError("Invalid object_version")
        if (self.platform, self.architecture) not in SUPPORTED_MODEL_TARGETS:
            raise ModelReleaseError("Unsupported model platform and architecture")
        if (
            not self.object_key
            or self.object_key.startswith("/")
            or ".." in self.object_key.split("/")
            or any(ord(character) < 32 for character in self.object_key)
        ):
            raise ModelReleaseError("Invalid object_key")
        if self.size_bytes <= 0:
            raise ModelReleaseError("Model size must be positive")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ModelReleaseError("Model SHA-256 must be lowercase hexadecimal")


@dataclass(frozen=True, slots=True)
class ModelRelease:
    release_id: int
    spec: ModelReleaseSpec
    status: ModelReleaseStatus
    created_at: datetime
    published_at: datetime | None = None
    withdrawn_at: datetime | None = None
