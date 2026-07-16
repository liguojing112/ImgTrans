from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from server.app import create_app
from server.config import ServerSettings
from server.infrastructure.database import Base, Database
from server.infrastructure.object_storage import S3ObjectStorageSigner


ADMIN_TOKEN = "test-admin-token-123456"
CLIENT_TOKEN = "test-client-token-123456"
SHA256 = "a" * 64


class FakeSigner:
    def create_download_url(self, object_key: str):
        return (
            f"https://objects.example.invalid/download/{object_key}?signature=hidden",
            datetime.now(timezone.utc) + timedelta(minutes=10),
        )


def _app():
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    app = create_app(
        ServerSettings(
            environment="test",
            admin_token=ADMIN_TOKEN,
            client_api_token=CLIENT_TOKEN,
        ),
        database,
        object_storage_signer=FakeSigner(),
    )
    return app


def _request(app, method: str, path: str, **kwargs) -> httpx.Response:
    async def execute() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(execute())


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _client_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {CLIENT_TOKEN}"}


def _release(version: str = "1.0", platform: str = "windows", architecture: str = "x86_64"):
    return {
        "model_id": "lama-inpainting",
        "version": version,
        "platform": platform,
        "architecture": architecture,
        "filename": "lama.onnx",
        "object_key": f"models/lama/{platform}/{version}/lama.onnx",
        "object_version": f"object-{version}",
        "size_bytes": 1024,
        "sha256": SHA256,
    }


def test_only_latest_published_matching_release_appears_in_manifest() -> None:
    app = _app()
    try:
        draft = _request(
            app, "POST", "/v1/admin/models/releases",
            headers=_admin_headers(), json=_release("1.0"),
        ).json()
        empty = _request(
            app, "GET", "/v1/models/manifest?platform=windows&architecture=x86_64",
            headers=_client_headers(),
        )
        assert empty.json() == {"schema_version": 1, "models": []}

        _request(
            app, "POST", f"/v1/admin/models/releases/{draft['release_id']}/publish",
            headers=_admin_headers(),
        )
        newer = _request(
            app, "POST", "/v1/admin/models/releases",
            headers=_admin_headers(), json=_release("2.0"),
        ).json()
        _request(
            app, "POST", f"/v1/admin/models/releases/{newer['release_id']}/publish",
            headers=_admin_headers(),
        )
        mac = _request(
            app, "POST", "/v1/admin/models/releases",
            headers=_admin_headers(), json=_release("1.0", "macos", "arm64"),
        ).json()
        _request(
            app, "POST", f"/v1/admin/models/releases/{mac['release_id']}/publish",
            headers=_admin_headers(),
        )

        response = _request(
            app, "GET", "/v1/models/manifest?platform=windows&architecture=x86_64",
            headers=_client_headers(),
        )
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "private, no-store"
        models = response.json()["models"]
        assert len(models) == 1
        assert models[0]["version"] == "2.0"
        assert "object_key" not in models[0]
        assert models[0]["download_url"].startswith("https://objects.example.invalid/")
    finally:
        app.state.database.close()


def test_withdrawal_removes_release_and_invalid_target_is_rejected() -> None:
    app = _app()
    try:
        release = _request(
            app, "POST", "/v1/admin/models/releases",
            headers=_admin_headers(), json=_release(),
        ).json()
        _request(
            app, "POST", f"/v1/admin/models/releases/{release['release_id']}/publish",
            headers=_admin_headers(),
        )
        withdrawn = _request(
            app, "POST", f"/v1/admin/models/releases/{release['release_id']}/withdraw",
            headers=_admin_headers(),
        )
        assert withdrawn.json()["status"] == "withdrawn"
        manifest = _request(
            app, "GET", "/v1/models/manifest?platform=windows&architecture=x86_64",
            headers=_client_headers(),
        )
        assert manifest.json()["models"] == []
        invalid = _request(
            app, "POST", "/v1/admin/models/releases",
            headers=_admin_headers(), json=_release(platform="windows", architecture="arm64"),
        )
        assert invalid.status_code == 422
    finally:
        app.state.database.close()


def test_manifest_and_admin_routes_require_separate_tokens() -> None:
    app = _app()
    try:
        manifest = _request(
            app, "GET", "/v1/models/manifest?platform=windows&architecture=x86_64"
        )
        assert manifest.status_code == 401
        admin = _request(app, "GET", "/v1/admin/models/releases", headers=_client_headers())
        assert admin.status_code == 401
        assert CLIENT_TOKEN not in admin.text
    finally:
        app.state.database.close()


def test_s3_signer_uses_bucket_key_and_bounded_expiry() -> None:
    calls = []

    class Client:
        def generate_presigned_url(self, operation, **kwargs):
            calls.append((operation, kwargs))
            return "https://storage.example.invalid/signed"

    signer = S3ObjectStorageSigner(Client(), "model-bucket", 600)
    before = datetime.now(timezone.utc)
    url, expires_at = signer.create_download_url("models/lama.onnx")
    assert url.endswith("/signed")
    assert calls == [(
        "get_object",
        {"Params": {"Bucket": "model-bucket", "Key": "models/lama.onnx"}, "ExpiresIn": 600},
    )]
    assert before + timedelta(seconds=590) < expires_at < before + timedelta(seconds=610)

