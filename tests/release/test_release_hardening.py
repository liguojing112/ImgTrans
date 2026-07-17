from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release_hardening import (
    build_release_manifest,
    scan_secret_payload,
    scan_source_tree,
    verify_release_manifest,
    version_sources,
    write_release_manifest,
)


def _version_tree(root: Path, version: str = "1.2.3") -> None:
    (root / "src").mkdir(parents=True)
    (root / "server").mkdir()
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "fixture"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    for package in ("src", "server"):
        (root / package / "__init__.py").write_text(
            f'__version__ = "{version}"\n',
            encoding="utf-8",
        )


def test_release_versions_are_semantic_and_consistent(tmp_path: Path) -> None:
    _version_tree(tmp_path)
    assert version_sources(tmp_path) == {
        "pyproject": "1.2.3",
        "desktop": "1.2.3",
        "server": "1.2.3",
    }
    (tmp_path / "server" / "__init__.py").write_text(
        '__version__ = "1.2.4"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="do not match"):
        version_sources(tmp_path)


def test_source_scan_rejects_secret_values_and_sensitive_files(tmp_path: Path) -> None:
    _version_tree(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "unsafe.py").write_text(
        'translator_key = "fixture-hardcoded-value-123456"\n',
        encoding="utf-8",
    )
    (tmp_path / "src" / ".env").write_text("ignored=value\n", encoding="utf-8")
    findings = scan_source_tree(tmp_path)
    assert "hardcoded-secret-assignment:scripts/unsafe.py" in findings
    assert "sensitive-file:src/.env" in findings


def test_secret_payload_labels_findings_without_returning_secret_text() -> None:
    value = b"password='fixture-password-value-123456'"
    findings = scan_secret_payload(value)
    assert findings == ("hardcoded-secret-assignment",)
    assert all("fixture-password" not in finding for finding in findings)


def test_binary_library_strings_do_not_trigger_private_key_or_aws_false_positive() -> None:
    binary = (
        b"\x00\x01-----BEGIN PRIVATE KEY-----\x00diagnostic"
        + b"\x00AKIAABCDEFGHIJKLMNOP\xff"
    )
    assert scan_secret_payload(binary) == ()


def test_complete_pem_private_key_structure_is_detected() -> None:
    pem = (
        b"-----BEGIN PRIVATE KEY-----\n"
        + b"A" * 80
        + b"\n-----END PRIVATE KEY-----"
    )
    assert scan_secret_payload(pem) == ("private-key",)


@pytest.mark.parametrize("target", ("windows-x64", "macos-arm64"))
def test_release_manifest_binds_archive_compatibility_and_rollback(
    tmp_path: Path,
    target: str,
) -> None:
    _version_tree(tmp_path)
    archive = tmp_path / f"ImgTrans-{target}.zip"
    archive.write_bytes(b"verified archive")
    manifest = build_release_manifest(tmp_path, target, archive)
    output = tmp_path / f"{target}.manifest.json"
    write_release_manifest(manifest, output)

    assert verify_release_manifest(output, archive, target) == ()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["version"] == "1.2.3"
    assert payload["models"]["bundled"] is False
    assert payload["models"]["independent_rollback"] is True
    assert payload["rollback"]["preserve_active_models"] is True
    assert len(payload["archive"]["sha256"]) == 64

    archive.write_bytes(b"tampered archive content")
    errors = verify_release_manifest(output, archive, target)
    assert "manifest archive size does not match" in errors
    assert "manifest archive hash does not match" in errors


def test_release_manifest_rejects_extra_sensitive_fields(tmp_path: Path) -> None:
    _version_tree(tmp_path)
    archive = tmp_path / "ImgTrans-windows-x64.zip"
    archive.write_bytes(b"verified archive")
    payload = build_release_manifest(tmp_path, "windows-x64", archive)
    payload["api_key"] = "fixture-hardcoded-value-123456"
    output = tmp_path / "manifest.json"
    write_release_manifest(payload, output)
    errors = verify_release_manifest(output, archive, "windows-x64")
    assert "manifest fields are invalid" in errors
    assert "manifest contains sensitive material" in errors
