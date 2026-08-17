from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "SmartDocumentOrganizer"


def default_scan_folder() -> str:
    documents = Path.home() / "Documents"
    return str(documents / "Scans")


@dataclass(slots=True)
class AppConfig:
    scan_folder: str = ""
    monitoring_enabled: bool = True
    auto_rename_enabled: bool = False
    auto_rename_threshold: float = 0.92
    filename_template: str = "{date}_{category}_{subject}"
    local_ai_enabled: bool = False
    local_ai_url: str = "http://127.0.0.1:11434/v1/chat/completions"
    local_ai_model: str = "qwen2.5:7b"
    start_with_windows: bool = False
    settle_seconds: float = 2.0
    max_pdf_pages: int = 12
    archive_on_apply: bool = False
    auto_archive_enabled: bool = False
    auto_archive_threshold: float = 0.92
    archive_rules: dict[str, str] = field(default_factory=lambda: {"考核": "考核"})

    def __post_init__(self) -> None:
        if not self.scan_folder:
            self.scan_folder = default_scan_folder()
        self.auto_rename_threshold = min(
            1.0, max(0.5, float(self.auto_rename_threshold))
        )
        self.settle_seconds = min(30.0, max(0.5, float(self.settle_seconds)))
        self.max_pdf_pages = min(100, max(1, int(self.max_pdf_pages)))
        self.auto_archive_threshold = min(
            1.0, max(0.5, float(self.auto_archive_threshold))
        )
        rules = self.archive_rules if isinstance(self.archive_rules, dict) else {}
        self.archive_rules = {
            str(category).strip(): str(folder).strip()
            for category, folder in rules.items()
            if str(category).strip() and str(folder).strip()
        }

    def archive_destination(self, category: str) -> Path | None:
        configured = self.archive_rules.get(category.strip())
        if not configured:
            return None
        destination = Path(os.path.expandvars(configured)).expanduser()
        if not destination.is_absolute():
            destination = Path(self.scan_folder).expanduser() / destination
        return destination.resolve()


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        base = Path(user_config_dir(APP_NAME, appauthor=False))
        self.path = path or base / "settings.json"

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            allowed = {field.name for field in fields(AppConfig)}
            return AppConfig(
                **{key: value for key, value in raw.items() if key in allowed}
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self.path)


def data_directory() -> Path:
    path = Path(user_data_dir(APP_NAME, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


class StartupManager:
    """Manage per-user Windows startup without requesting administrator rights."""

    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    VALUE_NAME = "SmartDocumentOrganizer"

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32"

    @classmethod
    def set_enabled(cls, enabled: bool, command: str) -> None:
        if not cls.available():
            return
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, cls.RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(key, cls.VALUE_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, cls.VALUE_NAME)
                except FileNotFoundError:
                    pass


def packaged_startup_command() -> str:
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return f'"{executable}" --background'
    return f'"{executable}" -m smartdoc.app --background'
