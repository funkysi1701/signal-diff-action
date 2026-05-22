#!/usr/bin/env python3
"""Collect git change summary after a CI crawl and PATCH to Signal Diff (best-effort)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from http_common import merge_headers


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


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


def _resolve_baseline(
    *,
    pr_base_sha: str,
    baseline_ref: str,
    event_name: str,
    api_base: str,
    api_key: str,
    repository: str,
    sitemap_url: str,
    exclude_job_id: str,
) -> str | None:
    if pr_base_sha:
        print(f"Using PR base commit as baseline: {pr_base_sha[:12]}...")
        return pr_base_sha

    if baseline_ref:
        print(f"Using baseline_ref input as baseline: {baseline_ref[:12]}...")
        return baseline_ref

    if event_name not in ("push", "workflow_dispatch"):
        print(f"Event '{event_name}' has no baseline_ref; skipping last-run lookup.")
        return None

    params: dict[str, str] = {"repository": repository, "sitemapUrl": sitemap_url}
    if exclude_job_id:
        params["excludeJobId"] = exclude_job_id
    query = urllib.parse.urlencode(params)
    url = f"{api_base}/api/ci/last-run?{query}"
    print(f"Querying last completed CI run: {url}")
    code, payload, _ = _http_json(
        "GET",
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "x-ci-api-key": api_key,
            "Accept": "application/json",
        },
    )
    if code == 404:
        print("No prior completed CI run for this repository and sitemap (first run is expected).")
        return None
    if code != 200 or not isinstance(payload, dict):
        print(f"Last-run lookup failed with HTTP {code}; skipping code change summary.")
        return None

    commit_sha = (payload.get("commitSha") or "").strip()
    if not commit_sha:
        print("Last-run response missing commitSha; skipping code change summary.")
        return None

    print(f"Using last-run commit as baseline: {commit_sha[:12]}...")
    return commit_sha


def _compare_url(repository: str, baseline: str, head: str, *, two_dot: bool) -> str:
    repo = urllib.parse.quote(repository, safe="/")
    sep = ".." if two_dot else "..."
    # SHAs are hex; keep the compare separator literal (do not percent-encode dots).
    return f"https://api.github.com/repos/{repo}/compare/{baseline}{sep}{head}"


def _github_compare(
    *,
    token: str,
    repository: str,
    baseline: str,
    head: str,
) -> tuple[dict | None, str | None]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    errors: list[str] = []
    for label, two_dot in (("three-dot", False), ("two-dot", True)):
        url = _compare_url(repository, baseline, head, two_dot=two_dot)
        code, payload, raw = _http_json("GET", url, headers=headers)
        if code == 200 and isinstance(payload, dict):
            if two_dot:
                print(f"GitHub compare succeeded using {label} range.")
            return payload, None
        if code in (403, 404):
            errors.append(f"{label} compare HTTP {code} ({url})")
            if raw:
                errors.append(raw[:300])
            continue
        return None, f"GitHub compare API failed with HTTP {code}: {raw[:500]}"

    return None, (
        "GitHub compare API could not diff baseline..head. "
        "Common causes: workflow re-run on an older commit while last-run baseline is newer, "
        "force-pushed history, or missing contents: read. "
        + " | ".join(errors)
    )


def _build_patch(compare: dict, *, baseline: str, head: str, max_files: int) -> dict:
    files = compare.get("files") or []
    commits = compare.get("commits") or []
    paths = [f.get("filename") for f in files if isinstance(f, dict) and f.get("filename")]
    paths = [p for p in paths if isinstance(p, str)]
    capped_paths = paths[:max_files]

    messages: list[str] = []
    for commit in commits[:20]:
        if not isinstance(commit, dict):
            continue
        commit_obj = commit.get("commit") if isinstance(commit.get("commit"), dict) else commit
        message = ""
        if isinstance(commit_obj, dict):
            message = (commit_obj.get("message") or "").strip()
        if message:
            messages.append(message.split("\n", 1)[0])

    compare_url = compare.get("html_url") or ""
    if not compare_url and "/" in _env("GITHUB_SERVER_URL", "https://github.com"):
        server = _env("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        repo = _env("REPOSITORY")
        if repo:
            compare_url = f"{server}/{repo}/compare/{baseline}...{head}"

    return {
        "baselineCommitSha": baseline,
        "headCommitSha": head,
        "compareUrl": compare_url or None,
        "commitCount": compare.get("total_commits") if compare.get("total_commits") is not None else len(commits),
        "changedFileCount": len(paths),
        "changedPaths": capped_paths,
        "commitMessages": messages,
        "collectedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def main() -> int:
    if _env("COLLECT_CODE_CHANGES", "true").lower() not in ("1", "true", "yes"):
        print("collect_code_changes=false; skipping code change summary.")
        return 0

    job_id = _env("JOB_ID")
    api_base = _env("API_BASE_URL").rstrip("/")
    api_key = _env("API_KEY")
    head = _env("COMMIT_SHA")
    repository = _env("REPOSITORY")
    sitemap_url = _env("SITEMAP_URL")
    github_token = _env("GITHUB_TOKEN")
    poll_status = _env("POLL_STATUS")
    max_files = int(_env("MAX_CHANGED_FILES", "50") or "50")

    if poll_status not in ("complete", "failed"):
        print(f"Crawl status '{poll_status}' is not terminal; skipping code change summary.")
        return 0

    if not job_id:
        print("Missing job_id; skipping code change summary.")
        return 0

    if not api_base or not api_key:
        print("Missing API configuration; skipping code change summary.")
        return 0

    if not head:
        print("Missing commit_sha; skipping code change summary.")
        return 0

    if not github_token:
        print(
            "No github_token available for GitHub API calls; skipping code change summary. "
            "Pass github_token or ensure the workflow grants contents: read."
        )
        return 0

    if _env("FORK_PR", "").lower() in ("1", "true", "yes"):
        print("Fork pull request detected; skipping code change summary (insufficient compare access).")
        return 0

    baseline = _resolve_baseline(
        pr_base_sha=_env("PR_BASE_SHA"),
        baseline_ref=_env("BASELINE_REF"),
        event_name=_env("GITHUB_EVENT_NAME"),
        api_base=api_base,
        api_key=api_key,
        repository=repository,
        sitemap_url=sitemap_url,
        exclude_job_id=job_id,
    )
    if not baseline:
        print("No baseline commit resolved; skipping code change summary.")
        return 0

    if baseline == head:
        print("Baseline and head commits are identical; skipping compare.")
        return 0

    compare, compare_error = _github_compare(
        token=github_token,
        repository=repository,
        baseline=baseline,
        head=head,
    )
    push_before = _env("GITHUB_EVENT_BEFORE")
    if compare is None and push_before and push_before not in (baseline, head):
        print(
            f"Retrying compare with github.event.before ({push_before[:12]}...) "
            f"instead of last-run baseline ({baseline[:12]}...)."
        )
        compare, compare_error = _github_compare(
            token=github_token,
            repository=repository,
            baseline=push_before,
            head=head,
        )
        if compare is not None:
            baseline = push_before

    if compare is None:
        print(compare_error or "GitHub compare failed; skipping code change summary.")
        return 0

    patch = _build_patch(compare, baseline=baseline, head=head, max_files=max(1, max_files))
    patch_url = f"{api_base}/api/jobs/{urllib.parse.quote(job_id, safe='')}/ci-changes"
    print(f"PATCH {patch_url}")

    code, _, raw = _http_json(
        "PATCH",
        patch_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "x-ci-api-key": api_key,
            "Accept": "application/json",
        },
        body=patch,
    )
    if code == 200:
        print("Attached CI code change summary to crawl job.")
        _mark_output_collected()
        return 0

    print(f"Failed to PATCH ci-changes (HTTP {code}); crawl result is unchanged. Response: {raw[:500]}")
    return 0


def _mark_output_collected() -> None:
    output_path = _env("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as fh:
        fh.write("collected=true\n")


if __name__ == "__main__":
    sys.exit(main())
