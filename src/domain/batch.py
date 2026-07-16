from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.domain.job import ImageStage


class BatchStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BatchItemStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            BatchItemStatus.COMPLETED,
            BatchItemStatus.FAILED,
            BatchItemStatus.CANCELLED,
        }


@dataclass(frozen=True, slots=True)
class BatchItemSnapshot:
    item_id: str
    source: Path
    status: BatchItemStatus = BatchItemStatus.QUEUED
    current_stage: ImageStage | None = None
    result_ref: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.item_id:
            raise ValueError("Batch item ID cannot be empty")
        if self.status is BatchItemStatus.COMPLETED and not self.result_ref:
            raise ValueError("Completed batch item requires a result reference")
        if self.status is BatchItemStatus.FAILED and not self.error:
            raise ValueError("Failed batch item requires an error")
        if self.status is not BatchItemStatus.RUNNING and self.current_stage is not None:
            raise ValueError("Only a running batch item can have an active stage")


@dataclass(frozen=True, slots=True)
class BatchSnapshot:
    batch_id: str
    status: BatchStatus
    items: tuple[BatchItemSnapshot, ...]
    max_active_items: int

    def __post_init__(self) -> None:
        if not self.batch_id or not self.items:
            raise ValueError("Batch snapshot requires an ID and at least one item")
        if self.max_active_items <= 0:
            raise ValueError("Maximum active item count must be positive")
        ids = tuple(item.item_id for item in self.items)
        if len(ids) != len(set(ids)):
            raise ValueError("Batch item IDs must be unique")

    @property
    def completed_count(self) -> int:
        return sum(item.status is BatchItemStatus.COMPLETED for item in self.items)

    @property
    def failed_count(self) -> int:
        return sum(item.status is BatchItemStatus.FAILED for item in self.items)

    @property
    def cancelled_count(self) -> int:
        return sum(item.status is BatchItemStatus.CANCELLED for item in self.items)

    @property
    def finished_count(self) -> int:
        return sum(item.status.terminal for item in self.items)

    @property
    def progress(self) -> float:
        return self.finished_count / len(self.items)
