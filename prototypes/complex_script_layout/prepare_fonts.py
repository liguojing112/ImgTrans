from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare(config_path: Path, output_dir: Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    base = f"https://raw.githubusercontent.com/notofonts/noto-fonts/{config['commit']}"
    for item in config["fonts"]:
        target = output_dir / item["file"]
        if not target.exists() or sha256(target) != item["sha256"]:
            with urlopen(f"{base}/{item['source_path']}", timeout=60) as response:
                target.write_bytes(response.read())
        actual = sha256(target)
        if actual != item["sha256"]:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"Hash mismatch for {item['file']}: {actual}")
        print(f"verified {item['file']} {actual}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("font-sources.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.config, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
