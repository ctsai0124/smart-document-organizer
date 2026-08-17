from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .config import AppConfig, ConfigStore, data_directory
from .database import Database
from .ocr import RapidOcrEngine
from .pipeline import DocumentPipeline
from .ui import MainWindow, UiBridge
from .watcher import FolderWatcher

LOGGER = logging.getLogger(__name__)


def make_app_icon(size: int = 64) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#233640"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, size - 4, size - 4, size * 0.2, size * 0.2)
    painter.setBrush(QColor("#35B6B0"))
    painter.drawRoundedRect(size * 0.20, size * 0.20, size * 0.60, size * 0.12, 3, 3)
    painter.setPen(QColor("#FFFFFF"))
    painter.setFont(
        QFont("Microsoft JhengHei UI", round(size * 0.28), QFont.Weight.Bold)
    )
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "文")
    painter.end()
    return QIcon(pixmap)


class ApplicationController:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.config_store = ConfigStore()
        self.config = self.config_store.load()
        self.database = Database(data_directory() / "documents.sqlite3")
        self.bridge = UiBridge()
        self.pipeline = DocumentPipeline(
            self.database,
            RapidOcrEngine(),
            lambda: self.config,
            self.bridge.data_changed.emit,
        )
        self.watcher = FolderWatcher(self.pipeline)
        self.window = MainWindow(
            database=self.database,
            config_store=self.config_store,
            get_config=lambda: self.config,
            save_config=self.save_config,
            pipeline=self.pipeline,
            watcher=self.watcher,
            bridge=self.bridge,
        )
        self.tray = self._create_tray()
        if self.config.monitoring_enabled:
            try:
                self.watcher.start(Path(self.config.scan_folder))
            except OSError as error:
                LOGGER.exception("Unable to start watcher")
                self.tray.showMessage(
                    "無法啟動監聽", str(error), QSystemTrayIcon.MessageIcon.Warning
                )
        self.monitor_action.setText("暫停監聽" if self.watcher.running else "開始監聽")
        self.bridge.monitoring_changed.emit(self.watcher.running)

    def _create_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(make_app_icon(), self.app)
        tray.setToolTip("智慧文件整理 2.0")
        menu = QMenu()
        show_action = menu.addAction("開啟待確認清單")
        show_action.triggered.connect(self.window.show_and_raise)
        self.monitor_action = menu.addAction("暫停監聽")
        self.monitor_action.triggered.connect(self.toggle_monitoring)
        menu.addSeparator()
        quit_action = menu.addAction("結束程式")
        quit_action.triggered.connect(self.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()
        return tray

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.window.show_and_raise()

    def toggle_monitoring(self) -> None:
        if self.watcher.running:
            self.watcher.stop()
        else:
            self.watcher.start(Path(self.config.scan_folder))
        self.monitor_action.setText("暫停監聽" if self.watcher.running else "開始監聽")
        self.bridge.monitoring_changed.emit(self.watcher.running)

    def save_config(self, config: AppConfig) -> None:
        self.config_store.save(config)
        self.config = config

    def quit(self) -> None:
        self.window.allow_close = True
        self.watcher.close()
        self.tray.hide()
        self.app.quit()


def configure_logging() -> None:
    log_path = data_directory() / "smartdoc.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
    )


def load_stylesheet() -> str:
    return (Path(__file__).with_name("style.qss")).read_text(encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="智慧文件整理 2.0")
    parser.add_argument("--background", action="store_true", help="只顯示系統匣圖示")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])
    configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("智慧文件整理 2.0")
    app.setOrganizationName("LocalDesk")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_app_icon())
    app.setStyleSheet(load_stylesheet())

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "無法啟動", "這台電腦目前沒有可用的系統匣。")
        return 1

    controller = ApplicationController(app)
    if not args.background:
        controller.window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
