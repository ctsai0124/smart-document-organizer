from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from .analyzer import LocalAIAnalyzer, RuleBasedAnalyzer
from .config import AppConfig
from .database import Database
from .fileops import (
    is_supported,
    rename_safely,
    restore_safely,
    source_fingerprint,
    wait_until_stable,
)
from .models import DocumentRecord, DocumentStatus
from .ocr import OcrEngine

LOGGER = logging.getLogger(__name__)


class DocumentPipeline:
    def __init__(
        self,
        database: Database,
        ocr_engine: OcrEngine,
        get_config: Callable[[], AppConfig],
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.database = database
        self.ocr_engine = ocr_engine
        self.get_config = get_config
        self.on_change = on_change or (lambda: None)
        self.rule_analyzer = RuleBasedAnalyzer()
        self._processing: set[str] = set()
        self._lock = threading.Lock()

    def process(self, path: Path, *, wait_for_file: bool = True) -> int | None:
        path = path.resolve()
        key = str(path).casefold()
        with self._lock:
            if key in self._processing:
                return None
            self._processing.add(key)
        document_id: int | None = None
        try:
            if not is_supported(path):
                return None
            config = self.get_config()
            if wait_for_file and not wait_until_stable(
                path, settle_seconds=config.settle_seconds
            ):
                raise TimeoutError("掃描檔在等待時間內仍持續寫入")
            fingerprint = source_fingerprint(path)
            if self.database.has_fingerprint(fingerprint):
                return None
            document_id = self.database.create_processing(path, fingerprint)
            self.on_change()

            ocr = self.ocr_engine.recognize(path, max_pdf_pages=config.max_pdf_pages)
            if not ocr.text.strip():
                raise ValueError("OCR 未辨識出文字，請確認掃描品質或文件語言")
            analysis = self.rule_analyzer.analyze(
                ocr.text,
                ocr_confidence=ocr.confidence,
                template=config.filename_template,
            )
            analysis = LocalAIAnalyzer(config).analyze(ocr.text, analysis)
            suggested_name = f"{analysis.suggested_stem}{path.suffix.lower()}"
            self.database.complete_analysis(
                document_id,
                suggested_name=suggested_name,
                confidence=analysis.confidence,
                category=analysis.category,
                ocr_text=ocr.text,
                summary=analysis.reason,
            )
            if (
                config.auto_rename_enabled
                and analysis.confidence >= config.auto_rename_threshold
            ):
                self.apply(document_id, suggested_name)
            self.on_change()
            return document_id
        except Exception as error:
            LOGGER.exception("Document processing failed: %s", path)
            if document_id is not None:
                self.database.mark_failed(document_id, str(error))
                self.on_change()
            return document_id
        finally:
            with self._lock:
                self._processing.discard(key)

    def apply(self, document_id: int, proposed_name: str | None = None) -> Path:
        document = self._required_document(document_id)
        if document.status not in {DocumentStatus.PENDING, DocumentStatus.APPLIED}:
            raise ValueError("只有待確認或已套用的文件可以改名")
        new_path = rename_safely(
            document.current_path, proposed_name or document.suggested_name
        )
        if new_path != document.current_path:
            self.database.add_rename(document.id, document.current_path, new_path)
        self.database.update_current_path(document.id, new_path, DocumentStatus.APPLIED)
        self.on_change()
        return new_path

    def ignore(self, document_id: int) -> None:
        self._required_document(document_id)
        self.database.set_status(document_id, DocumentStatus.IGNORED)
        self.on_change()

    def undo(self, document_id: int) -> Path:
        document = self._required_document(document_id)
        rename = self.database.latest_active_rename(document_id)
        if rename is None:
            raise ValueError("這份文件沒有可復原的改名紀錄")
        restored = restore_safely(document.current_path, rename.from_path)
        self.database.mark_rename_undone(rename.id)
        self.database.update_current_path(document.id, restored, DocumentStatus.PENDING)
        self.on_change()
        return restored

    def _required_document(self, document_id: int) -> DocumentRecord:
        document = self.database.get_document(document_id)
        if document is None:
            raise KeyError(f"找不到文件紀錄：{document_id}")
        return document
