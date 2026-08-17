from pathlib import Path

from smartdoc.config import AppConfig
from smartdoc.database import Database
from smartdoc.models import DocumentStatus
from smartdoc.ocr import OcrResult
from smartdoc.pipeline import DocumentPipeline

OCR_TEXT = """臺北市教育局
受文者：○○國民小學
發文日期：中華民國115年8月17日
發文字號：北市教人字第1150001234號
主旨：檢送年度人事業務會議紀錄，請查照。
說明：依本局會議決議辦理。
"""


class FakeOcr:
    def recognize(self, path: Path, max_pdf_pages: int = 12) -> OcrResult:
        return OcrResult(text=OCR_TEXT, confidence=0.98, pages_processed=1)


def test_pending_apply_and_undo(tmp_path: Path) -> None:
    source = tmp_path / "scan_001.pdf"
    source.write_bytes(b"fake pdf")
    database = Database(tmp_path / "documents.sqlite3")
    config = AppConfig(scan_folder=str(tmp_path), auto_rename_enabled=False)
    pipeline = DocumentPipeline(database, FakeOcr(), lambda: config)

    document_id = pipeline.process(source, wait_for_file=False)
    assert document_id is not None
    document = database.get_document(document_id)
    assert document is not None
    assert document.status == DocumentStatus.PENDING

    renamed = pipeline.apply(document_id)
    assert renamed.exists()
    assert renamed.name.startswith("2026-08-17_函文_")

    restored = pipeline.undo(document_id)
    assert restored == source
    assert restored.exists()
    assert database.get_document(document_id).status == DocumentStatus.PENDING


def test_high_confidence_auto_rename(tmp_path: Path) -> None:
    source = tmp_path / "IMG_401617.jpg"
    source.write_bytes(b"fake image")
    database = Database(tmp_path / "documents.sqlite3")
    config = AppConfig(
        scan_folder=str(tmp_path),
        auto_rename_enabled=True,
        auto_rename_threshold=0.90,
    )
    pipeline = DocumentPipeline(database, FakeOcr(), lambda: config)

    document_id = pipeline.process(source, wait_for_file=False)
    document = database.get_document(document_id)

    assert document is not None
    assert document.status == DocumentStatus.APPLIED
    assert document.current_path.exists()
    assert document.current_path.name != source.name
