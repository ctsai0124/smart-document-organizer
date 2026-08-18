import sys
from pathlib import Path

import pytest

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

    window.allow_close = True
    window.close()
    watcher.close()
    app.processEvents()
