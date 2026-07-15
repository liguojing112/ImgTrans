import hashlib
import json
from pathlib import Path


def test_pinned_fonts_have_verifiable_license_and_hashes(font_dir: Path) -> None:
    config = json.loads(
        Path("prototypes/complex_script_layout/font-sources.json").read_text(encoding="utf-8")
    )
    assert len(config["commit"]) == 40
    assert config["license"]["spdx"] == "OFL-1.1"
    for item in config["fonts"]:
        digest = hashlib.sha256((font_dir / item["file"]).read_bytes()).hexdigest()
        assert digest == item["sha256"]
