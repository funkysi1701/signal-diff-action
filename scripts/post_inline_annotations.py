#!/usr/bin/env python3
"""Post inline pull request review comments on high-risk changed files (best-effort)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ci_change_categories import categorize_changed_paths, classify_changed_path
from http_common import merge_headers
from patch_lines import first_changed_line_from_patch
from review_files import attention_emoji, review_reasons_for_path, select_files_requiring_review

DEFAULT_COMPARE_FILES_PATH = "/tmp/signaldiff-compare-files.json"
ANNOTATION_MARKER_PREFIX = "<!-- signaldiff-annotation:"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _truthy(value: str) -> bool:
    return value.lower() in ("1", "true", "yes")


def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict | None = None,
    timeout: int = 60,
) -> tuple[int, dict | list | None, str]:
    data = None
    req_headers = merge_headers(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            code = resp.getcode()
    except urllib.error.HTTPError as ex:
        raw = ex.read().decode("utf-8", errors="replace")
        code = ex.code
    except urllib.error.URLError as ex:
        return 0, None, str(ex.reason)

    if not raw:
        return code, None, ""
    try:
        return code, json.loads(raw), raw
    except json.JSONDecodeError:
        return code, None, raw


def annotation_marker(path: str) -> str:
    return f"{ANNOTATION_MARKER_PREFIX}{path} -->"


def build_annotation_body(
    *,
    path: str,
    reason: str,
    score: float | None,
    scan_url: str,
) -> str:
    emoji = attention_emoji(score or 0.0) if score is not None else "⚠️"
    lines = [
        f"{emoji} **Signal Diff: review recommended**",
        "",
        f"**File:** `{path}`",
    ]
    if reason:
        lines.append(f"**Reason:** {reason}")
    if score is not None:
        lines.append(f"**Risk score:** {score:.1f}/10")
    lines.append("")
    if scan_url:
        lines.append(f"[View full Signal Diff scan]({scan_url})")
        lines.append("")
    lines.append(annotation_marker(path))
    return "\n".join(lines)


def build_config_annotation_body(*, path: str, scan_url: str) -> str:
    lines = [
        "⚠️ **Signal Diff: configuration changed**",
        "",
        f"**File:** `{path}`",
        "",
        "This file is categorized as config. Review before merge.",
        "",
    ]
    if scan_url:
        lines.append(f"[View full Signal Diff scan]({scan_url})")
        lines.append("")
    lines.append(annotation_marker(path))
    return "\n".join(lines)


def select_annotation_targets(
    changed_paths: list[str],
    *,
    category_counts: dict[str, int] | None,
    max_files: int,
) -> list[tuple[str, str, float | None]]:
    """Return up to *max_files* ``(path, reason, score)`` tuples for inline comments."""
    cap = max(1, max_files)
    review_selected = select_files_requiring_review(
        changed_paths,
        category_counts=category_counts,
        changed_file_count=len(changed_paths),
        max_files=cap,
    )

    targets: list[tuple[str, str, float | None]] = [
        (path, reason, score) for path, score, reason in review_selected
    ]
    seen = {path for path, _, _ in targets}

    if len(targets) >= cap:
        return targets[:cap]

    config_candidates = sorted(
        path
        for path in changed_paths
        if path not in seen and classify_changed_path(path) == "config"
    )
    for path in config_candidates:
        if len(targets) >= cap:
            break
        targets.append((path, "configuration changed", None))
        seen.add(path)

    return targets


def _scan_url(api_base: str, job_id: str) -> str:
    if not api_base or not job_id:
        return ""
    return f"{api_base.rstrip('/')}/scan/{urllib.parse.quote(job_id, safe='')}"


def _list_review_comments(
    *,
    token: str,
    repository: str,
    pull_number: int,
) -> list[dict]:
    owner, repo = repository.split("/", 1)
    comments: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"per_page": "100", "page": str(page)})
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}/comments?{query}"
        code, payload, raw = _http_json(
            "GET",
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if code == 403:
            print(
                "GitHub denied listing pull request review comments (HTTP 403). "
                "Ensure the workflow grants pull-requests: write."
            )
            return []
        if code != 200 or not isinstance(payload, list):
            print(f"Failed to list PR review comments (HTTP {code}): {raw[:300]}")
            return comments

        comments.extend(entry for entry in payload if isinstance(entry, dict))
        if len(payload) < 100:
            break
        page += 1
    return comments


def _find_existing_comment_id(comments: list[dict], path: str) -> int | None:
    marker = annotation_marker(path)
    for comment in comments:
        body = comment.get("body") or ""
        if marker in body:
            comment_id = comment.get("id")
            if isinstance(comment_id, int):
                return comment_id
    return None


def _upsert_review_comment(
    *,
    token: str,
    repository: str,
    pull_number: int,
    commit_sha: str,
    path: str,
    line: int,
    side: str,
    body: str,
    existing_id: int | None,
) -> bool:
    owner, repo = repository.split("/", 1)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if existing_id is not None:
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/comments/{existing_id}"
        code, _, raw = _http_json("PATCH", url, headers=headers, body={"body": body})
        if code == 200:
            print(f"Updated inline annotation on {path}:{line} (comment {existing_id}).")
            return True
        print(f"Failed to update inline annotation on {path} (HTTP {code}): {raw[:300]}")
        return False

    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}/comments"
    payload = {
        "body": body,
        "commit_id": commit_sha,
        "path": path,
        "line": line,
        "side": side,
    }
    code, _, raw = _http_json("POST", url, headers=headers, body=payload)
    if code == 201:
        print(f"Posted inline annotation on {path}:{line} ({side}).")
        return True
    print(f"Failed to post inline annotation on {path} (HTTP {code}): {raw[:300]}")
    return False


def post_inline_annotations_from_compare(
    compare_data: dict,
    *,
    token: str,
    repository: str,
    pull_number: int,
    commit_sha: str,
    api_base: str,
    job_id: str,
    max_files: int,
) -> int:
    files = compare_data.get("files") or []
    patch_by_path = {
        entry.get("filename"): entry.get("patch")
        for entry in files
        if isinstance(entry, dict) and entry.get("filename")
    }

    changed_paths = compare_data.get("changedPaths") or []
    if not isinstance(changed_paths, list):
        changed_paths = []
    changed_paths = [path for path in changed_paths if isinstance(path, str) and path.strip()]

    category_counts = compare_data.get("categoryCounts")
    if not isinstance(category_counts, dict):
        category_counts = categorize_changed_paths(changed_paths)

    targets = select_annotation_targets(
        changed_paths,
        category_counts=category_counts,
        max_files=max_files,
    )
    if not targets:
        print("No qualifying files for inline annotations.")
        return 0

    existing_comments = _list_review_comments(
        token=token,
        repository=repository,
        pull_number=pull_number,
    )
    scan_url = _scan_url(api_base, job_id)
    posted = 0

    for path, reason, score in targets:
        patch = patch_by_path.get(path)
        if not isinstance(patch, str) or not patch.strip():
            print(f"Skipping inline annotation for {path}: no compare patch available.")
            continue

        line_info = first_changed_line_from_patch(patch)
        if line_info is None:
            print(f"Skipping inline annotation for {path}: could not resolve a changed line.")
            continue

        line, side = line_info
        if score is None:
            body = build_config_annotation_body(path=path, scan_url=scan_url)
        else:
            body = build_annotation_body(path=path, reason=reason, score=score, scan_url=scan_url)

        existing_id = _find_existing_comment_id(existing_comments, path)
        if _upsert_review_comment(
            token=token,
            repository=repository,
            pull_number=pull_number,
            commit_sha=commit_sha,
            path=path,
            line=line,
            side=side,
            body=body,
            existing_id=existing_id,
        ):
            posted += 1

    return posted


def main() -> int:
    if not _truthy(_env("INLINE_ANNOTATIONS", "false")):
        print("inline_annotations=false; skipping inline PR annotations.")
        return 0

    if _env("GITHUB_EVENT_NAME") != "pull_request":
        print("Not a pull_request event; skipping inline PR annotations.")
        return 0

    if _truthy(_env("FORK_PR", "false")):
        print("Fork pull request detected; skipping inline PR annotations (insufficient compare access).")
        return 0

    pull_number_raw = _env("PULL_REQUEST_NUMBER")
    if not pull_number_raw:
        print("Missing pull_request_number; skipping inline PR annotations.")
        return 0

    try:
        pull_number = int(pull_number_raw)
    except ValueError:
        print(f"Invalid pull_request_number '{pull_number_raw}'; skipping inline PR annotations.")
        return 0

    token = _env("GITHUB_TOKEN")
    if not token:
        print(
            "No github_token available for inline PR annotations. "
            "Pass github_token and grant pull-requests: write."
        )
        return 0

    repository = _env("REPOSITORY")
    commit_sha = _env("COMMIT_SHA")
    if not repository or not commit_sha:
        print("Missing repository or commit_sha; skipping inline PR annotations.")
        return 0

    compare_path = Path(_env("COMPARE_FILES_PATH", DEFAULT_COMPARE_FILES_PATH))
    if not compare_path.is_file():
        print(
            f"Compare file data not found at {compare_path}. "
            "Enable collect_code_changes or re-run after a successful compare."
        )
        return 0

    try:
        compare_data = json.loads(compare_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        print(f"Could not read compare file data ({compare_path}): {ex}")
        return 0

    if not isinstance(compare_data, dict):
        print("Compare file data is invalid; skipping inline PR annotations.")
        return 0

    max_files = int(_env("ANNOTATION_MAX_FILES", "3") or "3")
    posted = post_inline_annotations_from_compare(
        compare_data,
        token=token,
        repository=repository,
        pull_number=pull_number,
        commit_sha=commit_sha,
        api_base=_env("API_BASE_URL"),
        job_id=_env("JOB_ID"),
        max_files=max(1, max_files),
    )
    print(f"Inline PR annotations complete ({posted} comment(s) posted or updated).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
