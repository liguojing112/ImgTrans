from __future__ import annotations

from typing import Protocol

from server.domain.image_limits import ImageLimitValues, ImageLimitVersion


class ImageLimitRepository(Protocol):
    def create_draft(self, values: ImageLimitValues) -> ImageLimitVersion: ...

    def update_draft(
        self, version: int, values: ImageLimitValues
    ) -> ImageLimitVersion: ...

    def publish(self, version: int) -> ImageLimitVersion: ...

    def rollback(self, source_version: int) -> ImageLimitVersion: ...

    def get_published(self) -> ImageLimitVersion | None: ...

    def list_versions(self) -> tuple[ImageLimitVersion, ...]: ...


class ManageImageLimits:
    def __init__(self, repository: ImageLimitRepository) -> None:
        self._repository = repository

    def create_draft(self, values: ImageLimitValues) -> ImageLimitVersion:
        return self._repository.create_draft(values)

    def update_draft(
        self, version: int, values: ImageLimitValues
    ) -> ImageLimitVersion:
        return self._repository.update_draft(version, values)

    def publish(self, version: int) -> ImageLimitVersion:
        return self._repository.publish(version)

    def rollback(self, source_version: int) -> ImageLimitVersion:
        return self._repository.rollback(source_version)

    def list_versions(self) -> tuple[ImageLimitVersion, ...]:
        return self._repository.list_versions()


class GetClientConfig:
    def __init__(
        self,
        repository: ImageLimitRepository,
        cache_ttl_seconds: int,
    ) -> None:
        self._repository = repository
        self._cache_ttl_seconds = cache_ttl_seconds

    def execute(self) -> tuple[ImageLimitVersion, int]:
        published = self._repository.get_published()
        if published is None:
            raise LookupError("No image limit configuration is published")
        return published, self._cache_ttl_seconds
