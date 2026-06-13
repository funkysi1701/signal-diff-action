#!/usr/bin/env python3
"""Classify changed repository paths into coarse buckets for PR summaries."""

from __future__ import annotations

from fnmatch import fnmatch


CATEGORY_KEYS = ("code", "tests", "config", "dependencies", "migrations", "docs")

_CATEGORY_LABELS = {
    "code": "Code",
    "tests": "Tests",
    "config": "Config",
    "dependencies": "Dependencies",
    "migrations": "Migrations",
    "docs": "Docs",
}


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def classify_changed_path(path: str) -> str:
    """Return a category key for *path* (see CATEGORY_KEYS) or ``other``."""
    normalized = _normalize_path(path)
    lower = normalized.lower()
    basename = lower.rsplit("/", 1)[-1]

    if _is_test_path(lower, basename):
        return "tests"
    if _is_doc_path(lower):
        return "docs"
    if _is_migration_path(lower):
        return "migrations"
    if _is_dependency_path(lower, basename):
        return "dependencies"
    if _is_config_path(lower, basename):
        return "config"
    if _is_production_code_path(lower):
        return "code"

    return "other"


def categorize_changed_paths(paths: list[str]) -> dict[str, int]:
    """Count paths per category; omits empty buckets and ``other``."""
    counts: dict[str, int] = {}
    for path in paths:
        if not isinstance(path, str) or not path.strip():
            continue
        category = classify_changed_path(path)
        if category == "other":
            continue
        counts[category] = counts.get(category, 0) + 1
    return counts


def format_category_counts(counts: dict[str, int]) -> str:
    """Render non-zero buckets as ``Code: 8 · Tests: 1``."""
    parts: list[str] = []
    for key in CATEGORY_KEYS:
        count = counts.get(key, 0)
        if count > 0:
            parts.append(f"{_CATEGORY_LABELS[key]}: {count}")
    return " · ".join(parts)


def _is_test_path(lower: str, basename: str) -> bool:
    return (
        fnmatch(basename, "*test*")
        or fnmatch(basename, "*.spec.*")
        or fnmatch(basename, "*.test.*")
        or fnmatch(lower, "tests")
        or fnmatch(lower, "tests/*")
        or fnmatch(lower, "tests/**/*")
        or fnmatch(lower, "__tests__")
        or fnmatch(lower, "__tests__/*")
        or fnmatch(lower, "__tests__/**/*")
        or "/tests/" in lower
        or "/__tests__/" in lower
    )


def _is_doc_path(lower: str) -> bool:
    return fnmatch(lower, "docs") or fnmatch(lower, "docs/*") or fnmatch(lower, "docs/**/*") or lower.endswith(".md")


def _is_migration_path(lower: str) -> bool:
    return (
        fnmatch(lower, "**/migrations")
        or fnmatch(lower, "**/migrations/*")
        or fnmatch(lower, "**/migrations/**/*")
        or "migration" in lower
    )


def _is_dependency_path(lower: str, basename: str) -> bool:
    patterns = (
        "*.csproj",
        "package.json",
        "go.mod",
        "requirements.txt",
        "*.lock",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "gemfile.lock",
        "cargo.lock",
        "poetry.lock",
    )
    return any(fnmatch(lower, pattern) or fnmatch(basename, pattern) for pattern in patterns)


def _is_config_path(lower: str, basename: str) -> bool:
    if lower == ".github" or lower.startswith(".github/"):
        return True
    patterns = (
        "appsettings*",
        "*.env",
        "*.env.*",
        "docker-compose*",
        "docker-compose.*",
    )
    return any(fnmatch(lower, pattern) or fnmatch(basename, pattern) for pattern in patterns)


def _is_production_code_path(lower: str) -> bool:
    if fnmatch(lower, "src") or fnmatch(lower, "src/*") or fnmatch(lower, "src/**/*"):
        return True
    if fnmatch(lower, "lib") or fnmatch(lower, "lib/*") or fnmatch(lower, "lib/**/*"):
        return True

    code_suffixes = (
        ".cs",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".rb",
        ".php",
        ".vue",
        ".svelte",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".swift",
        ".m",
        ".scala",
        ".razor",
    )
    return lower.endswith(code_suffixes)
