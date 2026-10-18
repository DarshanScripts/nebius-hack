from contracts.models import PipelineError, StageFailure

STAGE = "voice"


def fail(code: str, message: str, *, retryable: bool = False) -> StageFailure:
    return StageFailure(PipelineError(code=code, stage=STAGE, message=message, retryable=retryable))
