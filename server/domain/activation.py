from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re


class ActivationError(ValueError):
    pass


class ActivationNotFound(ActivationError):
    pass


class ActivationConflict(ActivationError):
    pass


class ActivationDenied(ActivationError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ActivationPlanValues:
    name: str
    amount_minor: int
    currency: str
    duration_days: int
    enabled: bool = True

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name or len(normalized_name) > 100:
            raise ActivationError("Activation plan name is invalid")
        if self.amount_minor < 0:
            raise ActivationError("Activation plan amount cannot be negative")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ActivationError("Activation plan currency is invalid")
        if not 1 <= self.duration_days <= 3650:
            raise ActivationError("Activation plan duration is invalid")


@dataclass(frozen=True, slots=True)
class ActivationPlan:
    plan_id: int
    values: ActivationPlanValues
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ActivationCode:
    code_id: str
    plan_id: int
    duration_days: int
    disabled: bool
    bound: bool
    created_at: datetime
    activated_at: datetime | None
    expires_at: datetime | None
    disabled_at: datetime | None


@dataclass(frozen=True, slots=True)
class DeviceActivation:
    code_id: str
    plan_id: int
    activated_at: datetime
    expires_at: datetime

