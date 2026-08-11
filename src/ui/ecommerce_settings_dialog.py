"""电商翻译设置对话框 — 可视化编辑词库覆盖与 LLM 提示词。

词库只展示用户自定义/覆盖的条目；内置词库作为默认兜底，翻译时先命中
用户覆盖，再命中内置。提示词留空时使用内置模板。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.infrastructure.ecommerce_terms import ECOMMERCE_TERMS


class EcommerceSettingsDialog(QDialog):
    def __init__(
        self,
        user_terms: dict[str, str],
        user_prompt: str | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("电商翻译设置")
        self.setMinimumWidth(560)
        self.setMinimumHeight(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        terms_label = QLabel("词库覆盖（中文短语 → 英文翻译）：覆盖内置词库或新增词条")
        terms_label.setObjectName("settingsSectionTitle")
        layout.addWidget(terms_label)

        self.terms_table = QTableWidget(0, 2)
        self.terms_table.setObjectName("ecommerceTermsTable")
        self.terms_table.setHorizontalHeaderLabels(["中文短语", "英文翻译"])
        self.terms_table.horizontalHeader().setStretchLastSection(True)
        self.terms_table.setColumnWidth(0, 220)
        layout.addWidget(self.terms_table, stretch=1)

        row_buttons = QHBoxLayout()
        add_button = QPushButton("添加行")
        add_button.setObjectName("settingsSmallButton")
        add_button.clicked.connect(self._add_row)
        remove_button = QPushButton("删除选中行")
        remove_button.setObjectName("settingsSmallButton")
        remove_button.clicked.connect(self._remove_selected_rows)
        builtin_button = QPushButton("查看内置词库")
        builtin_button.setObjectName("settingsSmallButton")
        builtin_button.clicked.connect(self._show_builtin_terms)
        row_buttons.addWidget(add_button)
        row_buttons.addWidget(remove_button)
        row_buttons.addStretch()
        row_buttons.addWidget(builtin_button)
        layout.addLayout(row_buttons)

        prompt_label = QLabel("LLM 提示词（留空使用内置模板）：")
        prompt_label.setObjectName("settingsSectionTitle")
        layout.addWidget(prompt_label)
        self.prompt_editor = QPlainTextEdit()
        self.prompt_editor.setObjectName("ecommercePromptEditor")
        self.prompt_editor.setPlaceholderText("可自定义翻译风格要求；留空则使用内置提示词")
        self.prompt_editor.setMaximumHeight(150)
        layout.addWidget(self.prompt_editor)

        hint = QLabel(
            "提示：翻译时先命中词库覆盖，再命中内置词库；未命中的短语才走 LLM。"
            "内置词库参考可通过“查看内置词库”查看。"
        )
        hint.setObjectName("settingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        button_row = QHBoxLayout()
        reset_button = QPushButton("恢复默认")
        reset_button.setObjectName("settingsResetButton")
        reset_button.clicked.connect(self._reset_defaults)
        save_button = QPushButton("保存")
        save_button.setObjectName("settingsSaveButton")
        save_button.clicked.connect(self.accept)
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("settingsCancelButton")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(reset_button)
        button_row.addStretch()
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

        self._populate(user_terms, user_prompt)

    def _populate(self, user_terms: dict[str, str], user_prompt: str | None) -> None:
        self.terms_table.setRowCount(0)
        for source, target in user_terms.items():
            row = self.terms_table.rowCount()
            self.terms_table.insertRow(row)
            self.terms_table.setItem(row, 0, QTableWidgetItem(source))
            self.terms_table.setItem(row, 1, QTableWidgetItem(target))
        self.prompt_editor.setPlainText(user_prompt or "")
        if not user_terms:
            self._add_row()

    def resulting_settings(self) -> tuple[dict[str, str], str | None]:
        terms: dict[str, str] = {}
        for row in range(self.terms_table.rowCount()):
            source = self.terms_table.item(row, 0)
            target = self.terms_table.item(row, 1)
            source_text = source.text().strip() if source is not None else ""
            target_text = target.text().strip() if target is not None else ""
            if source_text and target_text:
                terms[source_text] = target_text
        prompt = self.prompt_editor.toPlainText().strip()
        return terms, (prompt or None)

    def _add_row(self) -> None:
        row = self.terms_table.rowCount()
        self.terms_table.insertRow(row)
        self.terms_table.setItem(row, 0, QTableWidgetItem(""))
        self.terms_table.setItem(row, 1, QTableWidgetItem(""))

    def _remove_selected_rows(self) -> None:
        rows = sorted({index.row() for index in self.terms_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.terms_table.removeRow(row)

    def _show_builtin_terms(self) -> None:
        lines = "\n".join(
            f"{source}  →  {target}"
            for source, target in ECOMMERCE_TERMS.items()
        )
        QMessageBox.information(self, "内置词库", lines)

    def _reset_defaults(self) -> None:
        self.terms_table.setRowCount(0)
        self.prompt_editor.clear()
        self._add_row()
