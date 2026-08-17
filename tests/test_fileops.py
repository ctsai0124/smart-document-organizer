from pathlib import Path

from smartdoc.fileops import (
    collision_safe_path,
    rename_safely,
    restore_safely,
    sanitize_filename_stem,
    source_fingerprint,
)


def test_sanitizes_windows_filename() -> None:
    assert sanitize_filename_stem(" 主旨：測試 / 會議? ") == "主旨-測試 - 會議"
    assert sanitize_filename_stem("CON") == "CON_文件"


def test_collision_gets_numbered_suffix(tmp_path: Path) -> None:
    existing = tmp_path / "文件.pdf"
    existing.write_bytes(b"existing")
    assert collision_safe_path(existing) == tmp_path / "文件_2.pdf"


def test_rename_and_restore_without_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "scan_001.pdf"
    source.write_bytes(b"document")
    fingerprint = source_fingerprint(source)

    renamed = rename_safely(source, "2026-08-17_會議紀錄.pdf")
    assert renamed.exists()
    assert not source.exists()
    assert source_fingerprint(renamed) == fingerprint

    source.write_bytes(b"occupied")
    restored = restore_safely(renamed, source)
    assert restored.name == "scan_001_2.pdf"
    assert source.read_bytes() == b"occupied"
