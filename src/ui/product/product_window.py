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
    closed = Signal()  # 窗口被关闭（含点右上角 X），供宿主恢复主界面

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
        account_actions: dict | None = None,
        request_quit=None,
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
        self._account_actions = account_actions or {}
        self._request_quit = request_quit
        self._closing_for_quit = False
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
        top_bar.setStyleSheet("background: #ffffff;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 4, 12, 4)

        title = QLabel("商品详情生成")
        title.setObjectName("pageTitle")
        top_layout.addWidget(title)

        top_layout.addStretch()

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

        # 首页：菜单栏按钮形式，点击即跳转（无下拉）
        home_action = QAction("首页", self)
        home_action.triggered.connect(self.back_requested.emit)
        menu.addAction(home_action)

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

        file_menu.addSeparator()

        back_action = QAction("返回首页", self)
        back_action.triggered.connect(self.back_requested.emit)
        file_menu.addAction(back_action)

        quit_action = QAction("退出", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self._on_quit)
        file_menu.addAction(quit_action)

        help_menu = menu.addMenu("帮助")
        help_action = QAction("使用说明…", self)
        help_action.triggered.connect(self._show_help_dialog)
        help_menu.addAction(help_action)

        account_actions = self._account_actions
        if account_actions:
            account_menu = menu.addMenu("账户")
            activate_action = QAction("激活…", self)
            activate_action.triggered.connect(
                account_actions.get("activate") or (lambda: None)
            )
            account_menu.addAction(activate_action)

            renew_action = QAction("续购时长/次数…", self)
            renew_action.triggered.connect(
                account_actions.get("renew") or (lambda: None)
            )
            account_menu.addAction(renew_action)

            quota_action = QAction("查看额度…", self)
            quota_action.triggered.connect(
                account_actions.get("quota") or (lambda: None)
            )
            account_menu.addAction(quota_action)

    def _show_help_dialog(self) -> None:
        from src.ui.help_dialog import HelpDialog

        HelpDialog(self).show()

    def _on_quit(self) -> None:
        """退出应用：先关商品窗口（不触发首页恢复），再关主窗口。"""
        self._closing_for_quit = True
        self.close()
        if self._request_quit is not None:
            self._request_quit()

    def _connect_signals(self) -> None:
        self._step_indicator.step_clicked.connect(self._on_step_clicked)
        self._step_source.next_requested.connect(self._go_to_analysis)
        self._step_analysis.analyze_requested.connect(self._on_analyze)
        self._step_analysis.next_requested.connect(self._go_to_copywriting)
        self._step_analysis.prev_requested.connect(self._go_to_source)
        self._step_analysis.fact_changed.connect(self._on_fact_changed)
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
        # 进入文案页时同步商品图片列表（分析成功时已设置，这里兜底）
        self._step_copywriting.set_source_images(
            [str(img.path) for img in self._model.images],
            image_info=self._image_info_list(),
        )
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

    # —— AI 分析 ——

    def _on_analyze(self) -> None:
        images = self._step_source.images()
        info = self._step_source.manual_info()
        if not images:
            QMessageBox.warning(self, "提示", "请先上传商品图片。")
            return
        if not self._check_quota_available():
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
            try:
                self._model.analysis_result = result
                self._step_analysis.set_result(result)
                self._step_copywriting.set_source_images(
                    [str(img.path) for img in image_paths],
                    image_info=self._image_info_list(),
                )
            except Exception as error:
                print(f"[ProductWindow] 分析结果处理异常: {error}")
                import traceback

                traceback.print_exc()
            finally:
                # 无论结果处理是否出错，都恢复分析按钮状态
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

    def _check_quota_available(self) -> bool:
        """商品详情使用前检查是否购买了次数包；未购买弹窗提示。"""
        if self._quota_client is None:
            return True
        token = self._access_token() if self._access_token else None
        if not token:
            QMessageBox.warning(self, "提示", "请先激活应用后再使用商品详情生成")
            return False
        try:
            info = self._quota_client.get_usage(token)
        except Exception as error:
            QMessageBox.warning(self, "提示", f"无法获取商品详情次数：{error}")
            return False
        if info.quota_total <= 0:
            QMessageBox.warning(
                self, "提示", "当前是时长包，请购买次数包后使用商品详情生成"
            )
            return False
        return True

    def _ensure_quota(self) -> None:
        """生成前原子扣减一次商品详情次数；不足则抛错中止。"""
        if self._quota_client is None:
            return  # 未配置用量服务，不强制
        token = self._access_token() if self._access_token else None
        if not token:
            raise RuntimeError("请先激活应用后再使用商品详情生成")
        info = self._quota_client.consume(token)
        if not info.consumed:
            if info.quota_total <= 0:
                raise RuntimeError("当前是时长包，请购买次数包后使用商品详情生成")
            raise RuntimeError("商品详情次数已用完，请购买次数包")

    def _on_generate(self) -> None:
        fact = self._step_analysis.current_fact()
        if fact is None:
            QMessageBox.warning(self, "提示", "请先完成 AI 分析。")
            return
        if not self._check_quota_available():
            return
        info = self._model.manual_info
        settings = self._step_copywriting.settings()

        self._cancel_requested = False
        self._task_start_time = time.time()
        self._generating = True
        self._step_copywriting.set_generating(True)
        self._model.copywriting_started.emit()

        # 每张图片独立生成一套文案（用该图的事实；无单图事实用合并事实）
        analysis = self._model.analysis_result
        per_facts = list(analysis.per_image_facts) if analysis else []
        if not per_facts:
            per_facts = [fact]
        image_count = len(per_facts)
        self.statusBar().showMessage(
            f"正在为 {image_count} 张图片并行生成文案..."
        )

        def _run():
            self._ensure_quota()
            from concurrent.futures import ThreadPoolExecutor

            def _generate_one(index: int):
                current = (
                    per_facts[index] if per_facts[index] is not None else fact
                )
                return index, self._generate_copywriting.execute(
                    current, info, settings
                )

            results: dict[int, object] = {}
            with ThreadPoolExecutor(
                max_workers=max(1, len(per_facts))
            ) as pool:
                futures = [
                    pool.submit(_generate_one, i)
                    for i in range(len(per_facts))
                ]
                for future in futures:
                    index, result = future.result()
                    results[index] = result
            return results

        def _on_success(results):
            elapsed = time.time() - self._task_start_time
            self._generating = False
            self._model.copywriting_results = results
            self._step_copywriting.set_results(results)
            self._step_copywriting.set_generating(False)
            self.statusBar().showMessage(
                f"文案生成完成（{len(results)} 张图），耗时 {elapsed:.1f}s"
            )
            self._model.copywriting_finished.emit(results.get(0))

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
        # 单条重新生成只更新当前图片对应的那套文案
        index = self._step_copywriting.current_result_index
        cr = self._model.copywriting_results.get(index)
        if cr is None:
            return
        if hasattr(partial, "tags") and partial.tags:
            cr.tags = partial.tags
        if hasattr(partial, "keywords") and partial.keywords:
            cr.keywords = partial.keywords
        if hasattr(partial, "titles") and partial.titles:
            cr.titles = partial.titles
        if hasattr(partial, "selling_points") and partial.selling_points:
            cr.selling_points = partial.selling_points
        if hasattr(partial, "intro") and partial.intro:
            cr.intro = partial.intro
        if hasattr(partial, "detail_modules") and partial.detail_modules:
            cr.detail_modules = partial.detail_modules
        self._model.copywriting_results[index] = cr
        self._step_copywriting.set_result(cr)

    # —— 编辑器交互 ——

    def _on_item_change(self, item_type: str, item_id: str, value: str) -> None:
        # 编辑只作用于当前图片对应的那套文案
        index = self._step_copywriting.current_result_index
        cr = self._model.copywriting_results.get(index)
        if cr is None:
            return
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
            results = self._model.copywriting_results
            image_info = self._image_info_list()
            exported: list[Path] = []
            if len(results) > 1:
                # 多图独立文案：每张图导出一份文件（文件名带图序号，
                # 且只含该图片的信息，避免每份文件重复全部图片信息）
                target_path = Path(path)
                for index, per_result in sorted(results.items()):
                    name = target_path.stem + f"_图{index + 1}" + target_path.suffix
                    per_path = target_path.with_name(name)
                    per_image = (
                        [image_info[index]]
                        if index < len(image_info)
                        else None
                    )
                    exported.append(
                        self._export_copywriting.execute(
                            per_result, per_path, fmt, image_info=per_image
                        )
                    )
            else:
                exported.append(
                    self._export_copywriting.execute(
                        result, Path(path), fmt, image_info=image_info
                    )
                )
            if len(exported) > 1:
                self.statusBar().showMessage(
                    f"已导出 {len(exported)} 份文案到 {Path(path).parent}"
                )
            else:
                self.statusBar().showMessage(f"已导出: {exported[0]}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _image_info_list(self) -> list[dict]:
        """组装每张商品图片的分析信息（导出/逐图查看用）。"""
        result = self._model.analysis_result
        if result is None:
            return []
        info: list[dict] = []
        for index, path in enumerate(result.source_images):
            understanding = (
                result.image_understandings[index]
                if index < len(result.image_understandings)
                else None
            )
            ocr = (
                result.per_image_ocr_texts[index]
                if index < len(result.per_image_ocr_texts)
                else ""
            )
            fact = (
                result.per_image_facts[index]
                if index < len(result.per_image_facts)
                else None
            )
            understanding_text = ""
            if understanding is not None:
                understanding_text = " ".join(
                    part
                    for part in (
                        understanding.category,
                        understanding.appearance,
                        understanding.usage_scene,
                    )
                    if part
                )
            fact_text = ""
            if fact is not None:
                fact_text = " ".join(
                    part
                    for part in (
                        fact.name,
                        fact.brand,
                        fact.model,
                        fact.specs,
                        fact.material,
                    )
                    if part
                )
            info.append(
                {
                    "path": path,
                    "ocr": ocr,
                    "understanding": understanding_text,
                    "fact": fact_text,
                }
            )
        return info

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

    def closeEvent(self, event) -> None:
        if not self._closing_for_quit:
            self.closed.emit()
        super().closeEvent(event)

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
            "QPushButton { color: #dc2626; background: transparent; border: 1px solid #dc2626;"
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
        # 先恢复分析结果，再填充图片列表（含每图信息）
        self._step_copywriting.set_source_images(
            [str(img.path) for img in project.source_images],
            image_info=self._image_info_list(),
        )
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
            return f"未激活或授权已失效，请重新激活，或联系客服 ({msg})"
        if "429" in msg or "rate limit" in msg_lower or "quota" in msg_lower or "额度" in msg:
            return f"API 额度不足或请求频率超限，请稍后重试或联系供应商 ({msg})"
        if "timeout" in msg_lower or "timed out" in msg_lower:
            return f"请求超时，请检查网络连接 ({msg})"
        if "connection" in msg_lower or "refused" in msg_lower or "network" in msg_lower:
            return f"网络连接失败，请检查网络 ({msg})"
        if "max_tokens" in msg_lower or "参数非法" in msg:
            return f"模型参数错误，请联系供应商 ({msg})"
        return msg
