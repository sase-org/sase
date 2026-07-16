"""Tests for plan file archiving and frontmatter utilities."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sase.llm_provider._plan_utils import (
    add_create_time_frontmatter,
    move_plan_to_sase,
)

from tests.conftest import redirect_sase_home


def test_move_plan_to_sase_moves_and_strips_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sase_plan_*.md input is moved into the archive, renamed, and consumed."""
    src_file = tmp_path / "sase_plan_feature.md"
    src_file.write_text("plan content")

    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    dest = move_plan_to_sase(str(src_file))

    assert dest.exists()
    assert dest.read_text() == "plan content"
    # Plans are sharded by YYYYMM; parent is <sase_home>/plans/<shard>.
    assert dest.parent.parent == sase_home / "plans"
    # The "sase_plan_" prefix is stripped from the archived name.
    assert dest.name == "feature.md"
    # The scratch source file was consumed by the move.
    assert not src_file.exists()


def test_move_plan_to_sase_dedup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dedup counter still applies when the archive holds the target basename."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)

    first = tmp_path / "feature.md"
    first.write_text("first")
    dest1 = move_plan_to_sase(str(first))
    assert dest1.name == "feature.md"
    assert not first.exists()

    # A fresh scratch file with the same basename gets a dedup counter.
    second = tmp_path / "feature.md"
    second.write_text("second")
    dest2 = move_plan_to_sase(str(second))

    assert dest2.name == "feature_1.md"
    assert dest2.read_text() == "second"
    assert not second.exists()


def test_add_create_time_frontmatter_no_existing() -> None:
    """Prepends frontmatter when the content has none."""
    dt = datetime(2026, 3, 20, 14, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    result = add_create_time_frontmatter("# My Plan\nDetails", dt)
    assert (
        result
        == "---\ncreate_time: 2026-03-20 14:30:00\nstatus: wip\n---\n# My Plan\nDetails"
    )


def test_add_create_time_frontmatter_existing_frontmatter() -> None:
    """Inserts create_time into existing frontmatter."""
    content = "---\ntitle: foo\n---\n# Plan"
    dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    result = add_create_time_frontmatter(content, dt)
    assert (
        result
        == "---\ntitle: foo\ncreate_time: 2026-01-01 00:00:00\nstatus: wip\n---\n# Plan"
    )


def test_add_create_time_frontmatter_overwrites_existing_field() -> None:
    """Overwrites an existing create_time field and adds status if missing."""
    content = "---\ncreate_time: 2025-01-01\n---\n# Plan"
    dt = datetime(2026, 3, 20, 14, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    result = add_create_time_frontmatter(content, dt)
    assert result == "---\ncreate_time: 2026-03-20 14:30:00\nstatus: wip\n---\n# Plan"


def test_add_create_time_frontmatter_no_duplicate_status() -> None:
    """Does not duplicate status when it already exists in frontmatter."""
    content = "---\nstatus: wip\n---\n# Plan"
    dt = datetime(2026, 3, 20, 14, 30, 0, tzinfo=ZoneInfo("America/New_York"))
    result = add_create_time_frontmatter(content, dt)
    assert result == "---\nstatus: wip\ncreate_time: 2026-03-20 14:30:00\n---\n# Plan"
    # Exactly one status field
    assert result.count("status:") == 1
