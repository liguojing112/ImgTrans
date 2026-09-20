"""去水印每日额度限制 — 编辑器窗口 gating 行为。"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.infrastructure.doubao_share import ShareImage
from src.infrastructure.quota_client import WatermarkQuota
from src.ui.editor.main_window import EditorMainWindow


class _FakeQuotaClient:
    def __init__(self, get_info: WatermarkQuota, consume_info: WatermarkQuota):
        self.get_info = get_info
        self.consume_info = consume_info
        self.calls: list = []

    def get_watermark(self, token: str) -> WatermarkQuota:
        self.calls.append(("get", token))
        return self.get_info

    def consume_watermark(self, token: str, amount: int = 1) -> WatermarkQuota:
        self.calls.append(("consume", token, amount))
        return self.consume_info


class _SyncTaskRunner:
    """同步执行任务，方便断言。"""

    def submit(self, work, on_success, on_error):
        try:
            on_success(work())
        except Exception as error:
            on_error(error)


def _image(key: str = "abc123") -> ShareImage:
    return ShareImage(
        url=f"https://cdn.example.test/{key}-image_raw.png",
        key=key,
        width=10,
        height=10,
        order=1,
    )


def _qapp() -> None:
    QApplication.instance() or QApplication(["watermark-quota-test"])


def _window(
    monkeypatch,
    quota_client,
    token,
    downloads: dict,
):
    monkeypatch.setattr(
        "src.ui.editor.main_window.download_image",
        lambda url: b"png-bytes",
    )
    window = EditorMainWindow(
        import_image=object(),
        task_runner=_SyncTaskRunner(),
        quota_client=quota_client,
        access_token=(lambda: token) if token is not None else None,
    )
    window._enter_editor()
    window._on_import = lambda *args, **kwargs: downloads.setdefault("imported", []).append(args)
    return window


def _status(window) -> str:
    return window._editor_page.watermark_removal_dialog.status.text()


def test_import_requires_activation(monkeypatch):
    _qapp()
    client = _FakeQuotaClient(
        WatermarkQuota(5, 0, 5), WatermarkQuota(5, 1, 4, consumed=True)
    )
    downloads: dict = {}
    window = _window(monkeypatch, client, None, downloads)
    try:
        window._on_watermark_import(_image())
        assert _status(window) == "请先激活应用，再使用去水印"
        assert client.calls == []  # 未激活不发起任何额度请求
        assert "imported" not in downloads
    finally:
        window.close()


def test_import_rejects_plan_without_watermark_quota(monkeypatch):
    _qapp()
    client = _FakeQuotaClient(
        WatermarkQuota(0, 0, 0), WatermarkQuota(0, 0, 0)
    )
    downloads: dict = {}
    window = _window(monkeypatch, client, "itd_test", downloads)
    try:
        window._on_watermark_import(_image())
        assert _status(window) == "当前套餐不含去水印次数，请购买含去水印的套餐后使用"
        assert all(call[0] != "consume" for call in client.calls)
        assert "imported" not in downloads
    finally:
        window.close()


def test_import_rejects_when_daily_quota_exhausted(monkeypatch):
    _qapp()
    client = _FakeQuotaClient(
        WatermarkQuota(5, 5, 0), WatermarkQuota(5, 5, 0)
    )
    downloads: dict = {}
    window = _window(monkeypatch, client, "itd_test", downloads)
    try:
        window._on_watermark_import(_image())
        assert _status(window) == "今日去水印次数不足：剩余 0 张，需要 1 张"
        assert all(call[0] != "consume" for call in client.calls)
        assert "imported" not in downloads
    finally:
        window.close()


def test_import_consumes_one_then_downloads(monkeypatch):
    _qapp()
    client = _FakeQuotaClient(
        WatermarkQuota(5, 0, 5), WatermarkQuota(5, 1, 4, consumed=True)
    )
    downloads: dict = {}
    window = _window(monkeypatch, client, "itd_test", downloads)
    try:
        window._on_watermark_import(_image())
        assert client.calls == [("get", "itd_test"), ("consume", "itd_test", 1)]
        assert "已取到无水印原图" in _status(window)
        assert len(downloads["imported"]) == 1
    finally:
        window.close()


def test_save_all_rejects_batch_larger_than_remaining(monkeypatch):
    _qapp()
    client = _FakeQuotaClient(
        WatermarkQuota(5, 4, 1), WatermarkQuota(5, 4, 1)
    )
    downloads: dict = {}
    window = _window(monkeypatch, client, "itd_test", downloads)
    try:
        images = (_image("a"), _image("b"), _image("c"))
        window._on_watermark_save_all(images, "/tmp/imgtrans-watermark-test")
        assert _status(window) == "今日去水印次数不足：剩余 1 张，需要 3 张"
        assert all(call[0] != "consume" for call in client.calls)
    finally:
        window.close()


def test_save_all_consumes_batch_size(monkeypatch):
    _qapp()
    client = _FakeQuotaClient(
        WatermarkQuota(5, 0, 5), WatermarkQuota(5, 3, 2, consumed=True)
    )
    downloads: dict = {}
    window = _window(monkeypatch, client, "itd_test", downloads)
    try:
        images = (_image("a"), _image("b"), _image("c"))
        window._on_watermark_save_all(images, "/tmp/imgtrans-watermark-test")
        assert ("consume", "itd_test", 3) in client.calls
        assert "已保存 3 张" in _status(window)
    finally:
        window.close()


def test_consume_rejection_during_download_blocks_import(monkeypatch):
    _qapp()
    # 预检通过但扣减被拒（并发竞争）→ 不下载、不导入
    client = _FakeQuotaClient(
        WatermarkQuota(5, 4, 1), WatermarkQuota(5, 5, 0)
    )
    downloads: dict = {}
    window = _window(monkeypatch, client, "itd_test", downloads)
    try:
        window._on_watermark_import(_image())
        assert _status(window) == "今日去水印次数不足：剩余 0 张，需要 1 张"
        assert "imported" not in downloads
    finally:
        window.close()
