#!/usr/bin/env python3
"""Build decision-focused PR comment and workflow summary markdown from a Signal Diff job."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ci_change_categories import format_category_counts
from http_common import merge_headers
from risk_score import compute_risk_score, format_risk_score

REPORT_TITLE = "## Signal Diff Report"


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


def _job_url(api_base_url: str, job_id: str) -> str:
    return f"{_normalize_api_base(api_base_url)}/api/jobs/{job_id}"


def _fetch_json(url: str, api_key: str = "") -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["x-ci-api-key"] = api_key
    req = urllib.request.Request(url, headers=merge_headers(headers), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"Could not fetch {url}: {exc}", file=sys.stderr)
        return None


def _fetch_job(status_url: str, api_key: str, api_base_url: str, job_id: str) -> dict[str, Any] | None:
    resolved = _resolve_status_url(status_url, api_base_url, job_id)
    return _fetch_json(resolved, api_key)


def _fetch_baseline_job(api_base_url: str, baseline_job_id: str, api_key: str) -> dict[str, Any] | None:
    url = _job_url(api_base_url, baseline_job_id)
    job = _fetch_json(url, api_key)
    if job is not None:
        return job
    if api_key:
        return _fetch_json(url, "")
    return None


def _field(obj: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not obj:
        return default
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return default


def _int_field(obj: dict[str, Any] | None, *keys: str, default: int = 0) -> int:
    value = _field(obj, *keys, default=default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _finding_counts(job: dict[str, Any] | None) -> tuple[int, int, int, int]:
    errors = _int_field(job, "errorCount", "ErrorCount")
    warnings = _int_field(job, "warningCount", "WarningCount")
    total = errors + warnings
    return total, errors, warnings, _int_field(job, "infoCount", "InfoCount")


def _fail_policy_would_fail(fail_mode: str, errors: int, warnings: int) -> bool:
    mode = (fail_mode or "error").strip().lower()
    if mode == "none":
        return False
    if mode == "errororwarning":
        return errors > 0 or warnings > 0
    return errors > 0


def _verdict(status: str, fail_mode: str, errors: int, warnings: int) -> tuple[str, str]:
    normalized = (status or "").strip().lower()
    if normalized != "complete":
        return "Fail", "❌"
    if _fail_policy_would_fail(fail_mode, errors, warnings):
        return "Fail", "❌"
    return "Pass", "✅"


def _finding_severity(finding: dict[str, Any]) -> str:
    severity = _field(finding, "severity", "Severity", default="")
    return str(severity).strip()


def _deploy_diff_severity_label(run_diff: dict[str, Any] | None) -> str:
    if not run_diff:
        return "Compared"
    findings = _field(run_diff, "newFindings", "NewFindings", default=[]) or []
    if isinstance(findings, list):
        if any(isinstance(item, dict) and _finding_severity(item).lower() == "error" for item in findings):
            return "Critical"
        if any(isinstance(item, dict) and _finding_severity(item).lower() == "warning" for item in findings):
            return "Warning"
    new_count = _int_field(run_diff, "newFindingCount", "NewFindingCount")
    if new_count > 0:
        return "Info"
    if _int_field(run_diff, "resolvedFindingCount", "ResolvedFindingCount") > 0:
        return "Improved"
    return "Compared"


def _format_finding_line(finding: dict[str, Any]) -> str:
    url = _field(finding, "url", "Url", default="")
    severity = _finding_severity(finding)
    check = _field(finding, "checkName", "CheckName", default="")
    message = _field(finding, "message", "Message", default="")
    parts = [p for p in (severity, check, message) if p]
    detail = " — ".join(str(p) for p in parts) if parts else "Finding"
    if url:
        return f"- [{url}]({url}) — {detail}"
    return f"- {detail}"


def _format_delta(value: int) -> str:
    if value > 0:
        return f"+{value}"
    if value < 0:
        return f"−{abs(value)}"
    return "0"


def _format_baseline_comparison(
    *,
    baseline_job: dict[str, Any] | None,
    current_job: dict[str, Any] | None,
    run_diff: dict[str, Any] | None,
    current_errors: int,
    current_warnings: int,
) -> list[str]:
    lines = ["**Baseline comparison**"]
    new_count = _int_field(run_diff, "newFindingCount", "NewFindingCount")
    resolved_count = _int_field(run_diff, "resolvedFindingCount", "ResolvedFindingCount")

    if baseline_job:
        prev_total, prev_errors, prev_warnings, _ = _finding_counts(baseline_job)
        lines.append(f"Previous scan: {prev_total} findings ({prev_errors} errors, {prev_warnings} warnings)")
    elif run_diff and _field(run_diff, "baselineJobId", "BaselineJobId"):
        lines.append("Previous scan: _baseline job unavailable_")

    current_total = current_errors + current_warnings
    if current_job:
        current_total, current_errors, current_warnings, _ = _finding_counts(current_job)
    lines.append(f"Current scan:  {current_total} findings ({current_errors} errors, {current_warnings} warnings)")
    lines.append(f"New: {_format_delta(new_count)} · Resolved: −{resolved_count}")
    return lines


def _changed_paths_field(code_changes: dict[str, Any] | None) -> list[str]:
    if not code_changes:
        return []
    raw = _field(code_changes, "changedPaths", "ChangedPaths", default=[])
    if not isinstance(raw, list):
        return []
    return [path for path in raw if isinstance(path, str) and path.strip()]


def _category_counts_field(code_changes: dict[str, Any] | None) -> dict[str, int]:
    if not code_changes:
        return {}
    raw = _field(code_changes, "categoryCounts", "CategoryCounts", default={})
    if not isinstance(raw, dict):
        return {}
    counts: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            counts[key] = count
    return counts


def _format_lines_changed(lines_added: int, lines_removed: int) -> str:
    if lines_added <= 0 and lines_removed <= 0:
        return ""
    return f"+{lines_added} / −{lines_removed}"


def build_comment(
    *,
    job: dict[str, Any] | None,
    baseline_job: dict[str, Any] | None = None,
    status: str,
    errors: int,
    warnings: int,
    pages: int,
    job_id: str,
    api_base_url: str,
    workflow_run_url: str,
    fail_mode: str,
    max_new_findings: int,
    risk_score_enabled: bool = True,
) -> str:
    lines: list[str] = [REPORT_TITLE, ""]

    run_diff = _field(job, "runDiff", "RunDiff")
    code_changes = _field(job, "ciCodeChanges", "CiCodeChanges")
    ci = _field(job, "ci", "Ci")

    verdict, verdict_icon = _verdict(status, fail_mode, errors, warnings)
    severity = _deploy_diff_severity_label(run_diff if isinstance(run_diff, dict) else None)
    lines.append(f"### {verdict_icon} {verdict} · **{severity}** severity")
    lines.append("")

    new_count = _int_field(run_diff if isinstance(run_diff, dict) else None, "newFindingCount", "NewFindingCount")
    resolved_count = _int_field(
        run_diff if isinstance(run_diff, dict) else None,
        "resolvedFindingCount",
        "ResolvedFindingCount",
    )
    changed_files = _int_field(code_changes if isinstance(code_changes, dict) else None, "changedFileCount", "ChangedFileCount")
    lines_added = _int_field(code_changes if isinstance(code_changes, dict) else None, "linesAdded", "LinesAdded")
    lines_removed = _int_field(code_changes if isinstance(code_changes, dict) else None, "linesRemoved", "LinesRemoved")
    category_counts = _category_counts_field(code_changes if isinstance(code_changes, dict) else None)
    changed_paths = _changed_paths_field(code_changes if isinstance(code_changes, dict) else None)

    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    if risk_score_enabled:
        risk = compute_risk_score(
            changed_paths=changed_paths,
            category_counts=category_counts,
            changed_file_count=changed_files,
            run_diff=run_diff if isinstance(run_diff, dict) else None,
            errors=errors,
            warnings=warnings,
            fail_mode=fail_mode,
            status=status,
        )
        lines.append(f"| Risk score | {format_risk_score(risk['score'])} |")
    lines.append(f"| SEO errors | {errors} |")
    lines.append(f"| SEO warnings | {warnings} |")
    lines.append(f"| New findings (vs baseline) | {_format_delta(new_count)} |")
    lines.append(f"| Resolved findings | {resolved_count} |")
    if changed_files > 0 or (isinstance(code_changes, dict) and _field(code_changes, "compareUrl", "CompareUrl")):
        display_files = changed_files if changed_files > 0 else "—"
        lines.append(f"| Files changed (this PR) | {display_files} |")
    lines_changed = _format_lines_changed(lines_added, lines_removed)
    if lines_changed:
        lines.append(f"| Lines changed (this PR) | {lines_changed} |")
    if category_counts:
        lines.append(f"| Change categories | {format_category_counts(category_counts)} |")
    lines.append(f"| Pages crawled | {pages} |")
    lines.append("")

    if isinstance(run_diff, dict):
        lines.append("### SEO findings (vs baseline)")
        lines.append("")
        lines.extend(
            _format_baseline_comparison(
                baseline_job=baseline_job,
                current_job=job,
                run_diff=run_diff,
                current_errors=errors,
                current_warnings=warnings,
            )
        )
        lines.append("")

        headline = str(_field(run_diff, "headline", "Headline", default="")).strip()
        if headline:
            lines.append(f"**{headline}**")
            lines.append("")

        impact = str(_field(run_diff, "impactSummary", "ImpactSummary", default="")).strip()
        if impact:
            lines.append(impact)
            lines.append("")

        findings = _field(run_diff, "newFindings", "NewFindings", default=[]) or []
        if new_count > 0 and isinstance(findings, list) and findings:
            lines.append("**New findings:**")
            cap = max(1, max_new_findings)
            listed = [item for item in findings if isinstance(item, dict)][:cap]
            for finding in listed:
                lines.append(_format_finding_line(finding))
            if new_count > cap:
                lines.append(f"- _…and {new_count - cap} more in Signal Diff._")
            lines.append("")

        if resolved_count > 0:
            lines.append(f"_{resolved_count} resolved finding(s) vs baseline._")
            lines.append("")

    if isinstance(code_changes, dict):
        compare_url = str(_field(code_changes, "compareUrl", "CompareUrl", default="")).strip()
        if compare_url or changed_files > 0 or lines_changed or category_counts:
            lines.append("### Repository changes")
            lines.append("")
            if compare_url:
                label = f"{changed_files} changed file(s)" if changed_files > 0 else "Compare on GitHub"
                lines.append(f"- [{label}]({compare_url})")
            elif changed_files > 0:
                lines.append(f"- {changed_files} changed file(s)")
            if lines_changed:
                lines.append(f"- Lines: {lines_changed}")
            category_summary = format_category_counts(category_counts)
            if category_summary:
                lines.append(f"- {category_summary}")
            lines.append("")
            lines.append("_Repository file changes are separate from SEO crawl findings._")
            lines.append("")

    lines.append("### Links")
    lines.append("")
    web = _web_origin(api_base_url)
    if web and job_id:
        lines.append(f"- [View scan in Signal Diff]({web}/scan/{job_id})")
    resolved_workflow_url = workflow_run_url.strip()
    if not resolved_workflow_url and isinstance(ci, dict):
        resolved_workflow_url = str(_field(ci, "workflowRunUrl", "WorkflowRunUrl", default="")).strip()
    if resolved_workflow_url:
        lines.append(f"- [Workflow run]({resolved_workflow_url})")
    if job_id:
        lines.append(f"- Job ID: `{job_id}`")

    return "\n".join(lines).rstrip() + "\n"


def build_fallback_comment(
    *,
    status: str,
    errors: int,
    warnings: int,
    pages: int,
    job_id: str,
    api_base_url: str,
    workflow_run_url: str,
    fail_mode: str,
    risk_score_enabled: bool = True,
) -> str:
    return build_comment(
        job=None,
        baseline_job=None,
        status=status,
        errors=errors,
        warnings=warnings,
        pages=pages,
        job_id=job_id,
        api_base_url=api_base_url,
        workflow_run_url=workflow_run_url,
        fail_mode=fail_mode,
        max_new_findings=5,
        risk_score_enabled=risk_score_enabled,
    )


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
    risk_score_enabled = _env("RISK_SCORE_ENABLED", "true").lower() in ("1", "true", "yes")

    job: dict[str, Any] | None = None
    if status_url or (api_base_url and job_id):
        job = _fetch_job(status_url, api_key, api_base_url, job_id)

    baseline_job: dict[str, Any] | None = None
    if job and api_base_url:
        run_diff = _field(job, "runDiff", "RunDiff")
        baseline_job_id = ""
        if isinstance(run_diff, dict):
            baseline_job_id = str(_field(run_diff, "baselineJobId", "BaselineJobId", default="")).strip()
        if baseline_job_id:
            baseline_job = _fetch_baseline_job(api_base_url, baseline_job_id, api_key)

    if job is None:
        body = build_fallback_comment(
            status=status,
            errors=errors,
            warnings=warnings,
            pages=pages,
            job_id=job_id,
            api_base_url=api_base_url,
            workflow_run_url=workflow_run_url,
            fail_mode=fail_mode,
            risk_score_enabled=risk_score_enabled,
        )
    else:
        body = build_comment(
            job=job,
            baseline_job=baseline_job,
            status=status,
            errors=errors,
            warnings=warnings,
            pages=pages,
            job_id=job_id,
            api_base_url=api_base_url,
            workflow_run_url=workflow_run_url,
            fail_mode=fail_mode,
            max_new_findings=max_new_findings,
            risk_score_enabled=risk_score_enabled,
        )

    out_path = _env("COMMENT_BODY_PATH", "/tmp/signaldiff-pr-comment.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"Wrote report body to {out_path}")

    summary_path = _env("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(body)
        print(f"Appended report to {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
