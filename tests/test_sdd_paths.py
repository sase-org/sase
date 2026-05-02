"""Tests for SDD path and date lookup helpers."""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sase.sdd.files import (
    find_sdd_file,
    get_primary_workspace_dir,
    get_sdd_dir,
    get_yyyymm,
)


# ---------------------------------------------------------------------------
# get_primary_workspace_dir
# ---------------------------------------------------------------------------


def test_primary_workspace_dir_ws1() -> None:
    assert (
        get_primary_workspace_dir("/home/user/myproject", 1) == "/home/user/myproject"
    )


def test_primary_workspace_dir_ws0() -> None:
    assert (
        get_primary_workspace_dir("/home/user/myproject", 0) == "/home/user/myproject"
    )


def test_primary_workspace_dir_ws2() -> None:
    result = get_primary_workspace_dir("/home/user/myproject_2", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_ws3() -> None:
    result = get_primary_workspace_dir("/home/user/myproject_3", 3)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_suffix_in_parent_component() -> None:
    """Suffix in a parent path component, not the final one."""
    result = get_primary_workspace_dir("/google/src/cloud/bbugyi/pat_102/google3", 102)
    assert result == "/google/src/cloud/bbugyi/pat/google3"


def test_primary_workspace_dir_no_suffix() -> None:
    """If workspace dir does not end with _N suffix, return as-is."""
    result = get_primary_workspace_dir("/home/user/myproject", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_trailing_slash() -> None:
    result = get_primary_workspace_dir("/home/user/myproject_2/", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_prefers_project_workspace_dir() -> None:
    with (
        patch("sase.sdd.files.Path.home", return_value=Path("/home/user")),
        patch("sase.workspace_provider.get_workspace_name", return_value="myproject"),
        patch(
            "sase.workspace_provider.utils.parse_workspace_dir",
            return_value="/home/user/myproject",
        ),
    ):
        result = get_primary_workspace_dir("/home/user/myproject_2", 1)
    assert result == "/home/user/myproject"


# ---------------------------------------------------------------------------
# get_sdd_dir
# ---------------------------------------------------------------------------


def test_get_sdd_dir_version_controlled() -> None:
    result = get_sdd_dir("/home/user/project", 1, version_controlled=True)
    assert result == Path("/home/user/project/sdd")


def test_get_sdd_dir_not_version_controlled() -> None:
    result = get_sdd_dir("/home/user/project", 1, version_controlled=False)
    assert result == Path("/home/user/project/.sase/sdd")


def test_get_sdd_dir_not_version_controlled_ws2() -> None:
    result = get_sdd_dir("/home/user/project_2", 2, version_controlled=False)
    assert result == Path("/home/user/project/.sase/sdd")


def test_get_sdd_dir_not_version_controlled_suffix_in_parent() -> None:
    result = get_sdd_dir(
        "/google/src/cloud/bbugyi/pat_102/google3", 102, version_controlled=False
    )
    assert result == Path("/google/src/cloud/bbugyi/pat/google3/.sase/sdd")


# ---------------------------------------------------------------------------
# get_yyyymm
# ---------------------------------------------------------------------------


def test_get_yyyymm_default() -> None:
    """get_yyyymm returns a 6-digit YYYYMM string."""
    dt = datetime(2025, 11, 15, 10, 30, 0, tzinfo=ZoneInfo("UTC"))
    assert get_yyyymm(dt) == "202511"


def test_get_yyyymm_january() -> None:
    dt = datetime(2026, 1, 5, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    assert get_yyyymm(dt) == "202601"


# ---------------------------------------------------------------------------
# find_sdd_file
# ---------------------------------------------------------------------------


def test_find_sdd_file_prompts_flat() -> None:
    """find_sdd_file returns canonical prompt flat path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "prompts").mkdir()
        (base / "prompts" / "my_plan.md").write_text("prompt", encoding="utf-8")
        result = find_sdd_file(base, "prompts", "my_plan.md")
        assert result == base / "prompts" / "my_plan.md"


def test_find_sdd_file_legacy_yyyymm() -> None:
    """find_sdd_file finds legacy file in YYYYMM subdirectory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "plans" / "202603").mkdir(parents=True)
        (base / "plans" / "202603" / "my_plan.md").write_text("plan", encoding="utf-8")
        result = find_sdd_file(base, "plans", "my_plan.md")
        assert result == base / "plans" / "202603" / "my_plan.md"


def test_find_sdd_file_prefers_flat() -> None:
    """find_sdd_file prefers flat path over YYYYMM when both exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "prompts").mkdir()
        (base / "prompts" / "my_plan.md").write_text("flat", encoding="utf-8")
        (base / "prompts" / "202603").mkdir()
        (base / "prompts" / "202603" / "my_plan.md").write_text(
            "yyyymm", encoding="utf-8"
        )
        result = find_sdd_file(base, "prompts", "my_plan.md")
        assert result == base / "prompts" / "my_plan.md"


def test_find_sdd_file_prefers_canonical_sdd_over_legacy() -> None:
    """Canonical sdd/<kind> wins over legacy root <kind>."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "sdd" / "prompts" / "202603").mkdir(parents=True)
        (base / "specs" / "202603").mkdir(parents=True)
        canonical = base / "sdd" / "prompts" / "202603" / "my_plan.md"
        legacy = base / "specs" / "202603" / "my_plan.md"
        canonical.write_text("canonical", encoding="utf-8")
        legacy.write_text("legacy", encoding="utf-8")

        result = find_sdd_file(base, "specs", "my_plan.md")
        assert result == canonical


def test_find_sdd_file_legacy_specs_alias() -> None:
    """Legacy specs paths remain visible through prompt lookup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "sdd" / "specs" / "202603").mkdir(parents=True)
        legacy = base / "sdd" / "specs" / "202603" / "my_plan.md"
        legacy.write_text("legacy", encoding="utf-8")

        assert find_sdd_file(base, "prompts", "my_plan.md") == legacy
        assert find_sdd_file(base, "specs", "my_plan.md") == legacy


def test_find_sdd_file_supports_epics_and_legends() -> None:
    """Resolution covers all SDD plan-like kinds."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "sdd" / "epics" / "202603").mkdir(parents=True)
        (base / "sdd" / "legends" / "202603").mkdir(parents=True)
        epic = base / "sdd" / "epics" / "202603" / "roadmap.md"
        legend = base / "sdd" / "legends" / "202603" / "roadmap.md"
        epic.write_text("epic", encoding="utf-8")
        legend.write_text("legend", encoding="utf-8")

        assert find_sdd_file(base, "epics", "roadmap.md") == epic
        assert find_sdd_file(base, "legends", "roadmap.md") == legend


def test_find_sdd_file_missing() -> None:
    """find_sdd_file returns None when file does not exist anywhere."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "prompts").mkdir()
        result = find_sdd_file(base, "prompts", "nonexistent.md")
        assert result is None
