from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_customer_image_e2e import (
    _public_error_code,
    discover_images,
    main,
    validate_language_pair,
)


def test_customer_image_discovery_is_deterministic_filtered_and_limited(
    tmp_path: Path,
) -> None:
    for name in ("b.webp", "A.JPG", "c.png", "notes.txt"):
        (tmp_path / name).write_bytes(b"fixture")
    assert [path.name for path in discover_images(tmp_path, 2)] == [
        "A.JPG",
        "b.webp",
    ]


def test_customer_image_discovery_rejects_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="没有支持的图片"):
        discover_images(tmp_path, 10)


def test_customer_e2e_fails_before_reading_images_without_backend_configuration(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv("IMGTRANS_API_BASE_URL", raising=False)
    monkeypatch.delenv("IMGTRANS_API_TOKEN", raising=False)
    assert main(
        [
            "--input-dir",
            str(tmp_path / "missing"),
            "--output-dir",
            str(tmp_path / "output"),
            "--ocr-language",
            "zh-Hans",
            "--target-language",
            "en",
        ]
    ) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "IMGTRANS_API_BASE_URL 未配置" in captured.err


def test_customer_item_error_output_uses_only_stable_code() -> None:
    class _CodedError(RuntimeError):
        code = "backend_unavailable"

    assert _public_error_code(_CodedError("secret customer text")) == "backend_unavailable"
    assert _public_error_code(OSError(r"C:\private\customer.png")) == "OSError"


def test_customer_e2e_rejects_same_ocr_and_target_language() -> None:
    with pytest.raises(ValueError, match="不能相同"):
        validate_language_pair("zh-Hans", "zh-Hans")
