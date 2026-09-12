from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from server import __version__
from server.admin.routes import admin_router
from server.admin.security import AdminSecurity
from server.api.contracts import ApiError, ErrorResponse
from server.api.activation import activation_router, admin_activation_router
from server.api.correlation import CORRELATION_HEADER, normalize_correlation_id
from server.api.image_limits import admin_image_limits_router, client_config_router
from server.api.payment import admin_payment_router, payment_router
from server.api.product_llm import llm_router
from server.api.routes import health_router, v1_router
from server.api.translation import translation_router
from server.api.usage import usage_router
from server.application.image_limits import GetClientConfig, ManageImageLimits
from server.application.activation import (
    ActivateDevice,
    ActivationSecretHasher,
    ActivationStatusCheck,
    AuthorizeDeviceToken,
    ManageActivationCodes,
    ManageActivationPlans,
    UnavailableDeviceTokenAuthorizer,
)
from server.application.audit import AuditManagementAction
from server.application.admin_users import ManageAdminUsers
from server.application.payment import (
    CreatePaymentOrder,
    GetPaymentOrder,
    RefundPaymentOrder,
    HandlePaymentCallback,
    ListPaymentOrders,
)
from server.application.service_settings import (
    DEFAULT_WECHAT_NOTIFY_URL,
    ManageServiceSettings,
)
from server.application.usage import ManageUsage
from server.application.translation import TranslateText, TranslationProvider
from server.config import ServerSettings
from server.infrastructure.database import Database
from server.infrastructure.admin_user_repository import SqlAlchemyAdminUserRepository
from server.infrastructure.payment_repository import SqlAlchemyPaymentRepository
from server.infrastructure.secrets_cipher import SecretsCipher
from server.infrastructure.service_settings_repository import (
    SqlAlchemyServiceSettingsRepository,
)
from server.infrastructure.wechat_pay_gateway import (
    UnavailableWechatGateway,
    WechatPayV3Gateway,
)
from server.infrastructure.glm_gateway import GlmGateway
from server.infrastructure.image_limits_repository import (
    SqlAlchemyImageLimitRepository,
)
from server.infrastructure.activation_repository import SqlAlchemyActivationRepository
from server.infrastructure.audit_repository import SqlAlchemyAuditRepository
from server.infrastructure.rate_limiter import InMemoryRateLimiter
from server.domain.activation import (
    ActivationConflict,
    ActivationError,
    ActivationNotFound,
)
from server.domain.image_limits import (
    ImageLimitConflict,
    ImageLimitError,
    ImageLimitNotFound,
)
from server.domain.payment import (
    PaymentConflict,
    PaymentError,
    PaymentNotFound,
)
from server.infrastructure.microsoft_translator import (
    MicrosoftTranslatorAdapter,
    UnavailableTranslationProvider,
)


def create_app(
    settings: ServerSettings | None = None,
    database: Database | None = None,
    translation_provider: TranslationProvider | None = None,
) -> FastAPI:
    settings = settings or ServerSettings.from_env()
    database = database or Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        database.close()

    app = FastAPI(
        title="ImgTrans API",
        version=__version__,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.rate_limiter = InMemoryRateLimiter()
    audit_repository = SqlAlchemyAuditRepository(database)
    app.state.audit_management = AuditManagementAction(audit_repository)
    admin_user_repository = SqlAlchemyAdminUserRepository(database)
    app.state.manage_admin_users = ManageAdminUsers(admin_user_repository)
    if (
        settings.admin_session_secret is not None
        and settings.admin_username is not None
        and settings.admin_password_hash is not None
    ):
        if not app.state.manage_admin_users.has_super():
            try:
                app.state.manage_admin_users.create_super_from_env(
                    settings.admin_username,
                    settings.admin_password_hash,
                )
            except Exception:
                logging.getLogger("imgtrans.server").exception(
                    "seed_admin_user_failed"
                )
    app.state.admin_security = (
        AdminSecurity(
            settings.admin_session_secret,
            settings.admin_session_ttl_seconds,
            authenticate=app.state.manage_admin_users.authenticate,
        )
        if settings.admin_session_secret is not None
        else None
    )
    image_limit_repository = SqlAlchemyImageLimitRepository(database)
    app.state.manage_image_limits = ManageImageLimits(image_limit_repository)
    app.state.get_client_config = GetClientConfig(
        image_limit_repository,
        settings.client_config_ttl_seconds,
    )
    settings_cipher = SecretsCipher.load(
        Path(__file__).resolve().parent.parent / "config" / "settings-key.bin"
    )
    activation_repository = SqlAlchemyActivationRepository(
        database, cipher=settings_cipher
    )
    app.state.manage_activation_plans = ManageActivationPlans(activation_repository)
    activation_hasher = (
        ActivationSecretHasher(settings.activation_secret)
        if settings.activation_secret is not None
        else None
    )
    app.state.manage_activation_codes = ManageActivationCodes(
        activation_repository,
        activation_hasher,
    )
    app.state.device_authorization_enabled = activation_hasher is not None
    app.state.manage_usage = ManageUsage(activation_repository, activation_hasher)
    if activation_hasher is not None:
        app.state.activate_device = ActivateDevice(
            activation_repository,
            activation_hasher,
        )
        app.state.authorize_device_token = AuthorizeDeviceToken(
            activation_repository,
            activation_hasher,
        )
        app.state.activation_status_check = ActivationStatusCheck(
            activation_repository,
            activation_hasher,
        )
    else:
        app.state.activate_device = None
        app.state.authorize_device_token = UnavailableDeviceTokenAuthorizer()
        app.state.activation_status_check = None
    payment_repository = SqlAlchemyPaymentRepository(database)

    # 第三方服务配置（微信密钥加密存数据库，可运行期切换）
    service_settings_repository = SqlAlchemyServiceSettingsRepository(database)
    app.state.manage_service_settings = ManageServiceSettings(
        settings_cipher,
        service_settings_repository,
        notify_url=settings.wechat_notify_url or DEFAULT_WECHAT_NOTIFY_URL,
    )

    def _wechat_config_provider():
        database_config = app.state.manage_service_settings.load_wechat_settings()
        if database_config:
            return database_config
        if settings.wechat_pay_configured:
            return {
                "appid": settings.wechat_appid,
                "mchid": settings.wechat_mchid,
                "apiv3_key": settings.wechat_apiv3_key,
                "private_key": settings.wechat_private_key,
                "serial_no": settings.wechat_serial_no,
                "platform_cert": settings.wechat_platform_cert,
                "notify_url": settings.wechat_notify_url,
            }
        return None

    payment_gateway = WechatPayV3Gateway(_wechat_config_provider)

    def _glm_config_provider():
        database_config = app.state.manage_service_settings.load_glm_settings()
        if database_config:
            return database_config
        if settings.glm_api_key:
            return {
                "api_key": settings.glm_api_key,
                "model": settings.glm_model or "",
                "base_url": settings.glm_base_url or "",
            }
        return None

    app.state.glm_gateway = GlmGateway(_glm_config_provider)
    app.state.create_payment_order = CreatePaymentOrder(
        payment_gateway,
        app.state.manage_activation_plans,
        payment_repository,
        activation_codes=app.state.manage_activation_codes,
    )
    app.state.handle_payment_callback = HandlePaymentCallback(
        payment_gateway,
        payment_repository,
        app.state.manage_activation_codes.issue,
        app.state.manage_activation_plans,
        renew_code=app.state.manage_activation_codes.renew_by_code_id,
    )
    app.state.get_payment_order = GetPaymentOrder(payment_repository)
    app.state.refund_payment_order = RefundPaymentOrder(payment_repository)
    app.state.list_payment_orders = ListPaymentOrders(payment_repository)
    if translation_provider is None:
        translation_provider = (
            MicrosoftTranslatorAdapter(
                settings.translator_endpoint,
                settings.translator_key,
                settings.translator_region,
                settings.translator_timeout_seconds,
            )
            if settings.translator_key is not None
            else UnavailableTranslationProvider()
        )
    app.state.translate_text = TranslateText(translation_provider)

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        correlation_id = normalize_correlation_id(
            request.headers.get(CORRELATION_HEADER)
        )
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and response.status_code < 400
            and (
                request.url.path.startswith("/v1/admin/")
                or request.url.path.startswith("/admin")
            )
        ):
            actor = getattr(request.state, "admin_actor", None)
            if actor is not None:
                try:
                    app.state.audit_management.record(
                        actor=actor,
                        action=getattr(
                            request.state,
                            "audit_action",
                            request.method.lower(),
                        ),
                        resource=request.url.path,
                        correlation_id=correlation_id,
                        status_code=response.status_code,
                    )
                except Exception:
                    logging.getLogger("imgtrans.server").exception(
                        "administrator_audit_write_failed correlation_id=%s",
                        correlation_id,
                    )
        response.headers[CORRELATION_HEADER] = correlation_id
        if request.url.path.startswith("/admin") and not request.url.path.startswith(
            "/admin/static/"
        ):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; "
                "frame-ancestors 'none'; base-uri 'none'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            if settings.environment.lower() in {"production", "prod"}:
                response.headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains"
                )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        message = error.detail if isinstance(error.detail, str) else "Request failed"
        return _error_response(
            request,
            error.status_code,
            "http_error",
            message,
            error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, _: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            request,
            422,
            "invalid_request",
            "Request validation failed",
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, _: Exception) -> JSONResponse:
        return _error_response(
            request,
            500,
            "internal_error",
            "Internal server error",
        )

    async def domain_error(request: Request, error: ValueError) -> JSONResponse:
        if isinstance(
            error,
            (ActivationNotFound, ImageLimitNotFound),
        ):
            status_code = 404
        elif isinstance(
            error,
            (ActivationConflict, ImageLimitConflict),
        ):
            status_code = 409
        else:
            status_code = 422
        return _error_response(
            request,
            status_code,
            "domain_error",
            str(error),
        )

    for error_type in (ActivationError, ImageLimitError, PaymentError):
        app.add_exception_handler(error_type, domain_error)

    app.include_router(health_router)
    app.include_router(v1_router)
    app.include_router(client_config_router)
    app.include_router(admin_image_limits_router)
    app.include_router(translation_router)
    app.include_router(activation_router)
    app.include_router(admin_activation_router)
    app.include_router(payment_router)
    app.include_router(llm_router)
    app.include_router(admin_payment_router)
    app.include_router(usage_router)
    app.mount(
        "/admin/static",
        StaticFiles(directory=Path(__file__).parent / "admin" / "static"),
        name="admin-static",
    )
    app.include_router(admin_router)
    return app


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    correlation_id = getattr(
        request.state,
        "correlation_id",
        normalize_correlation_id(None),
    )
    payload = ErrorResponse(
        error=ApiError(
            code=code,
            message=message,
            correlation_id=correlation_id,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
        headers=headers,
    )
