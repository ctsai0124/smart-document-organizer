import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from smartdoc.fileops import (
    collision_safe_path,
    organize_safely,
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


def test_organize_moves_to_folder_and_restores(tmp_path: Path) -> None:
    source = tmp_path / "scan_002.pdf"
    source.write_bytes(b"assessment")
    destination_folder = tmp_path / "人事" / "考核"

    organized = organize_safely(source, "2026_考核資料.pdf", destination_folder)

    assert organized == destination_folder / "2026_考核資料.pdf"
    assert organized.read_bytes() == b"assessment"
    assert not source.exists()

    restored = restore_safely(organized, source)
    assert restored == source
    assert restored.read_bytes() == b"assessment"


def test_full_fingerprint_distinguishes_files_after_first_64_kib(
    tmp_path: Path,
) -> None:
    prefix = b"A" * (64 * 1024)
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(prefix + b"FIRST-DATA")
    second.write_bytes(prefix + b"OTHER-DATA")
    timestamp = 1_800_000_000_123_456_789
    os.utime(first, ns=(timestamp, timestamp))
    os.utime(second, ns=(timestamp, timestamp))

    assert source_fingerprint(first) != source_fingerprint(second)


def test_concurrent_same_name_moves_never_overwrite(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"FIRST")
    second.write_bytes(b"SECOND")
    destination = tmp_path / "organized"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda source: organize_safely(source, "same.pdf", destination),
                (first, second),
            )
        )

    assert {path.name for path in results} == {"same.pdf", "same_2.pdf"}
    assert {path.read_bytes() for path in results} == {b"FIRST", b"SECOND"}
