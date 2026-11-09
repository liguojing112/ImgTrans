"""门户入口配置客户端测试。"""

from __future__ import annotations

import json
from urllib.error import URLError

import pytest

from src.infrastructure.portal_config_client import (
    HttpPortalConfigClient,
    PortalConfigError,
    parse_portal_modules,
)


def test_parse_portal_modules_roundtrip() -> None:
    payload = json.dumps(
        {
            "modules": [
                {
                    "module_key": "wanxiang_note",
                    "title": "万象笔记",
                    "description": "记录图文灵感",
                    "image_url": "https://cdn.example.com/note.png",
                    "link_url": "https://note.example.com/app",
                }
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")

    modules = parse_portal_modules(payload)

    assert len(modules) == 1
    module = modules[0]
    assert module.module_key == "wanxiang_note"
    assert module.title == "万象笔记"
    assert module.description == "记录图文灵感"
    assert module.image_url == "https://cdn.example.com/note.png"
    assert module.link_url == "https://note.example.com/app"


def test_parse_portal_modules_accepts_optional_empty_fields() -> None:
    payload = json.dumps(
        {"modules": [{"module_key": "k", "title": "t", "image_url": ""}]}
    ).encode("utf-8")
    module = parse_portal_modules(payload)[0]
    assert module.description == ""
    assert module.link_url == ""


def test_parse_portal_modules_rejects_invalid_payloads() -> None:
    with pytest.raises(PortalConfigError):
        parse_portal_modules(b"not json")
    with pytest.raises(PortalConfigError):
        parse_portal_modules(json.dumps({"items": []}).encode("utf-8"))
    with pytest.raises(PortalConfigError):
        parse_portal_modules(json.dumps({"modules": [{"title": "t"}]}).encode("utf-8"))


def test_client_rejects_invalid_base_url() -> None:
    with pytest.raises(ValueError):
        HttpPortalConfigClient("ftp://example.com")
    with pytest.raises(ValueError):
        HttpPortalConfigClient("https://user:pass@example.com")


def test_client_fetch_surfaces_network_errors(monkeypatch) -> None:
    import src.infrastructure.portal_config_client as module

    def failing_urlopen(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr(module, "urlopen", failing_urlopen)
    client = HttpPortalConfigClient("https://example.com")
    with pytest.raises(PortalConfigError):
        client.fetch()
