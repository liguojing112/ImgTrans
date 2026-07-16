from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_model(config_path: Path, output_dir: Path) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / config["file"]
    if target.is_file() and target.stat().st_size == config["size"]:
        if file_sha256(target) == config["sha256"]:
            return target
    temporary = target.with_suffix(target.suffix + ".part")
    last_error: Exception | None = None
    for url in (config["url"], config["fallback_url"]):
        try:
            with urlopen(url, timeout=120) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if temporary.stat().st_size != config["size"]:
                raise RuntimeError("Downloaded model size does not match manifest")
            if file_sha256(temporary) != config["sha256"]:
                raise RuntimeError("Downloaded model hash does not match manifest")
            temporary.replace(target)
            return target
        except Exception as error:
            last_error = error
            temporary.unlink(missing_ok=True)
    raise RuntimeError(f"Could not download verified LaMa model: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--config", type=Path, default=Path(__file__).with_name("model-source.json")
    )
    args = parser.parse_args()
    path = prepare_model(args.config, args.output)
    print(path)
    print(file_sha256(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

