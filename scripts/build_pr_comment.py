#!/usr/bin/env python3
"""Build enriched PR comment markdown from a completed Signal Diff job JSON."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _normalize_api_base(url: str) -> str:
    base = url.rstrip("/")
    for suffix in ("/api/trigger/ci", "/trigger/ci", "/api/TriggerCiCrawl", "/TriggerCiCrawl"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    if base.endswith("/api"):
        base = base[:-4]
    return base.rstrip("/")


def _web_origin(api_base_url: str) -> str:
    return _normalize_api_base(api_base_url)


def _resolve_status_url(status_url: str, api_base_url: str, job_id: str) -> str:
    if status_url.startswith("http://") or status_url.startswith("https://"):
        return status_url
    base = _normalize_api_base(api_base_url)
    if status_url.startswith("/"):
        return f"{base}{status_url}"
    if status_url:
        return f"{base}/{status_url.lstrip('/')}"
    return f"{base}/api/jobs/{job_id}"


def _fetch_job(status_url: str, api_key: str, api_base_url: str, job_id: str) -> dict[str, Any] | None:
    resolved = _resolve_status_url(status_url, api_base_url, job_id)
    req = urllib.request.Request(
        resolved,
        headers={
            "Authorization": f"Bearer {api_key}",
            "x-ci-api-key": api_key,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"Could not fetch job for PR comment: {exc}", file=sys.stderr)
        return None


def _fail_policy_would_fail(fail_mode: str, errors: int, warnings: int) -> bool:
    mode = (fail_mode or "error").strip().lower()
    if mode == "none":
        return False
    if mode == "errororwarning":
        return errors > 0 or warnings > 0
    return errors > 0


def _format_finding_line(finding: dict[str, Any]) -> str:
    url = finding.get("url") or finding.get("Url") or ""
    severity = finding.get("severity") or finding.get("Severity") or ""
    check = finding.get("checkName") or finding.get("CheckName") or ""
    message = finding.get("message") or finding.get("Message") or ""
    parts = [p for p in (severity, check, message) if p]
    detail = " — ".join(str(p) for p in parts) if parts else "Finding"
    if url:
        return f"- [{url}]({url}) — {detail}"
    return f"- {detail}"


def build_comment(
    *,
    job: dict[str, Any] | None,
    status: str,
    errors: int,
    warnings: int,
    pages: int,
    job_id: str,
    api_base_url: str,
    workflow_run_url: str,
    fail_mode: str,
    max_new_findings: int,
) -> str:
    lines = ["### Signal Diff Crawl Result", ""]

    lines.append(f"- Status: `{status}`")
    lines.append(f"- Pages: `{pages}`")
    lines.append(f"- Errors: `{errors}`")
    lines.append(f"- Warnings: `{warnings}`")
    lines.append(f"- Job ID: `{job_id}`")

    web = _web_origin(api_base_url)
    if web:
        lines.append(f"- [Open in Signal Diff]({web}/scan/{job_id})")

    if workflow_run_url:
        lines.append(f"- [Workflow run]({workflow_run_url})")

    run_diff = (job or {}).get("runDiff") or (job or {}).get("RunDiff")
    ci = (job or {}).get("ci") or (job or {}).get("Ci")
    code_changes = (job or {}).get("ciCodeChanges") or (job or {}).get("CiCodeChanges")

    new_count = int((run_diff or {}).get("newFindingCount") or (run_diff or {}).get("NewFindingCount") or 0)
    show_details = new_count > 0 or _fail_policy_would_fail(fail_mode, errors, warnings)

    if show_details and run_diff:
        headline = (run_diff.get("headline") or run_diff.get("Headline") or "").strip()
        if headline:
            lines.extend(["", f"**Run diff:** {headline}"])
        else:
            lines.extend(["", "**Run diff**"])

        delta_errors = (run_diff.get("deltaErrors") or run_diff.get("DeltaErrors"))
        delta_warnings = (run_diff.get("deltaWarnings") or run_diff.get("DeltaWarnings"))
        if delta_errors is not None or delta_warnings is not None:
            lines.append(
                f"- Δ errors: `{delta_errors or 0}` · Δ warnings: `{delta_warnings or 0}` · "
                f"new findings: `{new_count}`"
            )

        findings = run_diff.get("newFindings") or run_diff.get("NewFindings") or []
        if new_count > 0 and isinstance(findings, list) and findings:
            lines.append("")
            lines.append("**New findings (sample):**")
            cap = max(1, max_new_findings)
            for finding in findings[:cap]:
                if isinstance(finding, dict):
                    lines.append(_format_finding_line(finding))
            if new_count > cap:
                lines.append(f"- _…and {new_count - cap} more in Signal Diff._")

    if code_changes:
        compare_url = (code_changes.get("compareUrl") or code_changes.get("CompareUrl") or "").strip()
        changed_files = code_changes.get("changedFileCount") or code_changes.get("ChangedFileCount")
        if compare_url or changed_files is not None:
            lines.extend(["", "**Code changes**"])
            if compare_url:
                label = f"{changed_files} changed file(s)" if changed_files is not None else "Compare on GitHub"
                lines.append(f"- [{label}]({compare_url})")
            elif changed_files is not None:
                lines.append(f"- Changed files: `{changed_files}`")

    if ci and not workflow_run_url:
        wf = (ci.get("workflowRunUrl") or ci.get("WorkflowRunUrl") or "").strip()
        if wf:
            lines.append(f"- [Workflow run]({wf})")

    if not show_details:
        lines.extend(["", "No new run-diff findings vs baseline. Review full details in Signal Diff."])
    elif not run_diff and not code_changes:
        lines.extend(["", "Review full details in Signal Diff."])

    return "\n".join(lines) + "\n"


def main() -> int:
    status_url = _env("STATUS_URL")
    api_key = _env("API_KEY")
    api_base_url = _env("API_BASE_URL")
    job_id = _env("JOB_ID")
    status = _env("POLL_STATUS", "unknown")
    errors = int(_env("POLL_ERRORS", "0") or "0")
    warnings = int(_env("POLL_WARNINGS", "0") or "0")
    pages = int(_env("POLL_PAGES", "0") or "0")
    workflow_run_url = _env("WORKFLOW_RUN_URL")
    fail_mode = _env("FAIL_MODE", "error")
    max_new_findings = int(_env("MAX_NEW_FINDINGS_IN_COMMENT", "5") or "5")

    job: dict[str, Any] | None = None
    if api_key and (status_url or job_id):
        job = _fetch_job(status_url, api_key, api_base_url, job_id)

    body = build_comment(
        job=job,
        status=status,
        errors=errors,
        warnings=warnings,
        pages=pages,
        job_id=job_id,
        api_base_url=api_base_url,
        workflow_run_url=workflow_run_url,
        fail_mode=fail_mode,
        max_new_findings=max_new_findings,
    )

    out_path = _env("COMMENT_BODY_PATH", "/tmp/signaldiff-pr-comment.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"Wrote PR comment body to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
