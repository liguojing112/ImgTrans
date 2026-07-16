import os
from pathlib import Path
import subprocess
import sys


def test_server_module_smoke_exits_successfully() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "IMGTRANS_ENVIRONMENT": "test",
            "IMGTRANS_DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "IMGTRANS_DOCS_ENABLED": "false",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-m", "server", "--smoke-test"],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "imgtrans-server ready api=v1"
