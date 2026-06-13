#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from review_files import (  # noqa: E402
    attention_emoji,
    format_files_requiring_review,
    is_docs_or_tests_only_change,
    review_reasons_for_path,
    select_files_requiring_review,
    should_show_files_requiring_review,
)


class ReviewReasonTests(unittest.TestCase):
    def test_auth_path_reason(self) -> None:
        reasons = review_reasons_for_path("src/Auth/JwtProvider.cs")
        self.assertIn("auth-sensitive area", reasons)
        self.assertIn("business logic (non-test source)", reasons)

    def test_payment_path_reason(self) -> None:
        reasons = review_reasons_for_path("src/Payments/PaymentService.cs")
        self.assertIn("payment path", reasons)

    def test_production_config_reason(self) -> None:
        reasons = review_reasons_for_path("appsettings.Production.json")
        self.assertIn("production configuration", reasons)
        self.assertNotIn("business logic (non-test source)", reasons)

    def test_migration_reason(self) -> None:
        reasons = review_reasons_for_path("db/migrations/20240101_init.sql")
        self.assertIn("database migration", reasons)

    def test_dependency_manifest_reason(self) -> None:
        reasons = review_reasons_for_path("package.json")
        self.assertIn("dependency manifest", reasons)

    def test_secrets_reason(self) -> None:
        reasons = review_reasons_for_path("src/Api/Secrets/ConnectionStringProvider.cs")
        self.assertIn("secrets or credentials", reasons)


class ReviewSelectionTests(unittest.TestCase):
    def test_auth_and_payment_rank_above_generic_code(self) -> None:
        selected = select_files_requiring_review(
            [
                "src/app/Home.tsx",
                "src/Payments/PaymentService.cs",
                "src/Auth/JwtProvider.cs",
            ],
            changed_file_count=3,
        )
        paths = [path for path, _score, _reason in selected]
        self.assertIn("src/Payments/PaymentService.cs", paths)
        self.assertIn("src/Auth/JwtProvider.cs", paths)
        self.assertNotIn("src/app/Home.tsx", paths)

    def test_top_five_cap(self) -> None:
        paths = [
            f"src/Auth/Provider{i}.cs"
            for i in range(10)
        ]
        selected = select_files_requiring_review(paths, changed_file_count=10, max_files=5)
        self.assertEqual(len(selected), 5)

    def test_docs_only_changes_return_empty(self) -> None:
        selected = select_files_requiring_review(
            ["docs/guide.md", "README.md"],
            category_counts={"docs": 2},
            changed_file_count=2,
        )
        self.assertEqual(selected, [])

    def test_tests_only_changes_return_empty(self) -> None:
        selected = select_files_requiring_review(
            ["SignalDiff.Tests/Web/JobsHttpTests.cs"],
            category_counts={"tests": 1},
            changed_file_count=1,
        )
        self.assertEqual(selected, [])

    def test_low_score_generic_paths_excluded(self) -> None:
        selected = select_files_requiring_review(
            ["src/app/Home.tsx"],
            category_counts={"code": 1},
            changed_file_count=1,
        )
        self.assertEqual(selected, [])

    def test_production_config_selected_without_code_category(self) -> None:
        selected = select_files_requiring_review(
            ["appsettings.Production.json"],
            category_counts={"config": 1},
            changed_file_count=1,
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0][2], "production configuration")


class ReviewVisibilityTests(unittest.TestCase):
    def test_should_show_when_high_attention_files_exist(self) -> None:
        selected = [("appsettings.Production.json", 10.0, "production configuration")]
        self.assertTrue(
            should_show_files_requiring_review(
                category_counts={"config": 1},
                changed_file_count=1,
                selected=selected,
            )
        )

    def test_should_hide_for_docs_only_even_with_selected(self) -> None:
        selected = [("docs/guide.md", 0.0, "business logic (non-test source)")]
        self.assertFalse(
            should_show_files_requiring_review(
                category_counts={"docs": 1},
                changed_file_count=1,
                selected=selected,
            )
        )

    def test_is_docs_or_tests_only(self) -> None:
        self.assertTrue(is_docs_or_tests_only_change({"docs": 2}, 2))
        self.assertTrue(is_docs_or_tests_only_change({"tests": 1, "docs": 1}, 2))
        self.assertFalse(is_docs_or_tests_only_change({"code": 1, "tests": 1}, 2))


class ReviewFormattingTests(unittest.TestCase):
    def test_format_section_includes_paths_and_reasons(self) -> None:
        lines = format_files_requiring_review(
            [
                ("src/Auth/JwtProvider.cs", 12.0, "auth-sensitive area, business logic (non-test source)"),
            ]
        )
        body = "\n".join(lines)
        self.assertIn("### Files requiring review", body)
        self.assertIn("🔴 High attention", body)
        self.assertIn("`src/Auth/JwtProvider.cs` — auth-sensitive area", body)

    def test_attention_emoji_thresholds(self) -> None:
        self.assertEqual(attention_emoji(8.0), "🔴")
        self.assertEqual(attention_emoji(5.0), "🟡")
        self.assertEqual(attention_emoji(1.0), "🟢")


if __name__ == "__main__":
    unittest.main()
