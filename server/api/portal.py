from __future__ import annotations

from fastapi import APIRouter, Request, Response

from server.api.contracts import StrictContract
from server.api.rate_limit import enforce_rate_limit


class PortalModulePayload(StrictContract):
    module_key: str
    title: str
    description: str
    image_url: str
    link_url: str


class PortalModulesResponse(StrictContract):
    modules: tuple[PortalModulePayload, ...]


portal_router = APIRouter(prefix="/v1", tags=["portal"])


@portal_router.get("/portal-modules", response_model=PortalModulesResponse)
def list_portal_modules(
    request: Request, response: Response
) -> PortalModulesResponse:
    enforce_rate_limit(request, "portal-modules", limit=120, window_seconds=60)
    modules = request.app.state.portal_repository.list_enabled()
    response.headers["Cache-Control"] = "public, max-age=300"
    return PortalModulesResponse(
        modules=tuple(
            PortalModulePayload(
                module_key=module.module_key,
                title=module.title,
                description=module.description,
                image_url=module.image_url,
                link_url=module.link_url,
            )
            for module in modules
        )
    )
