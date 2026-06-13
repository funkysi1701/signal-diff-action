#!/usr/bin/env python3
"""Select high-attention changed paths and map them to reviewer-facing reasons."""

from __future__ import annotations

from fnmatch import fnmatch

from ci_change_categories import classify_changed_path
from risk_score import score_changed_path

DEFAULT_MIN_SCORE = 1.0
DEFAULT_MAX_FILES = 5

_REASON_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "**/secrets/**",
            "**/.env*",
            "*secret*",
            "*password*",
            "*connectionstring*",
        ),
        "secrets or credentials",
    ),
    (
        (
            "**/auth/**",
            "*auth*",
            "*jwt*",
        ),
        "auth-sensitive area",
    ),
    (
        (
            "**/payments/**",
            "**/payment/**",
            "*payment*",
        ),
        "payment path",
    ),
    (
        (
            "**/migrations/**",
            "**/migration/**",
            "*migration*",
        ),
        "database migration",
    ),
    (
        (
            "appsettings.production*",
            "appsettings.*.production*",
            "*.production.json",
        ),
        "production configuration",
    ),
    (
        (
            "*.csproj",
            "package.json",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "go.mod",
            "go.sum",
            "requirements.txt",
            "poetry.lock",
            "gemfile.lock",
            "cargo.lock",
            "*.lock",
        ),
        "dependency manifest",
    ),
)


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _path_matches_pattern(path: str, pattern: str) -> bool:
    lower_path = path.lower()
    lower_pattern = pattern.lower()
    basename = lower_path.rsplit("/", 1)[-1]
    return fnmatch(lower_path, lower_pattern) or fnmatch(basename, lower_pattern)


def _path_matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = _normalize_path(path)
    lower = normalized.lower()
    compact = lower.replace("/", "").replace(".", "").replace("-", "").replace("_", "")
    for pattern in patterns:
        if _path_matches_pattern(lower, pattern):
            return True
        token = pattern.strip("*").lower()
        if token and len(token) >= 4 and token in compact:
            return True
    return False


def review_reasons_for_path(path: str) -> list[str]:
    """Return ordered, de-duplicated human-readable reasons for *path*."""
    reasons: list[str] = []
    for patterns, reason in _REASON_RULES:
        if _path_matches_any(path, patterns):
            reasons.append(reason)

    category = classify_changed_path(path)
    if category == "code" and "business logic (non-test source)" not in reasons:
        reasons.append("business logic (non-test source)")

    return reasons


def is_docs_or_tests_only_change(category_counts: dict[str, int], changed_file_count: int) -> bool:
    """True when every changed file is categorized as docs or tests."""
    if changed_file_count <= 0:
        return False
    if not category_counts:
        return False

    docs = category_counts.get("docs", 0)
    tests = category_counts.get("tests", 0)
    return changed_file_count - docs - tests <= 0


def should_show_files_requiring_review(
    *,
    category_counts: dict[str, int],
    changed_file_count: int,
    selected: list[tuple[str, float, str]],
) -> bool:
    if is_docs_or_tests_only_change(category_counts, changed_file_count):
        return False
    return len(selected) > 0


def select_files_requiring_review(
    changed_paths: list[str],
    *,
    category_counts: dict[str, int] | None = None,
    changed_file_count: int = 0,
    max_files: int = DEFAULT_MAX_FILES,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[tuple[str, float, str]]:
    """Return up to *max_files* ``(path, score, reason)`` tuples ranked by attention score."""
    counts = dict(category_counts or {})
    if changed_file_count <= 0:
        changed_file_count = len([path for path in changed_paths if path.strip()])

    if is_docs_or_tests_only_change(counts, changed_file_count):
        return []

    candidates: list[tuple[str, float, str]] = []
    for path in changed_paths:
        if not isinstance(path, str) or not path.strip():
            continue

        score = score_changed_path(path)
        reasons = review_reasons_for_path(path)
        pattern_reasons = [reason for reason in reasons if reason != "business logic (non-test source)"]
        if score < min_score and not pattern_reasons:
            continue

        reason_text = ", ".join(reasons)
        candidates.append((path, score, reason_text))

    candidates.sort(key=lambda item: (-item[1], item[0].lower()))
    cap = max(1, max_files)
    return candidates[:cap]


def attention_emoji(max_score: float) -> str:
    if max_score >= 7.0:
        return "🔴"
    if max_score >= 4.0:
        return "🟡"
    return "🟢"


def format_files_requiring_review(selected: list[tuple[str, float, str]]) -> list[str]:
    """Render the Files requiring review markdown block."""
    if not selected:
        return []

    max_score = max(score for _, score, _ in selected)
    emoji = attention_emoji(max_score)
    lines = [
        "### Files requiring review",
        "",
        f"{emoji} High attention",
    ]
    for path, _score, reason in selected:
        lines.append(f"- `{path}` — {reason}")
    lines.append("")
    return lines
