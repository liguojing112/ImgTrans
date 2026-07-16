from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
from typing import Callable, Protocol

from server.domain.activation import (
    ActivationCode,
    ActivationConflict,
    ActivationPlan,
    ActivationPlanValues,
    DeviceActivation,
)


class ActivationRepository(Protocol):
    def create_plan(self, values: ActivationPlanValues) -> ActivationPlan: ...

    def update_plan(
        self, plan_id: int, values: ActivationPlanValues
    ) -> ActivationPlan: ...

    def list_plans(self) -> tuple[ActivationPlan, ...]: ...

    def get_plan(self, plan_id: int) -> ActivationPlan: ...

    def create_codes(
        self,
        plan_id: int,
        duration_days: int,
        code_digests: tuple[str, ...],
    ) -> tuple[ActivationCode, ...]: ...

    def list_codes(self) -> tuple[ActivationCode, ...]: ...

    def disable_code(self, code_id: str, now: datetime) -> ActivationCode: ...

    def activate(
        self,
        code_digest: str,
        device_digest: str,
        token_digest: str,
        now: datetime,
    ) -> DeviceActivation: ...

    def authorize_token(self, token_digest: str, now: datetime) -> bool: ...


@dataclass(frozen=True, slots=True)
class IssuedActivationCode:
    activation: ActivationCode
    plaintext: str


@dataclass(frozen=True, slots=True)
class ActivationGrant:
    activation: DeviceActivation
    access_token: str


class ActivationSecretHasher:
    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("Activation secret must contain at least 32 characters")
        self._secret = secret.encode("utf-8")

    def digest_code(self, value: str) -> str:
        return self._digest("code", value)

    def digest_device(self, value: str) -> str:
        return self._digest("device", value)

    def digest_token(self, value: str) -> str:
        return self._digest("token", value)

    def _digest(self, purpose: str, value: str) -> str:
        return hmac.new(
            self._secret,
            f"{purpose}:{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


class ManageActivationPlans:
    def __init__(self, repository: ActivationRepository) -> None:
        self._repository = repository

    def create(self, values: ActivationPlanValues) -> ActivationPlan:
        return self._repository.create_plan(values)

    def update(
        self, plan_id: int, values: ActivationPlanValues
    ) -> ActivationPlan:
        return self._repository.update_plan(plan_id, values)

    def list_all(self) -> tuple[ActivationPlan, ...]:
        return self._repository.list_plans()


class ManageActivationCodes:
    _ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    def __init__(
        self,
        repository: ActivationRepository,
        hasher: ActivationSecretHasher | None,
        random_choice: Callable[[str], str] = secrets.choice,
    ) -> None:
        self._repository = repository
        self._hasher = hasher
        self._random_choice = random_choice

    def issue(self, plan_id: int, count: int) -> tuple[IssuedActivationCode, ...]:
        if self._hasher is None:
            raise ActivationConflict("Activation service is not configured")
        plan = self._repository.get_plan(plan_id)
        if not plan.values.enabled:
            raise ActivationConflict("Disabled activation plans cannot issue codes")
        if not 1 <= count <= 100:
            raise ValueError("Activation code count must be between 1 and 100")
        for _ in range(3):
            plaintext = tuple(self._generate_code() for _ in range(count))
            if len(set(plaintext)) != count:
                continue
            digests = tuple(self._hasher.digest_code(code) for code in plaintext)
            try:
                activations = self._repository.create_codes(
                    plan.plan_id,
                    plan.values.duration_days,
                    digests,
                )
            except ActivationConflict:
                continue
            return tuple(
                IssuedActivationCode(activation, code)
                for activation, code in zip(activations, plaintext, strict=True)
            )
        raise ActivationConflict("Unable to allocate unique activation codes")

    def list_all(self) -> tuple[ActivationCode, ...]:
        return self._repository.list_codes()

    def disable(self, code_id: str) -> ActivationCode:
        return self._repository.disable_code(code_id, datetime.now(timezone.utc))

    def _generate_code(self) -> str:
        raw = "".join(self._random_choice(self._ALPHABET) for _ in range(32))
        return "IT-" + "-".join(raw[index : index + 4] for index in range(0, 32, 4))


class ActivateDevice:
    def __init__(
        self,
        repository: ActivationRepository,
        hasher: ActivationSecretHasher,
        token_factory: Callable[[int], str] = secrets.token_urlsafe,
    ) -> None:
        self._repository = repository
        self._hasher = hasher
        self._token_factory = token_factory

    def execute(self, activation_code: str, device_id: str) -> ActivationGrant:
        code_digest = self._hasher.digest_code(activation_code)
        device_digest = self._hasher.digest_device(device_id)
        for _ in range(3):
            access_token = f"itd_{self._token_factory(32)}"
            try:
                activation = self._repository.activate(
                    code_digest,
                    device_digest,
                    self._hasher.digest_token(access_token),
                    datetime.now(timezone.utc),
                )
            except ActivationConflict:
                continue
            return ActivationGrant(activation, access_token)
        raise ActivationConflict("Unable to allocate a unique device token")


class AuthorizeDeviceToken:
    def __init__(
        self,
        repository: ActivationRepository,
        hasher: ActivationSecretHasher,
    ) -> None:
        self._repository = repository
        self._hasher = hasher

    def authorize(self, token: str) -> bool:
        if not token.startswith("itd_") or len(token) > 256:
            return False
        return self._repository.authorize_token(
            self._hasher.digest_token(token),
            datetime.now(timezone.utc),
        )


class UnavailableDeviceTokenAuthorizer:
    def authorize(self, token: str) -> bool:
        return False
