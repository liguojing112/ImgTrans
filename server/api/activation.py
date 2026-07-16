from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import Field, model_validator

from server.api.auth import require_admin
from server.api.contracts import StrictContract
from server.api.rate_limit import enforce_rate_limit
from server.domain.activation import (
    ActivationCode,
    ActivationConflict,
    ActivationDenied,
    ActivationError,
    ActivationNotFound,
    ActivationPlan,
    ActivationPlanValues,
)


class ActivationPlanPayload(StrictContract):
    name: str = Field(min_length=1, max_length=100)
    amount_minor: int = Field(ge=0, le=1_000_000_000_000)
    currency: str = Field(default="CNY", pattern=r"^[A-Z]{3}$")
    duration_days: int = Field(ge=1, le=3650)
    enabled: bool = True

    def to_domain(self) -> ActivationPlanValues:
        return ActivationPlanValues(**self.model_dump())


class ActivationPlanResponse(ActivationPlanPayload):
    plan_id: int
    created_at: datetime
    updated_at: datetime


class ActivationPlanListResponse(StrictContract):
    plans: tuple[ActivationPlanResponse, ...]


class IssueActivationCodesRequest(StrictContract):
    plan_id: int = Field(gt=0)
    count: int = Field(default=1, ge=1, le=100)


class IssuedActivationCodeResponse(StrictContract):
    code_id: str
    activation_code: str
    plan_id: int
    duration_days: int
    created_at: datetime


class IssuedActivationCodesResponse(StrictContract):
    codes: tuple[IssuedActivationCodeResponse, ...]


class ActivationCodeResponse(StrictContract):
    code_id: str
    plan_id: int
    duration_days: int
    status: Literal["unbound", "active", "expired", "disabled"]
    bound: bool
    created_at: datetime
    activated_at: datetime | None
    expires_at: datetime | None
    disabled_at: datetime | None


class ActivationCodeListResponse(StrictContract):
    codes: tuple[ActivationCodeResponse, ...]


class ActivateDeviceRequest(StrictContract):
    activation_code: str = Field(
        pattern=r"^IT-(?:[A-HJ-NP-Z2-9]{4}-){7}[A-HJ-NP-Z2-9]{4}$"
    )
    device_id: str = Field(min_length=16, max_length=256)

    @model_validator(mode="after")
    def validate_device_id(self) -> "ActivateDeviceRequest":
        if not self.device_id.strip() or any(ord(character) < 32 for character in self.device_id):
            raise ValueError("device_id is invalid")
        return self


class ActivateDeviceResponse(StrictContract):
    status: Literal["active"]
    plan_id: int
    activated_at: datetime
    expires_at: datetime
    access_token: str
    token_type: Literal["Bearer"]


activation_router = APIRouter(prefix="/v1/activations", tags=["activation"])
admin_activation_router = APIRouter(
    prefix="/v1/admin/activation",
    tags=["admin-activation"],
)


@activation_router.post("/validate", response_model=ActivateDeviceResponse)
def activate_device(
    payload: ActivateDeviceRequest,
    request: Request,
    response: Response,
) -> ActivateDeviceResponse:
    enforce_rate_limit(request, "activation", limit=20, window_seconds=60)
    _require_activation_enabled(request)
    try:
        grant = request.app.state.activate_device.execute(
            payload.activation_code,
            payload.device_id,
        )
    except ActivationDenied as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ActivationConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    response.headers["Cache-Control"] = "no-store"
    return ActivateDeviceResponse(
        status="active",
        plan_id=grant.activation.plan_id,
        activated_at=grant.activation.activated_at,
        expires_at=grant.activation.expires_at,
        access_token=grant.access_token,
        token_type="Bearer",
    )


@admin_activation_router.post(
    "/plans",
    response_model=ActivationPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_plan(
    payload: ActivationPlanPayload,
    request: Request,
) -> ActivationPlanResponse:
    require_admin(request)
    try:
        plan = request.app.state.manage_activation_plans.create(payload.to_domain())
    except ActivationError as error:
        raise _domain_http_error(error) from error
    return _plan_response(plan)


@admin_activation_router.put(
    "/plans/{plan_id}", response_model=ActivationPlanResponse
)
def update_plan(
    plan_id: int,
    payload: ActivationPlanPayload,
    request: Request,
) -> ActivationPlanResponse:
    require_admin(request)
    try:
        plan = request.app.state.manage_activation_plans.update(
            plan_id, payload.to_domain()
        )
    except ActivationError as error:
        raise _domain_http_error(error) from error
    return _plan_response(plan)


@admin_activation_router.get(
    "/plans", response_model=ActivationPlanListResponse
)
def list_plans(request: Request) -> ActivationPlanListResponse:
    require_admin(request)
    return ActivationPlanListResponse(
        plans=tuple(
            _plan_response(plan)
            for plan in request.app.state.manage_activation_plans.list_all()
        )
    )


@admin_activation_router.post(
    "/codes",
    response_model=IssuedActivationCodesResponse,
    status_code=status.HTTP_201_CREATED,
)
def issue_codes(
    payload: IssueActivationCodesRequest,
    request: Request,
    response: Response,
) -> IssuedActivationCodesResponse:
    require_admin(request)
    _require_activation_enabled(request)
    try:
        issued = request.app.state.manage_activation_codes.issue(
            payload.plan_id,
            payload.count,
        )
    except ActivationError as error:
        raise _domain_http_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return IssuedActivationCodesResponse(
        codes=tuple(
            IssuedActivationCodeResponse(
                code_id=item.activation.code_id,
                activation_code=item.plaintext,
                plan_id=item.activation.plan_id,
                duration_days=item.activation.duration_days,
                created_at=item.activation.created_at,
            )
            for item in issued
        )
    )


@admin_activation_router.get(
    "/codes", response_model=ActivationCodeListResponse
)
def list_codes(request: Request) -> ActivationCodeListResponse:
    require_admin(request)
    return ActivationCodeListResponse(
        codes=tuple(
            _code_response(code)
            for code in request.app.state.manage_activation_codes.list_all()
        )
    )


@admin_activation_router.post(
    "/codes/{code_id}/disable", response_model=ActivationCodeResponse
)
def disable_code(code_id: str, request: Request) -> ActivationCodeResponse:
    require_admin(request)
    try:
        code = request.app.state.manage_activation_codes.disable(code_id)
    except ActivationError as error:
        raise _domain_http_error(error) from error
    return _code_response(code)


def _require_activation_enabled(request: Request) -> None:
    if not request.app.state.device_authorization_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Activation service is not configured",
        )


def _domain_http_error(error: ActivationError) -> HTTPException:
    if isinstance(error, ActivationNotFound):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, ActivationConflict):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


def _plan_response(plan: ActivationPlan) -> ActivationPlanResponse:
    return ActivationPlanResponse(
        plan_id=plan.plan_id,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        **{
            "name": plan.values.name,
            "amount_minor": plan.values.amount_minor,
            "currency": plan.values.currency,
            "duration_days": plan.values.duration_days,
            "enabled": plan.values.enabled,
        },
    )


def _code_response(code: ActivationCode) -> ActivationCodeResponse:
    now = datetime.now(code.created_at.tzinfo)
    if code.disabled:
        status_value = "disabled"
    elif code.expires_at is not None and code.expires_at <= now:
        status_value = "expired"
    elif code.bound:
        status_value = "active"
    else:
        status_value = "unbound"
    return ActivationCodeResponse(
        code_id=code.code_id,
        plan_id=code.plan_id,
        duration_days=code.duration_days,
        status=status_value,
        bound=code.bound,
        created_at=code.created_at,
        activated_at=code.activated_at,
        expires_at=code.expires_at,
        disabled_at=code.disabled_at,
    )
