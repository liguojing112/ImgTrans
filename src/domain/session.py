from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SessionChanges:
    single_image_dirty: bool = False
    pending_batch_items: set[str] = field(default_factory=set)

    @property
    def has_unexported_changes(self) -> bool:
        return self.single_image_dirty or bool(self.pending_batch_items)

    def mark_single_changed(self) -> None:
        self.single_image_dirty = True

    def mark_single_exported(self) -> None:
        self.single_image_dirty = False

    def replace_batch_results(self, item_ids: set[str]) -> None:
        self.pending_batch_items = set(item_ids)

    def mark_batch_exported(self, item_ids: set[str]) -> None:
        self.pending_batch_items.difference_update(item_ids)

    def clear_batch(self) -> None:
        self.pending_batch_items.clear()

    def clear_all(self) -> None:
        self.single_image_dirty = False
        self.pending_batch_items.clear()

    def warning_summary(self) -> str:
        parts = []
        if self.single_image_dirty:
            parts.append("当前单图有未导出的处理或编辑结果")
        if self.pending_batch_items:
            parts.append(f"批次中有 {len(self.pending_batch_items)} 张成功图片尚未导出")
        return "；".join(parts)
