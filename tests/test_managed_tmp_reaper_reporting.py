"""Dry-run and describe() reporting for the managed-tmp reaper."""

from __future__ import annotations

from pathlib import Path

from tests._managed_tmp_reaper_helpers import HOUR, NOW, _aged_file, reap_managed_tmpdir


def test_dry_run_reports_selected_entries_without_removing_them(
    tmp_path: Path,
) -> None:
    stale = _aged_file(tmp_path, "editors/note.md", age_seconds=13 * HOUR)

    result = reap_managed_tmpdir(tmp_path, now=NOW, apply=False)

    assert stale.exists()
    assert not result.apply
    assert result.selected == 1
    assert result.removed == 0
    assert result.selected_by_subdir == {"editors": 1}
    assert result.removed_by_subdir == {}
    assert result.describe() == (f"would reclaim 1 entries under {tmp_path}: editors=1")


def test_describe_names_the_busiest_buckets(tmp_path: Path) -> None:
    for index in range(3):
        _aged_file(tmp_path, f"editors/n{index}.md", age_seconds=13 * HOUR)
    _aged_file(tmp_path, "viewers/diff.txt", age_seconds=13 * HOUR)

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert result.describe() == (
        f"reclaimed 4 entries under {tmp_path}: editors=3, viewers=1"
    )


def test_describe_reports_an_idle_pass(tmp_path: Path) -> None:
    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert result.describe() == f"nothing stale under {tmp_path}"


def test_describe_flags_a_capped_pass(tmp_path: Path) -> None:
    for index in range(2):
        _aged_file(tmp_path, f"editors/n{index}.md", age_seconds=13 * HOUR)

    result = reap_managed_tmpdir(tmp_path, now=NOW, max_removals=1)

    assert result.describe().endswith("(removal budget reached)")
