from smartdoc.analyzer import (
    RuleBasedAnalyzer,
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
    assert "_考核_" in result.suggested_stem
