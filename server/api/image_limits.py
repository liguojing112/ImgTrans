from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import Field, model_validator

from server.api.contracts import StrictContract
from server.api.auth import require_admin
from server.api.rate_limit import enforce_rate_limit
from server.domain.image_limits import (
    ImageLimitConflict,
    ImageLimitError,
    ImageLimitNotFound,
    ImageLimitValues,
    ImageLimitVersion,
)


class ImageLimitPayload(StrictContract):
    min_width: int = Field(gt=0)
    min_height: int = Field(gt=0)
    max_width: int = Field(gt=0)
    max_height: int = Field(gt=0)
    max_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "ImageLimitPayload":
        if self.min_width > self.max_width:
            raise ValueError("min_width cannot exceed max_width")
        if self.min_height > self.max_height:
            raise ValueError("min_height cannot exceed max_height")
        return self

    def to_domain(self) -> ImageLimitValues:
        return ImageLimitValues(**self.model_dump())


class ImageLimitVersionResponse(ImageLimitPayload):
    version: int
    status: Literal["draft", "published", "superseded"]
    created_at: datetime
    published_at: datetime | None
    source_version: int | None


class ImageLimitVersionListResponse(StrictContract):
    versions: tuple[ImageLimitVersionResponse, ...]


class ClientConfigResponse(StrictContract):
    schema_version: Literal[1]
    config_version: int
    cache_ttl_seconds: int
    image_limits: ImageLimitPayload


client_config_router = APIRouter(prefix="/v1", tags=["client-config"])
admin_image_limits_router = APIRouter(
    prefix="/v1/admin/image-limits",
    tags=["admin-image-limits"],
)


@client_config_router.get("/client-config", response_model=ClientConfigResponse)
def get_client_config(request: Request, response: Response) -> ClientConfigResponse:
    enforce_rate_limit(request, "client-config", limit=120, window_seconds=60)
    try:
        published, ttl = request.app.state.get_client_config.execute()
    except LookupError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Client configuration is not published",
        ) from error
    response.headers["Cache-Control"] = f"public, max-age={ttl}"
    response.headers["ETag"] = f'W/"image-limits-{published.version}"'
    return ClientConfigResponse(
        schema_version=1,
        config_version=published.version,
        cache_ttl_seconds=ttl,
        image_limits=ImageLimitPayload(**_values_dict(published.values)),
    )


@admin_image_limits_router.post(
    "/drafts",
    response_model=ImageLimitVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_draft(
    payload: ImageLimitPayload,
    request: Request,
) -> ImageLimitVersionResponse:
    require_admin(request)
    return _version_response(
        request.app.state.manage_image_limits.create_draft(payload.to_domain())
    )


@admin_image_limits_router.put(
    "/drafts/{version}",
    response_model=ImageLimitVersionResponse,
)
def update_draft(
    version: int,
    payload: ImageLimitPayload,
    request: Request,
) -> ImageLimitVersionResponse:
    require_admin(request)
    try:
        result = request.app.state.manage_image_limits.update_draft(
            version, payload.to_domain()
        )
    except (ImageLimitNotFound, ImageLimitConflict) as error:
        raise _domain_http_error(error) from error
    return _version_response(result)


@admin_image_limits_router.post(
    "/drafts/{version}/publish",
    response_model=ImageLimitVersionResponse,
)
def publish_draft(
    version: int,
    request: Request,
) -> ImageLimitVersionResponse:
    require_admin(request)
    try:
        result = request.app.state.manage_image_limits.publish(version)
    except (ImageLimitNotFound, ImageLimitConflict) as error:
        raise _domain_http_error(error) from error
    return _version_response(result)


@admin_image_limits_router.post(
    "/versions/{version}/rollback",
    response_model=ImageLimitVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def rollback_version(
    version: int,
    request: Request,
) -> ImageLimitVersionResponse:
    require_admin(request)
    try:
        result = request.app.state.manage_image_limits.rollback(version)
    except (ImageLimitNotFound, ImageLimitConflict) as error:
        raise _domain_http_error(error) from error
    return _version_response(result)


@admin_image_limits_router.get(
    "/versions",
    response_model=ImageLimitVersionListResponse,
)
def list_versions(
    request: Request,
) -> ImageLimitVersionListResponse:
    require_admin(request)
    return ImageLimitVersionListResponse(
        versions=tuple(
            _version_response(version)
            for version in request.app.state.manage_image_limits.list_versions()
        )
    )


def _domain_http_error(error: ImageLimitError) -> HTTPException:
    if isinstance(error, ImageLimitNotFound):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(status_code=409, detail=str(error))


def _version_response(version: ImageLimitVersion) -> ImageLimitVersionResponse:
    return ImageLimitVersionResponse(
        version=version.version,
        status=version.status.value,
        created_at=version.created_at,
        published_at=version.published_at,
        source_version=version.source_version,
        **_values_dict(version.values),
    )


def _values_dict(values: ImageLimitValues) -> dict[str, int]:
    return {
        "min_width": values.min_width,
        "min_height": values.min_height,
        "max_width": values.max_width,
        "max_height": values.max_height,
        "max_bytes": values.max_bytes,
    }
