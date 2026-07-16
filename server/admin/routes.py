from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.concurrency import run_in_threadpool

from server.admin.security import (
    LOGIN_NONCE_COOKIE,
    SESSION_COOKIE,
    AdminSecurity,
    AdminSession,
)
from server.domain.activation import ActivationPlanValues
from server.domain.image_limits import ImageLimitValues
from server.domain.models import ModelReleaseSpec
from server.api.rate_limit import enforce_rate_limit
from server.domain.translation import TranslationTextItem, TranslationTextRequest


_ROOT = Path(__file__).resolve().parent
_TEMPLATES = Environment(
    loader=FileSystemLoader(_ROOT / "templates"),
    autoescape=select_autoescape(("html", "xml")),
)
_MAX_FORM_BYTES = 64 * 1024

admin_router = APIRouter(prefix="/admin", tags=["admin-console"])


@admin_router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    security = _security(request)
    if security.parse_session(request.cookies.get(SESSION_COOKIE)) is not None:
        return RedirectResponse("/admin", status_code=303)
    nonce, csrf_token = security.create_login_nonce()
    response = _render(
        "login.html",
        request,
        title="管理员登录",
        login_csrf=csrf_token,
        error=None,
    )
    response.set_cookie(
        LOGIN_NONCE_COOKIE,
        nonce,
        max_age=600,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="strict",
        path="/admin",
    )
    return response


@admin_router.post("/login", response_class=HTMLResponse)
async def login(request: Request) -> Response:
    security = _security(request)
    form = await _read_form(request)
    if not security.verify_login_csrf(
        request.cookies.get(LOGIN_NONCE_COOKIE),
        form.get("csrf_token", ""),
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    client_host = request.client.host if request.client is not None else "unknown"
    enforce_rate_limit(
        request,
        "admin-login",
        limit=10,
        window_seconds=300,
        identity=f"{client_host}:{form.get('username', '')}",
    )
    credentials_valid = await run_in_threadpool(
        security.verify_credentials,
        form.get("username", ""),
        form.get("password", ""),
    )
    if not credentials_valid:
        nonce, csrf_token = security.create_login_nonce()
        response = _render(
            "login.html",
            request,
            title="管理员登录",
            login_csrf=csrf_token,
            error="用户名或密码错误",
            status_code=401,
        )
        response.set_cookie(
            LOGIN_NONCE_COOKIE,
            nonce,
            max_age=600,
            httponly=True,
            secure=_secure_cookie(request),
            samesite="strict",
            path="/admin",
        )
        return response
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        security.create_session(),
        max_age=security.session_ttl_seconds,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="strict",
        path="/admin",
    )
    response.delete_cookie(LOGIN_NONCE_COOKIE, path="/admin")
    request.state.admin_actor = security.username
    request.state.audit_action = "login"
    return response


@admin_router.post("/logout")
async def logout(request: Request) -> Response:
    session, _ = await _protected_form(request)
    request.state.audit_action = "logout"
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/admin")
    request.state.admin_actor = session.username
    return response


@admin_router.get("", response_class=HTMLResponse)
def dashboard(request: Request) -> Response:
    session = _require_session(request)
    return _render_protected(
        "dashboard.html",
        request,
        session,
        title="管理概览",
        settings=request.app.state.settings.public_summary(),
    )


@admin_router.get("/image-limits", response_class=HTMLResponse)
def image_limits_page(request: Request) -> Response:
    session = _require_session(request)
    return _image_limits_response(request, session)


@admin_router.post("/image-limits/drafts")
async def create_image_limit_draft(request: Request) -> Response:
    _, form = await _protected_form(request)
    values = ImageLimitValues(
        min_width=_integer(form, "min_width"),
        min_height=_integer(form, "min_height"),
        max_width=_integer(form, "max_width"),
        max_height=_integer(form, "max_height"),
        max_bytes=_integer(form, "max_bytes"),
    )
    request.app.state.manage_image_limits.create_draft(values)
    return _redirect("/admin/image-limits")


@admin_router.post("/image-limits/{version}/publish")
async def publish_image_limits(version: int, request: Request) -> Response:
    await _protected_form(request)
    request.app.state.manage_image_limits.publish(version)
    return _redirect("/admin/image-limits")


@admin_router.post("/image-limits/{version}/rollback")
async def rollback_image_limits(version: int, request: Request) -> Response:
    await _protected_form(request)
    request.app.state.manage_image_limits.rollback(version)
    return _redirect("/admin/image-limits")


@admin_router.get("/models", response_class=HTMLResponse)
def models_page(request: Request) -> Response:
    session = _require_session(request)
    return _models_response(request, session)


@admin_router.post("/models/releases")
async def create_model_release(request: Request) -> Response:
    _, form = await _protected_form(request)
    request.app.state.manage_model_releases.create(
        ModelReleaseSpec(
            model_id=_required(form, "model_id"),
            version=_required(form, "version"),
            platform=_required(form, "platform"),
            architecture=_required(form, "architecture"),
            filename=_required(form, "filename"),
            object_key=_required(form, "object_key"),
            object_version=_required(form, "object_version"),
            size_bytes=_integer(form, "size_bytes"),
            sha256=_required(form, "sha256"),
        )
    )
    return _redirect("/admin/models")


@admin_router.post("/models/releases/{release_id}/publish")
async def publish_model_release(release_id: int, request: Request) -> Response:
    await _protected_form(request)
    request.app.state.manage_model_releases.publish(release_id)
    return _redirect("/admin/models")


@admin_router.post("/models/releases/{release_id}/withdraw")
async def withdraw_model_release(release_id: int, request: Request) -> Response:
    await _protected_form(request)
    request.app.state.manage_model_releases.withdraw(release_id)
    return _redirect("/admin/models")


@admin_router.get("/translation", response_class=HTMLResponse)
def translation_page(request: Request) -> Response:
    session = _require_session(request)
    return _translation_response(request, session)


@admin_router.post("/translation/test", response_class=HTMLResponse)
async def test_translation_connection(request: Request) -> Response:
    session, _ = await _protected_form(request)
    result = await run_in_threadpool(
        request.app.state.translate_text.execute,
        TranslationTextRequest(
            items=(TranslationTextItem("connectivity-check", "connection check"),),
            source_language="en",
            target_language="zh-Hans",
            correlation_id=request.state.correlation_id,
        ),
    )
    item = result.items[0]
    connectivity_result = (
        f"连接成功（{result.provider}）"
        if item.translated_text is not None
        else f"连接失败：{item.error_code}"
    )
    return _translation_response(request, session, connectivity_result)


def _translation_response(
    request: Request,
    session: AdminSession,
    connectivity_result: str | None = None,
) -> HTMLResponse:
    settings = request.app.state.settings
    return _render_protected(
        "translation.html",
        request,
        session,
        title="翻译服务",
        translator_configured=settings.translator_key is not None,
        translator_region_configured=settings.translator_region is not None,
        client_auth_configured=(
            settings.client_api_token is not None
            or request.app.state.device_authorization_enabled
        ),
        connectivity_result=connectivity_result,
    )


@admin_router.get("/activation", response_class=HTMLResponse)
def activation_page(request: Request) -> Response:
    session = _require_session(request)
    return _activation_response(request, session)


@admin_router.post("/activation/plans")
async def create_activation_plan(request: Request) -> Response:
    _, form = await _protected_form(request)
    request.app.state.manage_activation_plans.create(_plan_values(form))
    return _redirect("/admin/activation")


@admin_router.post("/activation/plans/{plan_id}")
async def update_activation_plan(plan_id: int, request: Request) -> Response:
    _, form = await _protected_form(request)
    request.app.state.manage_activation_plans.update(plan_id, _plan_values(form))
    return _redirect("/admin/activation")


@admin_router.post("/activation/codes", response_class=HTMLResponse)
async def issue_activation_codes(request: Request) -> Response:
    session, form = await _protected_form(request)
    if not request.app.state.device_authorization_enabled:
        raise HTTPException(status_code=503, detail="Activation service is not configured")
    issued = request.app.state.manage_activation_codes.issue(
        _integer(form, "plan_id"),
        _integer(form, "count"),
    )
    response = _activation_response(
        request,
        session,
        issued_codes=tuple(item.plaintext for item in issued),
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_router.post("/activation/codes/{code_id}/disable")
async def disable_activation_code(code_id: str, request: Request) -> Response:
    await _protected_form(request)
    request.app.state.manage_activation_codes.disable(code_id)
    return _redirect("/admin/activation")


@admin_router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request) -> Response:
    session = _require_session(request)
    return _render_protected(
        "audit.html",
        request,
        session,
        title="操作审计",
        events=request.app.state.audit_management.list_recent(),
    )


def _security(request: Request) -> AdminSecurity:
    security = request.app.state.admin_security
    if security is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Administrator console is not configured",
        )
    return security


def _require_session(request: Request) -> AdminSession:
    session = _security(request).parse_session(request.cookies.get(SESSION_COOKIE))
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Administrator login required",
            headers={"Location": "/admin/login"},
        )
    request.state.admin_actor = session.username
    return session


async def _protected_form(
    request: Request,
) -> tuple[AdminSession, dict[str, str]]:
    session = _require_session(request)
    form = await _read_form(request)
    if not _security(request).verify_csrf(session, form.get("csrf_token", "")):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return session, form


async def _read_form(request: Request) -> dict[str, str]:
    content_type = request.headers.get("Content-Type", "").split(";", 1)[0].strip()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=415, detail="Unsupported form content type")
    body = await request.body()
    if len(body) > _MAX_FORM_BYTES:
        raise HTTPException(status_code=413, detail="Form body is too large")
    try:
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=64)
    except (UnicodeDecodeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Form body is invalid") from error
    if any(len(values) != 1 for values in parsed.values()):
        raise HTTPException(status_code=422, detail="Duplicate form field")
    return {key: values[0] for key, values in parsed.items()}


def _image_limits_response(request: Request, session: AdminSession) -> HTMLResponse:
    return _render_protected(
        "image_limits.html",
        request,
        session,
        title="图片限制",
        versions=request.app.state.manage_image_limits.list_versions(),
    )


def _models_response(request: Request, session: AdminSession) -> HTMLResponse:
    return _render_protected(
        "models.html",
        request,
        session,
        title="模型发布",
        releases=request.app.state.manage_model_releases.list_all(),
    )


def _activation_response(
    request: Request,
    session: AdminSession,
    *,
    issued_codes: tuple[str, ...] = (),
) -> HTMLResponse:
    return _render_protected(
        "activation.html",
        request,
        session,
        title="激活管理",
        plans=request.app.state.manage_activation_plans.list_all(),
        codes=request.app.state.manage_activation_codes.list_all(),
        issued_codes=issued_codes,
        activation_configured=request.app.state.device_authorization_enabled,
    )


def _render_protected(
    template: str,
    request: Request,
    session: AdminSession,
    **context,
) -> HTMLResponse:
    return _render(
        template,
        request,
        username=session.username,
        csrf_token=_security(request).csrf_token(session),
        **context,
    )


def _render(
    template: str,
    request: Request,
    *,
    status_code: int = 200,
    **context,
) -> HTMLResponse:
    content = _TEMPLATES.get_template(template).render(
        request=request,
        **context,
    )
    return HTMLResponse(content, status_code=status_code)


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _required(form: dict[str, str], name: str) -> str:
    value = form.get(name, "").strip()
    if not value:
        raise HTTPException(status_code=422, detail=f"{name} is required")
    return value


def _integer(form: dict[str, str], name: str) -> int:
    try:
        return int(_required(form, name))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"{name} must be an integer") from error


def _plan_values(form: dict[str, str]) -> ActivationPlanValues:
    return ActivationPlanValues(
        name=_required(form, "name"),
        amount_minor=_integer(form, "amount_minor"),
        currency=_required(form, "currency"),
        duration_days=_integer(form, "duration_days"),
        enabled=form.get("enabled") == "true",
    )


def _secure_cookie(request: Request) -> bool:
    return request.app.state.settings.environment.lower() in {"production", "prod"}
