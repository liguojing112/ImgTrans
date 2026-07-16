import pytest

from src.domain.job import (
    CancellationToken,
    ImageJob,
    ImageStage,
    JobCancelled,
    JobStatus,
)


def test_image_job_requires_ordered_stages_before_completion() -> None:
    job = ImageJob()
    job.start()
    for stage in ImageStage:
        job.advance(stage)
        assert job.current_stage is stage
        job.finish_stage()
    job.complete()
    assert job.status is JobStatus.COMPLETED
    assert tuple(job.completed_stages) == tuple(ImageStage)


def test_image_job_rejects_out_of_order_transition() -> None:
    job = ImageJob()
    job.start()
    with pytest.raises(RuntimeError):
        job.advance(ImageStage.TRANSLATION)


def test_cancellation_token_raises_structured_cancel_signal() -> None:
    token = CancellationToken()
    token.cancel()
    with pytest.raises(JobCancelled):
        token.throw_if_cancelled()
