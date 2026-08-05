"""商品详情生成主窗口 — 三步式工作流。

顶部栏: 返回首页 | 标题 | 保存
步骤指示器 | QStackedWidget(第1步/第2步/第3步)
文件菜单: 保存项目 / 打开项目
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src.application.product_analysis import AnalyzeProduct
from src.application.copywriting import GenerateCopywriting
from src.application.product_export import ExportCopywriting
from src.domain.product_info import ProductProject
from src.infrastructure.llm_adapter import LLMAdapter
from src.infrastructure.project_store import ProjectStore
from src.ui.editor.theme import EDITOR_DARK_THEME
from src.ui.product.product_model import ProductModel
from src.ui.product.step_source import StepSource
from src.ui.product.step_analysis import StepAnalysis
from src.ui.product.step_copywriting import StepCopywriting
from src.ui.product.widgets.step_indicator import StepIndicator


class ProductWindow(QMainWindow):
    """商品详情生成主窗口 — 三步式工作流。"""

    back_requested = Signal()
    parse_hint_signal = Signal(str)  # 解析中的用户提示（跨线程）

    _AUTO_SAVE_INTERVAL = 60_000  # 自动保存间隔（毫秒）
    _ANALYZE_TIMEOUT = 300  # 分析超时（秒）
    _GENERATE_TIMEOUT = 600  # 生成超时（秒）

    def __init__(
        self,
        task_runner: object,
        codec: object,
        ocr_adapter: object,
        llm_adapter: LLMAdapter,
        quota_client=None,
        access_token=None,
    ) -> None:
        super().__init__()
        self.setProperty("editorStyle", True)
        self.setObjectName("productWindow")
        self.setWindowTitle("优译图AI - 商品详情生成")
        self.setMinimumSize(1024, 680)
        self.resize(1280, 820)

        self._task_runner = task_runner
        self._codec = codec
        self._ocr = ocr_adapter
        self._llm = llm_adapter
        self._quota_client = quota_client
        self._access_token = access_token
        self._project_id: str | None = None
        self._project_store: ProjectStore | None = None

        self._model = ProductModel()
        self._cancel_requested = False
        self._generating = False
        self._regenerating_items: set[str] = set()
        self._task_start_time: float = 0.0

        self._analyze_product = AnalyzeProduct(ocr_adapter, llm_adapter, image_loader=codec.load)
        self._generate_copywriting = GenerateCopywriting(llm_adapter)
        self._export_copywriting = ExportCopywriting()

        self._build_ui()
        self._connect_signals()
        self.setStyleSheet(EDITOR_DARK_THEME)

        # 自动保存
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.timeout.connect(self._on_auto_save)
        self._auto_save_timer.start(self._AUTO_SAVE_INTERVAL)

    def _build_ui(self) -> None:
        central = QWidget()
        central.setProperty("editorStyle", True)
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部栏
        top_bar = QWidget()
        top_bar.setFixedHeight(44)
        top_bar.setStyleSheet("background: #232336;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 4, 12, 4)

        back_btn = QPushButton("← 返回首页")
        back_btn.clicked.connect(self.back_requested.emit)
        top_layout.addWidget(back_btn)

        title = QLabel("商品详情生成")
        title.setStyleSheet("color: #e0e0f0; font-size: 15px; font-weight: bold;")
        top_layout.addWidget(title)

        top_layout.addStretch()

        save_btn = QPushButton("💾 保存")
        save_btn.setToolTip("保存当前项目")
        save_btn.clicked.connect(self._on_save_project)
        top_layout.addWidget(save_btn)

        layout.addWidget(top_bar)

        # 步骤指示器
        self._step_indicator = StepIndicator()
        layout.addWidget(self._step_indicator)

        # 步骤页面
        self._step_stack = QStackedWidget()
        self._step_source = StepSource()
        self._step_analysis = StepAnalysis()
        self._step_copywriting = StepCopywriting()
        self._step_stack.addWidget(self._step_source)
        self._step_stack.addWidget(self._step_analysis)
        self._step_stack.addWidget(self._step_copywriting)
        layout.addWidget(self._step_stack, stretch=1)

        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("就绪")
        self._build_menus()

    def _build_menus(self) -> None:
        menu = self.menuBar()
        menu.setNativeMenuBar(False)

        file_menu = menu.addMenu("文件")
        save_action = QAction("保存项目", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self._on_save_project)
        file_menu.addAction(save_action)

        load_action = QAction("打开项目...", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self._on_load_project)
        file_menu.addAction(load_action)

        file_menu.addSeparator()

        rename_action = QAction("重命名项目", self)
        rename_action.triggered.connect(self._on_rename_project)
        file_menu.addAction(rename_action)

        duplicate_action = QAction("复制项目", self)
        duplicate_action.triggered.connect(self._on_duplicate_project)
        file_menu.addAction(duplicate_action)

        file_menu.addSeparator()

        delete_action = QAction("删除项目...", self)
        delete_action.triggered.connect(self._on_delete_project)
        file_menu.addAction(delete_action)

    def _connect_signals(self) -> None:
        self._step_indicator.step_clicked.connect(self._on_step_clicked)
        self._step_source.next_requested.connect(self._go_to_analysis)
        self._step_source.parse_requested.connect(self._on_parse_link)
        self.parse_hint_signal.connect(self._on_parse_hint)
        self._step_analysis.analyze_requested.connect(self._on_analyze)
        self._step_analysis.next_requested.connect(self._go_to_copywriting)
        self._step_analysis.prev_requested.connect(self._go_to_source)
        self._step_analysis.fact_changed.connect(self._on_fact_changed)
        self._step_analysis.fact_confirmed.connect(self._on_fact_confirmed)
        self._step_analysis.fact_uncertain.connect(self._on_fact_uncertain)
        self._step_copywriting.generate_all_requested.connect(self._on_generate)
        self._step_copywriting.generate_tags_requested.connect(
            lambda: self._on_regenerate_item("tags"))
        self._step_copywriting.generate_keywords_requested.connect(
            lambda: self._on_regenerate_item("keywords"))
        self._step_copywriting.generate_titles_requested.connect(
            lambda: self._on_regenerate_item("titles"))
        self._step_copywriting.generate_selling_points_requested.connect(
            lambda: self._on_regenerate_item("selling_points"))
        self._step_copywriting.generate_intro_requested.connect(
            lambda: self._on_regenerate_item("intro"))
        self._step_copywriting.generate_detail_requested.connect(
            lambda section: self._on_regenerate_item(f"detail:{section}"))
        self._step_copywriting.item_changed.connect(self._on_item_change)
        self._step_copywriting.settings_changed.connect(
            lambda s: setattr(self._model, '_copywriting_settings', s))
        self._step_copywriting.prev_requested.connect(self._go_to_analysis)
        self._step_copywriting.finish_requested.connect(self._on_finish)
        self._step_copywriting.export_txt_requested.connect(
            lambda p: self._on_export("txt"))
        self._step_copywriting.export_json_requested.connect(
            lambda p: self._on_export("json"))
        self._step_copywriting.export_csv_requested.connect(
            lambda p: self._on_export("csv"))

    # —— 步骤导航 ——

    def _go_to_step(self, index: int) -> None:
        self._model.current_step = index
        self._step_stack.setCurrentIndex(index)
        self._step_indicator.set_active(index)
        self._on_auto_save()

    def _on_step_clicked(self, step: int) -> None:
        self._go_to_step(step)

    def _go_to_source(self) -> None:
        self._go_to_step(0)

    def _go_to_analysis(self) -> None:
        info = self._step_source.manual_info()
        if not info.name and not self._step_source.images():
            QMessageBox.warning(self, "提示", "请先上传商品图片或输入商品名称。")
            return
        self._model.manual_info = info
        self._model.images = self._step_source.images()
        self._step_indicator.set_completed(0)
        self._go_to_step(1)
        self._on_analyze()

    def _go_to_copywriting(self) -> None:
        if self._model.analysis_result is None:
            QMessageBox.warning(self, "提示", "请先完成 AI 分析。")
            return
        self._step_indicator.set_completed(1)
        self._go_to_step(2)
        self._on_generate()

    def _on_finish(self) -> None:
        # 生成中或尚未生成时不允许完成
        if self._generating or self._model.copywriting_result is None:
            QMessageBox.warning(self, "提示", "请先完成文案生成。")
            return
        # 完成时自动保存项目，并显示保存位置
        self._on_save_project(silent=True)
        from src.platform.paths import PlatformPaths
        projects_dir = PlatformPaths.discover().data_dir / "projects"
        save_path = projects_dir / f"{self._project_id}.json"
        QMessageBox.information(
            self, "完成",
            "商品文案生成完成！项目已自动保存。\n\n"
            f"保存位置:\n{save_path}\n\n"
            "可通过「文件 → 打开项目」随时继续编辑，\n"
            "或通过导出按钮保存文案结果。"
        )

    # —— 链接解析 ——

    def _on_parse_hint(self, text: str) -> None:
        """解析中的人工验证提示（主线程）。"""
        self.statusBar().showMessage(text)
        self._step_source.set_parse_busy(True)
        self._step_source.set_parse_hint(text)

    def _on_parse_link(self, url: str) -> None:
        from src.application.link_parse import LinkParseError, LinkParser

        self._step_source.set_parse_busy(True)
        self.statusBar().showMessage("正在解析商品链接...")

        # 后台线程 → UI 的安全提示桥
        def _challenge_hint(text: str):
            self._parse_hint_signal.emit(text)

        parser = LinkParser(on_challenge=_challenge_hint)

        def _run():
            result = parser.parse(url)
            return result

        def _on_success(result):
            try:
                self._step_source.set_parse_busy(False)
                if not result.title and not result.images:
                    self._step_source.set_parse_error("未能从该链接提取到商品信息，页面可能为动态渲染")
                    return
                self._step_source.set_parse_result(
                    title=result.title,
                    description=result.description,
                    attributes=result.attributes,
                    platform=result.platform,
                )
                # 下载主图并加入图片列表
                if result.images:
                    self._download_link_images(result.images[:3])
                if not result.platform:
                    self.statusBar().showMessage("解析完成（未知平台，可能不完整）")
                else:
                    self.statusBar().showMessage(f"链接解析完成: {result.platform}")
            except Exception as e:
                print(f"[ProductWindow] 解析结果处理失败: {e}")

        def _on_error(error: Exception):
            self._step_source.set_parse_busy(False)
            msg = str(error)
            print(f"[ProductWindow] 链接解析失败: {msg}")
            self._step_source.set_parse_error(msg)
            self.statusBar().showMessage(f"链接解析失败: {msg}")

        self._task_runner.submit(_run, on_success=_on_success, on_error=_on_error)

    def _download_link_images(self, urls: list[str]) -> None:
        """后台下载链接图片到缓存目录并加入图片列表。"""
        def _run():
            from src.platform.paths import PlatformPaths
            cache_dir = PlatformPaths.discover().cache_dir / "link_images"
            cache_dir.mkdir(parents=True, exist_ok=True)
            downloaded: list[Path] = []
            for i, url in enumerate(urls):
                try:
                    import urllib.request
                    req = urllib.request.Request(url, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = resp.read()
                    if len(data) < 1000:
                        continue  # 太小的响应不是有效图片
                    ext = ".jpg"
                    ctype = resp.headers.get("Content-Type", "")
                    if "png" in ctype:
                        ext = ".png"
                    elif "webp" in ctype:
                        ext = ".webp"
                    path = cache_dir / f"link_{i}_{uuid.uuid4().hex[:8]}{ext}"
                    path.write_bytes(data)
                    downloaded.append(path)
                except Exception as e:
                    print(f"[ProductWindow] 下载图片失败 {url[:60]}: {e}")
            return downloaded

        def _on_success(downloaded: list[Path]):
            if downloaded:
                for path in downloaded:
                    self._step_source.add_image(path)
                self.statusBar().showMessage(f"已下载 {len(downloaded)} 张商品图片")

        def _on_error(error: Exception):
            print(f"[ProductWindow] 图片下载失败: {error}")

        self._task_runner.submit(_run, on_success=_on_success, on_error=_on_error)

    # —— AI 分析 ——

    def _on_analyze(self) -> None:
        images = self._step_source.images()
        info = self._step_source.manual_info()
        if not images:
            QMessageBox.warning(self, "提示", "请先上传商品图片。")
            return
        image_paths = [img.path for img in images]

        self._cancel_requested = False
        self._task_start_time = time.time()
        self._step_analysis.set_analyzing(True)
        self.statusBar().showMessage("正在分析商品...")
        self._model.analysis_started.emit()

        def _run():
            return self._analyze_product.execute(image_paths, info)

        def _on_success(result):
            elapsed = time.time() - self._task_start_time
            self._model.analysis_result = result
            self._step_analysis.set_result(result)
            self._step_analysis.set_analyzing(False)
            has_vision = bool(result.image_understanding and (
                result.image_understanding.category or result.image_understanding.appearance
            ))
            if has_vision:
                self.statusBar().showMessage(f"AI 分析完成，耗时 {elapsed:.1f}s")
            elif result.raw_llm_response:
                self.statusBar().showMessage(f"AI Vision 返回异常，原始响应已保存，耗时 {elapsed:.1f}s")
            else:
                self.statusBar().showMessage("AI Vision 无响应，请检查 LLM 配置")
            self._model.analysis_finished.emit(result)

        def _on_error(error: Exception):
            msg = self._classify_error(str(error))
            print(f"[ProductWindow] AI 分析失败: {msg}")
            try:
                self._step_analysis.set_error(msg)
                self._step_analysis.set_analyzing(False)
                self.statusBar().showMessage(f"分析失败: {msg}")
                self._model.analysis_failed.emit(msg)
            except Exception:
                print(f"[ProductWindow] 分析错误回调自身异常: {error}")

        self._task_runner.submit(_run, on_success=_on_success, on_error=_on_error)

    # —— 文案生成 ——

    def _ensure_quota(self) -> None:
        """生成前原子扣减一次商品详情次数；不足则抛错中止。"""
        if self._quota_client is None:
            return  # 未配置用量服务，不强制
        token = self._access_token() if self._access_token else None
        if not token:
            raise RuntimeError("请先激活应用后再使用商品详情生成")
        info = self._quota_client.consume(token)
        if not info.consumed:
            raise RuntimeError("商品详情次数不足，请购买次数包")

    def _on_generate(self) -> None:
        fact = self._step_analysis.current_fact()
        if fact is None:
            QMessageBox.warning(self, "提示", "请先完成 AI 分析。")
            return
        info = self._model.manual_info
        settings = self._step_copywriting.settings()

        self._cancel_requested = False
        self._task_start_time = time.time()
        self._generating = True
        self._step_copywriting.set_generating(True)
        self.statusBar().showMessage("正在生成文案...")
        self._model.copywriting_started.emit()

        def _run():
            self._ensure_quota()
            return self._generate_copywriting.execute(fact, info, settings)

        def _on_success(result):
            elapsed = time.time() - self._task_start_time
            self._generating = False
            self._model.copywriting_result = result
            self._step_copywriting.set_result(result)
            self._step_copywriting.set_generating(False)
            self.statusBar().showMessage(f"文案生成完成，耗时 {elapsed:.1f}s")
            self._model.copywriting_finished.emit(result)

        def _on_error(error: Exception):
            msg = self._classify_error(str(error))
            print(f"[ProductWindow] 文案生成失败: {msg}")
            try:
                self._generating = False
                self._step_copywriting.set_generating(False)
                self.statusBar().showMessage(f"生成失败: {msg}")
                self._model.copywriting_failed.emit(msg)
            except Exception:
                print(f"[ProductWindow] 错误回调自身异常: {error}")

        self._task_runner.submit(_run, on_success=_on_success, on_error=_on_error)

    # —— 单条重新生成 ——

    def _on_regenerate_item(self, item_type: str) -> None:
        if item_type in self._regenerating_items:
            return
        fact = self._step_analysis.current_fact()
        if fact is None:
            return
        info = self._model.manual_info
        settings = self._step_copywriting.settings()
        self._regenerating_items.add(item_type)
        self._step_copywriting.set_regeneration_active(item_type, True)
        self.statusBar().showMessage(f"正在重新生成: {item_type}...")

        def _run():
            return self._generate_copywriting.regenerate_item(
                fact, info, settings, item_type)

        def _finish() -> None:
            self._regenerating_items.discard(item_type)
            self._step_copywriting.set_regeneration_active(item_type, False)

        def _on_success(result):
            if result:
                self._merge_partial_result(result)
            _finish()
            self.statusBar().showMessage("重新生成完成")

        def _on_error(error: Exception):
            _finish()
            self.statusBar().showMessage(f"重新生成失败: {self._classify_error(str(error))}")

        self._task_runner.submit(_run, on_success=_on_success, on_error=_on_error)

    def _merge_partial_result(self, partial: object) -> None:
        if self._model.copywriting_result is None:
            return
        cr = self._model.copywriting_result
        if hasattr(partial, "tags") and partial.tags:
            cr.tags = partial.tags
            self._step_copywriting._tag_editor.set_tags(cr.tags)
        if hasattr(partial, "keywords") and partial.keywords:
            cr.keywords = partial.keywords
            self._step_copywriting._kw_editor.set_keywords(cr.keywords)
        if hasattr(partial, "titles") and partial.titles:
            cr.titles = partial.titles
            self._step_copywriting._title_editor.set_titles(cr.titles)
        if hasattr(partial, "selling_points") and partial.selling_points:
            cr.selling_points = partial.selling_points
            self._step_copywriting._sp_editor.set_selling_points(cr.selling_points)
        if hasattr(partial, "intro") and partial.intro:
            cr.intro = partial.intro
            self._step_copywriting.set_result(cr)
        if hasattr(partial, "detail_modules") and partial.detail_modules:
            cr.detail_modules = partial.detail_modules
            self._step_copywriting.set_result(cr)

    # —— 编辑器交互 ——

    def _on_item_change(self, item_type: str, item_id: str, value: str) -> None:
        if self._model.copywriting_result is None:
            return
        cr = self._model.copywriting_result
        if item_type == "tag":
            for t in cr.tags:
                if t.id == item_id:
                    t.tag = value
                    break
        elif item_type == "keyword":
            for k in cr.keywords:
                if k.id == item_id:
                    k.keyword = value
                    break
        elif item_type == "title":
            for t in cr.titles:
                if t.id == item_id:
                    t.title = value
                    t.char_count = len(value)
                    break
        elif item_type == "selling_point":
            for s in cr.selling_points:
                if s.id == item_id:
                    s.text = value
                    break
        elif item_type == "selling_point_lock":
            for s in cr.selling_points:
                if s.id == item_id:
                    s.locked = not s.locked
                    break
        elif item_type == "tag_delete":
            cr.tags = [t for t in cr.tags if t.id != item_id]
        elif item_type == "keyword_delete":
            cr.keywords = [k for k in cr.keywords if k.id != item_id]
        elif item_type == "title_delete":
            cr.titles = [t for t in cr.titles if t.id != item_id]
        elif item_type == "selling_point_delete":
            cr.selling_points = [s for s in cr.selling_points if s.id != item_id]

    # —— 事实编辑 ——

    def _on_fact_changed(self, field_name: str, value: str) -> None:
        if self._model.analysis_result and self._model.analysis_result.product_fact:
            f = self._model.analysis_result.product_fact
            f = f.with_field(field_name, value)
            f.source[field_name] = "手动修改"
            self._model.analysis_result.product_fact = f

    def _on_fact_confirmed(self, field_name: str) -> None:
        if self._model.analysis_result and self._model.analysis_result.product_fact:
            f = self._model.analysis_result.product_fact
            f.confirmed[field_name] = True
            f.uncertain.pop(field_name, None)

    def _on_fact_uncertain(self, field_name: str) -> None:
        if self._model.analysis_result and self._model.analysis_result.product_fact:
            f = self._model.analysis_result.product_fact
            f.uncertain[field_name] = True
            f.confirmed.pop(field_name, None)

    # —— 导出 ——

    def _on_export(self, fmt: str) -> None:
        result = self._model.copywriting_result
        if result is None:
            QMessageBox.warning(self, "提示", "请先生成文案。")
            return
        result = self._step_copywriting.collect_result(result)
        default_name = f"copywriting_{self._model.manual_info.name or 'export'}"
        if fmt == "txt":
            default_name += ".txt"
            filter_str = "文本文件 (*.txt)"
        elif fmt == "csv":
            default_name += ".csv"
            filter_str = "CSV 文件 (*.csv)"
        else:
            default_name += ".json"
            filter_str = "JSON 文件 (*.json)"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出文案", default_name, filter_str,
        )
        if not path:
            return
        try:
            target = self._export_copywriting.execute(result, Path(path), fmt)
            self.statusBar().showMessage(f"已导出: {target}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    # —— 保存 / 加载 ——

    def _init_project_store(self) -> ProjectStore:
        if self._project_store is None:
            from src.platform.paths import PlatformPaths
            projects_dir = PlatformPaths.discover().data_dir / "projects"
            self._project_store = ProjectStore(projects_dir)
        return self._project_store

    def _on_auto_save(self) -> None:
        if self._project_id and self._model.is_dirty:
            self._on_save_project(silent=True)
            self._model.is_dirty = False

    def _on_save_project(self, silent: bool = False) -> None:
        store = self._init_project_store()
        now = datetime.now(timezone.utc).isoformat()
        if self._project_id is None:
            self._project_id = str(uuid.uuid4())
            self._project_created_at = now

        info = self._model.manual_info
        copywriting_settings = self._step_copywriting.settings()
        project = ProductProject(
            id=self._project_id,
            name=info.name or "未命名项目",
            created_at=getattr(self, "_project_created_at", now),
            updated_at=now,
            source_images=getattr(self._model, "images", []),
            manual_info=info,
            analysis_result=self._model.analysis_result,
            copywriting_result=self._model.copywriting_result,
            target_language=copywriting_settings.target_language,
            current_step=self._model.current_step,
        )
        # 收集编辑器中最新的结果
        if project.copywriting_result and self._step_copywriting._result:
            project.copywriting_result = self._step_copywriting.collect_result(
                self._step_copywriting._result)
        store.save(project)
        if not silent:
            self.statusBar().showMessage(f"项目已保存: {project.name}")

    def _on_load_project(self) -> None:
        store = self._init_project_store()
        recent = store.list_recent(limit=30)
        if not recent:
            QMessageBox.information(self, "提示", "没有已保存的项目。")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("打开项目")
        dlg.setMinimumSize(550, 380)
        dlg.setProperty("editorStyle", True)
        dlg.setStyleSheet(EDITOR_DARK_THEME)

        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.addWidget(QLabel("选择一个项目打开:"))

        lst = QListWidget()
        for entry in recent:
            name = entry.get("name", "")
            updated = entry.get("updated_at", "")[:16].replace("T", " ")
            step = entry.get("current_step", 0)
            lang = entry.get("target_language", "")
            lst.addItem(f"{name}  —  {updated}  [步骤 {step + 1}] {lang}")
            lst.item(lst.count() - 1).setData(Qt.ItemDataRole.UserRole, entry["id"])
        dlg_layout.addWidget(lst)

        btn_row = QHBoxLayout()
        delete_btn = QPushButton("删除选中")
        delete_btn.setStyleSheet(
            "QPushButton { color: #ff6b6b; background: transparent; border: 1px solid #ff6b6b;"
            "  padding: 4px 12px; border-radius: 4px; }"
            "QPushButton:hover { background: #4a2a2a; }"
        )
        delete_btn.clicked.connect(lambda: self._delete_from_list(lst, dlg))
        btn_row.addWidget(delete_btn)
        btn_row.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel
        )
        btn_row.addWidget(buttons)
        dlg_layout.addLayout(btn_row)

        def _do_open():
            idx = lst.currentRow()
            if idx < 0:
                return
            pid = lst.item(idx).data(Qt.ItemDataRole.UserRole)
            self._load_project(pid)
            dlg.accept()

        buttons.accepted.connect(_do_open)
        buttons.rejected.connect(dlg.reject)
        buttons.button(QDialogButtonBox.StandardButton.Open).clicked.connect(
            lambda: _do_open()
        )
        dlg.exec()

    def _delete_from_list(self, lst: QListWidget, dlg: QDialog) -> None:
        idx = lst.currentRow()
        if idx < 0:
            return
        pid = lst.item(idx).data(Qt.ItemDataRole.UserRole)
        name = lst.item(idx).text().split("  —  ")[0]
        confirm = QMessageBox.question(
            self, "确认删除", f"确定要删除项目「{name}」吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            store = self._init_project_store()
            store.delete(pid)
            lst.takeItem(idx)
            if self._project_id == pid:
                self._project_id = None
            self.statusBar().showMessage(f"已删除项目: {name}")

    def _load_project(self, project_id: str) -> None:
        store = self._init_project_store()
        project = store.load(project_id)
        if project is None:
            QMessageBox.warning(self, "错误", f"无法加载项目: {project_id}")
            return

        self._project_id = project.id
        self._project_created_at = project.created_at
        self._step_copywriting._settings_panel.set_target_language(
            project.target_language
        )

        self._step_source.set_images(project.source_images)
        if project.manual_info:
            self._step_source.set_manual_info(project.manual_info)
            self._model.manual_info = project.manual_info
        if project.analysis_result:
            self._model.analysis_result = project.analysis_result
            self._step_analysis.set_result(project.analysis_result)
        if project.copywriting_result:
            self._model.copywriting_result = project.copywriting_result
            self._step_copywriting.set_result(project.copywriting_result)

        self._go_to_step(project.current_step)
        self.statusBar().showMessage(f"已打开项目: {project.name}")

    # —— 项目管理 ——

    def _on_rename_project(self) -> None:
        if self._project_id is None:
            QMessageBox.information(self, "提示", "请先保存项目。")
            return
        name, ok = QInputDialog.getText(
            self, "重命名项目", "新名称:",
            QLineEdit.EchoMode.Normal,
            self._model.manual_info.name or "",
        )
        if ok and name.strip():
            self._model.manual_info.name = name.strip()
            self._on_save_project()
            self.statusBar().showMessage(f"项目已重命名: {name.strip()}")

    def _on_duplicate_project(self) -> None:
        if self._project_id is None:
            QMessageBox.information(self, "提示", "请先保存项目。")
            return
        old_id = self._project_id
        self._project_id = str(uuid.uuid4())
        self._project_created_at = datetime.now(timezone.utc).isoformat()
        self._on_save_project()
        self.statusBar().showMessage("项目已复制")

    def _on_delete_project(self) -> None:
        if self._project_id is None:
            QMessageBox.information(self, "提示", "当前没有打开的项目。")
            return
        confirm = QMessageBox.question(
            self, "确认删除",
            "确定要删除当前项目吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            store = self._init_project_store()
            store.delete(self._project_id)
            self._project_id = None
            self.statusBar().showMessage("项目已删除")

    # —— 错误分类 ——

    def _classify_error(self, msg: str) -> str:
        msg_lower = msg.lower()
        if "401" in msg or "unauthorized" in msg_lower or "invalid api" in msg_lower:
            return f"未激活或授权已失效，请先在账户中激活 ({msg})"
        if "429" in msg or "rate limit" in msg_lower or "quota" in msg_lower or "额度" in msg:
            return f"API 额度不足或请求频率超限，请稍后重试或联系供应商 ({msg})"
        if "timeout" in msg_lower or "timed out" in msg_lower:
            return f"请求超时，请检查网络连接 ({msg})"
        if "connection" in msg_lower or "refused" in msg_lower or "network" in msg_lower:
            return f"网络连接失败，请检查网络 ({msg})"
        if "max_tokens" in msg_lower or "参数非法" in msg:
            return f"模型参数错误，请联系供应商 ({msg})"
        return msg
