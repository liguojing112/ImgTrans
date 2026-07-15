from pathlib import Path
import os

import pytest

from prototypes.complex_script_layout.prepare_fonts import prepare


@pytest.fixture(scope="session")
def font_dir() -> Path:
    directory = Path(os.environ.get("M0_COMPLEX_FONT_DIR", "artifacts/m0/complex-layout/fonts"))
    prepare(Path("prototypes/complex_script_layout/font-sources.json"), directory)
    return directory
