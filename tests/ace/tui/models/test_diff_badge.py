"""Tests for Agents-tab diff badge classification."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.models import _diff_badge as diff_badge_mod
from sase.ace.tui.models._diff_badge import (
    diff_has_real_edits,
    diff_text_has_real_edits,
)


def _git_diff(path: str) -> str:
    return f"""diff --git a/{path} b/{path}
--- a/{path}
+++ b/{path}
@@ -1 +1 @@
-old
+new
"""


def test_diff_text_has_real_edits_classifies_paths() -> None:
    assert diff_text_has_real_edits(_git_diff("src/app.py")) is True
    assert diff_text_has_real_edits(_git_diff("sdd/plans/202606/change.md")) is False
    assert (
        diff_text_has_real_edits(_git_diff("sdd/plans/202606/prompts/change.md"))
        is False
    )
    # Mixed code + bookkeeping counts as a real edit.
    assert (
        diff_text_has_real_edits(
            _git_diff("sdd/prompts/202606/p.md") + _git_diff("src/app.py")
        )
        is True
    )
    # Unparsed text fails open, matching the persisted classifier.
    assert diff_text_has_real_edits("not a unified diff\n") is True


def test_diff_has_real_edits_is_false_for_sdd_only_diff(tmp_path: Path) -> None:
    diff_path = tmp_path / "commit_diff.diff"
    diff_path.write_text(
        _git_diff("sdd/prompts/202606/change.md")
        + _git_diff("sdd/plans/202606/change.md"),
        encoding="utf-8",
    )

    assert diff_has_real_edits(str(diff_path)) is False


def test_diff_has_real_edits_is_true_for_mixed_sdd_and_code_diff(
    tmp_path: Path,
) -> None:
    diff_path = tmp_path / "commit_diff.diff"
    diff_path.write_text(
        _git_diff("sdd/prompts/202606/change.md") + _git_diff("src/app.py"),
        encoding="utf-8",
    )

    assert diff_has_real_edits(str(diff_path)) is True


def test_diff_has_real_edits_is_false_for_sase_plan_only_diff(
    tmp_path: Path,
) -> None:
    diff_path = tmp_path / "prompt_step.diff"
    diff_path.write_text(_git_diff("notes/sase_plan_review.md"), encoding="utf-8")

    assert diff_has_real_edits(str(diff_path)) is False


def test_diff_has_real_edits_is_false_for_rename_only_plan_diff(
    tmp_path: Path,
) -> None:
    diff_path = tmp_path / "commit_diff.diff"
    diff_path.write_text(
        """diff --git a/sdd/plans/202606/old.md b/sdd/plans/202606/new.md
similarity index 100%
rename from sdd/plans/202606/old.md
rename to sdd/plans/202606/new.md
""",
        encoding="utf-8",
    )

    assert diff_has_real_edits(str(diff_path)) is False


def test_diff_has_real_edits_accepts_sase_sdd_variant(tmp_path: Path) -> None:
    diff_path = tmp_path / "commit_diff.diff"
    diff_path.write_text(
        _git_diff(".sase/sdd/plans/202606/change.md"),
        encoding="utf-8",
    )

    assert diff_has_real_edits(str(diff_path)) is False


def test_diff_has_real_edits_fails_open_for_missing_or_unparsed_diff(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.diff"
    unparsed = tmp_path / "unparsed.diff"
    unparsed.write_text("not a unified diff\n", encoding="utf-8")

    assert diff_has_real_edits(str(missing)) is True
    assert diff_has_real_edits(str(unparsed)) is True


def test_diff_has_real_edits_cache_invalidates_when_file_metadata_changes(
    tmp_path: Path,
) -> None:
    diff_path = tmp_path / "commit_diff.diff"
    diff_path.write_text(_git_diff("sdd/prompts/202606/change.md"), encoding="utf-8")
    assert diff_has_real_edits(str(diff_path)) is False

    diff_path.write_text(_git_diff("src/app.py") + "+extra\n", encoding="utf-8")
    assert diff_has_real_edits(str(diff_path)) is True


def test_diff_badge_cache_stays_bounded_across_many_diff_artifacts(
    tmp_path: Path,
) -> None:
    """sase-zn.9.3 heap attribution: a repeated-refresh regression.

    A terminal agent's diff_path file never changes again, so its cache key
    is permanent. Before this fix the cache had no cap, so classifying one
    unique diff artifact per agent ever loaded grew it for the process's
    entire lifetime.
    """
    diff_badge_mod._diff_badge_cache.clear()
    artifact_count = diff_badge_mod._DIFF_BADGE_CACHE_MAX * 2
    for i in range(artifact_count):
        diff_path = tmp_path / f"commit_diff_{i}.diff"
        diff_path.write_text(_git_diff(f"src/app_{i}.py"), encoding="utf-8")
        diff_has_real_edits(str(diff_path))

    assert (
        0
        < len(diff_badge_mod._diff_badge_cache)
        <= diff_badge_mod._DIFF_BADGE_CACHE_MAX
    )
