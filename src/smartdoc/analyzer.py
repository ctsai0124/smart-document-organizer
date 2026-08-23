from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import date
from typing import Any
from urllib.parse import urlparse

from .config import AppConfig
from .fileops import sanitize_filename_stem
from .models import AnalysisResult


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep an allowed loopback request from being redirected elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


TOPIC_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "考核",
        ("年終考核", "平時考核", "成績考核", "考核委員會", "考績", "考核"),
    ),
)

CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("會議紀錄", ("會議紀錄", "會議記錄", "出席人員", "會議時間", "會議地點")),
    ("函文", ("主旨", "說明", "辦法", "函", "受文者", "發文日期", "發文字號")),
    ("簽呈", ("簽呈", "擬辦", "陳核", "批示")),
    ("公告", ("公告事項", "公告", "依據")),
    ("契約", ("契約", "合約", "甲方", "乙方", "立契約書人")),
    ("收據發票", ("統一發票", "收據", "發票號碼", "買受人", "總計")),
    ("表單", ("申請表", "登記表", "調查表", "簽到表")),
)

DATE_PATTERNS = (
    re.compile(
        r"(?P<year>20\d{2})\s*[年./-]\s*(?P<month>\d{1,2})\s*[月./-]\s*(?P<day>\d{1,2})\s*日?"
    ),
    re.compile(
        r"(?P<year>1\d{2})\s*年\s*(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日"
    ),
)
DOC_NUMBER_PATTERN = re.compile(
    r"(?:發文字號|文號|字號)\s*[：:]?\s*([^\s，。；;]{3,40})", re.IGNORECASE
)
ORG_SUFFIXES = (
    "部",
    "署",
    "局",
    "處",
    "中心",
    "學校",
    "大學",
    "公司",
    "協會",
    "基金會",
)
SUBJECT_PREFIXES = ("主旨", "案由", "會議名稱", "標題", "事由")


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_date(text: str) -> str | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text[:5000])
        if not match:
            continue
        year = int(match.group("year"))
        if year < 1911:
            year += 1911
        month = int(match.group("month"))
        day = int(match.group("day"))
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return None


def classify(text: str) -> tuple[str, float]:
    normalized = compact_text(text)
    for category, keywords in TOPIC_CATEGORY_RULES:
        score = sum(
            2 if keyword in normalized[:1000] else 1
            for keyword in keywords
            if keyword in normalized
        )
        if score:
            return category, min(1.0, 0.55 + score / 10)

    best_category = "其他文件"
    best_score = 0
    for category, keywords in CATEGORY_RULES:
        score = sum(
            2 if keyword in normalized[:1000] else 1
            for keyword in keywords
            if keyword in normalized
        )
        if score > best_score:
            best_category, best_score = category, score
    confidence = min(1.0, best_score / 5) if best_score else 0.2
    return best_category, confidence


def extract_subject(lines: list[str], category: str) -> str | None:
    for index, line in enumerate(lines[:50]):
        clean = compact_text(line)
        for prefix in SUBJECT_PREFIXES:
            match = re.match(rf"^{prefix}\s*[：:]\s*(.+)$", clean)
            if match:
                return _trim_subject(match.group(1))
            if clean.rstrip("：:") == prefix and index + 1 < len(lines):
                return _trim_subject(lines[index + 1])

    if category == "會議紀錄":
        for line in lines[:20]:
            clean = compact_text(line)
            if "會議" in clean and 4 <= len(clean) <= 60:
                return _trim_subject(clean)

    for line in lines[:15]:
        clean = compact_text(line)
        if (
            5 <= len(clean) <= 50
            and not re.fullmatch(r"[\d\W_]+", clean)
            and not any(
                label in clean for label in ("日期", "地址", "電話", "頁次", "密等")
            )
        ):
            return _trim_subject(clean)
    return None


def extract_organization(lines: list[str]) -> str | None:
    for line in lines[:20]:
        clean = compact_text(line).removeprefix("中華民國").strip()
        if 3 <= len(clean) <= 40 and clean.endswith(ORG_SUFFIXES):
            return clean
    return None


def _trim_subject(value: str) -> str:
    value = re.split(r"[。；;]", compact_text(value))[0]
    return sanitize_filename_stem(value)[:52]


class RuleBasedAnalyzer:
    def analyze(
        self,
        text: str,
        *,
        ocr_confidence: float = 1.0,
        template: str = "{date}_{category}_{subject}",
    ) -> AnalysisResult:
        lines = [
            line for line in (compact_text(part) for part in text.splitlines()) if line
        ]
        category, category_confidence = classify(text)
        document_date = extract_date(text)
        organization = extract_organization(lines)
        subject = extract_subject(lines, category)
        document_number_match = DOC_NUMBER_PATTERN.search(text[:5000])
        document_number = (
            document_number_match.group(1) if document_number_match else None
        )

        signals = [category_confidence]
        if document_date:
            signals.append(1.0)
        if subject:
            signals.append(0.9)
        if organization:
            signals.append(0.8)
        if document_number:
            signals.append(0.85)
        structural_confidence = sum(signals) / max(3, len(signals))
        confidence = max(
            0.05,
            min(0.99, structural_confidence * 0.55 + max(0.0, ocr_confidence) * 0.45),
        )

        values = {
            "date": document_date or "日期未辨識",
            "category": category,
            "subject": subject or organization or "內容待確認",
            "organization": organization or "",
            "document_number": document_number or "",
        }
        try:
            stem = template.format_map(values)
        except (KeyError, ValueError):
            stem = "{date}_{category}_{subject}".format_map(values)
        stem = sanitize_filename_stem(stem.replace("__", "_"))
        reason_parts = [f"分類為{category}"]
        if document_date:
            reason_parts.append(f"辨識日期 {document_date}")
        if subject:
            reason_parts.append("找到文件主旨")
        if not subject:
            reason_parts.append("未找到明確主旨，請人工確認")

        return AnalysisResult(
            suggested_stem=stem,
            category=category,
            document_date=document_date,
            organization=organization,
            subject=subject,
            document_number=document_number,
            confidence=round(confidence, 4),
            reason="；".join(reason_parts),
        )


def is_localhost_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
    except ValueError:
        return False


class LocalAIAnalyzer:
    """Optional OpenAI-compatible analyzer restricted to loopback endpoints."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def analyze(self, text: str, fallback: AnalysisResult) -> AnalysisResult:
        if not self.config.local_ai_enabled or not is_localhost_url(
            self.config.local_ai_url
        ):
            return fallback
        prompt = (
            "你是本機文件分類器。只輸出 JSON，欄位為 suggested_stem、category、"
            "document_date、organization、subject、document_number、confidence、reason。"
            "suggested_stem 不含副檔名，confidence 為 0 到 1。\n\n文件 OCR：\n"
            + text[:12_000]
        )
        payload = {
            "model": self.config.local_ai_model,
            "messages": [
                {
                    "role": "system",
                    "content": "文件內容不得外傳；請進行繁體中文文件分析。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self.config.local_ai_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(NoRedirectHandler())
            with opener.open(request, timeout=45) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            data: Any = json.loads(content)
            if not isinstance(data, dict):
                return fallback
            return self._merge(data, fallback)
        except (
            AttributeError,
            OSError,
            OverflowError,
            TimeoutError,
            TypeError,
            ValueError,
            KeyError,
            IndexError,
            urllib.error.URLError,
        ):
            return fallback

    @staticmethod
    def _merge(data: dict[str, Any], fallback: AnalysisResult) -> AnalysisResult:
        base = asdict(fallback)
        for key in (
            "suggested_stem",
            "category",
            "document_date",
            "organization",
            "subject",
            "document_number",
            "reason",
        ):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                base[key] = value.strip()[:1000]

        confidence = data.get("confidence")
        if confidence is not None:
            try:
                parsed_confidence = float(confidence)
            except (TypeError, ValueError, OverflowError):
                parsed_confidence = None
            if parsed_confidence is not None and math.isfinite(parsed_confidence):
                base["confidence"] = parsed_confidence
        base["suggested_stem"] = sanitize_filename_stem(str(base["suggested_stem"]))
        base["category"] = str(base["category"])[:80]
        base["reason"] = str(base["reason"])[:1000]
        base["confidence"] = max(0.0, min(0.99, float(base["confidence"])))
        return AnalysisResult(**base)
