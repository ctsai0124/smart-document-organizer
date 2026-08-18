from datetime import datetime

from smartdoc.learning import (
    build_filename_template,
    looks_like_default_filename,
    render_filename_template,
    suggest_from_memories,
    text_similarity,
)
from smartdoc.models import AnalysisResult, NamingMemoryRecord


def assessment_analysis(year: int) -> AnalysisResult:
    roc_year = year - 1911
    return AnalysisResult(
        suggested_stem=f"{year}-08-17_考核_檢送{roc_year}年度教師成績考核名冊",
        category="考核",
        document_date=f"{year}-08-17",
        organization=None,
        subject=f"檢送{roc_year}年度教師成績考核名冊",
        document_number=None,
        confidence=0.97,
        reason="分類為考核",
    )


def test_default_scanner_names_are_not_learning_examples() -> None:
    assert looks_like_default_filename("scan_001.pdf")
    assert looks_like_default_filename("IMG-401617.jpg")
    assert looks_like_default_filename("20260818_001.pdf")
    assert not looks_like_default_filename("115年度教師成績考核名冊.pdf")


def test_template_adapts_roc_year_to_new_document() -> None:
    template = build_filename_template(
        "115年度教師成績考核名冊.pdf", assessment_analysis(2026)
    )

    assert template == "{roc_year}年度教師成績{category}名冊"
    assert (
        render_filename_template(template, assessment_analysis(2027))
        == "116年度教師成績考核名冊"
    )


def test_similar_memory_proposes_adapted_name() -> None:
    old_text = "發文日期民國115年 主旨檢送115年度教師成績考核名冊 考核委員會"
    new_text = "發文日期民國116年 主旨檢送116年度教師成績考核名冊 考核委員會"
    now = datetime.now().astimezone()
    memory = NamingMemoryRecord(
        id=7,
        document_id=3,
        source_name="115年度教師成績考核名冊.pdf",
        final_name="115年度教師成績考核名冊.pdf",
        filename_template="{roc_year}年度教師成績{category}名冊",
        category="考核",
        ocr_text=old_text,
        created_at=now,
        updated_at=now,
    )

    suggestion = suggest_from_memories(
        [memory], assessment_analysis(2027), new_text, threshold=0.58
    )

    assert text_similarity(old_text, new_text) > 0.90
    assert suggestion is not None
    assert suggestion.suggested_stem == "116年度教師成績考核名冊"
    assert suggestion.memory_id == 7
