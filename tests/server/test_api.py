import asyncio

import httpx

from server.app import create_app
from server.config import ServerSettings


def _request(app, method: str, path: str, **kwargs) -> httpx.Response:
    async def execute() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(execute())


def test_health_and_service_contracts_are_versioned() -> None:
    app = create_app(ServerSettings(environment="test"))
    live = _request(app, "GET", "/health/live")
    ready = _request(app, "GET", "/health/ready")
    info = _request(app, "GET", "/v1/service-info")
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok"}
    assert info.status_code == 200
    assert info.json() == {
        "service": "imgtrans-server",
        "service_version": "0.1.0",
        "api_version": "v1",
        "environment": "test",
    }
    app.state.database.close()


def test_correlation_id_is_preserved_or_safely_replaced() -> None:
    app = create_app(ServerSettings(environment="test"))
    accepted = _request(
        app,
        "GET",
        "/health/live",
        headers={"X-Correlation-ID": "batch_7.image-2"},
    )
    rejected = _request(
        app,
        "GET",
        "/health/live",
        headers={"X-Correlation-ID": "invalid header\r\nvalue"},
    )
    assert accepted.headers["X-Correlation-ID"] == "batch_7.image-2"
    assert rejected.headers["X-Correlation-ID"] != "invalid header\r\nvalue"
    assert len(rejected.headers["X-Correlation-ID"]) == 32
    app.state.database.close()


def test_error_contract_contains_correlation_id_without_request_content() -> None:
    app = create_app(ServerSettings(environment="test"))
    response = _request(
        app,
        "GET",
        "/missing?text=private-product-copy",
        headers={"X-Correlation-ID": "request-123"},
    )
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "http_error",
            "message": "Not Found",
            "correlation_id": "request-123",
        }
    }
    assert "private-product-copy" not in response.text
    assert response.headers["X-Correlation-ID"] == "request-123"
    app.state.database.close()


class _UnavailableDatabase:
    def probe(self) -> bool:
        return False

    def close(self) -> None:
        pass


def test_readiness_reports_dependency_failure_without_failing_liveness() -> None:
    app = create_app(
        ServerSettings(environment="test"),
        database=_UnavailableDatabase(),
    )
    assert _request(app, "GET", "/health/live").status_code == 200
    ready = _request(app, "GET", "/health/ready")
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable"}
