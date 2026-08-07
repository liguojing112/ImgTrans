"""管理后台用户管理用例。"""

from __future__ import annotations

from datetime import datetime, timezone

from server.admin.security import hash_admin_password, verify_password
from server.domain.admin_users import (
    SUB_ROLE,
    SUPER_ROLE,
    AdminUser,
    AdminUserCreate,
    AdminUserDenied,
    AdminUserError,
    AdminUserNotFound,
    validate_password,
    validate_username,
)


class ManageAdminUsers:
    """后台用户 CRUD 与认证用例。"""

    def __init__(self, repository) -> None:
        self._repository = repository

    # —— 认证 ——

    def authenticate(self, username: str, password: str) -> AdminUser | None:
        user = self._repository.find_by_username(username)
        if user is None:
            return None
        if not user.enabled:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    def record_login(self, user_id: int) -> None:
        self._repository.record_login(user_id)

    # —— 种子超管（首次启动从环境变量导入） ——

    def create_super_from_env(self, username: str, password_hash: str) -> AdminUser:
        """把环境变量配置的 admin 导入为种子超管账号。"""
        normalized = validate_username(username)
        now = datetime.now(timezone.utc)
        user = AdminUser(
            user_id=0,
            username=normalized,
            password_hash=password_hash,
            role=SUPER_ROLE,
            permissions=frozenset(),
            enabled=True,
            created_at=now,
        )
        return self._repository.create(user)

    # —— 子账号管理 ——

    def create_subuser(
        self,
        username: str,
        password: str,
        permissions: frozenset[str],
    ) -> AdminUser:
        spec = AdminUserCreate(
            username=username,
            password=password,
            permissions=permissions,
        )
        now = datetime.now(timezone.utc)
        user = AdminUser(
            user_id=0,
            username=spec.username,
            password_hash=hash_admin_password(spec.password),
            role=SUB_ROLE,
            permissions=spec.permissions,
            enabled=True,
            created_at=now,
        )
        return self._repository.create(user)

    def list_all(self) -> list[AdminUser]:
        return self._repository.list_all()

    def has_super(self) -> bool:
        return self._repository.count_super() > 0

    def set_permissions(
        self, user_id: int, permissions: frozenset[str]
    ) -> AdminUser:
        user = self._require(user_id)
        if user.is_super:
            raise AdminUserDenied("cannot_edit_super", "不能修改超管账号的权限")
        return self._repository.update_permissions(user_id, permissions)

    def set_enabled(self, user_id: int, enabled: bool) -> AdminUser:
        user = self._require(user_id)
        if user.is_super:
            raise AdminUserDenied("cannot_disable_super", "不能停用超管账号")
        return self._repository.set_enabled(user_id, enabled)

    def reset_password(self, user_id: int, new_password: str) -> AdminUser:
        user = self._require(user_id)
        validate_password(new_password)
        return self._repository.update_password(
            user_id, hash_admin_password(new_password)
        )

    def delete(self, user_id: int) -> None:
        user = self._require(user_id)
        if user.is_super:
            raise AdminUserDenied("cannot_delete_super", "不能删除超管账号")
        self._repository.delete(user_id)

    def change_own_password(
        self, username: str, current_password: str, new_password: str
    ) -> AdminUser:
        user = self._repository.find_by_username(username)
        if user is None:
            raise AdminUserNotFound(f"用户不存在: {username}")
        if not verify_password(current_password, user.password_hash):
            raise AdminUserDenied("wrong_password", "当前密码不正确")
        validate_password(new_password)
        return self._repository.update_password(
            user.user_id, hash_admin_password(new_password)
        )

    # —— 辅助 ——

    def _require(self, user_id: int) -> AdminUser:
        user = self._repository.get(user_id)
        if user is None:
            raise AdminUserNotFound(f"用户不存在: {user_id}")
        return user
