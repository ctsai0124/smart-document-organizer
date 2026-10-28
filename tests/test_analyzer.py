from smartdoc.analyzer import (
    LocalAIAnalyzer,
    RuleBasedAnalyzer,
    classify,
    extract_date,
    extract_organization,
    is_localhost_url,
)

SAMPLE_DOCUMENT = """臺北市教育局
受文者：○○國民小學
發文日期：中華民國115年8月17日
發文字號：北市教人字第1150001234號
主旨：檢送年度人事業務會議紀錄，請查照。
說明：依本局會議決議辦理。
"""


def test_extracts_roc_date() -> None:
    assert extract_date(SAMPLE_DOCUMENT) == "2026-08-17"


def test_organization_keeps_leading_country_character() -> None:
    assert extract_organization(["國立臺灣大學"]) == "國立臺灣大學"


def test_proposes_safe_public_document_name() -> None:
    result = RuleBasedAnalyzer().analyze(SAMPLE_DOCUMENT, ocr_confidence=0.98)

    assert result.document_date == "2026-08-17"
    assert result.category == "函文"
    assert result.organization == "臺北市教育局"
    assert result.document_number == "北市教人字第1150001234號"
    assert result.suggested_stem.startswith("2026-08-17_函文_")
    assert result.confidence >= 0.9


def test_local_ai_endpoint_is_restricted_to_loopback() -> None:
    assert is_localhost_url("http://127.0.0.1:11434/v1/chat/completions")
    assert is_localhost_url("http://localhost:1234/v1/chat/completions")
    assert not is_localhost_url("https://api.example.com/v1/chat/completions")
    assert not is_localhost_url("file:///tmp/socket")


def test_assessment_topic_takes_priority_over_public_document_form() -> None:
    text = """臺北市教育局 函
受文者：○○國民小學
主旨：檢送本年度教職員成績考核及年終考核作業規定。
說明：請依考核委員會決議辦理。
"""

    result = RuleBasedAnalyzer().analyze(text, ocr_confidence=0.98)

    assert result.category == "考核"
    assert result.suggested_stem.startswith("考核_")
    assert "日期未辨識" not in result.suggested_stem


def test_local_ai_merge_ignores_invalid_field_types() -> None:
    fallback = RuleBasedAnalyzer().analyze(SAMPLE_DOCUMENT, ocr_confidence=0.98)

    result = LocalAIAnalyzer._merge(
        {
            "suggested_stem": ["invalid"],
            "category": {"invalid": True},
            "confidence": [],
            "reason": 123,
        },
        fallback,
    )

    assert result == fallback


def test_labeled_issue_date_wins_over_earlier_unrelated_date() -> None:
    text = "附件版本 2025年1月2日\n發文日期：中華民國115年10月28日"

    assert extract_date(text) == "2026-10-28"


def test_document_header_is_not_mistaken_for_subject() -> None:
    text = """高雄市政府教育局 函
地址：高雄市鳳山區光復路二段132號
承辦單位：人事室
發文日期：中華民國115年10月28日
發文字號：高市教人字第1150001234號
說明：請依規定辦理。
"""

    result = RuleBasedAnalyzer().analyze(text)

    assert result.subject is None
    assert result.confidence <= 0.75
    assert "內容待確認" not in result.suggested_stem
    assert "日期未辨識" not in result.suggested_stem


def test_page_marker_and_organization_are_not_fallback_subjects() -> None:
    text = """--- 第 1 頁 ---
高雄市政府教育局
發文日期：中華民國115年10月28日
發文字號：高市教人字第1150001234號
"""

    result = RuleBasedAnalyzer().analyze(text)

    assert result.organization == "高雄市政府教育局"
    assert result.subject is None
    assert result.confidence <= 0.75


def test_single_generic_assessment_mention_does_not_override_form() -> None:
    category, _ = classify("臺北市教育局 函，本文件僅於說明中提及考核一次。")

    assert category == "函文"


def test_local_ai_merge_rejects_unknown_category_and_invalid_date() -> None:
    fallback = RuleBasedAnalyzer().analyze(SAMPLE_DOCUMENT, ocr_confidence=0.98)

    result = LocalAIAnalyzer._merge(
        {"category": "任意新分類", "document_date": "明天", "confidence": 1},
        fallback,
    )

    assert result.category == fallback.category
    assert result.document_date == fallback.document_date
    assert fallback.confidence <= result.confidence <= 0.99
