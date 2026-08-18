from pathlib import Path

import pytest

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


class AssessmentOcr:
    def recognize(self, path: Path, max_pdf_pages: int = 12) -> OcrResult:
        return OcrResult(
            text="""臺北市教育局 函
受文者：○○國民小學
發文日期：中華民國115年8月17日
主旨：檢送本年度教職員成績考核及年終考核作業規定。
說明：請提考核委員會審議。
""",
            confidence=0.98,
            pages_processed=1,
        )


class YearlyAssessmentOcr:
    def recognize(self, path: Path, max_pdf_pages: int = 12) -> OcrResult:
        roc_year = 116 if "116" in path.name else 115
        return OcrResult(
            text=f"""臺北市教育局 函
發文日期：中華民國{roc_year}年8月17日
主旨：檢送{roc_year}年度教師成績考核名冊。
說明：請提考核委員會審議。
""",
            confidence=0.98,
            pages_processed=1,
        )


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


def test_confirmed_apply_renames_and_archives_then_undoes(tmp_path: Path) -> None:
    scan_folder = tmp_path / "scans"
    scan_folder.mkdir()
    source = scan_folder / "scan_考核.pdf"
    source.write_bytes(b"fake assessment")
    destination = tmp_path / "人事資料" / "考核"
    database = Database(tmp_path / "documents.sqlite3")
    config = AppConfig(
        scan_folder=str(scan_folder),
        archive_on_apply=True,
        archive_rules={"考核": str(destination)},
    )
    pipeline = DocumentPipeline(database, AssessmentOcr(), lambda: config)

    document_id = pipeline.process(source, wait_for_file=False)
    document = database.get_document(document_id)
    assert document is not None
    assert document.category == "考核"
    assert document.status == DocumentStatus.PENDING

    organized = pipeline.apply(document_id)
    assert organized.parent == destination
    assert organized.name.startswith("2026-08-17_考核_")
    assert not source.exists()

    restored = pipeline.undo(document_id)
    assert restored == source
    assert restored.exists()


def test_high_confidence_auto_archive_can_preserve_original_name(
    tmp_path: Path,
) -> None:
    scan_folder = tmp_path / "scans"
    scan_folder.mkdir()
    source = scan_folder / "scan_003.pdf"
    source.write_bytes(b"fake assessment")
    destination = tmp_path / "分類" / "考核"
    database = Database(tmp_path / "documents.sqlite3")
    config = AppConfig(
        scan_folder=str(scan_folder),
        auto_rename_enabled=False,
        auto_archive_enabled=True,
        auto_archive_threshold=0.50,
        archive_rules={"考核": str(destination)},
    )
    pipeline = DocumentPipeline(database, AssessmentOcr(), lambda: config)

    document_id = pipeline.process(source, wait_for_file=False)
    document = database.get_document(document_id)

    assert document is not None
    assert document.status == DocumentStatus.APPLIED
    assert document.current_path == destination / "scan_003.pdf"
    assert document.current_path.exists()


def test_confirmed_original_name_teaches_future_suggestion(tmp_path: Path) -> None:
    scan_folder = tmp_path / "scans"
    scan_folder.mkdir()
    database = Database(tmp_path / "documents.sqlite3")
    config = AppConfig(
        scan_folder=str(scan_folder),
        naming_memory_enabled=True,
        naming_memory_threshold=0.58,
    )
    pipeline = DocumentPipeline(database, YearlyAssessmentOcr(), lambda: config)

    example = scan_folder / "115年度教師成績考核名冊.pdf"
    example.write_bytes(b"assessment-115")
    example_id = pipeline.process(example, wait_for_file=False)
    assert example_id is not None
    memory = pipeline.learn_name(example_id, example.name)
    pipeline.ignore(example_id)
    assert memory.filename_template == "{roc_year}年度教師成績{category}名冊"

    incoming = scan_folder / "scan_116.pdf"
    incoming.write_bytes(b"assessment-116")
    incoming_id = pipeline.process(incoming, wait_for_file=False)
    incoming_document = database.get_document(incoming_id)

    assert incoming_document is not None
    assert incoming_document.suggested_name == "116年度教師成績考核名冊.pdf"
    assert "參考本機命名記憶" in incoming_document.summary


def test_default_scanner_name_is_rejected_as_memory(tmp_path: Path) -> None:
    source = tmp_path / "scan_999.pdf"
    source.write_bytes(b"fake pdf")
    database = Database(tmp_path / "documents.sqlite3")
    config = AppConfig(scan_folder=str(tmp_path))
    pipeline = DocumentPipeline(database, FakeOcr(), lambda: config)
    document_id = pipeline.process(source, wait_for_file=False)

    with pytest.raises(ValueError, match="預設檔名"):
        pipeline.learn_name(document_id, source.name)

    assert database.naming_memory_count() == 0
