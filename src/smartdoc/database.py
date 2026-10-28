from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .models import (
    AnalysisCorrectionRecord,
    DocumentRecord,
    DocumentStatus,
    FieldAliasRecord,
    NamingMemoryRecord,
    RenameRecord,
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
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
                    document_date TEXT,
                    organization TEXT,
                    subject TEXT,
                    document_number TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_documents_status
                ON documents(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS renames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL REFERENCES documents(id),
                    from_path TEXT NOT NULL,
                    to_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    undone_at TEXT
                );

                CREATE TABLE IF NOT EXISTS naming_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL UNIQUE REFERENCES documents(id),
                    source_name TEXT NOT NULL,
                    final_name TEXT NOT NULL,
                    filename_template TEXT NOT NULL,
                    category TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_naming_memories_category
                ON naming_memories(category, updated_at DESC);

                CREATE TABLE IF NOT EXISTS analysis_corrections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL UNIQUE REFERENCES documents(id),
                    source_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    document_date TEXT,
                    organization TEXT,
                    subject TEXT,
                    document_number TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_analysis_corrections_updated
                ON analysis_corrections(updated_at DESC);

                CREATE TABLE IF NOT EXISTS analysis_field_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    correction_id INTEGER NOT NULL
                        REFERENCES analysis_corrections(id) ON DELETE CASCADE,
                    field_name TEXT NOT NULL,
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(correction_id, field_name, label)
                );
                """
            )
            self._ensure_document_columns(connection)

    @staticmethod
    def _ensure_document_columns(connection: sqlite3.Connection) -> None:
        existing = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(documents)").fetchall()
        }
        for name in ("document_date", "organization", "subject", "document_number"):
            if name not in existing:
                connection.execute(f"ALTER TABLE documents ADD COLUMN {name} TEXT")

    def has_fingerprint(self, fingerprint: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM documents WHERE source_fingerprint = ?", (fingerprint,)
            ).fetchone()
        return row is not None

    def get_document_by_fingerprint(self, fingerprint: str) -> DocumentRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE source_fingerprint = ?", (fingerprint,)
            ).fetchone()
        return self._document_from_row(row) if row else None

    def update_fingerprint(self, document_id: int, fingerprint: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE OR IGNORE documents SET source_fingerprint = ? WHERE id = ?",
                (fingerprint, document_id),
            )
        return cursor.rowcount > 0

    def claim_processing(
        self, path: Path, fingerprint: str, *, force: bool = False
    ) -> tuple[int, bool]:
        """Atomically create a document or reclaim a previously failed one."""
        now = utc_now()
        with self.connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO documents (
                        original_path, current_path, source_fingerprint, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(path),
                        str(path),
                        fingerprint,
                        DocumentStatus.PROCESSING.value,
                        now,
                        now,
                    ),
                )
                return int(cursor.lastrowid), True
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT id, status FROM documents WHERE source_fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
                if row is None:
                    raise
                document_id = int(row["id"])
                if row["status"] != DocumentStatus.FAILED.value and not force:
                    return document_id, False
                connection.execute(
                    """
                    UPDATE documents
                    SET original_path = ?, current_path = ?, status = ?, error = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        str(path),
                        str(path),
                        DocumentStatus.PROCESSING.value,
                        now,
                        document_id,
                    ),
                )
                return document_id, True

    def recover_interrupted_processing(self) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE documents
                SET status = ?, error = ?, updated_at = ?
                WHERE status = ?
                """,
                (
                    DocumentStatus.FAILED.value,
                    "上次執行在辨識完成前中斷，可重新送出處理。",
                    utc_now(),
                    DocumentStatus.PROCESSING.value,
                ),
            )
        return cursor.rowcount

    def create_processing(self, path: Path, fingerprint: str) -> int:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO documents (
                    original_path, current_path, source_fingerprint, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(path),
                    str(path),
                    fingerprint,
                    DocumentStatus.PROCESSING.value,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def complete_analysis(
        self,
        document_id: int,
        *,
        suggested_name: str,
        confidence: float,
        category: str,
        ocr_text: str,
        summary: str,
        document_date: str | None = None,
        organization: str | None = None,
        subject: str | None = None,
        document_number: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE documents
                SET suggested_name = ?, confidence = ?, category = ?, ocr_text = ?,
                    summary = ?, document_date = ?, organization = ?, subject = ?,
                    document_number = ?, status = ?, error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    suggested_name,
                    confidence,
                    category,
                    ocr_text,
                    summary,
                    document_date,
                    organization,
                    subject,
                    document_number,
                    DocumentStatus.PENDING.value,
                    utc_now(),
                    document_id,
                ),
            )

    def mark_failed(self, document_id: int, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE documents SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (DocumentStatus.FAILED.value, error[:1000], utc_now(), document_id),
            )

    def set_status(self, document_id: int, status: DocumentStatus) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE documents SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, utc_now(), document_id),
            )

    def update_current_path(
        self, document_id: int, path: Path, status: DocumentStatus
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE documents SET current_path = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (str(path), status.value, utc_now(), document_id),
            )

    def add_rename(self, document_id: int, from_path: Path, to_path: Path) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO renames(document_id, from_path, to_path, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (document_id, str(from_path), str(to_path), utc_now()),
            )
            return int(cursor.lastrowid)

    def record_move(
        self,
        document_id: int,
        from_path: Path,
        to_path: Path,
        status: DocumentStatus = DocumentStatus.APPLIED,
    ) -> int:
        """Record the move and current path in one SQLite transaction."""
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO renames(document_id, from_path, to_path, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (document_id, str(from_path), str(to_path), now),
            )
            connection.execute(
                """
                UPDATE documents SET current_path = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (str(to_path), status.value, now, document_id),
            )
            return int(cursor.lastrowid)

    def mark_rename_undone(self, rename_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE renames SET undone_at = ? WHERE id = ?", (utc_now(), rename_id)
            )

    def record_undo(
        self, rename_id: int, document_id: int, restored_path: Path
    ) -> None:
        """Mark a rename undone and update the document in one transaction."""
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                "UPDATE renames SET undone_at = ? WHERE id = ?", (now, rename_id)
            )
            connection.execute(
                """
                UPDATE documents SET current_path = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(restored_path),
                    DocumentStatus.PENDING.value,
                    now,
                    document_id,
                ),
            )

    def get_document(self, document_id: int) -> DocumentRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        return self._document_from_row(row) if row else None

    def list_documents(
        self,
        status: DocumentStatus | None = None,
        limit: int = 500,
        *,
        include_ocr_text: bool = True,
    ) -> list[DocumentRecord]:
        ocr_column = "ocr_text" if include_ocr_text else "'' AS ocr_text"
        query = f"""
            SELECT id, original_path, current_path, suggested_name, status,
                   confidence, category, {ocr_column}, summary, document_date,
                   organization, subject, document_number, error, created_at, updated_at
            FROM documents
        """
        params: tuple[object, ...]
        if status is not None:
            query += " WHERE status = ?"
            params = (status.value, limit)
        else:
            params = (limit,)
        query += " ORDER BY updated_at DESC LIMIT ?"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._document_from_row(row) for row in rows]

    def latest_active_rename(self, document_id: int) -> RenameRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM renames
                WHERE document_id = ? AND undone_at IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                (document_id,),
            ).fetchone()
        if not row:
            return None
        return RenameRecord(
            id=row["id"],
            document_id=row["document_id"],
            from_path=Path(row["from_path"]),
            to_path=Path(row["to_path"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            undone_at=datetime.fromisoformat(row["undone_at"])
            if row["undone_at"]
            else None,
        )

    def counts(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS total FROM documents GROUP BY status"
            ).fetchall()
        return {row["status"]: row["total"] for row in rows}

    def save_naming_memory(
        self,
        document_id: int,
        *,
        source_name: str,
        final_name: str,
        filename_template: str,
        category: str,
    ) -> NamingMemoryRecord:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO naming_memories (
                    document_id, source_name, final_name, filename_template,
                    category, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    source_name = excluded.source_name,
                    final_name = excluded.final_name,
                    filename_template = excluded.filename_template,
                    category = excluded.category,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    source_name,
                    final_name,
                    filename_template,
                    category,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT m.*, d.ocr_text
                FROM naming_memories AS m
                JOIN documents AS d ON d.id = m.document_id
                WHERE m.document_id = ?
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("無法儲存命名記憶")
        return self._naming_memory_from_row(row)

    def list_naming_memories(
        self,
        category: str | None = None,
        limit: int = 500,
        *,
        include_ocr_text: bool = True,
    ) -> list[NamingMemoryRecord]:
        ocr_column = "d.ocr_text" if include_ocr_text else "'' AS ocr_text"
        query = f"""
            SELECT m.*, {ocr_column}
            FROM naming_memories AS m
            JOIN documents AS d ON d.id = m.document_id
        """
        params: tuple[object, ...]
        if category:
            query += " WHERE m.category = ?"
            params = (category, limit)
        else:
            params = (limit,)
        query += " ORDER BY m.updated_at DESC LIMIT ?"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._naming_memory_from_row(row) for row in rows]

    def delete_naming_memory(self, memory_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM naming_memories WHERE id = ?", (memory_id,)
            )
        return cursor.rowcount > 0

    def naming_memory_count(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM naming_memories"
            ).fetchone()
        return int(row["total"]) if row else 0

    def save_analysis_correction(
        self,
        document_id: int,
        *,
        source_name: str,
        category: str,
        document_date: str | None,
        organization: str | None,
        subject: str | None,
        document_number: str | None,
        aliases: list[tuple[str, str]],
        suggested_name: str | None = None,
        confidence: float | None = None,
        summary: str | None = None,
    ) -> AnalysisCorrectionRecord:
        now = utc_now()
        with self.connect() as connection:
            if suggested_name is not None:
                if confidence is None or summary is None:
                    raise ValueError("更新文件分析時必須提供信心與摘要")
                connection.execute(
                    """
                    UPDATE documents
                    SET suggested_name = ?, confidence = ?, category = ?, summary = ?,
                        document_date = ?, organization = ?, subject = ?,
                        document_number = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        suggested_name,
                        confidence,
                        category,
                        summary,
                        document_date,
                        organization,
                        subject,
                        document_number,
                        now,
                        document_id,
                    ),
                )
            connection.execute(
                """
                INSERT INTO analysis_corrections (
                    document_id, source_name, category, document_date,
                    organization, subject, document_number, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    source_name = excluded.source_name,
                    category = excluded.category,
                    document_date = excluded.document_date,
                    organization = excluded.organization,
                    subject = excluded.subject,
                    document_number = excluded.document_number,
                    updated_at = excluded.updated_at
                """,
                (
                    document_id,
                    source_name,
                    category,
                    document_date,
                    organization,
                    subject,
                    document_number,
                    now,
                    now,
                ),
            )
            correction_row = connection.execute(
                "SELECT * FROM analysis_corrections WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if correction_row is None:
                raise RuntimeError("無法儲存分析校正")
            correction_id = int(correction_row["id"])
            connection.execute(
                "DELETE FROM analysis_field_aliases WHERE correction_id = ?",
                (correction_id,),
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO analysis_field_aliases (
                    correction_id, field_name, label, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (correction_id, field_name, label, now)
                    for field_name, label in aliases
                ],
            )
        correction = self.get_analysis_correction(correction_id)
        if correction is None:
            raise RuntimeError("無法讀回分析校正")
        return correction

    def get_analysis_correction(
        self, correction_id: int
    ) -> AnalysisCorrectionRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT c.*, d.ocr_text
                FROM analysis_corrections AS c
                JOIN documents AS d ON d.id = c.document_id
                WHERE c.id = ?
                """,
                (correction_id,),
            ).fetchone()
            if row is None:
                return None
            alias_rows = connection.execute(
                """
                SELECT * FROM analysis_field_aliases
                WHERE correction_id = ? ORDER BY field_name, label
                """,
                (correction_id,),
            ).fetchall()
        return self._analysis_correction_from_row(row, alias_rows)

    def list_analysis_corrections(
        self, limit: int = 500, *, include_ocr_text: bool = True
    ) -> list[AnalysisCorrectionRecord]:
        ocr_column = "d.ocr_text" if include_ocr_text else "'' AS ocr_text"
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT c.*, {ocr_column}
                FROM analysis_corrections AS c
                JOIN documents AS d ON d.id = c.document_id
                ORDER BY c.updated_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            correction_ids = [int(row["id"]) for row in rows]
            aliases_by_correction: dict[int, list[sqlite3.Row]] = {
                correction_id: [] for correction_id in correction_ids
            }
            if correction_ids:
                placeholders = ",".join("?" for _ in correction_ids)
                alias_rows = connection.execute(
                    f"""
                    SELECT * FROM analysis_field_aliases
                    WHERE correction_id IN ({placeholders})
                    ORDER BY field_name, label
                    """,
                    correction_ids,
                ).fetchall()
                for alias_row in alias_rows:
                    aliases_by_correction[int(alias_row["correction_id"])].append(
                        alias_row
                    )
        return [
            self._analysis_correction_from_row(
                row, aliases_by_correction[int(row["id"])]
            )
            for row in rows
        ]

    def list_field_aliases(self, limit: int = 1000) -> list[FieldAliasRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM analysis_field_aliases
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._field_alias_from_row(row) for row in rows]

    def delete_analysis_correction(self, correction_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM analysis_corrections WHERE id = ?", (correction_id,)
            )
        return cursor.rowcount > 0

    @staticmethod
    def _document_from_row(row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"],
            original_path=Path(row["original_path"]),
            current_path=Path(row["current_path"]),
            suggested_name=row["suggested_name"],
            status=DocumentStatus(row["status"]),
            confidence=float(row["confidence"]),
            category=row["category"],
            ocr_text=row["ocr_text"],
            summary=row["summary"],
            document_date=row["document_date"],
            organization=row["organization"],
            subject=row["subject"],
            document_number=row["document_number"],
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _naming_memory_from_row(row: sqlite3.Row) -> NamingMemoryRecord:
        return NamingMemoryRecord(
            id=row["id"],
            document_id=row["document_id"],
            source_name=row["source_name"],
            final_name=row["final_name"],
            filename_template=row["filename_template"],
            category=row["category"],
            ocr_text=row["ocr_text"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @classmethod
    def _analysis_correction_from_row(
        cls, row: sqlite3.Row, alias_rows: list[sqlite3.Row]
    ) -> AnalysisCorrectionRecord:
        return AnalysisCorrectionRecord(
            id=row["id"],
            document_id=row["document_id"],
            source_name=row["source_name"],
            category=row["category"],
            document_date=row["document_date"],
            organization=row["organization"],
            subject=row["subject"],
            document_number=row["document_number"],
            ocr_text=row["ocr_text"],
            aliases=tuple(cls._field_alias_from_row(item) for item in alias_rows),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _field_alias_from_row(row: sqlite3.Row) -> FieldAliasRecord:
        return FieldAliasRecord(
            id=row["id"],
            correction_id=row["correction_id"],
            field_name=row["field_name"],
            label=row["label"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
