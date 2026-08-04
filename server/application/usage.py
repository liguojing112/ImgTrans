"""商品详情次数额度用例 — 查询剩余 / 原子扣减 / 用量记录。"""

from __future__ import annotations

from datetime import datetime, timezone

from server.application.activation import ActivationSecretHasher
from server.domain.activation import UsageRecord


class ManageUsage:
    def __init__(
        self,
        repository,
        hasher: ActivationSecretHasher | None,
    ) -> None:
        self._repository = repository
        self._hasher = hasher

    def get_usage(self, token: str) -> tuple[int, int]:
        """返回 (quota_total, quota_remaining)；无效 token 返回 (0,0)。"""
        if self._hasher is None:
            return (0, 0)
        return self._repository.get_usage(self._hasher.digest_token(token))

    def consume(self, token: str, amount: int = 1) -> tuple[bool, int]:
        """原子扣减一次。返回 (是否成功, 剩余次数)。"""
        if self._hasher is None:
            return (False, 0)
        return self._repository.consume_quota(
            self._hasher.digest_token(token),
            amount,
            datetime.now(timezone.utc),
        )

    def list_usage(self, limit: int = 100) -> list[UsageRecord]:
        return self._repository.list_usage(limit)
