"""Tests for SDD path and date lookup helpers."""

from importlib import resources
import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from sase.sdd._paths import _resolve_primary_from_marker
from sase.sdd.env import set_sdd_dir_env
from sase.sdd.files import (
    SDD_DIRECTORY_MAP_FILENAME,
    find_sdd_file,
    get_primary_workspace_dir,
    get_yyyymm,
    is_sdd_internal_path,
    _resolve_sdd_asset_path,
    _resolve_sdd_readme_path,
)
from sase.sdd.store import SddStore


def _write_checkout_marker(checkout_dir: Path, primary: Path) -> None:
    """Write a managed-checkout marker under *checkout_dir*."""
    marker_dir = checkout_dir / ".sase"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "checkout.json").write_text(
        json.dumps(
            {
                "primary_workspace_dir": str(primary),
                "project_key": "org/proj",
                "project_name": "proj",
                "registry_path": str(checkout_dir.parent / "registry.json"),
                "schema_version": 1,
                "workspace_num": 7,
            }
        ),
        encoding="utf-8",
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


def test_resolve_primary_from_marker_reads_checkout_marker(tmp_path: Path) -> None:
    checkout = tmp_path / "state" / "org" / "proj" / "proj_7"
    primary = tmp_path / "home" / "projects" / "org" / "proj"
    _write_checkout_marker(checkout, primary)
    assert _resolve_primary_from_marker(str(checkout)) == str(primary)


def test_resolve_primary_from_marker_missing_returns_none(tmp_path: Path) -> None:
    assert _resolve_primary_from_marker(str(tmp_path / "no" / "marker")) is None


def test_primary_workspace_dir_uses_marker_when_project_unresolved(
    tmp_path: Path,
) -> None:
    """Managed checkouts far from their primary resolve via the checkout
    marker, not sibling-suffix stripping.

    Regression: separate_repo SDD storage read the store record from the
    suffix-stripped path (``.../proj/proj``) instead of the real primary,
    so agent launches failed to materialize the SDD sidecar repo.
    """
    checkout = tmp_path / "state" / "workspaces" / "org" / "proj" / "proj_7"
    primary = tmp_path / "home" / "projects" / "org" / "proj"
    _write_checkout_marker(checkout, primary)

    # Simulate the project-spec lookup failing (workspace name does not match
    # the registered project), which is what forced the broken fallback.
    with patch("sase.sdd._paths.resolve_primary_from_project", return_value=None):
        result = get_primary_workspace_dir(str(checkout), 7)

    assert result == str(primary)
    # The old suffix-stripping fallback would have returned this wrong path.
    assert result != str(checkout.parent / "proj")


# ---------------------------------------------------------------------------
# resolve_sdd_readme_path
# ---------------------------------------------------------------------------


def test_resolve_sdd_readme_path_default_uses_cwd_sdd(tmp_path: Path) -> None:
    assert _resolve_sdd_readme_path(cwd=tmp_path) == tmp_path / "sdd" / "README.md"


def test_resolve_sdd_readme_path_project_root(tmp_path: Path) -> None:
    assert (
        _resolve_sdd_readme_path(str(tmp_path), cwd=Path("/tmp"))
        == tmp_path / "sdd" / "README.md"
    )


def test_resolve_sdd_readme_path_sdd_root(tmp_path: Path) -> None:
    sdd_root = tmp_path / "sdd"
    assert (
        _resolve_sdd_readme_path(str(sdd_root), cwd=Path("/tmp"))
        == sdd_root / "README.md"
    )


def test_resolve_sdd_readme_path_detects_plans_only_sdd_root(
    tmp_path: Path,
) -> None:
    sdd_root = tmp_path / "custom-sdd"
    (sdd_root / "plans").mkdir(parents=True)

    assert (
        _resolve_sdd_readme_path(str(sdd_root), cwd=Path("/tmp"))
        == sdd_root / "README.md"
    )


def test_resolve_sdd_readme_path_detects_research_only_sdd_root(
    tmp_path: Path,
) -> None:
    sdd_root = tmp_path / "custom-sdd"
    (sdd_root / "research").mkdir(parents=True)

    assert (
        _resolve_sdd_readme_path(str(sdd_root), cwd=Path("/tmp"))
        == sdd_root / "README.md"
    )


def test_resolve_sdd_asset_path_follows_readme_root(tmp_path: Path) -> None:
    assert (
        _resolve_sdd_asset_path(str(tmp_path), cwd=Path("/tmp"))
        == tmp_path / "sdd" / "assets" / SDD_DIRECTORY_MAP_FILENAME
    )


def test_sdd_directory_map_package_resource_exists() -> None:
    resource = resources.files("sase.sdd").joinpath(
        "assets", SDD_DIRECTORY_MAP_FILENAME
    )
    assert resource.is_file()
    assert resource.name == SDD_DIRECTORY_MAP_FILENAME


@pytest.mark.parametrize(
    "rel_path",
    [
        "plans/202607/prompts/foo.md",
        "202607/prompts/foo.md",
        "sdd/plans/202607/prompts/foo.md",
        "prompts/202607/foo.md",
        "specs/202607/foo.md",
        "sdd/specs/202607/foo.md",
        "beads/foo.md",
        "sdd/beads/foo.md",
        "README.md",
        "plans/README.md",
        "research/README.md",
        "sdd/README.md",
        "sdd/plans/README.md",
    ],
)
def test_is_sdd_internal_path(rel_path: str) -> None:
    assert is_sdd_internal_path(rel_path) is True


@pytest.mark.parametrize(
    "rel_path",
    [
        "plans/202607/foo.md",
        "202607/foo.md",
        "research/202607/foo.md",
        "sdd/research/202607/foo.md",
        "notes/custom.md",
        "research/prompts.md",
    ],
)
def test_is_sdd_internal_path_keeps_user_facing_documents(rel_path: str) -> None:
    assert is_sdd_internal_path(rel_path) is False


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


@pytest.mark.parametrize("split_beads", [False, True])
def test_agent_env_exports_all_sidecar_kind_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    split_beads: bool,
) -> None:
    plans = tmp_path / "sase" / "repos" / "plans"
    research = tmp_path / "sase" / "repos" / "research"
    beads = tmp_path / "sase" / "repos" / "beads"
    store = SddStore(
        "sidecar_repos",
        plans,
        plans,
        sidecar_dirs={"research": research},
        beads_dir=beads if split_beads else None,
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_dir", lambda *_args: plans)
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    env: dict[str, str] = {}

    set_sdd_dir_env(env, workspace_dir=str(tmp_path), workspace_num=1)

    assert env == {
        "SASE_SDD_DIR": str(plans),
        "SASE_SDD_PLANS_DIR": str(plans),
        "SASE_SDD_BEADS_DIR": str(beads if split_beads else plans / "beads"),
        "SASE_SDD_RESEARCH_DIR": str(research),
    }


# ---------------------------------------------------------------------------
# find_sdd_file
# ---------------------------------------------------------------------------


def test_find_sdd_file_prompts_nested() -> None:
    """find_sdd_file returns the canonical nested prompt path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        nested = base / "plans" / "202603" / "prompts" / "my_plan.md"
        nested.parent.mkdir(parents=True)
        nested.write_text("prompt", encoding="utf-8")
        result = find_sdd_file(base, "prompts", "my_plan.md")
        assert result == nested


def test_find_sdd_file_sharded_plan() -> None:
    """find_sdd_file finds a canonical file in a YYYYMM subdirectory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "plans" / "202603").mkdir(parents=True)
        (base / "plans" / "202603" / "my_plan.md").write_text("plan", encoding="utf-8")
        result = find_sdd_file(base, "plans", "my_plan.md")
        assert result == base / "plans" / "202603" / "my_plan.md"


def test_find_sdd_file_finds_canonical_in_tree_plan() -> None:
    """The ``plans`` kind resolves the canonical ``sdd/plans`` location."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "sdd" / "plans" / "202603").mkdir(parents=True)
        canonical = base / "sdd" / "plans" / "202603" / "my_plan.md"
        canonical.write_text("plan", encoding="utf-8")

        result = find_sdd_file(base, "plans", "my_plan.md")
        assert result == canonical


def test_find_sdd_file_prefers_nested_over_legacy() -> None:
    """find_sdd_file prefers the canonical nested path over legacy roots."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        legacy = base / "prompts" / "my_plan.md"
        legacy.parent.mkdir()
        legacy.write_text("legacy", encoding="utf-8")
        nested = base / "plans" / "202603" / "prompts" / "my_plan.md"
        nested.parent.mkdir(parents=True)
        nested.write_text("nested", encoding="utf-8")
        result = find_sdd_file(base, "prompts", "my_plan.md")
        assert result == nested


def test_find_sdd_file_prefers_canonical_sdd_over_legacy() -> None:
    """Canonical sdd/<kind> wins over legacy root <kind>."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "sdd" / "plans" / "202603" / "prompts").mkdir(parents=True)
        (base / "specs" / "202603").mkdir(parents=True)
        canonical = base / "sdd" / "plans" / "202603" / "prompts" / "my_plan.md"
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


def test_find_sdd_file_does_not_accept_legacy_epics_kind() -> None:
    """Tier vocabulary is not accepted as a physical lookup directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "sdd" / "plans" / "202603").mkdir(parents=True)
        epic = base / "sdd" / "plans" / "202603" / "roadmap.md"
        epic.write_text("epic", encoding="utf-8")

        assert find_sdd_file(base, "epics", "roadmap.md") is None


def test_find_sdd_file_missing() -> None:
    """find_sdd_file returns None when file does not exist anywhere."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "prompts").mkdir()
        result = find_sdd_file(base, "prompts", "nonexistent.md")
        assert result is None
