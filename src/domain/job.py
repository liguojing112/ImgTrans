from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import Event


class ImageStage(str, Enum):
    OCR = "ocr"
    TRANSLATION = "translation"
    INPAINTING = "inpainting"
    LAYOUT = "layout"
    RENDERING = "rendering"


class JobStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class JobCancelled(RuntimeError):
    pass


@dataclass(slots=True)
class ImageJob:
    status: JobStatus = JobStatus.READY
    current_stage: ImageStage | None = None
    completed_stages: list[ImageStage] = field(default_factory=list)
    error: str | None = None

    def start(self) -> None:
        if self.status is not JobStatus.READY:
            raise RuntimeError("Only a ready image job can start")
        self.status = JobStatus.RUNNING

    def advance(self, stage: ImageStage) -> None:
        if self.status is not JobStatus.RUNNING:
            raise RuntimeError("Only a running image job can advance")
        expected_index = len(self.completed_stages)
        stages = tuple(ImageStage)
        if expected_index >= len(stages) or stages[expected_index] is not stage:
            raise RuntimeError("Image job stages must run in order")
        self.current_stage = stage

    def finish_stage(self) -> None:
        if self.status is not JobStatus.RUNNING or self.current_stage is None:
            raise RuntimeError("Image job has no active stage")
        self.completed_stages.append(self.current_stage)
        self.current_stage = None

    def complete(self) -> None:
        if self.status is not JobStatus.RUNNING or tuple(self.completed_stages) != tuple(ImageStage):
            raise RuntimeError("Image job cannot complete before all stages")
        self.status = JobStatus.COMPLETED

    def cancel(self) -> None:
        if self.status in {JobStatus.READY, JobStatus.RUNNING}:
            self.status = JobStatus.CANCELLED
            self.current_stage = None

    def fail(self, error: Exception) -> None:
        if self.status is JobStatus.RUNNING:
            self.status = JobStatus.FAILED
            self.current_stage = None
            self.error = str(error) or type(error).__name__


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def throw_if_cancelled(self) -> None:
        if self._event.is_set():
            raise JobCancelled("图片翻译任务已取消")
