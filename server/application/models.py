from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from server.domain.models import ModelRelease, ModelReleaseSpec


class ModelReleaseRepository(Protocol):
    def create(self, spec: ModelReleaseSpec) -> ModelRelease: ...

    def publish(self, release_id: int) -> ModelRelease: ...

    def withdraw(self, release_id: int) -> ModelRelease: ...

    def list_all(self) -> tuple[ModelRelease, ...]: ...

    def list_published(
        self, platform: str, architecture: str
    ) -> tuple[ModelRelease, ...]: ...


class ObjectStorageSigner(Protocol):
    def create_download_url(self, object_key: str) -> tuple[str, datetime]: ...


@dataclass(frozen=True, slots=True)
class ModelManifestItem:
    release: ModelRelease
    download_url: str
    download_url_expires_at: datetime


class ManageModelReleases:
    def __init__(self, repository: ModelReleaseRepository) -> None:
        self._repository = repository

    def create(self, spec: ModelReleaseSpec) -> ModelRelease:
        return self._repository.create(spec)

    def publish(self, release_id: int) -> ModelRelease:
        return self._repository.publish(release_id)

    def withdraw(self, release_id: int) -> ModelRelease:
        return self._repository.withdraw(release_id)

    def list_all(self) -> tuple[ModelRelease, ...]:
        return self._repository.list_all()


class GetModelManifest:
    def __init__(
        self,
        repository: ModelReleaseRepository,
        signer: ObjectStorageSigner,
    ) -> None:
        self._repository = repository
        self._signer = signer

    def execute(
        self, platform: str, architecture: str
    ) -> tuple[ModelManifestItem, ...]:
        return tuple(
            ModelManifestItem(release, *self._signer.create_download_url(release.spec.object_key))
            for release in self._repository.list_published(platform, architecture)
        )

