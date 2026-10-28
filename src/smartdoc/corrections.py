from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .analyzer import compact_text, extract_date, render_analysis_stem
from .fileops import sanitize_filename_stem
from .learning import text_similarity
from .models import AnalysisCorrectionRecord, AnalysisResult, FieldAliasRecord

LEARNABLE_FIELDS = ("document_date", "organization", "subject", "document_number")
LABEL_PATTERN = re.compile(r"^[\u3400-\u9fffA-Za-z0-9（）() _-]{1,20}$")


@dataclass(frozen=True, slots=True)
class AnalysisCorrectionSuggestion:
    correction_id: int
    example_name: str
    category: str
    similarity: float


def infer_field_aliases(
    ocr_text: str, analysis: AnalysisResult
) -> list[tuple[str, str]]:
    """Learn only explicit labels whose corrected value is present on that line."""
    aliases: set[tuple[str, str]] = set()
    values = {
        "organization": analysis.organization,
        "subject": analysis.subject,
        "document_number": analysis.document_number,
    }
    for raw_line in ocr_text.splitlines()[:100]:
        line = compact_text(raw_line)
        for field_name, corrected_value in values.items():
            if not corrected_value or corrected_value not in line:
                continue
            label = _safe_label(line[: line.index(corrected_value)])
            if label:
                aliases.add((field_name, label))
        if analysis.document_date and extract_date(line) == analysis.document_date:
            match = re.search(r"(?:20\d{2}|1\d{2})\s*[年./-]", line)
            if match:
                label = _safe_label(line[: match.start()])
                if label:
                    aliases.add(("document_date", label))
    return sorted(aliases)


def apply_field_aliases(
    ocr_text: str,
    analysis: AnalysisResult,
    aliases: list[FieldAliasRecord],
    *,
    template: str,
) -> AnalysisResult:
    if not aliases:
        return analysis
    fields_by_label: dict[str, set[str]] = {}
    for alias in aliases:
        fields_by_label.setdefault(alias.label, set()).add(alias.field_name)
    learned: dict[str, list[str]] = {}
    for alias in aliases:
        if len(fields_by_label[alias.label]) != 1:
            continue
        learned.setdefault(alias.field_name, []).append(alias.label)

    updates: dict[str, str | None] = {}
    used_labels: list[str] = []
    for raw_line in ocr_text.splitlines()[:100]:
        line = compact_text(raw_line)
        for field_name, labels in learned.items():
            if field_name in updates:
                continue
            for field_label in labels:
                match = re.match(rf"^{re.escape(field_label)}\s*[：:]\s*(.+)$", line)
                if not match:
                    continue
                value = _alias_value(field_name, match.group(1))
                if value:
                    updates[field_name] = value
                    used_labels.append(field_label)
                    break
    if not updates:
        return analysis
    updated = replace(analysis, **updates)
    return replace(
        updated,
        suggested_stem=render_analysis_stem(template, updated),
        reason=(
            f"{analysis.reason}；依已確認欄位標籤「{'、'.join(sorted(set(used_labels)))}」判讀"
        ),
    )


def suggest_category_correction(
    corrections: list[AnalysisCorrectionRecord],
    ocr_text: str,
    *,
    threshold: float,
) -> AnalysisCorrectionSuggestion | None:
    best: AnalysisCorrectionSuggestion | None = None
    for correction in corrections:
        similarity = text_similarity(ocr_text, correction.ocr_text)
        if similarity < threshold:
            continue
        candidate = AnalysisCorrectionSuggestion(
            correction_id=correction.id,
            example_name=correction.source_name,
            category=correction.category,
            similarity=round(similarity, 4),
        )
        if best is None or candidate.similarity > best.similarity:
            best = candidate
    return best


def _safe_label(value: str) -> str | None:
    label = value.strip().rstrip("：:").strip()
    if not label or not LABEL_PATTERN.fullmatch(label):
        return None
    if not re.search(r"[\u3400-\u9fffA-Za-z]", label):
        return None
    return label


def _alias_value(field_name: str, raw_value: str) -> str | None:
    value = compact_text(raw_value)
    if field_name == "document_date":
        return extract_date(value)
    if field_name == "subject":
        return sanitize_filename_stem(value)[:80] or None
    if field_name == "organization":
        return value[:80] or None
    if field_name == "document_number":
        return value.split()[0][:80] or None
    return None
