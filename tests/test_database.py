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
