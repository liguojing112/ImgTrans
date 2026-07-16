from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from server import __version__
from server.api.contracts import HealthResponse, ServiceInfoResponse


health_router = APIRouter(prefix="/health", tags=["health"])
v1_router = APIRouter(prefix="/v1", tags=["client"])


@health_router.get("/live", response_model=HealthResponse)
def live() -> HealthResponse:
    return HealthResponse(status="ok")


@health_router.get(
    "/ready",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
def ready(request: Request, response: Response) -> HealthResponse:
    try:
        available = request.app.state.database.probe()
    except Exception:
        available = False
    if not available:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="unavailable")
    return HealthResponse(status="ok")


@v1_router.get("/service-info", response_model=ServiceInfoResponse)
def service_info(request: Request) -> ServiceInfoResponse:
    return ServiceInfoResponse(
        service="imgtrans-server",
        service_version=__version__,
        api_version="v1",
        environment=request.app.state.settings.environment,
    )
