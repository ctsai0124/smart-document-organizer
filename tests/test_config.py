from pathlib import Path

from smartdoc.config import AppConfig, ConfigStore


def test_config_round_trip(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    expected = AppConfig(
        scan_folder=str(tmp_path / "scans"),
        auto_rename_enabled=True,
        auto_rename_threshold=0.95,
        archive_on_apply=True,
        auto_archive_enabled=True,
        auto_archive_threshold=0.94,
        archive_rules={"考核": str(tmp_path / "人事" / "考核")},
        naming_memory_enabled=False,
        naming_memory_threshold=0.66,
    )

    store.save(expected)
    actual = store.load()

    assert actual.scan_folder == expected.scan_folder
    assert actual.auto_rename_enabled is True
    assert actual.auto_rename_threshold == 0.95
    assert actual.archive_on_apply is True
    assert actual.auto_archive_enabled is True
    assert actual.auto_archive_threshold == 0.94
    assert actual.archive_rules == expected.archive_rules
    assert actual.naming_memory_enabled is False
    assert actual.naming_memory_threshold == 0.66


def test_relative_archive_destination_uses_scan_folder(tmp_path: Path) -> None:
    config = AppConfig(
        scan_folder=str(tmp_path / "scans"), archive_rules={"考核": "人事/考核"}
    )

    assert config.archive_destination("考核") == tmp_path / "scans" / "人事" / "考核"
    assert config.archive_destination("其他文件") is None


def test_invalid_config_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("not-json", encoding="utf-8")

    loaded = ConfigStore(path).load()

    assert loaded.filename_template == "{date}_{category}_{subject}"
