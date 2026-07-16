from pathlib import Path

import pytest

from src.domain.batch import (
    BatchItemSnapshot,
    BatchItemStatus,
    BatchSnapshot,
    BatchStatus,
)
from src.domain.job import ImageStage


def test_batch_snapshot_counts_terminal_items_and_progress() -> None:
    items = (
        BatchItemSnapshot("1", Path("one.png"), BatchItemStatus.COMPLETED, result_ref="r1"),
        BatchItemSnapshot("2", Path("two.png"), BatchItemStatus.FAILED, error="broken"),
        BatchItemSnapshot("3", Path("three.png"), BatchItemStatus.CANCELLED),
        BatchItemSnapshot("4", Path("four.png"), BatchItemStatus.RUNNING, ImageStage.OCR),
    )
    snapshot = BatchSnapshot("batch-1", BatchStatus.RUNNING, items, 2)
    assert snapshot.completed_count == 1
    assert snapshot.failed_count == 1
    assert snapshot.cancelled_count == 1
    assert snapshot.finished_count == 3
    assert snapshot.progress == pytest.approx(0.75)


def test_batch_item_rejects_inconsistent_terminal_data() -> None:
    with pytest.raises(ValueError):
        BatchItemSnapshot("1", Path("one.png"), BatchItemStatus.COMPLETED)
    with pytest.raises(ValueError):
        BatchItemSnapshot("1", Path("one.png"), BatchItemStatus.FAILED)
    with pytest.raises(ValueError):
        BatchItemSnapshot(
            "1", Path("one.png"), BatchItemStatus.QUEUED, ImageStage.OCR
        )
