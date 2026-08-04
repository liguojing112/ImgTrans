"""管理后台用户与权限领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re


class AdminUserError(ValueError):
    pass


class AdminUserNotFound(AdminUserError):
    pass


class AdminUserConflict(AdminUserError):
    pass


class AdminUserDenied(AdminUserError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# 子账号可按模块勾选的权限
SUPER_ROLE = "super"
SUB_ROLE = "sub"
SUPER_PERMISSIONS = frozenset(
    {"activation", "image_limits", "models", "translation", "audit", "users", "payments", "usage"}
)
MODULE_PERMISSIONS = frozenset(
    {"activation", "image_limits", "models", "translation", "audit", "payments", "usage"}
)
PERMISSION_LABELS = {
    "activation": "激活管理",
    "image_limits": "图片限制",
    "models": "模型发布",
    "translation": "翻译服务",
    "audit": "审计日志",
    "payments": "订单",
    "usage": "用量记录",
}


def parse_permissions(value: str) -> frozenset[str]:
    if not value:
        return frozenset()
    # users 权限仅超管序列化需要；子账号创建/勾选仍用 MODULE_PERMISSIONS 限制
    valid = MODULE_PERMISSIONS | {"users"}
    unknown = {part for part in value.split(",") if part and part not in valid}
    if unknown:
        raise AdminUserError(f"Unknown permissions: {', '.join(sorted(unknown))}")
    return frozenset(part for part in value.split(",") if part)


def format_permissions(permissions: frozenset[str]) -> str:
    return ",".join(sorted(permissions))


def validate_username(username: str) -> str:
    normalized = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", normalized):
        raise AdminUserError("Administrator username is invalid")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise AdminUserError("Administrator password must contain at least 12 characters")


@dataclass(frozen=True, slots=True)
class AdminUser:
    """后台用户（超管或子账号）。"""

    user_id: int
    username: str
    password_hash: str
    role: str
    permissions: frozenset[str]
    enabled: bool
    created_at: datetime
    last_login_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.role not in {SUPER_ROLE, SUB_ROLE}:
            raise AdminUserError("Administrator role is invalid")
        if self.role == SUPER_ROLE:
            object.__setattr__(self, "permissions", SUPER_PERMISSIONS)

    @property
    def is_super(self) -> bool:
        return self.role == SUPER_ROLE

    def has_permission(self, permission: str) -> bool:
        if self.is_super:
            return True
        return permission in self.permissions


@dataclass(frozen=True, slots=True)
class AdminUserCreate:
    """创建子账号的输入。"""

    username: str
    password: str
    permissions: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        validate_username(self.username)
        validate_password(self.password)
        unknown = self.permissions - MODULE_PERMISSIONS
        if unknown:
            raise AdminUserError(f"Unknown permissions: {', '.join(sorted(unknown))}")
