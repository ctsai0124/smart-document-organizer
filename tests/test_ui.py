import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from smartdoc.config import AppConfig, ConfigStore
from smartdoc.database import Database
from smartdoc.ocr import OcrResult
from smartdoc.pipeline import DocumentPipeline
from smartdoc.ui import MainWindow, UiBridge
from smartdoc.watcher import FolderWatcher

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows Qt platform smoke test"
)


class NoopOcr:
    def recognize(self, path: Path, max_pdf_pages: int = 12) -> OcrResult:
        return OcrResult(text="考核", confidence=0.99, pages_processed=1)


def test_main_window_builds_with_archive_settings(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    config = AppConfig(scan_folder=str(tmp_path / "scans"))
    database = Database(tmp_path / "documents.sqlite3")
    bridge = UiBridge()
    pipeline = DocumentPipeline(database, NoopOcr(), lambda: config)
    watcher = FolderWatcher(pipeline)
    window = MainWindow(
        database=database,
        config_store=ConfigStore(tmp_path / "settings.json"),
        get_config=lambda: config,
        save_config=lambda value: None,
        pipeline=pipeline,
        watcher=watcher,
        bridge=bridge,
    )

    assert window.queue_table.columnCount() == 6
    assert window.archive_rules_table.rowCount() == 1
    assert window.archive_rules_table.item(0, 0).text() == "考核"
    assert window.pages.count() == 4
    assert window.naming_memory_checkbox.isChecked()
    assert window.memory_table.columnCount() == 5
    assert not window.retry_history_button.isEnabled()

    first = tmp_path / "first.pdf"
    first.write_bytes(b"first")
    first_id = pipeline.process(first, wait_for_file=False)
    assert first_id is not None
    window.refresh_queue()
    first_row = next(
        row
        for row in range(window.queue_table.rowCount())
        if int(window.queue_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
        == first_id
    )
    window.queue_table.item(first_row, 0).setCheckState(Qt.CheckState.Checked)
    window.queue_table.item(first_row, 2).setText("我的人工修改.pdf")

    second = tmp_path / "second.pdf"
    second.write_bytes(b"second")
    assert pipeline.process(second, wait_for_file=False) is not None
    window.refresh_queue()
    first_row = next(
        row
        for row in range(window.queue_table.rowCount())
        if int(window.queue_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
        == first_id
    )
    assert window.queue_table.item(first_row, 0).checkState() == Qt.CheckState.Checked
    assert window.queue_table.item(first_row, 2).text() == "我的人工修改.pdf"

    database.mark_failed(first_id, "temporary error")
    window.refresh_history()
    failed_row = next(
        row
        for row in range(window.history_table.rowCount())
        if int(window.history_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
        == first_id
    )
    window.history_table.selectRow(failed_row)
    window._update_history_actions()
    assert window.retry_history_button.isEnabled()

    window.allow_close = True
    window.close()
    watcher.close()
    app.processEvents()
