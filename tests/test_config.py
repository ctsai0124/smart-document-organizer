from pathlib import Path

from smartdoc.config import AppConfig, ConfigStore


def test_config_round_trip(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "settings.json")
    expected = AppConfig(
        scan_folder=str(tmp_path / "scans"),
        auto_rename_enabled=True,
        auto_rename_threshold=0.95,
    )

    store.save(expected)
    actual = store.load()

    assert actual.scan_folder == expected.scan_folder
    assert actual.auto_rename_enabled is True
    assert actual.auto_rename_threshold == 0.95


def test_invalid_config_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("not-json", encoding="utf-8")

    loaded = ConfigStore(path).load()

    assert loaded.filename_template == "{date}_{category}_{subject}"
