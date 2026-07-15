from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from prototypes.rapidocr_multilingual.adapter import RapidOCRAdapter
from prototypes.rapidocr_multilingual.model_router import ModelRouter


def test_adapter_initializes_a_model_only_once_per_batch(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    created = []

    def factory(params: dict[str, str]):
        created.append(params)

        def engine(*args, **kwargs):
            return SimpleNamespace(
                boxes=[[[0, 0], [10, 0], [10, 10], [0, 10]]],
                txts=["hello"],
                scores=[0.99],
            )

        return engine

    adapter = RapidOCRAdapter(engine_factory=factory)
    route = ModelRouter(Path("prototypes/rapidocr_multilingual/model-config.json")).route("en")
    adapter.recognize(image, route)
    adapter.recognize(image, route)

    assert len(created) == 1
    assert adapter.initialization_counts == {"ppocrv6-multilingual-small": 1}


def test_low_confidence_is_reported_explicitly(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")

    def factory(params: dict[str, str]):
        return lambda *args, **kwargs: SimpleNamespace(
            boxes=[[[0, 0], [10, 0], [10, 10], [0, 10]]],
            txts=["uncertain"],
            scores=[0.2],
        )

    adapter = RapidOCRAdapter(confidence_threshold=0.5, engine_factory=factory)
    route = ModelRouter(Path("prototypes/rapidocr_multilingual/model-config.json")).route("en")
    assert adapter.recognize(image, route)[0].status == "low_confidence"

