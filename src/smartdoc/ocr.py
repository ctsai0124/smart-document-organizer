from __future__ import annotations

import io
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

    def _get_engine(self) -> Any:
        if self._engine is None:
            from rapidocr import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def recognize(self, path: Path, max_pdf_pages: int = 12) -> OcrResult:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            images = self._render_pdf(path, max_pdf_pages)
        else:
            images = [str(path)]

        page_texts: list[str] = []
        scores: list[float] = []
        pages_processed = 0
        engine = self._get_engine()
        for page_number, image in enumerate(images, start=1):
            pages_processed = page_number
            result = engine(image)
            texts, page_scores = self._unpack_result(result)
            if texts:
                page_texts.append(f"--- 第 {page_number} 頁 ---\n" + "\n".join(texts))
                scores.extend(page_scores)
        text = "\n\n".join(page_texts)
        return OcrResult(
            text=text,
            confidence=sum(scores) / len(scores) if scores else 0.0,
            pages_processed=pages_processed,
        )

    @staticmethod
    def _render_pdf(path: Path, max_pages: int):
        import pymupdf
        from PIL import Image

        with pymupdf.open(path) as document:
            for page in document.pages(0, min(len(document), max_pages)):
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0), alpha=False)
                yield Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")

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
