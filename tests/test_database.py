import sqlite3
from pathlib import Path

from smartdoc.database import Database
from smartdoc.models import DocumentStatus


def test_document_and_rename_history(tmp_path: Path) -> None:
    database = Database(tmp_path / "documents.sqlite3")
    source = tmp_path / "scan_001.pdf"
    document_id = database.create_processing(source, "fingerprint")
    database.complete_analysis(
        document_id,
        suggested_name="2026-08-17_函文_測試.pdf",
        confidence=0.95,
        category="函文",
        ocr_text="主旨：測試",
        summary="找到文件主旨",
    )
    destination = tmp_path / "2026-08-17_函文_測試.pdf"
    rename_id = database.add_rename(document_id, source, destination)
    database.update_current_path(document_id, destination, DocumentStatus.APPLIED)

    document = database.get_document(document_id)
    rename = database.latest_active_rename(document_id)

    assert document is not None
    assert document.status == DocumentStatus.APPLIED
    assert document.current_path == destination
    assert rename is not None
    assert rename.id == rename_id
    assert database.counts()[DocumentStatus.APPLIED.value] == 1


def test_naming_memory_can_be_saved_listed_and_deleted(tmp_path: Path) -> None:
    database = Database(tmp_path / "documents.sqlite3")
    source = tmp_path / "115年度教師成績考核名冊.pdf"
    document_id = database.create_processing(source, "memory-fingerprint")
    database.complete_analysis(
        document_id,
        suggested_name="2026-08-17_考核_教師成績考核名冊.pdf",
        confidence=0.97,
        category="考核",
        ocr_text="115年度教師成績考核名冊",
        summary="分類為考核",
    )

    memory = database.save_naming_memory(
        document_id,
        source_name=source.name,
        final_name=source.name,
        filename_template="{roc_year}年度教師成績{category}名冊",
        category="考核",
    )

    assert database.naming_memory_count() == 1
    assert database.list_naming_memories("考核")[0].id == memory.id
    assert database.delete_naming_memory(memory.id)
    assert database.naming_memory_count() == 0


def test_analysis_correction_and_aliases_can_be_saved_and_deleted(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "documents.sqlite3")
    source = tmp_path / "scan_001.pdf"
    document_id = database.create_processing(source, "correction-fingerprint")
    database.complete_analysis(
        document_id,
        suggested_name="其他文件.pdf",
        confidence=0.6,
        category="其他文件",
        ocr_text="案件名稱：115年度代理教師甄選結果",
        summary="待確認",
    )

    correction = database.save_analysis_correction(
        document_id,
        source_name=source.name,
        category="人事甄選",
        document_date=None,
        organization=None,
        subject="115年度代理教師甄選結果",
        document_number=None,
        aliases=[("subject", "案件名稱")],
    )

    listed = database.list_analysis_corrections()
    assert listed[0].id == correction.id
    assert listed[0].category == "人事甄選"
    assert listed[0].aliases[0].label == "案件名稱"
    assert database.list_field_aliases()[0].field_name == "subject"
    assert database.delete_analysis_correction(correction.id)
    assert database.list_analysis_corrections() == []
    assert database.list_field_aliases() == []


def test_failed_document_can_be_reclaimed_for_retry(tmp_path: Path) -> None:
    database = Database(tmp_path / "documents.sqlite3")
    source = tmp_path / "retry.pdf"
    document_id, claimed = database.claim_processing(source, "sha256:retry")
    assert claimed
    database.mark_failed(document_id, "temporary error")

    reclaimed_id, reclaimed = database.claim_processing(source, "sha256:retry")

    assert reclaimed
    assert reclaimed_id == document_id
    document = database.get_document(document_id)
    assert document is not None
    assert document.status == DocumentStatus.PROCESSING
    assert document.error is None


def test_interrupted_processing_is_recovered_as_failed(tmp_path: Path) -> None:
    database = Database(tmp_path / "documents.sqlite3")
    source = tmp_path / "interrupted.pdf"
    document_id = database.create_processing(source, "sha256:interrupted")

    assert database.recover_interrupted_processing() == 1

    document = database.get_document(document_id)
    assert document is not None
    assert document.status == DocumentStatus.FAILED
    assert "重新送出" in (document.error or "")


def test_record_move_updates_history_and_path_together(tmp_path: Path) -> None:
    database = Database(tmp_path / "documents.sqlite3")
    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.pdf"
    document_id = database.create_processing(source, "sha256:move")

    rename_id = database.record_move(document_id, source, destination)

    document = database.get_document(document_id)
    rename = database.latest_active_rename(document_id)
    assert document is not None
    assert document.current_path == destination
    assert document.status == DocumentStatus.APPLIED
    assert rename is not None
    assert rename.id == rename_id


def test_structured_analysis_is_persisted_and_list_can_skip_ocr(tmp_path: Path) -> None:
    database = Database(tmp_path / "documents.sqlite3")
    source = tmp_path / "scan.pdf"
    document_id = database.create_processing(source, "sha256:structured")
    database.complete_analysis(
        document_id,
        suggested_name="2026-10-28_函文_測試.pdf",
        confidence=0.95,
        category="函文",
        ocr_text="很長的 OCR 文字",
        summary="找到文件主旨",
        document_date="2026-10-28",
        organization="高雄市政府教育局",
        subject="測試",
        document_number="高市教字第1號",
    )

    full = database.get_document(document_id)
    summary = database.list_documents(include_ocr_text=False)[0]

    assert full is not None
    assert full.subject == "測試"
    assert full.document_number == "高市教字第1號"
    assert summary.ocr_text == ""


def test_existing_database_is_migrated_with_structured_columns(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_path TEXT NOT NULL,
                current_path TEXT NOT NULL,
                source_fingerprint TEXT NOT NULL UNIQUE,
                suggested_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                category TEXT NOT NULL DEFAULT '其他文件',
                ocr_text TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    database = Database(path)
    source = tmp_path / "legacy.pdf"
    document_id = database.create_processing(source, "sha256:legacy-schema")
    database.complete_analysis(
        document_id,
        suggested_name="測試.pdf",
        confidence=0.9,
        category="函文",
        ocr_text="主旨：測試",
        summary="測試",
        subject="測試",
    )

    assert database.get_document(document_id).subject == "測試"
