from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


class ActivationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ActivationSession:
    plan_id: int
    activated_at: datetime
    expires_at: datetime
    access_token: str = field(repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.plan_id, bool) or not isinstance(self.plan_id, int) or self.plan_id <= 0:
            raise ValueError("Activation plan ID must be positive")
        if self.activated_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Activation timestamps must include a timezone")
        if self.expires_at <= self.activated_at:
            raise ValueError("Activation expiry must follow activation time")
        if len(self.access_token) < 16 or any(
            ord(character) < 32 for character in self.access_token
        ):
            raise ValueError("Activation access token is invalid")

    @property
    def active(self) -> bool:
        return self.expires_at > datetime.now(timezone.utc)
