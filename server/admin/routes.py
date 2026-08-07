from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

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
from server.domain.activation import ActivationConflict, ActivationError, ActivationPlanValues
from server.domain.admin_users import (
    AdminUserError,
    MODULE_PERMISSIONS,
    PERMISSION_LABELS,
)
from server.domain.image_limits import ImageLimitConflict, ImageLimitValues
from server.api.rate_limit import enforce_rate_limit
from server.domain.translation import TranslationTextItem, TranslationTextRequest


_ROOT = Path(__file__).resolve().parent
_TEMPLATES = Environment(
    loader=FileSystemLoader(_ROOT / "templates"),
    autoescape=select_autoescape(("html", "xml")),
)
_MAX_FORM_BYTES = 64 * 1024
_BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")

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
    if credentials_valid is None:
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
        security.create_session(
            credentials_valid.username,
            credentials_valid.role,
            credentials_valid.permissions,
        ),
        max_age=security.session_ttl_seconds,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="strict",
        path="/admin",
    )
    response.delete_cookie(LOGIN_NONCE_COOKIE, path="/admin")
    request.state.admin_actor = credentials_valid.username
    request.state.audit_action = "login"
    manage = getattr(request.app.state, "manage_admin_users", None)
    if manage is not None:
        manage.record_login(credentials_valid.user_id)
    return response


@admin_router.post("/logout")
async def logout(request: Request) -> Response:
    session, _ = await _protected_form(request)
    request.state.audit_action = "logout"
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/admin")
    request.state.admin_actor = session.username
    return response


_DASHBOARD_LABELS = {
    "environment": "运行环境",
    "host": "服务地址",
    "port": "端口",
    "log_level": "日志级别",
    "docs_enabled": "API 文档",
    "client_config_ttl_seconds": "客户端配置缓存（秒）",
    "translator_configured": "翻译服务",
    "activation_configured": "激活服务",
    "admin_console_configured": "管理后台",
    "wechat_pay_configured": "微信支付",
}


@admin_router.get("", response_class=HTMLResponse)
def dashboard(request: Request) -> Response:
    session = _require_session(request)
    summary = request.app.state.settings.public_summary()
    return _render_protected(
        "dashboard.html",
        request,
        session,
        title="管理概览",
        settings=[
            (_DASHBOARD_LABELS.get(key, key), value)
            for key, value in summary.items()
        ],
    )


@admin_router.get("/image-limits", response_class=HTMLResponse)
def image_limits_page(request: Request) -> Response:
    session = _require_session(request)
    _require_permission(request, session, "image_limits")
    return _image_limits_response(request, session)


@admin_router.post("/image-limits/drafts")
async def create_image_limit_draft(request: Request) -> Response:
    session, form = await _protected_form(request)
    _require_permission(request, session, "image_limits")
    values = ImageLimitValues(
        min_width=_integer(form, "min_width"),
        min_height=_integer(form, "min_height"),
        max_width=_integer(form, "max_width"),
        max_height=_integer(form, "max_height"),
        max_bytes=_max_bytes(form),
    )
    request.app.state.manage_image_limits.create_draft(values)
    request.state.audit_action = "create_image_limit_draft"
    return _redirect("/admin/image-limits")


@admin_router.post("/image-limits/{version}/publish")
async def publish_image_limits(version: int, request: Request) -> Response:
    session, _ = await _protected_form(request)
    _require_permission(request, session, "image_limits")
    request.app.state.manage_image_limits.publish(version)
    request.state.audit_action = "publish_image_limits"
    return _redirect("/admin/image-limits")


@admin_router.post("/image-limits/{version}/rollback")
async def rollback_image_limits(version: int, request: Request) -> Response:
    session, _ = await _protected_form(request)
    _require_permission(request, session, "image_limits")
    request.app.state.manage_image_limits.rollback(version)
    request.state.audit_action = "rollback_image_limits"
    return _redirect("/admin/image-limits")


@admin_router.post("/image-limits/{version}/delete")
async def delete_image_limit_version(version: int, request: Request) -> Response:
    session, _ = await _protected_form(request)
    _require_permission(request, session, "image_limits")
    try:
        request.app.state.manage_image_limits.delete(version)
    except ImageLimitConflict as error:
        raise HTTPException(status_code=409, detail=str(error))
    request.state.audit_action = "delete_image_limit_version"
    return _redirect("/admin/image-limits")


@admin_router.get("/translation", response_class=HTMLResponse)
def translation_page(request: Request) -> Response:
    session = _require_session(request)
    _require_permission(request, session, "translation")
    return _translation_response(request, session)


@admin_router.post("/translation/test", response_class=HTMLResponse)
async def test_translation_connection(request: Request) -> Response:
    session, _ = await _protected_form(request)
    _require_permission(request, session, "translation")
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
    request.state.audit_action = "test_translation"
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
    _require_permission(request, session, "activation")
    return _activation_response(request, session)


@admin_router.post("/activation/plans")
async def create_activation_plan(request: Request) -> Response:
    session, form = await _protected_form(request)
    _require_permission(request, session, "activation")
    try:
        request.app.state.manage_activation_plans.create(_plan_values(form))
    except ActivationError as error:
        return _activation_response(request, session, error=_plan_error_message(error))
    request.state.audit_action = "create_activation_plan"
    return _redirect("/admin/activation")


@admin_router.post("/activation/plans/{plan_id}")
async def update_activation_plan(plan_id: int, request: Request) -> Response:
    session, form = await _protected_form(request)
    _require_permission(request, session, "activation")
    try:
        request.app.state.manage_activation_plans.update(plan_id, _plan_values(form))
    except ActivationError as error:
        return _activation_response(request, session, error=_plan_error_message(error))
    request.state.audit_action = "update_activation_plan"
    return _redirect("/admin/activation")


@admin_router.post("/activation/plans/{plan_id}/delete")
async def delete_activation_plan(plan_id: int, request: Request) -> Response:
    session, _ = await _protected_form(request)
    _require_permission(request, session, "activation")
    try:
        request.app.state.manage_activation_plans.delete(plan_id)
    except ActivationConflict as error:
        raise HTTPException(status_code=409, detail=str(error))
    request.state.audit_action = "delete_activation_plan"
    return _redirect("/admin/activation")


@admin_router.post("/activation/codes", response_class=HTMLResponse)
async def issue_activation_codes(request: Request) -> Response:
    session, form = await _protected_form(request)
    _require_permission(request, session, "activation")
    if not request.app.state.device_authorization_enabled:
        raise HTTPException(status_code=503, detail="Activation service is not configured")
    issued = request.app.state.manage_activation_codes.issue(
        _integer(form, "plan_id"),
        _integer(form, "count"),
    )
    request.state.audit_action = "issue_activation_codes"
    response = _activation_response(
        request,
        session,
        issued_codes=tuple(item.plaintext for item in issued),
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_router.post("/activation/codes/{code_id}/disable")
async def disable_activation_code(code_id: str, request: Request) -> Response:
    session, _ = await _protected_form(request)
    _require_permission(request, session, "activation")
    request.app.state.manage_activation_codes.disable(code_id)
    request.state.audit_action = "disable_activation_code"
    return _redirect("/admin/activation")


@admin_router.post("/activation/codes/{code_id}/enable")
async def enable_activation_code(code_id: str, request: Request) -> Response:
    session, _ = await _protected_form(request)
    _require_permission(request, session, "activation")
    request.app.state.manage_activation_codes.enable(code_id)
    request.state.audit_action = "enable_activation_code"
    return _redirect("/admin/activation")


_AUDIT_LABELS = {
    "login": "登录",
    "logout": "退出",
    "update_service_settings": "更新第三方配置",
    "create_admin_user": "新建账号",
    "update_admin_user_permissions": "修改账号权限",
    "enable_admin_user": "启用账号",
    "disable_admin_user": "停用账号",
    "reset_admin_user_password": "重置密码",
    "delete_admin_user": "删除子账号",
    "change_password": "修改密码",
    "create_activation_plan": "新建方案",
    "update_activation_plan": "修改方案",
    "delete_activation_plan": "删除方案",
    "issue_activation_codes": "手工发码",
    "disable_activation_code": "停用激活码",
    "enable_activation_code": "启用激活码",
    "create_image_limit_draft": "新建图片限制",
    "publish_image_limits": "发布图片限制",
    "rollback_image_limits": "回滚图片限制",
    "delete_image_limit_version": "删除图片限制版本",
    "test_translation": "测试翻译连接",
    "post": "表单提交",
    "get": "查看",
    "put": "修改",
    "delete": "删除",
}


def _format_beijing_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_BEIJING_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


@admin_router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request) -> Response:
    session = _require_session(request)
    _require_permission(request, session, "audit")
    return _render_protected(
        "audit.html",
        request,
        session,
        title="操作审计",
        events=request.app.state.audit_management.list_recent(),
        audit_labels=_AUDIT_LABELS,
        format_beijing_time=_format_beijing_time,
    )


# —— 订单管理（payments 权限） ——


@admin_router.get("/payments", response_class=HTMLResponse)
def payments_page(request: Request) -> Response:
    session = _require_session(request)
    _require_permission(request, session, "payments")
    listing = getattr(request.app.state, "list_payment_orders", None)
    page = max(1, _query_int(request, "page", 1))
    search = (request.query_params.get("q") or "").strip() or None
    orders, total = (
        listing.execute(page, _PAGE_SIZE, search)
        if listing is not None
        else ((), 0)
    )
    pages = max(1, -(-total // _PAGE_SIZE))
    code_states = request.app.state.manage_activation_codes.states(
        tuple(order.code_id for order in orders if order.code_id)
    )
    return _render_protected(
        "payments.html",
        request,
        session,
        title="订单",
        orders=orders,
        page=page,
        pages=pages,
        total=total,
        search=search or "",
        code_states=code_states,
    )


# —— 第三方配置（仅超管） ——


def _require_super(session: AdminSession) -> None:
    if session.role != "super":
        raise HTTPException(status_code=403, detail="仅超管可访问")


@admin_router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> Response:
    session = _require_session(request)
    _require_super(session)
    manage = getattr(request.app.state, "manage_service_settings", None)
    public = manage.get_public() if manage is not None else {}
    return _render_protected(
        "settings.html",
        request,
        session,
        title="第三方配置",
        settings=public,
    )


@admin_router.post("/settings")
async def save_settings(request: Request) -> Response:
    session, form = await _protected_form(request)
    _require_super(session)
    manage = getattr(request.app.state, "manage_service_settings", None)
    if manage is None:
        raise HTTPException(status_code=503, detail="第三方配置未启用")
    section = form.get("section", "wechat")
    if section == "glm":
        manage.save_glm(
            {
                "glm_api_key": form.get("glm_api_key", ""),
                "glm_model": form.get("glm_model", ""),
            }
        )
    else:
        manage.save_wechat(
            {
                "wechat_appid": form.get("wechat_appid", ""),
                "wechat_mchid": form.get("wechat_mchid", ""),
                "wechat_apiv3_key": form.get("wechat_apiv3_key", ""),
                "wechat_private_key": form.get("wechat_private_key", ""),
                "wechat_serial_no": form.get("wechat_serial_no", ""),
                "wechat_platform_cert": form.get("wechat_platform_cert", ""),
                "wechat_public_key_id": form.get("wechat_public_key_id", ""),
                "wechat_notify_url": form.get("wechat_notify_url", ""),
            }
        )
    request.state.audit_action = "update_service_settings"
    return _redirect("/admin/settings")


# —— 用量记录（usage 权限） ——


@admin_router.get("/usage", response_class=HTMLResponse)
def usage_page(request: Request) -> Response:
    session = _require_session(request)
    _require_permission(request, session, "usage")
    manage = getattr(request.app.state, "manage_usage", None)
    page = max(1, _query_int(request, "page", 1))
    search = (request.query_params.get("q") or "").strip() or None
    records, total = (
        manage.list_page(page, _PAGE_SIZE, search)
        if manage is not None
        else ((), 0)
    )
    pages = max(1, -(-total // _PAGE_SIZE))
    return _render_protected(
        "usage.html",
        request,
        session,
        title="用量记录",
        records=records,
        page=page,
        pages=pages,
        total=total,
        search=search or "",
    )


# —— 账号管理（仅超管 / users 权限） ——


def _manage_users(request: Request):
    manage = getattr(request.app.state, "manage_admin_users", None)
    if manage is None:
        raise HTTPException(status_code=503, detail="用户管理未配置")
    return manage


def _selected_permissions(form: dict[str, str]) -> frozenset[str]:
    return frozenset(
        key for key in MODULE_PERMISSIONS if form.get(f"perm_{key}") == "true"
    )


@admin_router.get("/users", response_class=HTMLResponse)
def users_page(request: Request) -> Response:
    session = _require_session(request)
    _require_permission(request, session, "users")
    return _render_protected(
        "users.html",
        request,
        session,
        title="账号管理",
        users=_manage_users(request).list_all(),
        permission_labels=PERMISSION_LABELS,
    )


@admin_router.post("/users")
async def create_admin_user(request: Request) -> Response:
    session, form = await _protected_form(request)
    _require_permission(request, session, "users")
    try:
        _manage_users(request).create_subuser(
            form.get("username", ""),
            form.get("password", ""),
            _selected_permissions(form),
        )
    except AdminUserError as error:
        raise HTTPException(status_code=422, detail=str(error))
    request.state.audit_action = "create_admin_user"
    return _redirect("/admin/users")


@admin_router.post("/users/{user_id}/permissions")
async def update_admin_user_permissions(user_id: int, request: Request) -> Response:
    session, form = await _protected_form(request)
    _require_permission(request, session, "users")
    try:
        _manage_users(request).set_permissions(user_id, _selected_permissions(form))
    except AdminUserError as error:
        raise HTTPException(status_code=422, detail=str(error))
    request.state.audit_action = "update_admin_user_permissions"
    return _redirect("/admin/users")


@admin_router.post("/users/{user_id}/enable")
async def enable_admin_user(user_id: int, request: Request) -> Response:
    session, _ = await _protected_form(request)
    _require_permission(request, session, "users")
    try:
        _manage_users(request).set_enabled(user_id, True)
    except AdminUserError as error:
        raise HTTPException(status_code=422, detail=str(error))
    request.state.audit_action = "enable_admin_user"
    return _redirect("/admin/users")


@admin_router.post("/users/{user_id}/disable")
async def disable_admin_user(user_id: int, request: Request) -> Response:
    session, _ = await _protected_form(request)
    _require_permission(request, session, "users")
    try:
        _manage_users(request).set_enabled(user_id, False)
    except AdminUserError as error:
        raise HTTPException(status_code=422, detail=str(error))
    request.state.audit_action = "disable_admin_user"
    return _redirect("/admin/users")


@admin_router.post("/users/{user_id}/reset-password")
async def reset_admin_user_password(user_id: int, request: Request) -> Response:
    session, form = await _protected_form(request)
    _require_permission(request, session, "users")
    try:
        _manage_users(request).reset_password(user_id, form.get("password", ""))
    except AdminUserError as error:
        raise HTTPException(status_code=422, detail=str(error))
    request.state.audit_action = "reset_admin_user_password"
    return _redirect("/admin/users")


@admin_router.post("/users/{user_id}/delete")
async def delete_admin_user(user_id: int, request: Request) -> Response:
    session, _ = await _protected_form(request)
    _require_permission(request, session, "users")
    try:
        _manage_users(request).delete(user_id)
    except AdminUserError as error:
        raise HTTPException(status_code=422, detail=str(error))
    request.state.audit_action = "delete_admin_user"
    return _redirect("/admin/users")


@admin_router.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request) -> Response:
    session = _require_session(request)
    return _render_protected(
        "change_password.html",
        request,
        session,
        title="修改密码",
        error=None,
    )


@admin_router.post("/change-password")
async def change_own_password(request: Request) -> Response:
    session, form = await _protected_form(request)
    try:
        _manage_users(request).change_own_password(
            session.username,
            form.get("current_password", ""),
            form.get("new_password", ""),
        )
    except AdminUserError as error:
        return _render_protected(
            "change_password.html",
            request,
            session,
            title="修改密码",
            error=str(error),
        )
    request.state.audit_action = "change_password"
    return _redirect("/admin")


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


def _require_permission(request: Request, session: AdminSession, permission: str) -> None:
    if session.role != "super" and permission not in session.permissions:
        raise HTTPException(status_code=403, detail="无权限访问该模块")


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


_PLAN_ERROR_MESSAGES = {
    "Activation plan sale price is invalid": "促销价必须低于原价（单位：元）",
    "Activation plan duration is invalid": "时长（小时）必须在 0~87600 之间",
    "Activation plan quota is invalid": "次数必须在 0~1000000 之间",
    "Activation plan must include duration or quota": "方案必须包含时长或次数",
    "Duration plan requires duration hours": "时长包必须填写时长（小时）",
    "Quota plan requires quota": "次数包必须填写次数",
    "Combo plan requires both duration and quota": "组合包必须同时填写时长和次数",
    "Activation plan amount cannot be negative": "原价不能为负数",
    "Activation plan currency is invalid": "货币代码无效（需 3 位大写字母）",
}


def _plan_error_message(error: ActivationError) -> str:
    return _PLAN_ERROR_MESSAGES.get(str(error), str(error))


def _activation_response(
    request: Request,
    session: AdminSession,
    *,
    issued_codes: tuple[str, ...] = (),
    error: str | None = None,
) -> HTMLResponse:
    page = max(1, _query_int(request, "page", 1))
    status = (request.query_params.get("status") or "").strip() or None
    search = (request.query_params.get("q") or "").strip()
    codes, total = request.app.state.manage_activation_codes.list_page(
        page, _PAGE_SIZE, status, search or None
    )
    pages = max(1, -(-total // _PAGE_SIZE))
    plans = request.app.state.manage_activation_plans.list_all()
    return _render_protected(
        "activation.html",
        request,
        session,
        title="激活管理",
        plans=plans,
        plan_names={plan.plan_id: plan.values.name for plan in plans},
        codes=codes,
        issued_codes=issued_codes,
        activation_configured=request.app.state.device_authorization_enabled,
        search=search,
        status=status or "all",
        page=page,
        pages=pages,
        total=total,
        error=error,
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
        role=session.role,
        permissions=session.permissions,
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


_PAGE_SIZE = 50


def _query_int(request: Request, name: str, default: int) -> int:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _integer(form: dict[str, str], name: str) -> int:
    try:
        return int(_required(form, name))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"{name} must be an integer") from error


# 数据库 max_bytes 为 PostgreSQL Integer（int32），上限约 2GB
_INT32_MAX = 2_147_483_647


def _max_bytes(form: dict[str, str], name: str = "max_bytes") -> int:
    """后台以 KB 输入，转换为字节并校验不超数据库 int32 上限。"""
    kilobytes = _integer(form, name)
    value = kilobytes * 1024
    if value > _INT32_MAX:
        raise HTTPException(
            status_code=422,
            detail="最大文件大小过大，请设置不超过 2097151 KB（约 2GB）",
        )
    return value


def _integer_or_zero(form: dict[str, str], name: str) -> int:
    raw = form.get(name, "").strip()
    if not raw:
        return 0
    return _integer(form, name)


def _yuan_to_minor(form: dict[str, str], name: str) -> int:
    """后台表单以"元"填金额，转换为内部分单位。"""
    raw = form.get(name, "").strip()
    if not raw:
        return 0
    try:
        return int(round(float(raw) * 100))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"{name} 金额格式无效") from error


def _plan_values(form: dict[str, str]) -> ActivationPlanValues:
    from datetime import datetime, timezone

    plan_type = form.get("plan_type", "duration")
    sale_amount_raw = form.get("sale_amount_minor", "").strip()
    sale_ends_raw = form.get("sale_ends_at", "").strip()
    sale_ends_at = None
    if sale_ends_raw:
        try:
            sale_ends_at = datetime.fromisoformat(sale_ends_raw)
            if sale_ends_at.tzinfo is None:
                sale_ends_at = sale_ends_at.replace(tzinfo=timezone.utc)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="促销截止时间格式无效") from error
    return ActivationPlanValues(
        name=_required(form, "name"),
        amount_minor=_yuan_to_minor(form, "amount_minor"),
        currency=_required(form, "currency"),
        duration_hours=_integer_or_zero(form, "duration_hours"),
        enabled=form.get("enabled") == "true",
        plan_type=plan_type,
        quota=_integer_or_zero(form, "quota"),
        sale_amount_minor=(
            _yuan_to_minor(form, "sale_amount_minor") if sale_amount_raw else None
        ),
        sale_ends_at=sale_ends_at,
        benefits=form.get("benefits", ""),
    )


def _secure_cookie(request: Request) -> bool:
    return request.app.state.settings.environment.lower() in {"production", "prod"}
