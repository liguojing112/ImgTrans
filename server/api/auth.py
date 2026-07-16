from __future__ import annotations

from secrets import compare_digest

from fastapi import HTTPException, Request, status
from server.api.rate_limit import enforce_rate_limit


def require_admin(request: Request) -> None:
    expected = request.app.state.settings.admin_token
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API is not configured",
        )
    token = _bearer_token(request)
    if token is None or not compare_digest(token, expected):
        raise _unauthorized("Administrator authorization failed")
    enforce_rate_limit(request, "admin-api", limit=120, window_seconds=60)
    request.state.admin_actor = "api-token"


def require_client(request: Request, unavailable_message: str) -> None:
    expected = request.app.state.settings.client_api_token
    device_enabled = request.app.state.device_authorization_enabled
    if expected is None and not device_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=unavailable_message,
        )
    token = _bearer_token(request)
    if token is None:
        raise _unauthorized("Client authorization failed")
    if expected is not None and compare_digest(token, expected):
        return
    if device_enabled and request.app.state.authorize_device_token.authorize(token):
        return
    raise _unauthorized("Client authorization failed")


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization")
    prefix = "Bearer "
    if authorization is None or not authorization.startswith(prefix):
        return None
    token = authorization[len(prefix) :]
    return token if token else None


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )
