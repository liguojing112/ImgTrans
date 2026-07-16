from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4
import json
import os
import time

from src.application.image_limits import (
    ImageLimitsCacheError,
    ImageLimitsRemoteError,
    ImageLimitsSnapshot,
)
from src.domain.image import ImageLimits


_MAX_CONFIG_BYTES = 64 * 1024


class JsonImageLimitsCache:
    def __init__(self, path: Path, max_pixels: int = 80_000_000) -> None:
        self._path = path
        self._max_pixels = max_pixels

    def load(self) -> ImageLimitsSnapshot | None:
        if not self._path.is_file():
            return None
        try:
            if self._path.stat().st_size > _MAX_CONFIG_BYTES:
                raise ImageLimitsCacheError("缓存文件超过安全大小")
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            return _snapshot_from_payload(payload, self._max_pixels, "cache")
        except ImageLimitsCacheError:
            raise
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise ImageLimitsCacheError("缓存文件无效") from error

    def save(self, snapshot: ImageLimitsSnapshot) -> None:
        payload = {
            "schema_version": 1,
            "config_version": snapshot.limits.config_version,
            "cache_ttl_seconds": snapshot.cache_ttl_seconds,
            "cached_at": int(time.time()),
            "image_limits": _limit_values(snapshot.limits),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_CONFIG_BYTES:
            raise ImageLimitsCacheError("配置超过缓存安全大小")
        temporary = self._path.with_name(f".{self._path.name}.{uuid4().hex}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        except OSError as error:
            raise ImageLimitsCacheError("无法原子保存图片限制缓存") from error
        finally:
            temporary.unlink(missing_ok=True)


class HttpImageLimitsClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 5.0,
        max_pixels: int = 80_000_000,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Backend URL must use HTTP or HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Backend URL cannot contain credentials, query or fragment")
        if timeout_seconds <= 0:
            raise ValueError("Timeout must be positive")
        self._url = f"{base_url.rstrip('/')}/v1/client-config"
        self._timeout_seconds = timeout_seconds
        self._max_pixels = max_pixels

    def fetch(self) -> ImageLimitsSnapshot:
        request = Request(
            self._url,
            headers={
                "Accept": "application/json",
                "User-Agent": "ImgTrans/0.1",
                "X-Correlation-ID": uuid4().hex,
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > _MAX_CONFIG_BYTES:
                    raise ImageLimitsRemoteError("远程配置响应过大")
                encoded = response.read(_MAX_CONFIG_BYTES + 1)
        except HTTPError as error:
            raise ImageLimitsRemoteError(
                f"远程配置服务返回 HTTP {error.code}"
            ) from error
        except (URLError, OSError, ValueError) as error:
            raise ImageLimitsRemoteError("无法连接远程配置服务") from error
        if len(encoded) > _MAX_CONFIG_BYTES:
            raise ImageLimitsRemoteError("远程配置响应过大")
        try:
            payload = json.loads(encoded.decode("utf-8"))
            return _snapshot_from_payload(payload, self._max_pixels, "remote")
        except (UnicodeDecodeError, ValueError, TypeError, KeyError) as error:
            raise ImageLimitsRemoteError("远程配置响应无效") from error


def _snapshot_from_payload(
    payload: object,
    max_pixels: int,
    source: str,
) -> ImageLimitsSnapshot:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Unsupported image limit schema")
    expected = {
        "schema_version",
        "config_version",
        "cache_ttl_seconds",
        "image_limits",
    }
    allowed = expected | {"cached_at"}
    if not expected.issubset(payload) or set(payload) - allowed:
        raise ValueError("Image limit payload fields are invalid")
    values = payload["image_limits"]
    if not isinstance(values, dict) or set(values) != {
        "min_width",
        "min_height",
        "max_width",
        "max_height",
        "max_bytes",
    }:
        raise ValueError("Image limit values are invalid")
    config_version = payload["config_version"]
    ttl = payload["cache_ttl_seconds"]
    if isinstance(config_version, bool) or not isinstance(config_version, int):
        raise ValueError("Config version must be an integer")
    if isinstance(ttl, bool) or not isinstance(ttl, int):
        raise ValueError("Cache TTL must be an integer")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values.values()):
        raise ValueError("Image limit values must be integers")
    limits = ImageLimits(
        **values,
        max_pixels=max_pixels,
        source=source,
        config_version=config_version,
    )
    return ImageLimitsSnapshot(limits, ttl)


def _limit_values(limits: ImageLimits) -> dict[str, int]:
    values = asdict(limits)
    return {
        key: values[key]
        for key in (
            "min_width",
            "min_height",
            "max_width",
            "max_height",
            "max_bytes",
        )
    }
