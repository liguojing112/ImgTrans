from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4
import json
import os
import shutil

from src.domain.models import InstalledModel, ModelDeliveryError, ModelManifestEntry
from src.platform.storage import StorageGuard, StorageUnavailableError


_MAX_MANIFEST_BYTES = 256 * 1024
_CHUNK_SIZE = 1024 * 1024
TokenSource = str | Callable[[], str | None]


class HttpModelManifestClient:
    def __init__(self, base_url: str, api_token: TokenSource, timeout_seconds: float = 10.0) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Backend URL must use HTTP or HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Backend URL cannot contain credentials, query or fragment")
        if isinstance(api_token, str) and not api_token:
            raise ValueError("API token is required")
        if not isinstance(api_token, str) and not callable(api_token):
            raise TypeError("API token must be a string or callable")
        if timeout_seconds <= 0:
            raise ValueError("Positive timeout is required")
        self._base_url = base_url.rstrip("/")
        self._token_source = api_token
        self._timeout_seconds = timeout_seconds

    def fetch(self, platform: str, architecture: str) -> tuple[ModelManifestEntry, ...]:
        api_token = self._resolve_token()
        query = urlencode({"platform": platform, "architecture": architecture})
        request = Request(
            f"{self._base_url}/v1/models/manifest?{query}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_token}",
                "User-Agent": "ImgTrans/0.1",
                "X-Correlation-ID": uuid4().hex,
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                encoded = response.read(_MAX_MANIFEST_BYTES + 1)
        except HTTPError as error:
            raise ModelDeliveryError(f"模型清单服务返回 HTTP {error.code}") from error
        except (URLError, OSError) as error:
            raise ModelDeliveryError("无法连接模型清单服务") from error
        if len(encoded) > _MAX_MANIFEST_BYTES:
            raise ModelDeliveryError("模型清单响应过大")
        try:
            payload = json.loads(encoded.decode("utf-8"))
            return _parse_manifest(payload, platform, architecture)
        except (UnicodeDecodeError, ValueError, TypeError, KeyError) as error:
            raise ModelDeliveryError("模型清单响应无效") from error

    def _resolve_token(self) -> str:
        value = (
            self._token_source()
            if callable(self._token_source)
            else self._token_source
        )
        if not isinstance(value, str) or len(value) < 16:
            raise ModelDeliveryError("请先激活应用后再检查模型更新")
        return value


class HttpRangeModelDownloader:
    def __init__(
        self,
        timeout_seconds: float = 30.0,
        storage_guard: StorageGuard | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Timeout must be positive")
        self._timeout_seconds = timeout_seconds
        self._storage_guard = storage_guard or StorageGuard()

    def download(
        self,
        entry: ModelManifestEntry,
        part_path: Path,
        state_path: Path,
        cancelled: Callable[[], bool],
    ) -> Path:
        try:
            existing_size = _trusted_resume_size(entry, part_path, state_path)
            self._storage_guard.ensure_available(
                part_path.parent,
                required_bytes=max(0, entry.size_bytes - existing_size),
                reserve_bytes=64 * 1024 * 1024,
            )
            return self._download(entry, part_path, state_path, cancelled)
        except StorageUnavailableError as error:
            raise ModelDeliveryError(str(error)) from error
        except OSError as error:
            raise ModelDeliveryError(
                "模型下载缓存不可用，请检查磁盘空间和目录权限"
            ) from error

    def _download(
        self,
        entry: ModelManifestEntry,
        part_path: Path,
        state_path: Path,
        cancelled: Callable[[], bool],
    ) -> Path:
        part_path.parent.mkdir(parents=True, exist_ok=True)
        state = _resume_identity(entry)
        saved = _load_json(state_path)
        if saved is not None and set(saved) - (set(state) | {"etag"}):
            saved = None
        if saved is not None and any(saved.get(key) != value for key, value in state.items()):
            part_path.unlink(missing_ok=True)
            state_path.unlink(missing_ok=True)
            saved = None
        if saved is None:
            part_path.unlink(missing_ok=True)
            _atomic_json(state_path, state)
            saved = state
        if not part_path.exists():
            part_path.touch()
        if part_path.stat().st_size > entry.size_bytes:
            part_path.unlink()
            part_path.touch()
        if part_path.stat().st_size == entry.size_bytes:
            return part_path
        return self._transfer(entry, part_path, state_path, saved, cancelled, True)

    def _transfer(
        self,
        entry: ModelManifestEntry,
        part_path: Path,
        state_path: Path,
        state: dict[str, object],
        cancelled: Callable[[], bool],
        allow_restart: bool,
    ) -> Path:
        offset = part_path.stat().st_size
        headers = {"User-Agent": "ImgTrans/0.1", "Accept": "application/octet-stream"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
            if state.get("etag"):
                headers["If-Range"] = str(state["etag"])
        request = Request(entry.download_url, headers=headers, method="GET")
        try:
            response = urlopen(request, timeout=self._timeout_seconds)
        except (HTTPError, URLError, OSError) as error:
            raise ModelDeliveryError("模型下载暂时中断，可稍后续传") from error
        with response:
            status_code = getattr(response, "status", response.getcode())
            response_etag = response.headers.get("ETag")
            if offset and status_code == 200:
                part_path.write_bytes(b"")
                offset = 0
            elif offset and status_code == 206:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {offset}-"):
                    raise ModelDeliveryError("服务端返回了无效的续传范围")
                if state.get("etag") and response_etag and state["etag"] != response_etag:
                    if not allow_restart:
                        raise ModelDeliveryError("远端模型在下载期间发生变化")
                    part_path.unlink(missing_ok=True)
                    state_path.unlink(missing_ok=True)
                    _atomic_json(state_path, _resume_identity(entry))
                    part_path.touch()
                    return self._transfer(
                        entry,
                        part_path,
                        state_path,
                        _resume_identity(entry),
                        cancelled,
                        False,
                    )
            elif status_code != 200:
                raise ModelDeliveryError("模型下载服务响应无效")
            if response_etag:
                state = {**state, "etag": response_etag}
                _atomic_json(state_path, state)
            mode = "ab" if offset else "wb"
            try:
                with part_path.open(mode) as output:
                    while True:
                        if cancelled():
                            raise ModelDeliveryError("模型更新已取消")
                        chunk = response.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        output.write(chunk)
                        if output.tell() > entry.size_bytes:
                            raise ModelDeliveryError("模型下载超过清单声明大小")
                    output.flush()
                    os.fsync(output.fileno())
            except OSError as error:
                raise ModelDeliveryError("模型下载写入失败，请检查磁盘空间") from error
        if part_path.stat().st_size != entry.size_bytes:
            raise ModelDeliveryError("模型下载未完成，可稍后续传")
        return part_path


class FileModelRepository:
    def __init__(
        self,
        root: Path,
        storage_guard: StorageGuard | None = None,
    ) -> None:
        self._root = root
        self._storage_guard = storage_guard or StorageGuard()

    def active(self, model_id: str) -> InstalledModel | None:
        _validate_safe_name(model_id)
        pointer = self._root / model_id / "current.json"
        if not pointer.is_file():
            return None
        try:
            payload = json.loads(pointer.read_text(encoding="utf-8"))
            if set(payload) != {"schema_version", "model_id", "version", "object_version", "sha256", "size_bytes", "path"}:
                raise ValueError
            if payload["schema_version"] != 1 or payload["model_id"] != model_id:
                raise ValueError
            candidate = (self._root / payload["path"]).resolve()
            candidate.relative_to(self._root.resolve())
            if not candidate.is_file():
                return None
            return InstalledModel(
                model_id=model_id,
                version=payload["version"],
                object_version=payload["object_version"],
                sha256=payload["sha256"],
                size_bytes=payload["size_bytes"],
                path=str(candidate),
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def install(self, entry: ModelManifestEntry, verified_file: Path) -> InstalledModel:
        target_dir = self._root / entry.model_id / entry.version
        target = target_dir / entry.filename
        temporary = target_dir / f".{entry.filename}.{uuid4().hex}.tmp"
        pointer = self._root / entry.model_id / "current.json"
        try:
            self._storage_guard.ensure_available(
                target_dir,
                required_bytes=entry.size_bytes,
                reserve_bytes=64 * 1024 * 1024,
            )
            target_dir.mkdir(parents=True, exist_ok=True)
            with verified_file.open("rb") as source, temporary.open("wb") as output:
                shutil.copyfileobj(source, output, _CHUNK_SIZE)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            relative = target.relative_to(self._root).as_posix()
            _atomic_json(
                pointer,
                {
                    "schema_version": 1,
                    "model_id": entry.model_id,
                    "version": entry.version,
                    "object_version": entry.object_version,
                    "sha256": entry.sha256,
                    "size_bytes": entry.size_bytes,
                    "path": relative,
                },
            )
        except (OSError, StorageUnavailableError) as error:
            raise ModelDeliveryError("模型安装失败，请检查磁盘空间和目录权限") from error
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return InstalledModel(
            entry.model_id,
            entry.version,
            entry.object_version,
            entry.sha256,
            entry.size_bytes,
            str(target.resolve()),
        )


def _parse_manifest(
    payload: object, platform: str, architecture: str
) -> tuple[ModelManifestEntry, ...]:
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "models"}:
        raise ValueError
    if payload["schema_version"] != 1 or not isinstance(payload["models"], list):
        raise ValueError
    required = {
        "model_id", "version", "platform", "architecture", "filename",
        "object_version", "size_bytes", "sha256", "download_url",
        "download_url_expires_at",
    }
    entries: list[ModelManifestEntry] = []
    seen: set[str] = set()
    for item in payload["models"]:
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError
        if item["platform"] != platform or item["architecture"] != architecture:
            raise ValueError
        if item["model_id"] in seen:
            raise ValueError
        seen.add(item["model_id"])
        entries.append(
            ModelManifestEntry(
                **{key: value for key, value in item.items() if key != "download_url_expires_at"},
                download_url_expires_at=datetime.fromisoformat(
                    item["download_url_expires_at"].replace("Z", "+00:00")
                ),
            )
        )
    return tuple(entries)


def _resume_identity(entry: ModelManifestEntry) -> dict[str, object]:
    return {
        "schema_version": 1,
        "model_id": entry.model_id,
        "version": entry.version,
        "platform": entry.platform,
        "architecture": entry.architecture,
        "object_version": entry.object_version,
        "size_bytes": entry.size_bytes,
        "sha256": entry.sha256,
    }


def _trusted_resume_size(
    entry: ModelManifestEntry,
    part_path: Path,
    state_path: Path,
) -> int:
    if not part_path.is_file():
        return 0
    state = _resume_identity(entry)
    saved = _load_json(state_path)
    if saved is None or set(saved) - (set(state) | {"etag"}):
        return 0
    if any(saved.get(key) != value for key, value in state.items()):
        return 0
    size = part_path.stat().st_size
    return size if 0 <= size <= entry.size_bytes else 0


def _load_json(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        with temporary.open("wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_safe_name(value: str) -> None:
    if not value or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for character in value):
        raise ModelDeliveryError("模型标识不安全")
