from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .fileops import sanitize_filename_stem
from .models import AnalysisResult, NamingMemoryRecord

DEFAULT_NAME_PATTERN = re.compile(
    r"^(?:(?:scan|img|image|document|doc|file|untitled|掃描|未命名)[-_ ]*\d*|[\d_-]{3,})$",
    re.IGNORECASE,
)
PLACEHOLDER_PATTERN = re.compile(r"\{[a-z_]+\}")


@dataclass(frozen=True, slots=True)
class NamingMemorySuggestion:
    suggested_stem: str
    memory_id: int
    example_name: str
    similarity: float


def looks_like_default_filename(filename: str) -> bool:
    stem = unicodedata.normalize("NFKC", Path(filename).stem).strip()
    return not stem or bool(DEFAULT_NAME_PATTERN.fullmatch(stem))


def build_filename_template(filename: str, analysis: AnalysisResult) -> str:
    template = sanitize_filename_stem(Path(filename).stem)
    replacements = (
        (analysis.document_number, "{document_number}"),
        (analysis.subject, "{subject}"),
        (analysis.organization, "{organization}"),
    )
    for value, placeholder in replacements:
        if value:
            template = template.replace(sanitize_filename_stem(value), placeholder)

    parsed_date = _parse_date(analysis.document_date)
    if parsed_date:
        year = str(parsed_date.year)
        roc_year = str(parsed_date.year - 1911)
        date_replacements = (
            (parsed_date.isoformat(), "{date}"),
            (parsed_date.strftime("%Y%m%d"), "{date_compact}"),
            (
                f"{roc_year}年{parsed_date.month:02d}月{parsed_date.day:02d}日",
                "{roc_date}",
            ),
            (
                f"{roc_year}年{parsed_date.month}月{parsed_date.day}日",
                "{roc_date}",
            ),
        )
        for value, placeholder in date_replacements:
            template = template.replace(value, placeholder)
        template = re.sub(rf"(?<!\d){re.escape(year)}(?!\d)", "{year}", template)
        template = re.sub(
            rf"(?<!\d){re.escape(roc_year)}(?!\d)", "{roc_year}", template
        )

    if analysis.category:
        template = template.replace(analysis.category, "{category}")
    return template


def render_filename_template(template: str, analysis: AnalysisResult) -> str | None:
    parsed_date = _parse_date(analysis.document_date)
    values: dict[str, str | None] = {
        "{category}": analysis.category,
        "{subject}": analysis.subject,
        "{organization}": analysis.organization,
        "{document_number}": analysis.document_number,
        "{date}": parsed_date.isoformat() if parsed_date else None,
        "{date_compact}": parsed_date.strftime("%Y%m%d") if parsed_date else None,
        "{year}": str(parsed_date.year) if parsed_date else None,
        "{roc_year}": str(parsed_date.year - 1911) if parsed_date else None,
        "{roc_date}": (
            f"{parsed_date.year - 1911}年{parsed_date.month}月{parsed_date.day}日"
            if parsed_date
            else None
        ),
    }
    rendered = template
    for placeholder in PLACEHOLDER_PATTERN.findall(template):
        value = values.get(placeholder)
        if not value:
            return None
        rendered = rendered.replace(placeholder, sanitize_filename_stem(value))
    return sanitize_filename_stem(rendered)


def text_similarity(first: str, second: str) -> float:
    first_features = _text_features(first)
    second_features = _text_features(second)
    if not first_features or not second_features:
        return 0.0
    shared = first_features.keys() & second_features.keys()
    numerator = sum(first_features[key] * second_features[key] for key in shared)
    first_length = math.sqrt(sum(value * value for value in first_features.values()))
    second_length = math.sqrt(sum(value * value for value in second_features.values()))
    return numerator / (first_length * second_length)


def suggest_from_memories(
    memories: list[NamingMemoryRecord],
    analysis: AnalysisResult,
    ocr_text: str,
    *,
    threshold: float,
) -> NamingMemorySuggestion | None:
    best: NamingMemorySuggestion | None = None
    for memory in memories:
        similarity = text_similarity(ocr_text, memory.ocr_text)
        if memory.category == analysis.category:
            similarity = min(1.0, similarity * 0.90 + 0.10)
        required = threshold
        if not PLACEHOLDER_PATTERN.search(memory.filename_template):
            required = max(0.80, threshold + 0.15)
        if similarity < required:
            continue
        rendered = render_filename_template(memory.filename_template, analysis)
        if not rendered:
            continue
        candidate = NamingMemorySuggestion(
            suggested_stem=rendered,
            memory_id=memory.id,
            example_name=memory.final_name,
            similarity=round(similarity, 4),
        )
        if best is None or candidate.similarity > best.similarity:
            best = candidate
    return best


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _text_features(value: str) -> Counter[str]:
    normalized = unicodedata.normalize("NFKC", value[:8000]).casefold()
    normalized = re.sub(r"\d+", "#", normalized)
    features: Counter[str] = Counter()
    for word in re.findall(r"[a-z][a-z0-9_-]{1,}", normalized):
        features[f"w:{word}"] += 1
    for sequence in re.findall(r"[\u3400-\u9fff]+", normalized):
        for size in (2, 3):
            for index in range(max(0, len(sequence) - size + 1)):
                features[f"c:{sequence[index : index + size]}"] += 1
    return features
