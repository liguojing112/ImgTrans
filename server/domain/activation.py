from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import re
from zoneinfo import ZoneInfo


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
    duration_hours: int = 0
    enabled: bool = True
    plan_type: str = "duration"  # duration | quota | combo
    quota: int = 0
    sale_amount_minor: int | None = None
    sale_ends_at: datetime | None = None
    sale_dates: tuple[date, ...] = ()
    sale_start_time: time | None = None
    sale_end_time: time | None = None
    benefits: str = ""
    hidden: bool = False

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name or len(normalized_name) > 100:
            raise ActivationError("Activation plan name is invalid")
        if self.amount_minor < 0:
            raise ActivationError("Activation plan amount cannot be negative")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ActivationError("Activation plan currency is invalid")
        if self.plan_type not in {"duration", "quota", "combo"}:
            raise ActivationError("Activation plan type is invalid")
        if not 0 <= self.duration_hours <= 87600:
            raise ActivationError("Activation plan duration is invalid")
        if not 0 <= self.quota <= 1_000_000:
            raise ActivationError("Activation plan quota is invalid")
        if self.duration_hours <= 0 and self.quota <= 0:
            raise ActivationError("Activation plan must include duration or quota")
        if self.plan_type == "duration" and self.duration_hours <= 0:
            raise ActivationError("Duration plan requires duration hours")
        if self.plan_type == "quota" and self.quota <= 0:
            raise ActivationError("Quota plan requires quota")
        if self.plan_type == "combo" and (self.duration_hours <= 0 or self.quota <= 0):
            raise ActivationError("Combo plan requires both duration and quota")
        if len(self.benefits) > 500:
            raise ActivationError("Activation plan benefits are too long")
        if self.sale_amount_minor is not None:
            if not 0 <= self.sale_amount_minor < self.amount_minor:
                raise ActivationError("Activation plan sale price is invalid")
        if self.sale_ends_at is not None and self.sale_ends_at.tzinfo is None:
            raise ActivationError("Activation plan sale deadline must include timezone")
        normalized_dates = tuple(sorted(set(self.sale_dates)))
        object.__setattr__(self, "sale_dates", normalized_dates)
        if normalized_dates and (
            self.sale_start_time is None or self.sale_end_time is None
        ):
            raise ActivationError("Activation plan sale schedule is incomplete")
        if (self.sale_start_time is None) != (self.sale_end_time is None):
            raise ActivationError("Activation plan sale schedule is incomplete")
        if (
            self.sale_start_time is not None
            and self.sale_end_time is not None
            and self.sale_start_time >= self.sale_end_time
        ):
            raise ActivationError("Activation plan sale time range is invalid")

    def is_on_sale(self, now: datetime) -> bool:
        return self.active_sale_ends_at(now) is not None

    def active_sale_ends_at(self, now: datetime) -> datetime | None:
        if now.tzinfo is None:
            raise ActivationError("Sale evaluation time must include timezone")
        if self.sale_amount_minor is None:
            return None
        if self.sale_dates:
            local_now = now.astimezone(ZoneInfo("Asia/Shanghai"))
            if local_now.date() not in self.sale_dates:
                return None
            assert self.sale_start_time is not None
            assert self.sale_end_time is not None
            if not self.sale_start_time <= local_now.time().replace(tzinfo=None) < self.sale_end_time:
                return None
            return datetime.combine(
                local_now.date(), self.sale_end_time, ZoneInfo("Asia/Shanghai")
            ).astimezone(now.tzinfo)
        return (
            self.sale_ends_at
            if self.sale_ends_at is not None and now < self.sale_ends_at
            else None
        )


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
    duration_hours: int
    disabled: bool
    bound: bool
    created_at: datetime
    activated_at: datetime | None
    expires_at: datetime | None
    disabled_at: datetime | None
    quota_total: int = 0
    quota_remaining: int = 0
    plaintext: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceActivation:
    code_id: str
    plan_id: int
    activated_at: datetime
    expires_at: datetime
    quota_total: int = 0
    quota_remaining: int = 0


@dataclass(frozen=True, slots=True)
class UsageRecord:
    usage_id: int
    code_id: str
    amount: int
    created_at: datetime
    plaintext: str | None = None

