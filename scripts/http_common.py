"""Shared HTTP helpers for signal-diff-action scripts."""

from __future__ import annotations

ACTION_USER_AGENT = "signal-diff-action/1.5"


def merge_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    """Return headers with a non-default User-Agent (avoids Cloudflare blocks on Python-urllib)."""
    merged: dict[str, str] = {"User-Agent": ACTION_USER_AGENT}
    if headers:
        merged.update(headers)
    return merged
