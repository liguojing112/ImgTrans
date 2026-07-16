import os
from pathlib import Path
import subprocess
import sys


def test_module_entrypoint_smoke_exits_successfully(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["LOCALAPPDATA"] = str(tmp_path / "local")
    environment["HOME"] = str(tmp_path / "home")
    completed = subprocess.run(
        [sys.executable, "-m", "src", "--smoke-test"],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
