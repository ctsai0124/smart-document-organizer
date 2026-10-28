from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(slots=True)
class OcrResult:
    text: str
    confidence: float
    pages_processed: int


class OcrEngine(Protocol):
    def recognize(self, path: Path, max_pdf_pages: int = 12) -> OcrResult: ...


class RapidOcrEngine:
    """Lazy-load RapidOCR so the tray app stays light until a file arrives."""

    def __init__(self) -> None:
        self._engine: Any | None = None
        self._engine_lock = threading.Lock()
        self._recognize_lock = threading.Lock()

    def _get_engine(self) -> Any:
        if self._engine is None:
            with self._engine_lock:
                if self._engine is None:
                    from rapidocr import RapidOCR

                    self._engine = RapidOCR()
        return self._engine

    def recognize(self, path: Path, max_pdf_pages: int = 12) -> OcrResult:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._recognize_pdf(path, max_pdf_pages)

        texts, scores = self._recognize_image(str(path))
        return OcrResult(
            text="\n".join(texts),
            confidence=sum(scores) / len(scores) if scores else 0.0,
            pages_processed=1,
        )

    def _recognize_pdf(self, path: Path, max_pages: int) -> OcrResult:
        import pymupdf
        from PIL import Image

        page_texts: list[str] = []
        scores: list[float] = []
        pages_processed = 0
        with pymupdf.open(path) as document:
            for page_number, page in enumerate(
                document.pages(0, min(len(document), max_pages)), start=1
            ):
                pages_processed = page_number
                embedded_text = page.get_text("text").strip()
                if len(embedded_text) >= 40:
                    texts = [embedded_text]
                    page_scores = [1.0]
                else:
                    pixmap = page.get_pixmap(
                        matrix=pymupdf.Matrix(2.0, 2.0), alpha=False
                    )
                    image = Image.frombytes(
                        "RGB", (pixmap.width, pixmap.height), pixmap.samples
                    )
                    texts, page_scores = self._recognize_image(image)
                if texts:
                    page_texts.append(
                        f"--- 第 {page_number} 頁 ---\n" + "\n".join(texts)
                    )
                    scores.extend(page_scores)
                if self._has_document_header("\n".join(page_texts)):
                    break
        return OcrResult(
            text="\n\n".join(page_texts),
            confidence=sum(scores) / len(scores) if scores else 0.0,
            pages_processed=pages_processed,
        )

    def _recognize_image(self, image: Any) -> tuple[list[str], list[float]]:
        engine = self._get_engine()
        with self._recognize_lock:
            return self._unpack_result(engine(image))

    @staticmethod
    def _has_document_header(text: str) -> bool:
        return bool(
            re.search(r"主\s*旨\s*[：:]", text)
            and re.search(r"發\s*文\s*日\s*期\s*[：:]", text)
        )

    @staticmethod
    def _unpack_result(result: Any) -> tuple[list[str], list[float]]:
        if result is None:
            return [], []
        if hasattr(result, "txts"):
            texts = [str(value) for value in (result.txts or [])]
            scores = [float(value) for value in (result.scores or [])]
            return texts, scores
        if isinstance(result, tuple):
            rows = result[0] or []
        else:
            rows = result or []
        texts: list[str] = []
        scores: list[float] = []
        for row in rows:
            if len(row) >= 3:
                texts.append(str(row[1]))
                scores.append(float(row[2]))
        return texts, scores
