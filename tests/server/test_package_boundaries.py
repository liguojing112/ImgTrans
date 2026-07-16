from pathlib import Path


def test_desktop_package_does_not_import_backend_package() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src"
    violations = []
    for source in source_root.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        if "from server" in text or "import server" in text:
            violations.append(source.relative_to(source_root))
    assert not violations
