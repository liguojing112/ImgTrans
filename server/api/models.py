from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import Field

from server.api.contracts import StrictContract
from server.api.auth import require_admin, require_client
from server.api.rate_limit import enforce_rate_limit
from server.domain.models import (
    ModelRelease,
    ModelReleaseConflict,
    ModelReleaseError,
    ModelReleaseNotFound,
    ModelReleaseSpec,
    SUPPORTED_MODEL_TARGETS,
)
from server.infrastructure.object_storage import ObjectStorageUnavailable


class ModelReleasePayload(StrictContract):
    model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    platform: Literal["windows", "macos"]
    architecture: Literal["x86_64", "arm64"]
    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    object_key: str = Field(min_length=1, max_length=512)
    object_version: str = Field(min_length=1, max_length=256)
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def to_domain(self) -> ModelReleaseSpec:
        return ModelReleaseSpec(**self.model_dump())


class ModelReleaseResponse(ModelReleasePayload):
    release_id: int
    status: Literal["draft", "published", "withdrawn"]
    created_at: datetime
    published_at: datetime | None
    withdrawn_at: datetime | None


class ModelReleaseListResponse(StrictContract):
    releases: tuple[ModelReleaseResponse, ...]


class ModelManifestItemResponse(StrictContract):
    model_id: str
    version: str
    platform: Literal["windows", "macos"]
    architecture: Literal["x86_64", "arm64"]
    filename: str
    object_version: str
    size_bytes: int
    sha256: str
    download_url: str
    download_url_expires_at: datetime


class ModelManifestResponse(StrictContract):
    schema_version: Literal[1]
    models: tuple[ModelManifestItemResponse, ...]


model_manifest_router = APIRouter(prefix="/v1", tags=["models"])
admin_models_router = APIRouter(prefix="/v1/admin/models", tags=["admin-models"])


@model_manifest_router.get("/models/manifest", response_model=ModelManifestResponse)
def get_manifest(
    request: Request,
    response: Response,
    platform: Literal["windows", "macos"] = Query(),
    architecture: Literal["x86_64", "arm64"] = Query(),
) -> ModelManifestResponse:
    enforce_rate_limit(request, "model-manifest", limit=120, window_seconds=60)
    require_client(request, "Model delivery is not enabled")
    if (platform, architecture) not in SUPPORTED_MODEL_TARGETS:
        raise HTTPException(status_code=422, detail="Unsupported model target")
    try:
        items = request.app.state.get_model_manifest.execute(platform, architecture)
    except ObjectStorageUnavailable as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model delivery is unavailable",
        ) from error
    response.headers["Cache-Control"] = "private, no-store"
    return ModelManifestResponse(
        schema_version=1,
        models=tuple(
            ModelManifestItemResponse(
                **_manifest_spec_dict(item.release),
                download_url=item.download_url,
                download_url_expires_at=item.download_url_expires_at,
            )
            for item in items
        ),
    )


@admin_models_router.post(
    "/releases",
    response_model=ModelReleaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_release(payload: ModelReleasePayload, request: Request) -> ModelReleaseResponse:
    require_admin(request)
    try:
        result = request.app.state.manage_model_releases.create(payload.to_domain())
    except ModelReleaseError as error:
        raise _domain_http_error(error) from error
    return _release_response(result)


@admin_models_router.post(
    "/releases/{release_id}/publish", response_model=ModelReleaseResponse
)
def publish_release(release_id: int, request: Request) -> ModelReleaseResponse:
    require_admin(request)
    try:
        result = request.app.state.manage_model_releases.publish(release_id)
    except ModelReleaseError as error:
        raise _domain_http_error(error) from error
    return _release_response(result)


@admin_models_router.post(
    "/releases/{release_id}/withdraw", response_model=ModelReleaseResponse
)
def withdraw_release(release_id: int, request: Request) -> ModelReleaseResponse:
    require_admin(request)
    try:
        result = request.app.state.manage_model_releases.withdraw(release_id)
    except ModelReleaseError as error:
        raise _domain_http_error(error) from error
    return _release_response(result)


@admin_models_router.get("/releases", response_model=ModelReleaseListResponse)
def list_releases(request: Request) -> ModelReleaseListResponse:
    require_admin(request)
    return ModelReleaseListResponse(
        releases=tuple(
            _release_response(release)
            for release in request.app.state.manage_model_releases.list_all()
        )
    )


def _domain_http_error(error: ModelReleaseError) -> HTTPException:
    if isinstance(error, ModelReleaseNotFound):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, ModelReleaseConflict):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


def _release_response(release: ModelRelease) -> ModelReleaseResponse:
    return ModelReleaseResponse(
        release_id=release.release_id,
        status=release.status.value,
        created_at=release.created_at,
        published_at=release.published_at,
        withdrawn_at=release.withdrawn_at,
        **_spec_dict(release),
    )


def _spec_dict(release: ModelRelease) -> dict[str, object]:
    spec = release.spec
    return {
        "model_id": spec.model_id,
        "version": spec.version,
        "platform": spec.platform,
        "architecture": spec.architecture,
        "filename": spec.filename,
        "object_key": spec.object_key,
        "object_version": spec.object_version,
        "size_bytes": spec.size_bytes,
        "sha256": spec.sha256,
    }


def _manifest_spec_dict(release: ModelRelease) -> dict[str, object]:
    values = _spec_dict(release)
    values.pop("object_key")
    return values
