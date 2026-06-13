#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from build_pr_comment import (  # noqa: E402
    REPORT_TITLE,
    build_comment,
    build_fallback_comment,
    _deploy_diff_severity_label,
    _fail_policy_would_fail,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class BuildPrCommentTests(unittest.TestCase):
    def test_leads_with_verdict_not_status_bullets(self) -> None:
        job = _load("job_with_run_diff.json")
        baseline = _load("baseline_job.json")
        body = build_comment(
            job=job,
            baseline_job=baseline,
            status="complete",
            errors=0,
            warnings=14,
            pages=120,
            job_id="current-job-002",
            api_base_url="https://api.signaldiff.dev",
            workflow_run_url="https://github.com/acme/repo/actions/runs/99",
            fail_mode="error",
            max_new_findings=5,
        )

        lines = body.splitlines()
        self.assertEqual(lines[0], REPORT_TITLE)
        self.assertTrue(any(line.startswith("### ✅ Pass") for line in lines))
        self.assertFalse(any(line.startswith("- Status:") for line in lines))
        self.assertFalse(any("No new run-diff findings vs baseline" in line for line in lines))

    def test_baseline_comparison_uses_previous_current_new_resolved(self) -> None:
        job = _load("job_with_run_diff.json")
        baseline = _load("baseline_job.json")
        body = build_comment(
            job=job,
            baseline_job=baseline,
            status="complete",
            errors=0,
            warnings=14,
            pages=120,
            job_id="current-job-002",
            api_base_url="https://api.signaldiff.dev",
            workflow_run_url="",
            fail_mode="error",
            max_new_findings=5,
        )

        self.assertIn("**Baseline comparison**", body)
        self.assertIn("Previous scan: 12 findings (0 errors, 12 warnings)", body)
        self.assertIn("Current scan:  14 findings (0 errors, 14 warnings)", body)
        self.assertIn("New: +2 · Resolved: −0", body)

    def test_impact_summary_surfaced_when_present(self) -> None:
        job = _load("job_with_run_diff.json")
        body = build_comment(
            job=job,
            baseline_job=None,
            status="complete",
            errors=0,
            warnings=14,
            pages=120,
            job_id="current-job-002",
            api_base_url="https://api.signaldiff.dev",
            workflow_run_url="",
            fail_mode="error",
            max_new_findings=5,
        )

        self.assertIn("MetaDescription: Description is too short (2 new occurrence(s)).", body)

    def test_repository_changes_separate_from_seo_findings(self) -> None:
        job = _load("job_with_run_diff.json")
        body = build_comment(
            job=job,
            baseline_job=None,
            status="complete",
            errors=0,
            warnings=14,
            pages=120,
            job_id="current-job-002",
            api_base_url="https://api.signaldiff.dev",
            workflow_run_url="",
            fail_mode="error",
            max_new_findings=5,
        )

        seo_idx = body.index("### SEO findings (vs baseline)")
        repo_idx = body.index("### Repository changes")
        self.assertLess(seo_idx, repo_idx)
        self.assertIn("Repository file changes are separate from SEO crawl findings", body)

    def test_critical_severity_for_error_findings(self) -> None:
        job = _load("job_critical.json")
        body = build_comment(
            job=job,
            baseline_job=None,
            status="complete",
            errors=1,
            warnings=0,
            pages=42,
            job_id="current-job-003",
            api_base_url="https://api.signaldiff.dev",
            workflow_run_url="",
            fail_mode="error",
            max_new_findings=5,
        )

        self.assertIn("### ❌ Fail · **Critical** severity", body)
        self.assertEqual(_deploy_diff_severity_label(job["runDiff"]), "Critical")

    def test_fallback_comment_uses_signal_diff_report_header(self) -> None:
        body = build_fallback_comment(
            status="complete",
            errors=0,
            warnings=3,
            pages=10,
            job_id="job-fallback",
            api_base_url="https://api.signaldiff.dev",
            workflow_run_url="https://github.com/acme/repo/actions/runs/1",
            fail_mode="error",
        )

        self.assertTrue(body.startswith(REPORT_TITLE))
        self.assertIn("### ✅ Pass · **Compared** severity", body)
        self.assertIn("[View scan in Signal Diff](https://api.signaldiff.dev/scan/job-fallback)", body)

    def test_fail_policy_error_or_warning(self) -> None:
        self.assertTrue(_fail_policy_would_fail("errorOrWarning", 0, 2))
        self.assertFalse(_fail_policy_would_fail("none", 3, 3))


if __name__ == "__main__":
    unittest.main()
