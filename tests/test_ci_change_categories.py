#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from ci_change_categories import (  # noqa: E402
    categorize_changed_paths,
    classify_changed_path,
    format_category_counts,
)


class CiChangeCategoriesTests(unittest.TestCase):
    def test_classify_representative_paths(self) -> None:
        cases = {
            "src/app/Home.tsx": "code",
            "lib/utils/math.py": "code",
            "SignalDiff.Api/Services/JobsHttp.cs": "code",
            "SignalDiff.Tests/Web/JobsHttpTests.cs": "tests",
            "tests/unit/foo.spec.ts": "tests",
            "__tests__/button.test.js": "tests",
            "docs/cosmos-provisioning.md": "docs",
            "README.md": "docs",
            "appsettings.Production.json": "config",
            ".github/workflows/dotnet-ci.yml": "config",
            "docker-compose.yml": "config",
            "SignalDiff.Api/SignalDiff.Api.csproj": "dependencies",
            "package.json": "dependencies",
            "go.mod": "dependencies",
            "requirements.txt": "dependencies",
            "package-lock.json": "dependencies",
            "db/migrations/20240101_init.sql": "migrations",
            "Services/UserMigrationService.cs": "migrations",
            "wwwroot/favicon.ico": "other",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(classify_changed_path(path), expected)

    def test_categorize_changed_paths_aggregates_counts(self) -> None:
        paths = [
            "src/a.ts",
            "src/b.ts",
            "SignalDiff.Tests/FooTests.cs",
            "appsettings.json",
            "package.json",
            "docs/guide.md",
            "README.md",
            "db/migrations/001.sql",
            "assets/logo.png",
        ]
        counts = categorize_changed_paths(paths)
        self.assertEqual(
            counts,
            {
                "code": 2,
                "tests": 1,
                "config": 1,
                "dependencies": 1,
                "docs": 2,
                "migrations": 1,
            },
        )

    def test_format_category_counts_omits_empty_buckets(self) -> None:
        rendered = format_category_counts({"code": 8, "tests": 1, "config": 1})
        self.assertEqual(rendered, "Code: 8 · Tests: 1 · Config: 1")

    def test_format_category_counts_returns_empty_for_no_buckets(self) -> None:
        self.assertEqual(format_category_counts({}), "")


if __name__ == "__main__":
    unittest.main()
