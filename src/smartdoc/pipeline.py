from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from .analyzer import LocalAIAnalyzer, RuleBasedAnalyzer
from .config import AppConfig
from .database import Database
from .fileops import (
    is_supported,
    organize_safely,
    restore_safely,
    source_fingerprint,
    wait_until_stable,
)
from .learning import (
    build_filename_template,
    looks_like_default_filename,
    suggest_from_memories,
)
from .models import DocumentRecord, DocumentStatus, NamingMemoryRecord
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
            memory_suggestion = None
            if config.naming_memory_enabled:
                memories = self.database.list_naming_memories(
                    category=analysis.category, limit=200
                )
                memory_suggestion = suggest_from_memories(
                    memories,
                    analysis,
                    ocr.text,
                    threshold=config.naming_memory_threshold,
                )
                if memory_suggestion:
                    analysis = replace(
                        analysis,
                        suggested_stem=memory_suggestion.suggested_stem,
                        reason=(
                            f"{analysis.reason}；參考本機命名記憶「"
                            f"{memory_suggestion.example_name}」"
                            f"（相似 {memory_suggestion.similarity:.0%}）"
                        ),
                    )
            suggested_name = f"{analysis.suggested_stem}{path.suffix.lower()}"
            self.database.complete_analysis(
                document_id,
                suggested_name=suggested_name,
                confidence=analysis.confidence,
                category=analysis.category,
                ocr_text=ocr.text,
                summary=analysis.reason,
            )
            auto_rename = (
                config.auto_rename_enabled
                and analysis.confidence >= config.auto_rename_threshold
                and (
                    memory_suggestion is None
                    or memory_suggestion.similarity >= config.auto_rename_threshold
                )
            )
            auto_archive = (
                config.auto_archive_enabled
                and analysis.confidence >= config.auto_archive_threshold
                and config.archive_destination(analysis.category) is not None
            )
            if auto_rename or auto_archive:
                self.apply(
                    document_id,
                    suggested_name if auto_rename else path.name,
                    archive=auto_archive,
                )
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

    def apply(
        self,
        document_id: int,
        proposed_name: str | None = None,
        *,
        archive: bool | None = None,
    ) -> Path:
        document = self._required_document(document_id)
        if document.status not in {DocumentStatus.PENDING, DocumentStatus.APPLIED}:
            raise ValueError("只有待確認或已套用的文件可以改名或歸檔")
        config = self.get_config()
        should_archive = config.archive_on_apply if archive is None else archive
        destination = (
            config.archive_destination(document.category) if should_archive else None
        )
        new_path = organize_safely(
            document.current_path,
            proposed_name or document.suggested_name,
            destination,
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

    def learn_name(
        self, document_id: int, final_name: str | None = None
    ) -> NamingMemoryRecord:
        document = self._required_document(document_id)
        chosen_name = final_name or document.current_path.name
        if looks_like_default_filename(chosen_name):
            raise ValueError(
                f"「{chosen_name}」看起來是掃描器預設檔名，不會加入命名記憶"
            )
        if not document.ocr_text.strip():
            raise ValueError("這份文件沒有可供學習的 OCR 文字")
        config = self.get_config()
        analysis = self.rule_analyzer.analyze(
            document.ocr_text,
            ocr_confidence=document.confidence,
            template=config.filename_template,
        )
        analysis = replace(analysis, category=document.category)
        filename_template = build_filename_template(chosen_name, analysis)
        memory = self.database.save_naming_memory(
            document.id,
            source_name=document.original_path.name,
            final_name=chosen_name,
            filename_template=filename_template,
            category=document.category,
        )
        self.on_change()
        return memory

    def delete_naming_memory(self, memory_id: int) -> bool:
        deleted = self.database.delete_naming_memory(memory_id)
        if deleted:
            self.on_change()
        return deleted

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
