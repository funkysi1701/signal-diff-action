#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from patch_lines import first_changed_line_from_patch  # noqa: E402
from post_inline_annotations import (  # noqa: E402
    annotation_marker,
    build_annotation_body,
    build_config_annotation_body,
    select_annotation_targets,
)


class PatchLineResolutionTests(unittest.TestCase):
    def test_first_addition_line_on_right_side(self) -> None:
        patch = "\n".join(
            [
                "@@ -10,2 +10,3 @@",
                " unchanged",
                "+added line",
            ]
        )
        result = first_changed_line_from_patch(patch)
        self.assertEqual(result, (11, "RIGHT"))

    def test_first_deletion_line_on_left_side(self) -> None:
        patch = "\n".join(
            [
                "@@ -42,1 +42,0 @@",
                "-ConnectionStrings__Default=old",
            ]
        )
        result = first_changed_line_from_patch(patch)
        self.assertEqual(result, (42, "LEFT"))

    def test_deletion_before_addition_prefers_first_change(self) -> None:
        patch = "\n".join(
            [
                "@@ -10,3 +10,4 @@",
                " context",
                "-removed",
                "+added",
            ]
        )
        result = first_changed_line_from_patch(patch)
        self.assertEqual(result, (11, "LEFT"))

    def test_skips_file_headers_and_finds_first_hunk(self) -> None:
        patch = "\n".join(
            [
                "--- a/appsettings.json",
                "+++ b/appsettings.json",
                "@@ -1,3 +1,4 @@",
                " {",
                "+  \"Logging\": \"Warning\",",
                " }",
            ]
        )
        result = first_changed_line_from_patch(patch)
        self.assertEqual(result, (2, "RIGHT"))

    def test_empty_or_missing_patch_returns_none(self) -> None:
        self.assertIsNone(first_changed_line_from_patch(""))
        self.assertIsNone(first_changed_line_from_patch("--- a/file\n+++ b/file\n"))


class AnnotationBodyTests(unittest.TestCase):
    def test_marker_is_embedded_for_idempotency(self) -> None:
        body = build_annotation_body(
            path="src/Auth/JwtProvider.cs",
            reason="auth-sensitive area",
            score=7.5,
            scan_url="https://signaldiff.dev/scan/job-1",
        )
        self.assertIn(annotation_marker("src/Auth/JwtProvider.cs"), body)
        self.assertIn("auth-sensitive area", body)

    def test_config_body_uses_config_wording(self) -> None:
        body = build_config_annotation_body(
            path="appsettings.json",
            scan_url="https://signaldiff.dev/scan/job-1",
        )
        self.assertIn("configuration changed", body)
        self.assertIn(annotation_marker("appsettings.json"), body)


class AnnotationTargetSelectionTests(unittest.TestCase):
    def test_high_risk_paths_rank_before_config_only_files(self) -> None:
        targets = select_annotation_targets(
            [
                "appsettings.json",
                "src/Auth/JwtProvider.cs",
                "README.md",
            ],
            category_counts={"config": 1, "code": 1, "docs": 1},
            max_files=2,
        )
        paths = [path for path, _reason, _score in targets]
        self.assertEqual(paths, ["src/Auth/JwtProvider.cs", "appsettings.json"])

    def test_respects_annotation_max_files_cap(self) -> None:
        paths = [f"src/Auth/Provider{i}.cs" for i in range(5)]
        targets = select_annotation_targets(
            paths,
            category_counts={"code": 5},
            max_files=3,
        )
        self.assertEqual(len(targets), 3)


if __name__ == "__main__":
    unittest.main()
