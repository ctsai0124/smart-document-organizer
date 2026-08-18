from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class DocumentStatus(StrEnum):
    PROCESSING = "processing"
    PENDING = "pending"
    APPLIED = "applied"
    IGNORED = "ignored"
    FAILED = "failed"


@dataclass(slots=True)
class AnalysisResult:
    suggested_stem: str
    category: str
    document_date: str | None
    organization: str | None
    subject: str | None
    document_number: str | None
    confidence: float
    reason: str


@dataclass(slots=True)
class DocumentRecord:
    id: int
    original_path: Path
    current_path: Path
    suggested_name: str
    status: DocumentStatus
    confidence: float
    category: str
    ocr_text: str
    summary: str
    error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class RenameRecord:
    id: int
    document_id: int
    from_path: Path
    to_path: Path
    created_at: datetime
    undone_at: datetime | None


@dataclass(slots=True)
class NamingMemoryRecord:
    id: int
    document_id: int
    source_name: str
    final_name: str
    filename_template: str
    category: str
    ocr_text: str
    created_at: datetime
    updated_at: datetime
