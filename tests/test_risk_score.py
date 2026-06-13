#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from risk_score import (  # noqa: E402
    compute_risk_score,
    format_risk_score,
    risk_label,
    score_changed_path,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class RiskScorePathTests(unittest.TestCase):
    def test_path_keyword_and_pattern_weights(self) -> None:
        cases = {
            "src/Auth/JwtProvider.cs": ("auth", "jwt"),
            "src/Payments/PaymentService.cs": ("payment",),
            "appsettings.Production.json": ("appsettings", "production"),
            "db/migrations/20240101_init.sql": ("migration",),
            "src/Api/Secrets/ConnectionStringProvider.cs": ("connectionstring", "secret"),
        }
        for path, _keywords in cases.items():
            with self.subTest(path=path):
                self.assertGreater(score_changed_path(path), 0.0)

    def test_docs_and_test_paths_score_near_zero(self) -> None:
        self.assertLess(score_changed_path("docs/guide.md"), 1.0)
        self.assertLess(score_changed_path("SignalDiff.Tests/Web/JobsHttpTests.cs"), 1.0)


class RiskScoreScenarioTests(unittest.TestCase):
    def test_auth_and_payment_paths_score_high(self) -> None:
        result = compute_risk_score(
            changed_paths=[
                "src/Payments/PaymentService.cs",
                "src/Auth/JwtProvider.cs",
            ],
            changed_file_count=2,
        )
        self.assertGreaterEqual(result["score"], 7.0)
        self.assertEqual(result["label"], "High")

    def test_production_config_change_scores_medium_or_higher(self) -> None:
        result = compute_risk_score(
            changed_paths=["appsettings.Production.json"],
            changed_file_count=1,
            category_counts={"config": 1},
        )
        self.assertGreaterEqual(result["score"], 4.0)
        self.assertIn(result["label"], ("Medium", "High"))

    def test_docs_only_changes_score_low(self) -> None:
        result = compute_risk_score(
            changed_paths=[
                "docs/cosmos-provisioning.md",
                "README.md",
                "docs/staging-environment.md",
            ],
            changed_file_count=3,
            category_counts={"docs": 3},
        )
        self.assertLess(result["score"], 4.0)
        self.assertEqual(result["label"], "Low")

    def test_tests_only_changes_score_low(self) -> None:
        result = compute_risk_score(
            changed_paths=[
                "SignalDiff.Tests/Web/JobsHttpTests.cs",
                "tests/unit/foo.spec.ts",
            ],
            changed_file_count=2,
            category_counts={"tests": 2},
        )
        self.assertLess(result["score"], 4.0)
        self.assertEqual(result["label"], "Low")

    def test_new_seo_errors_increase_score(self) -> None:
        job = _load("job_critical.json")
        result = compute_risk_score(
            run_diff=job["runDiff"],
            errors=1,
            warnings=0,
            fail_mode="error",
            status="complete",
        )
        self.assertGreaterEqual(result["score"], 4.0)
        self.assertGreater(result["seoRawScore"], 0.0)

    def test_new_seo_warnings_increase_score_moderately(self) -> None:
        job = _load("job_with_run_diff.json")
        result = compute_risk_score(
            run_diff=job["runDiff"],
            errors=0,
            warnings=14,
            fail_mode="error",
            status="complete",
        )
        self.assertGreater(result["score"], 0.0)
        self.assertLess(result["score"], 8.0)

    def test_mixed_code_and_seo_scores_higher_than_docs_only(self) -> None:
        job = _load("job_with_run_diff.json")
        mixed = compute_risk_score(
            changed_paths=[
                "src/Payments/PaymentService.cs",
                "appsettings.Production.json",
            ],
            changed_file_count=2,
            category_counts={"code": 1, "config": 1},
            run_diff=job["runDiff"],
            errors=0,
            warnings=14,
            fail_mode="error",
            status="complete",
        )
        docs_only = compute_risk_score(
            changed_paths=["docs/guide.md"],
            changed_file_count=1,
            category_counts={"docs": 1},
            run_diff=job["runDiff"],
            errors=0,
            warnings=14,
            fail_mode="error",
            status="complete",
        )
        self.assertGreater(mixed["score"], docs_only["score"])


class RiskScoreFormattingTests(unittest.TestCase):
    def test_risk_label_thresholds(self) -> None:
        self.assertEqual(risk_label(0.0), ("Low", "🟢"))
        self.assertEqual(risk_label(3.9), ("Low", "🟢"))
        self.assertEqual(risk_label(4.0), ("Medium", "🟡"))
        self.assertEqual(risk_label(6.9), ("Medium", "🟡"))
        self.assertEqual(risk_label(7.0), ("High", "🔴"))

    def test_format_risk_score_renders_emoji_label_and_numeric(self) -> None:
        self.assertEqual(format_risk_score(7.2), "🔴 High (7.2/10)")
        self.assertEqual(format_risk_score(4.5), "🟡 Medium (4.5/10)")


if __name__ == "__main__":
    unittest.main()
