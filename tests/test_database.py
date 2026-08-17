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
