from __future__ import annotations

import asyncio
import json
from unittest import mock

import httpx

from server.app import create_app
from server.config import ServerSettings
from server.infrastructure.database import Base, Database
from server.infrastructure.glm_gateway import GlmError, GlmGateway, GlmNotConfigured

CLIENT_TOKEN = "test-client-token-123456"


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, limit: int = -1) -> bytes:
        return self._payload if limit < 0 else self._payload[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_open(payload: bytes):
    def _open(request, timeout=None):
        return _FakeResponse(payload)

    return _open


def test_chat_returns_text() -> None:
    provider = lambda: {"api_key": "glm-key", "model": "glm-4v"}
    gateway = GlmGateway(provider)
    payload = json.dumps({"choices": [{"message": {"content": "你好"}}]}).encode("utf-8")
    with mock.patch("server.infrastructure.glm_gateway.urlopen", _fake_open(payload)):
        text = gateway.chat([{"role": "user", "content": "hi"}])
    assert text == "你好"


def test_chat_not_configured() -> None:
    gateway = GlmGateway(lambda: None)
    try:
        gateway.chat([{"role": "user", "content": "hi"}])
        raise AssertionError("expected GlmNotConfigured")
    except GlmNotConfigured:
        pass


def test_chat_retries_on_rate_limit() -> None:
    provider = lambda: {"api_key": "glm-key", "model": "glm-4.6v-flash"}
    gateway = GlmGateway(provider, max_attempts=3, sleeper=lambda seconds: None)
    rate_limited = json.dumps(
        {"error": {"code": "1305", "message": "访问量过大"}}
    ).encode("utf-8")
    ok = json.dumps({"choices": [{"message": {"content": "你好"}}]}).encode("utf-8")
    calls: list[int] = []

    def _open(request, timeout=None):
        calls.append(1)
        return _FakeResponse(rate_limited) if len(calls) == 1 else _FakeResponse(ok)

    with mock.patch("server.infrastructure.glm_gateway.urlopen", _open):
        text = gateway.chat([{"role": "user", "content": "hi"}])
    assert text == "你好"
    assert len(calls) == 2


def _app():
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    settings = ServerSettings(environment="test", client_api_token=CLIENT_TOKEN)
    return create_app(settings, database)


def test_llm_chat_unauthenticated() -> None:
    app = _app()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/llm/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )
            assert resp.status_code == 401

    asyncio.run(scenario())


def test_llm_chat_with_fake_gateway() -> None:
    app = _app()

    class FakeGateway:
        def chat(self, messages, model=None, max_tokens=None, temperature=None):
            assert messages[0]["content"] == "hi"
            return "生成的文案"

    app.state.glm_gateway = FakeGateway()

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/llm/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"Authorization": f"Bearer {CLIENT_TOKEN}"},
            )
            assert resp.status_code == 200
            assert resp.json()["text"] == "生成的文案"

    asyncio.run(scenario())


def test_llm_chat_unconfigured_gateway() -> None:
    app = _app()
    # 未配置 GLM key：真实网关但 provider 返回 None
    app.state.glm_gateway = GlmGateway(lambda: None)

    async def scenario():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/v1/llm/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"Authorization": f"Bearer {CLIENT_TOKEN}"},
            )
            assert resp.status_code == 503

    asyncio.run(scenario())
