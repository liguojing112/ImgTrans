from __future__ import annotations

from fastapi import HTTPException, Request, status


def enforce_rate_limit(
    request: Request,
    scope: str,
    *,
    limit: int,
    window_seconds: int,
    identity: str | None = None,
) -> None:
    identity = identity or _request_identity(request)
    if not request.app.state.rate_limiter.allow(
        scope,
        identity,
        limit,
        window_seconds,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={"Retry-After": str(window_seconds)},
        )


def _request_identity(request: Request) -> str:
    client_host = request.client.host if request.client is not None else "unknown"
    authorization = request.headers.get("Authorization", "")
    return f"{client_host}:{authorization}"
