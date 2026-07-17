from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
import hashlib
import json
from pathlib import Path
import re
import tomllib

from scripts.build_desktop import TARGETS


_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_VERSION_ASSIGNMENT = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$', re.MULTILINE)
_TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".json",
    ".md",
    ".py",
    ".spec",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_SOURCE_LOCATIONS = (
    Path("src"),
    Path("server"),
    Path("scripts"),
    Path("packaging"),
    Path(".github/workflows"),
    Path("pyproject.toml"),
)
_FORBIDDEN_FILENAMES = {".env", "credentials.json", "service-account.json"}
_SECRET_ASSIGNMENT = re.compile(
    rb"(?i)(?:translator[_-]?key|api[_-]?key|secret[_-]?key|client[_-]?secret|"
    rb"access[_-]?token|password)\s*[\"\']?\s*[:=]\s*[\"\']"
    rb"[^\"\'\r\n]{16,}[\"\']"
)
_DATABASE_CREDENTIAL = re.compile(
    rb"(?i)(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^:/\s@]+:[^@\s/]+@"
)
_BEARER_LITERAL = re.compile(rb"(?i)bearer\s+[a-z0-9._~+/=-]{20,}")
_AWS_ACCESS_KEY = re.compile(rb"AKIA[A-Z0-9]{16}")
_PEM_PRIVATE_KEY = re.compile(
    rb"(?i)-----BEGIN (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----\r?\n"
    rb"[A-Z0-9+/=\r\n]{64,}"
    rb"-----END (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----"
)


def version_sources(root: Path) -> dict[str, str]:
    with (root / "pyproject.toml").open("rb") as stream:
        project_version = tomllib.load(stream)["project"]["version"]
    values = {
        "pyproject": str(project_version),
        "desktop": _module_version(root / "src" / "__init__.py"),
        "server": _module_version(root / "server" / "__init__.py"),
    }
    if len(set(values.values())) != 1:
        raise ValueError("release version sources do not match")
    version = next(iter(values.values()))
    if not _VERSION.fullmatch(version):
        raise ValueError("release version is not valid semantic version text")
    return values


def scan_secret_payload(data: bytes) -> tuple[str, ...]:
    if not _looks_textual(data):
        return ()
    findings = []
    if _PEM_PRIVATE_KEY.search(data):
        findings.append("private-key")
    if _AWS_ACCESS_KEY.search(data):
        findings.append("aws-access-key")
    if _DATABASE_CREDENTIAL.search(data):
        findings.append("database-credential")
    if _BEARER_LITERAL.search(data):
        findings.append("bearer-token")
    if _SECRET_ASSIGNMENT.search(data):
        findings.append("hardcoded-secret-assignment")
    return tuple(findings)


def _looks_textual(data: bytes) -> bool:
    sample = data[: 64 * 1024]
    if not sample:
        return True
    if b"\x00" in sample:
        return False
    printable = sum(
        byte in {9, 10, 13} or 32 <= byte <= 126
        for byte in sample
    )
    return printable / len(sample) >= 0.85


def scan_source_tree(root: Path) -> tuple[str, ...]:
    findings: list[str] = []
    for path in _source_files(root):
        relative = path.relative_to(root).as_posix()
        if path.name.casefold() in _FORBIDDEN_FILENAMES or path.suffix.casefold() in {
            ".key",
            ".pem",
            ".p12",
            ".pfx",
        }:
            findings.append(f"sensitive-file:{relative}")
            continue
        try:
            data = path.read_bytes()
        except OSError as error:
            findings.append(f"unreadable:{relative}:{type(error).__name__}")
            continue
        findings.extend(f"{label}:{relative}" for label in scan_secret_payload(data))
    return tuple(findings)


def build_release_manifest(
    root: Path,
    target: str,
    archive: Path,
) -> dict[str, object]:
    if target not in TARGETS:
        raise ValueError("unsupported release target")
    if not archive.is_file():
        raise ValueError("release archive is missing")
    version = next(iter(version_sources(root).values()))
    compatibility = {
        "windows-x64": {"os": "Windows", "minimum": "10", "architecture": "x86_64"},
        "macos-arm64": {"os": "macOS", "minimum": "13", "architecture": "arm64"},
    }[target]
    return {
        "schema_version": 1,
        "product": "imgtrans",
        "version": version,
        "target": target,
        "compatibility": compatibility,
        "archive": {
            "file": archive.name,
            "size": archive.stat().st_size,
            "sha256": _sha256(archive),
        },
        "models": {
            "bundled": False,
            "independent_update": True,
            "independent_rollback": True,
        },
        "rollback": {
            "desktop": "install_previous_verified_archive",
            "preserve_active_models": True,
            "project_files_required": False,
        },
    }


def write_release_manifest(manifest: dict[str, object], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def verify_release_manifest(
    manifest_path: Path,
    archive: Path,
    expected_target: str | None = None,
) -> tuple[str, ...]:
    try:
        encoded = manifest_path.read_bytes()
        payload = json.loads(encoded.decode("utf-8"))
        archive_data = payload["archive"]
        compatibility = payload["compatibility"]
        models = payload["models"]
        rollback = payload["rollback"]
        errors = []
        if set(payload) != {
            "schema_version",
            "product",
            "version",
            "target",
            "compatibility",
            "archive",
            "models",
            "rollback",
        }:
            errors.append("manifest fields are invalid")
        if payload["schema_version"] != 1 or payload["product"] != "imgtrans":
            errors.append("manifest identity is invalid")
        if not isinstance(payload["version"], str) or not _VERSION.fullmatch(payload["version"]):
            errors.append("manifest version is invalid")
        if expected_target is not None and payload["target"] != expected_target:
            errors.append("manifest target does not match")
        expected_compatibility = {
            "windows-x64": {"os": "Windows", "minimum": "10", "architecture": "x86_64"},
            "macos-arm64": {"os": "macOS", "minimum": "13", "architecture": "arm64"},
        }.get(payload["target"])
        if compatibility != expected_compatibility:
            errors.append("manifest compatibility is invalid")
        if archive_data["file"] != archive.name:
            errors.append("manifest archive filename does not match")
        if archive_data["size"] != archive.stat().st_size:
            errors.append("manifest archive size does not match")
        if archive_data["sha256"] != _sha256(archive):
            errors.append("manifest archive hash does not match")
        if models != {
            "bundled": False,
            "independent_update": True,
            "independent_rollback": True,
        }:
            errors.append("manifest model rollback policy is invalid")
        if rollback["desktop"] != "install_previous_verified_archive":
            errors.append("manifest desktop rollback policy is invalid")
        if rollback["preserve_active_models"] is not True:
            errors.append("manifest model preservation policy is invalid")
        if rollback["project_files_required"] is not False:
            errors.append("manifest project-file policy is invalid")
        if scan_secret_payload(encoded):
            errors.append("manifest contains sensitive material")
        return tuple(errors)
    except (OSError, KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return ("release manifest is invalid",)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ImgTrans release hardening gates")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check-source")
    create = subparsers.add_parser("create-manifest")
    create.add_argument("--target", choices=TARGETS, required=True)
    create.add_argument("--archive", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify-manifest")
    verify.add_argument("--target", choices=TARGETS, required=True)
    verify.add_argument("--archive", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    arguments = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if arguments.command == "check-source":
        try:
            versions = version_sources(root)
        except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
            print(f"release gate failed: {error}")
            return 1
        findings = scan_source_tree(root)
        if findings:
            for finding in findings[:20]:
                print(f"release gate finding: {finding}")
            return 1
        print(f"release source verified: version={versions['desktop']}")
        return 0
    if arguments.command == "create-manifest":
        manifest = build_release_manifest(root, arguments.target, arguments.archive)
        write_release_manifest(manifest, arguments.output)
        errors = verify_release_manifest(arguments.output, arguments.archive, arguments.target)
    else:
        errors = verify_release_manifest(
            arguments.manifest,
            arguments.archive,
            arguments.target,
        )
    if errors:
        for error in errors:
            print(f"release gate failed: {error}")
        return 1
    print(f"release manifest verified: target={arguments.target}")
    return 0


def _source_files(root: Path) -> Iterable[Path]:
    for location in _SOURCE_LOCATIONS:
        candidate = root / location
        if candidate.is_file():
            yield candidate
            continue
        if not candidate.is_dir():
            continue
        for path in candidate.rglob("*"):
            if path.is_file() and (
                path.suffix.casefold() in _TEXT_SUFFIXES
                or path.name.casefold() in _FORBIDDEN_FILENAMES
            ):
                yield path


def _module_version(path: Path) -> str:
    match = _VERSION_ASSIGNMENT.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"version assignment missing: {path.name}")
    return match.group(1)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
