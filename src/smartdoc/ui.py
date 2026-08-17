from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import AppConfig, ConfigStore, StartupManager, packaged_startup_command
from .database import Database
from .fileops import SUPPORTED_EXTENSIONS
from .models import DocumentRecord, DocumentStatus
from .pipeline import DocumentPipeline
from .watcher import FolderWatcher

STATUS_LABELS = {
    DocumentStatus.PROCESSING: "辨識中",
    DocumentStatus.PENDING: "待確認",
    DocumentStatus.APPLIED: "已完成",
    DocumentStatus.IGNORED: "保留原名",
    DocumentStatus.FAILED: "處理失敗",
}


class UiBridge(QObject):
    data_changed = Signal()
    monitoring_changed = Signal(bool)


def label(text: str, object_name: str | None = None) -> QLabel:
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    return widget


def button(text: str, *, primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
    if primary:
        widget.setProperty("primary", True)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        database: Database,
        config_store: ConfigStore,
        get_config: Callable[[], AppConfig],
        save_config: Callable[[AppConfig], None],
        pipeline: DocumentPipeline,
        watcher: FolderWatcher,
        bridge: UiBridge,
    ) -> None:
        super().__init__()
        self.database = database
        self.config_store = config_store
        self.get_config = get_config
        self.save_config_callback = save_config
        self.pipeline = pipeline
        self.watcher = watcher
        self.bridge = bridge
        self.allow_close = False
        self.current_records: dict[int, DocumentRecord] = {}

        self.setWindowTitle("智慧文件整理 2.0")
        self.setMinimumSize(1060, 680)
        self.resize(1280, 780)
        self._build_ui()
        self.bridge.data_changed.connect(self.refresh_all)
        self.bridge.monitoring_changed.connect(self.refresh_monitor_status)
        self.refresh_all()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())

        self.pages = QStackedWidget()
        self.pages.setObjectName("pageStack")
        self.pages.addWidget(self._build_queue_page())
        self.pages.addWidget(self._build_history_page())
        self.pages.addWidget(self._build_settings_page())
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(218)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 24, 18, 20)
        layout.setSpacing(8)

        brand_row = QHBoxLayout()
        mark = label("文", "brandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(42, 42)
        brand_row.addWidget(mark)
        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(0)
        brand_copy.addWidget(label("智慧文件整理", "brandTitle"))
        brand_copy.addWidget(label("LOCAL DESK 2.0", "brandCaption"))
        brand_row.addLayout(brand_copy)
        layout.addLayout(brand_row)
        layout.addSpacing(24)

        self.nav_buttons: list[QPushButton] = []
        for index, title in enumerate(("待確認清單", "處理紀錄", "監聽設定")):
            nav = QPushButton(title)
            nav.setCheckable(True)
            nav.setProperty("nav", True)
            nav.setCursor(Qt.CursorShape.PointingHandCursor)
            nav.clicked.connect(lambda checked=False, page=index: self._show_page(page))
            self.nav_buttons.append(nav)
            layout.addWidget(nav)
        self.nav_buttons[0].setChecked(True)
        layout.addStretch(1)

        layout.addWidget(label("掃描器狀態", "sidebarCaption"))
        self.sidebar_monitor = label("● 正在監聽")
        self.sidebar_monitor.setStyleSheet(
            "color: #73D4CA; font-weight: 700; padding: 4px 0;"
        )
        layout.addWidget(self.sidebar_monitor)
        layout.addWidget(label("所有分析都在本機完成", "sidebarCaption"))
        return sidebar

    def _show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for position, nav in enumerate(self.nav_buttons):
            nav.setChecked(position == index)
        if index == 1:
            self.refresh_history()

    def _page_header(self, title: str, description: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(3)
        layout.addWidget(label(title, "pageTitle"))
        layout.addWidget(label(description, "pageDescription"))
        return layout

    def _build_queue_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.addLayout(
            self._page_header("待確認清單", "掃描完成後，只需要在這裡做最後一次確認。")
        )
        header_row.addStretch(1)
        scan_existing = button("掃描資料夾既有檔案")
        scan_existing.clicked.connect(self._scan_existing_folder)
        header_row.addWidget(scan_existing)
        add_files = button("加入既有文件")
        add_files.clicked.connect(self._add_files)
        header_row.addWidget(add_files)
        outer.addLayout(header_row)

        status = QFrame()
        status.setObjectName("statusStrip")
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(16, 12, 16, 12)
        self.status_dot = QFrame()
        self.status_dot.setObjectName("statusDot")
        self.status_dot.setFixedSize(10, 10)
        status_layout.addWidget(self.status_dot)
        status_copy = QVBoxLayout()
        status_copy.setSpacing(1)
        self.monitor_title = label("背景監聽中", "statusTitle")
        self.folder_label = label("", "folderPath")
        self.folder_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        status_copy.addWidget(self.monitor_title)
        status_copy.addWidget(self.folder_label)
        status_layout.addLayout(status_copy, 1)
        count_copy = QVBoxLayout()
        count_copy.setSpacing(0)
        self.pending_count = label("0", "countNumber")
        self.pending_count.setAlignment(Qt.AlignmentFlag.AlignRight)
        count_label = label("份等待確認", "countLabel")
        count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        count_copy.addWidget(self.pending_count)
        count_copy.addWidget(count_label)
        status_layout.addLayout(count_copy)
        outer.addWidget(status)
        self.status_strip = status

        action_row = QHBoxLayout()
        self.apply_button = button("套用勾選的檔名", primary=True)
        self.apply_button.clicked.connect(self._apply_checked)
        self.ignore_button = button("保留原檔名")
        self.ignore_button.clicked.connect(self._ignore_checked)
        action_row.addWidget(self.apply_button)
        action_row.addWidget(self.ignore_button)
        action_row.addStretch(1)
        self.refresh_button = button("重新整理")
        self.refresh_button.clicked.connect(self.refresh_all)
        action_row.addWidget(self.refresh_button)
        outer.addLayout(action_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.queue_table = QTableWidget(0, 6)
        self.queue_table.setHorizontalHeaderLabels(
            ("選取", "原始檔名", "建議檔名", "分類", "歸檔目標", "信心")
        )
        self.queue_table.setAlternatingRowColors(True)
        self.queue_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.verticalHeader().setDefaultSectionSize(48)
        header = self.queue_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.queue_table.itemSelectionChanged.connect(self._show_selected_detail)
        splitter.addWidget(self.queue_table)
        splitter.addWidget(self._build_detail_panel())
        splitter.setSizes([760, 340])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)
        return page

    def _build_detail_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("detailCard")
        panel.setMinimumWidth(300)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(label("文件判讀", "sectionLabel"))
        self.detail_name = label("選取一份文件")
        self.detail_name.setWordWrap(True)
        self.detail_name.setStyleSheet("font-size: 17px; font-weight: 700;")
        layout.addWidget(self.detail_name)
        self.confidence_bar = QProgressBar()
        self.confidence_bar.setRange(0, 100)
        self.confidence_bar.setTextVisible(False)
        layout.addWidget(self.confidence_bar)
        self.detail_reason = label("", "mutedText")
        self.detail_reason.setWordWrap(True)
        layout.addWidget(self.detail_reason)
        layout.addSpacing(6)
        layout.addWidget(label("OCR 文字預覽", "sectionLabel"))
        self.ocr_preview = QTextEdit()
        self.ocr_preview.setReadOnly(True)
        self.ocr_preview.setPlaceholderText("選取文件後顯示辨識結果")
        layout.addWidget(self.ocr_preview, 1)
        self.open_file_button = button("開啟原始文件")
        self.open_file_button.clicked.connect(self._open_selected_file)
        self.open_file_button.setEnabled(False)
        layout.addWidget(self.open_file_button)
        return panel

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addLayout(
            self._page_header("處理紀錄", "每次改名與歸檔都有跡可循；需要時可復原。")
        )
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(
            ("狀態", "目前檔名", "分類", "信心", "處理時間")
        )
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.history_table, 1)
        action_row = QHBoxLayout()
        self.undo_button = button("復原選取項目的檔名與位置")
        self.undo_button.clicked.connect(self._undo_selected)
        action_row.addWidget(self.undo_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        outer.addLayout(
            self._page_header(
                "監聽設定", "決定程式在哪裡等候新掃描，以及何時可以自動改名。"
            )
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 12, 0)
        content_layout.setSpacing(14)

        scan_card, scan_form = self._settings_card("掃描來源")
        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        self.scan_folder_input = QLineEdit()
        browse = button("選擇資料夾")
        browse.clicked.connect(self._choose_scan_folder)
        folder_layout.addWidget(self.scan_folder_input, 1)
        folder_layout.addWidget(browse)
        scan_form.addRow("監聽資料夾", folder_row)
        self.monitoring_checkbox = QCheckBox("啟動背景監聽")
        scan_form.addRow("", self.monitoring_checkbox)
        self.startup_checkbox = QCheckBox("登入 Windows 後自動啟動")
        self.startup_checkbox.setEnabled(StartupManager.available())
        scan_form.addRow("", self.startup_checkbox)
        content_layout.addWidget(scan_card)

        rename_card, rename_form = self._settings_card("命名與安全")
        self.template_input = QLineEdit()
        self.template_input.setPlaceholderText("{date}_{category}_{subject}")
        rename_form.addRow("檔名格式", self.template_input)
        hint = label(
            "可使用 {date}、{category}、{subject}、{organization}、{document_number}",
            "mutedText",
        )
        hint.setWordWrap(True)
        rename_form.addRow("", hint)
        self.auto_checkbox = QCheckBox("高信心文件直接改名")
        rename_form.addRow("", self.auto_checkbox)
        self.threshold_input = QDoubleSpinBox()
        self.threshold_input.setRange(0.50, 0.99)
        self.threshold_input.setSingleStep(0.01)
        self.threshold_input.setDecimals(2)
        rename_form.addRow("自動改名門檻", self.threshold_input)
        self.max_pages_input = QSpinBox()
        self.max_pages_input.setRange(1, 100)
        rename_form.addRow("PDF 最多辨識頁數", self.max_pages_input)
        content_layout.addWidget(rename_card)

        archive_card, archive_form = self._settings_card("分類歸檔")
        archive_hint = label(
            "辨識到指定分類後，可在確認套用時移動，或只讓高信心文件自動移動。相對路徑會建立在監聽資料夾內。",
            "mutedText",
        )
        archive_hint.setWordWrap(True)
        archive_form.addRow("", archive_hint)
        self.archive_rules_table = QTableWidget(0, 2)
        self.archive_rules_table.setHorizontalHeaderLabels(("辨識分類", "目的資料夾"))
        self.archive_rules_table.verticalHeader().setVisible(False)
        self.archive_rules_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.archive_rules_table.setMinimumHeight(150)
        self.archive_rules_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.archive_rules_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        archive_form.addRow("歸檔規則", self.archive_rules_table)
        rule_actions = QWidget()
        rule_actions_layout = QHBoxLayout(rule_actions)
        rule_actions_layout.setContentsMargins(0, 0, 0, 0)
        add_rule = button("新增規則")
        add_rule.clicked.connect(lambda: self._add_archive_rule())
        remove_rule = button("刪除規則")
        remove_rule.clicked.connect(self._remove_archive_rule)
        choose_archive = button("選擇目的資料夾")
        choose_archive.clicked.connect(self._choose_archive_folder)
        rule_actions_layout.addWidget(add_rule)
        rule_actions_layout.addWidget(remove_rule)
        rule_actions_layout.addWidget(choose_archive)
        rule_actions_layout.addStretch(1)
        archive_form.addRow("", rule_actions)
        self.archive_on_apply_checkbox = QCheckBox("確認套用時，同時移動到分類資料夾")
        archive_form.addRow("", self.archive_on_apply_checkbox)
        self.auto_archive_checkbox = QCheckBox("高信心文件直接自動歸檔")
        archive_form.addRow("", self.auto_archive_checkbox)
        self.archive_threshold_input = QDoubleSpinBox()
        self.archive_threshold_input.setRange(0.50, 0.99)
        self.archive_threshold_input.setSingleStep(0.01)
        self.archive_threshold_input.setDecimals(2)
        archive_form.addRow("自動歸檔門檻", self.archive_threshold_input)
        content_layout.addWidget(archive_card)

        ai_card, ai_form = self._settings_card("本機 AI（選用）")
        self.ai_checkbox = QCheckBox("使用 localhost 模型協助分類")
        ai_form.addRow("", self.ai_checkbox)
        self.ai_url_input = QLineEdit()
        ai_form.addRow("服務網址", self.ai_url_input)
        self.ai_model_input = QLineEdit()
        ai_form.addRow("模型名稱", self.ai_model_input)
        local_only = label(
            "安全限制：只接受 localhost、127.0.0.1 或 ::1，不會連線到其他主機。",
            "mutedText",
        )
        local_only.setWordWrap(True)
        ai_form.addRow("", local_only)
        content_layout.addWidget(ai_card)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        save = button("儲存並套用設定", primary=True)
        save.clicked.connect(self._save_settings)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_row.addWidget(save)
        outer.addLayout(save_row)
        self._load_settings_fields()
        return page

    @staticmethod
    def _settings_card(title: str) -> tuple[QFrame, QFormLayout]:
        card = QFrame()
        card.setObjectName("settingsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        title_label = label(title)
        title_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(title_label)
        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(form)
        return card, form

    def _load_settings_fields(self) -> None:
        config = self.get_config()
        self.scan_folder_input.setText(config.scan_folder)
        self.monitoring_checkbox.setChecked(config.monitoring_enabled)
        self.startup_checkbox.setChecked(config.start_with_windows)
        self.template_input.setText(config.filename_template)
        self.auto_checkbox.setChecked(config.auto_rename_enabled)
        self.threshold_input.setValue(config.auto_rename_threshold)
        self.max_pages_input.setValue(config.max_pdf_pages)
        self.archive_on_apply_checkbox.setChecked(config.archive_on_apply)
        self.auto_archive_checkbox.setChecked(config.auto_archive_enabled)
        self.archive_threshold_input.setValue(config.auto_archive_threshold)
        self.archive_rules_table.setRowCount(0)
        for category, folder in config.archive_rules.items():
            self._add_archive_rule(category, folder)
        self.ai_checkbox.setChecked(config.local_ai_enabled)
        self.ai_url_input.setText(config.local_ai_url)
        self.ai_model_input.setText(config.local_ai_model)

    def _save_settings(self) -> None:
        config = AppConfig(
            scan_folder=self.scan_folder_input.text().strip(),
            monitoring_enabled=self.monitoring_checkbox.isChecked(),
            auto_rename_enabled=self.auto_checkbox.isChecked(),
            auto_rename_threshold=self.threshold_input.value(),
            filename_template=self.template_input.text().strip()
            or "{date}_{category}_{subject}",
            local_ai_enabled=self.ai_checkbox.isChecked(),
            local_ai_url=self.ai_url_input.text().strip(),
            local_ai_model=self.ai_model_input.text().strip(),
            start_with_windows=self.startup_checkbox.isChecked(),
            max_pdf_pages=self.max_pages_input.value(),
            settle_seconds=self.get_config().settle_seconds,
            archive_on_apply=self.archive_on_apply_checkbox.isChecked(),
            auto_archive_enabled=self.auto_archive_checkbox.isChecked(),
            auto_archive_threshold=self.archive_threshold_input.value(),
            archive_rules=self._archive_rules_from_table(),
        )
        try:
            self.save_config_callback(config)
            StartupManager.set_enabled(
                config.start_with_windows, packaged_startup_command()
            )
            if config.monitoring_enabled:
                self.watcher.start(Path(config.scan_folder))
            else:
                self.watcher.stop()
            self.bridge.monitoring_changed.emit(self.watcher.running)
            QMessageBox.information(self, "設定已儲存", "新的監聽與命名設定已套用。")
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "無法儲存設定", str(error))

    def refresh_all(self) -> None:
        self.refresh_queue()
        self.refresh_history()
        self.refresh_monitor_status(self.watcher.running)

    def refresh_monitor_status(self, active: bool) -> None:
        config = self.get_config()
        self.status_strip.setProperty("active", active)
        self.status_dot.setProperty("active", active)
        self.status_strip.style().unpolish(self.status_strip)
        self.status_strip.style().polish(self.status_strip)
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)
        self.monitor_title.setText("背景監聽中" if active else "背景監聽已暫停")
        self.folder_label.setText(config.scan_folder)
        self.sidebar_monitor.setText("● 正在監聽" if active else "● 已暫停")
        self.sidebar_monitor.setStyleSheet(
            "color: #73D4CA; font-weight: 700; padding: 4px 0;"
            if active
            else "color: #E8AD68; font-weight: 700; padding: 4px 0;"
        )

    def refresh_queue(self) -> None:
        records = self.database.list_documents(DocumentStatus.PENDING)
        config = self.get_config()
        self.apply_button.setText(
            "套用檔名與歸檔" if config.archive_on_apply else "套用勾選的檔名"
        )
        self.current_records = {record.id: record for record in records}
        self.queue_table.setRowCount(0)
        for row, record in enumerate(records):
            self.queue_table.insertRow(row)
            check = QTableWidgetItem()
            check.setCheckState(Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, record.id)
            check.setFlags(check.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.queue_table.setItem(row, 0, check)
            original = QTableWidgetItem(record.current_path.name)
            original.setFlags(original.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.queue_table.setItem(row, 1, original)
            proposed = QTableWidgetItem(record.suggested_name)
            self.queue_table.setItem(row, 2, proposed)
            category = QTableWidgetItem(record.category)
            category.setFlags(category.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.queue_table.setItem(row, 3, category)
            destination = config.archive_destination(record.category)
            archive_target = QTableWidgetItem(str(destination) if destination else "—")
            archive_target.setFlags(
                archive_target.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            self.queue_table.setItem(row, 4, archive_target)
            confidence = QTableWidgetItem(f"{record.confidence:.0%}")
            confidence.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            confidence.setFlags(confidence.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.queue_table.setItem(row, 5, confidence)
        self.pending_count.setText(str(len(records)))
        has_rows = bool(records)
        self.apply_button.setEnabled(has_rows)
        self.ignore_button.setEnabled(has_rows)
        if has_rows:
            self.queue_table.selectRow(0)
        else:
            self.detail_name.setText("待確認清單是空的")
            self.detail_reason.setText("新掃描的文件會自動出現在這裡。")
            self.ocr_preview.clear()
            self.confidence_bar.setValue(0)
            self.open_file_button.setEnabled(False)

    def refresh_history(self) -> None:
        records = self.database.list_documents(limit=500)
        self.history_table.setRowCount(0)
        for row, record in enumerate(records):
            self.history_table.insertRow(row)
            values = (
                STATUS_LABELS[record.status],
                record.current_path.name,
                record.category,
                f"{record.confidence:.0%}",
                record.updated_at.astimezone().strftime("%Y-%m-%d %H:%M"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record.id)
                self.history_table.setItem(row, column, item)

    def _checked_rows(self) -> list[tuple[int, str]]:
        selected: list[tuple[int, str]] = []
        for row in range(self.queue_table.rowCount()):
            item = self.queue_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                selected.append(
                    (
                        int(item.data(Qt.ItemDataRole.UserRole)),
                        self.queue_table.item(row, 2).text(),
                    )
                )
        if not selected and self.queue_table.currentRow() >= 0:
            row = self.queue_table.currentRow()
            selected.append(
                (
                    int(self.queue_table.item(row, 0).data(Qt.ItemDataRole.UserRole)),
                    self.queue_table.item(row, 2).text(),
                )
            )
        return selected

    def _apply_checked(self) -> None:
        selected = self._checked_rows()
        if not selected:
            return
        errors: list[str] = []
        for document_id, proposed_name in selected:
            try:
                self.pipeline.apply(document_id, proposed_name)
            except (OSError, ValueError, KeyError) as error:
                errors.append(str(error))
        if errors:
            QMessageBox.warning(self, "部分文件未套用", "\n".join(errors[:5]))
        self.refresh_all()

    def _ignore_checked(self) -> None:
        for document_id, _ in self._checked_rows():
            self.pipeline.ignore(document_id)
        self.refresh_all()

    def _show_selected_detail(self) -> None:
        row = self.queue_table.currentRow()
        if row < 0:
            return
        item = self.queue_table.item(row, 0)
        if not item:
            return
        record = self.current_records.get(int(item.data(Qt.ItemDataRole.UserRole)))
        if not record:
            return
        self.detail_name.setText(record.current_path.name)
        detail = f"{record.summary}｜整體信心 {record.confidence:.0%}"
        destination = self.get_config().archive_destination(record.category)
        if destination:
            detail += f"｜歸檔目標：{destination}"
        self.detail_reason.setText(detail)
        self.confidence_bar.setValue(round(record.confidence * 100))
        self.ocr_preview.setPlainText(record.ocr_text)
        self.open_file_button.setEnabled(record.current_path.exists())

    def _open_selected_file(self) -> None:
        row = self.queue_table.currentRow()
        if row < 0:
            return
        document_id = int(self.queue_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
        record = self.current_records.get(document_id)
        if record and record.current_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(record.current_path)))

    def _undo_selected(self) -> None:
        row = self.history_table.currentRow()
        if row < 0:
            return
        document_id = int(
            self.history_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        )
        try:
            restored = self.pipeline.undo(document_id)
            QMessageBox.information(
                self,
                "文件已復原",
                f"已還原檔名與位置：{restored}",
            )
        except (OSError, ValueError, KeyError) as error:
            QMessageBox.warning(self, "無法復原", str(error))
        self.refresh_all()

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "選擇掃描文件",
            self.get_config().scan_folder,
            "文件 (*.pdf *.jpg *.jpeg *.png *.tif *.tiff *.bmp)",
        )
        for file in files:
            self.watcher.submit(Path(file))

    def _scan_existing_folder(self) -> None:
        folder = Path(self.get_config().scan_folder).expanduser()
        try:
            candidates = [
                path
                for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
            ]
        except OSError as error:
            QMessageBox.warning(self, "無法讀取資料夾", str(error))
            return
        if not candidates:
            QMessageBox.information(
                self, "沒有既有文件", "監聽資料夾內沒有支援的掃描檔案。"
            )
            return
        auto_note = (
            "\n目前已開啟高信心自動歸檔，符合門檻的文件可能會直接移動。"
            if self.get_config().auto_archive_enabled
            else ""
        )
        answer = QMessageBox.question(
            self,
            "掃描既有文件",
            f"將分析資料夾內 {len(candidates)} 份既有文件；已處理過的內容會自動略過。{auto_note}\n\n要繼續嗎？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        submitted = self.watcher.scan_existing(folder)
        QMessageBox.information(
            self,
            "已加入分析佇列",
            f"已送出 {submitted} 份文件，辨識完成後會更新待確認清單。",
        )

    def _choose_scan_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "選擇掃描資料夾", self.scan_folder_input.text()
        )
        if folder:
            self.scan_folder_input.setText(folder)

    def _add_archive_rule(self, category: str = "", folder: str = "") -> None:
        row = self.archive_rules_table.rowCount()
        self.archive_rules_table.insertRow(row)
        self.archive_rules_table.setItem(row, 0, QTableWidgetItem(category))
        self.archive_rules_table.setItem(row, 1, QTableWidgetItem(folder))
        self.archive_rules_table.setCurrentCell(row, 0)

    def _remove_archive_rule(self) -> None:
        row = self.archive_rules_table.currentRow()
        if row >= 0:
            self.archive_rules_table.removeRow(row)

    def _choose_archive_folder(self) -> None:
        row = self.archive_rules_table.currentRow()
        if row < 0:
            self._add_archive_rule()
            row = self.archive_rules_table.currentRow()
        current = self.archive_rules_table.item(row, 1)
        start = current.text().strip() if current else ""
        if not start or not Path(start).is_absolute():
            start = self.scan_folder_input.text().strip()
        folder = QFileDialog.getExistingDirectory(self, "選擇歸檔資料夾", start)
        if folder:
            self.archive_rules_table.setItem(row, 1, QTableWidgetItem(folder))

    def _archive_rules_from_table(self) -> dict[str, str]:
        rules: dict[str, str] = {}
        for row in range(self.archive_rules_table.rowCount()):
            category_item = self.archive_rules_table.item(row, 0)
            folder_item = self.archive_rules_table.item(row, 1)
            category = category_item.text().strip() if category_item else ""
            folder = folder_item.text().strip() if folder_item else ""
            if category and folder:
                rules[category] = folder
        return rules

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.allow_close:
            event.accept()
            return
        event.ignore()
        self.hide()

    def show_and_raise(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()
