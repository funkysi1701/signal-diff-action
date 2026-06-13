#!/usr/bin/env python3
"""Rule-based PR risk score from repository paths and SEO crawl signals."""

from __future__ import annotations

from fnmatch import fnmatch
from typing import Any

from ci_change_categories import categorize_changed_paths

PATH_KEYWORD_WEIGHTS: dict[str, float] = {
    "password": 10,
    "secret": 10,
    "connectionstring": 8,
    "migration": 8,
    "auth": 7,
    "payment": 7,
    "jwt": 7,
    "api": 5,
    "appsettings": 4,
}

PATH_PATTERN_BOOSTS: tuple[tuple[str, float], ...] = (
    ("**/migrations/**", 6),
    ("**/migration/**", 6),
    ("**/auth/**", 5),
    ("**/payments/**", 5),
    ("**/payment/**", 5),
    ("appsettings.production*", 6),
    ("appsettings.*.production*", 6),
    ("*.production.json", 5),
    ("**/secrets/**", 6),
    ("**/.env*", 5),
)

RISK_LABELS: tuple[tuple[float, str, str], ...] = (
    (4.0, "Low", "🟢"),
    (7.0, "Medium", "🟡"),
    (10.1, "High", "🔴"),
)

RAW_SCORE_DIVISOR = 3.0


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lower()


def _path_matches_pattern(path: str, pattern: str) -> bool:
    return fnmatch(path, pattern) or fnmatch(path.rsplit("/", 1)[-1], pattern)


def score_changed_path(path: str) -> float:
    """Return a raw risk contribution for a single changed path."""
    normalized = _normalize_path(path)
    if not normalized:
        return 0.0

    compact = normalized.replace("/", "").replace(".", "").replace("-", "").replace("_", "")
    score = 0.0
    for keyword, weight in PATH_KEYWORD_WEIGHTS.items():
        if keyword in compact or keyword in normalized:
            score += weight

    for pattern, boost in PATH_PATTERN_BOOSTS:
        if _path_matches_pattern(normalized, pattern.lower()):
            score += boost

    return score


def _aggregate_path_scores(paths: list[str]) -> float:
    per_path = sorted((score_changed_path(path) for path in paths if path.strip()), reverse=True)
    if not per_path:
        return 0.0
    total = per_path[0]
    if len(per_path) > 1:
        total += sum(per_path[1:]) * 0.4
    return total


def _category_modifier(category_counts: dict[str, int], changed_file_count: int) -> float:
    if changed_file_count <= 0 or not category_counts:
        return 1.0

    docs = category_counts.get("docs", 0)
    tests = category_counts.get("tests", 0)
    non_low_risk = changed_file_count - docs - tests
    if non_low_risk > 0:
        return 1.0

    if docs > 0 and tests == 0:
        return 0.2
    if tests > 0 and docs == 0:
        return 0.25
    if docs > 0 and tests > 0:
        return 0.3
    return 1.0


def _finding_severity(finding: dict[str, Any]) -> str:
    for key in ("severity", "Severity"):
        value = finding.get(key)
        if value is not None:
            return str(value).strip().lower()
    return ""


def _seo_raw_score(
    *,
    run_diff: dict[str, Any] | None,
    errors: int,
    warnings: int,
    fail_mode: str,
    status: str,
) -> float:
    score = 0.0
    new_count = 0
    findings: list[Any] = []

    if isinstance(run_diff, dict):
        raw_new = run_diff.get("newFindingCount", run_diff.get("NewFindingCount", 0))
        try:
            new_count = int(raw_new)
        except (TypeError, ValueError):
            new_count = 0
        raw_findings = run_diff.get("newFindings", run_diff.get("NewFindings", []))
        if isinstance(raw_findings, list):
            findings = raw_findings

    if new_count > 0:
        score += 2.0

    error_findings = 0
    warning_findings = 0
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        severity = _finding_severity(finding)
        if severity == "error":
            error_findings += 1
        elif severity == "warning":
            warning_findings += 1

    score += error_findings * 5.0
    score += warning_findings * 1.5

    if error_findings == 0 and warning_findings == 0 and new_count > 0:
        score += min(new_count, 5) * 1.0

    score += max(errors, 0) * 3.0
    score += min(max(warnings, 0), 10) * 0.5

    normalized_status = (status or "").strip().lower()
    mode = (fail_mode or "error").strip().lower()
    if normalized_status == "complete":
        if mode == "errororwarning" and (errors > 0 or warnings > 0):
            score += 2.0
        elif mode == "error" and errors > 0:
            score += 2.0

    return score


def _normalize_score(raw_score: float) -> float:
    if raw_score <= 0:
        return 0.0
    normalized = raw_score / RAW_SCORE_DIVISOR
    return round(min(10.0, normalized), 1)


def risk_label(score: float) -> tuple[str, str]:
    """Return ``(label, emoji)`` for a normalized 0–10 score."""
    for threshold, label, emoji in RISK_LABELS:
        if score < threshold:
            return label, emoji
    return RISK_LABELS[-1][1], RISK_LABELS[-1][2]


def format_risk_score(score: float) -> str:
    label, emoji = risk_label(score)
    return f"{emoji} {label} ({score}/10)"


def compute_risk_score(
    *,
    changed_paths: list[str] | None = None,
    category_counts: dict[str, int] | None = None,
    changed_file_count: int = 0,
    run_diff: dict[str, Any] | None = None,
    errors: int = 0,
    warnings: int = 0,
    fail_mode: str = "error",
    status: str = "complete",
) -> dict[str, Any]:
    """Compute normalized risk score and metadata for PR summaries."""
    paths = [path for path in (changed_paths or []) if isinstance(path, str) and path.strip()]
    if changed_file_count <= 0 and paths:
        changed_file_count = len(paths)

    counts = dict(category_counts or {})
    if not counts and paths:
        counts = categorize_changed_paths(paths)

    path_raw = _aggregate_path_scores(paths)
    seo_raw = _seo_raw_score(
        run_diff=run_diff,
        errors=errors,
        warnings=warnings,
        fail_mode=fail_mode,
        status=status,
    )
    modifier = _category_modifier(counts, changed_file_count)
    raw_total = (path_raw + seo_raw) * modifier
    score = _normalize_score(raw_total)
    label, emoji = risk_label(score)

    return {
        "score": score,
        "label": label,
        "emoji": emoji,
        "rawScore": round(raw_total, 2),
        "pathRawScore": round(path_raw, 2),
        "seoRawScore": round(seo_raw, 2),
        "categoryModifier": modifier,
    }
