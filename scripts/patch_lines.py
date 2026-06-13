#!/usr/bin/env python3
"""Resolve line numbers from GitHub compare unified-diff patches."""

from __future__ import annotations

import re

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def first_changed_line_from_patch(patch: str) -> tuple[int, str] | None:
    """Return ``(line, side)`` for the first addition or deletion in *patch*.

    *side* is ``RIGHT`` for additions and ``LEFT`` for deletions, matching the
    GitHub pull request review comment API.
    """
    if not patch or not patch.strip():
        return None

    old_line = 0
    new_line = 0
    in_hunk = False

    for raw in patch.splitlines():
        if raw.startswith("@@"):
            match = _HUNK_RE.match(raw)
            if not match:
                continue
            old_line = int(match.group(1))
            new_line = int(match.group(2))
            in_hunk = True
            continue

        if not in_hunk:
            continue
        if raw.startswith("+++") or raw.startswith("---"):
            continue

        if raw.startswith("+"):
            return new_line, "RIGHT"
        if raw.startswith("-"):
            return old_line, "LEFT"
        if raw.startswith(" ") or raw.startswith("\\"):
            old_line += 1
            new_line += 1

    return None
