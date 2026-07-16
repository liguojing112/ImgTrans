from typing import Literal

from pydantic import BaseModel, ConfigDict


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictContract):
    status: Literal["ok", "unavailable"]


class ServiceInfoResponse(StrictContract):
    service: Literal["imgtrans-server"]
    service_version: str
    api_version: Literal["v1"]
    environment: str


class ApiError(StrictContract):
    code: str
    message: str
    correlation_id: str


class ErrorResponse(StrictContract):
    error: ApiError
