from pathlib import Path

import pymupdf

from smartdoc.ocr import RapidOcrEngine


def test_pdf_text_layer_is_used_and_can_stop_after_first_page(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "text-layer.pdf"
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((72, 72), "FIRST PAGE WITH ENOUGH EMBEDDED TEXT FOR ANALYSIS")
    second = document.new_page()
    second.insert_text((72, 72), "SECOND PAGE SHOULD NOT BE READ")
    document.save(source)
    document.close()
    engine = RapidOcrEngine()
    monkeypatch.setattr(
        engine, "_has_document_header", lambda text: "FIRST PAGE" in text
    )

    result = engine.recognize(source, max_pdf_pages=6)

    assert result.pages_processed == 1
    assert "FIRST PAGE" in result.text
    assert "SECOND PAGE" not in result.text
    assert result.confidence == 1.0
