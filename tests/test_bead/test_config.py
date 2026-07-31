"""Tests for merged bead workflow configuration."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from sase.bead import config as bead_config
from sase.bead.config import (
    _detect_prefix,
    get_default_config,
    load_config,
    save_config,
)
from sase.bead.model import IssueType
from sase.bead.project import BeadProject


def test_get_default_config(tmp_path):
    config = get_default_config(tmp_path)
    assert "issue_prefix" in config
    assert config["next_counter"] == 1
    assert isinstance(config["owner"], str)


def test_save_and_load_config(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    config = {"issue_prefix": "test", "next_counter": 5, "owner": "user@example.com"}
    save_config(beads_dir, config)

    loaded = load_config(beads_dir)
    assert loaded == config


def test_load_config_missing_returns_defaults(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    config = load_config(beads_dir)
    assert "issue_prefix" in config
    assert config["next_counter"] == 1


def test_save_config_creates_json(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    config = {"issue_prefix": "proj", "next_counter": 1, "owner": ""}
    save_config(beads_dir, config)

    raw = (beads_dir / "config.json").read_text()
    parsed = json.loads(raw)
    assert parsed["issue_prefix"] == "proj"


def test_detect_prefix_uses_project_name_from_cwd(tmp_path, monkeypatch):
    """No PROJECT_NAME configured: the inferred key itself is the prefix."""
    root = tmp_path / ".sase" / "sdd"
    root.mkdir(parents=True)

    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd", lambda: "yserve"
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda key, *_args, **_kwargs: key,
    )
    assert _detect_prefix(root) == "yserve"


def test_detect_prefix_uses_project_display_name_when_key_differs(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd",
        lambda: "gh_bobs-org__bob-cli",
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda _key, *_args, **_kwargs: "bob-cli",
    )
    assert _detect_prefix(tmp_path) == "bob-cli"


def test_detect_prefix_falls_back_to_key_for_unsafe_label(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd",
        lambda: "bob-cli-key",
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda _key, *_args, **_kwargs: "bob cli",
    )
    assert _detect_prefix(tmp_path) == "bob-cli-key"


def test_detect_prefix_falls_through_to_directory_name_without_project(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd", lambda: None
    )
    root = tmp_path / "my-repo"
    root.mkdir()
    assert _detect_prefix(root) == "my-repo"


def test_init_beads_end_to_end_uses_project_display_name_prefix(tmp_path, monkeypatch):
    """Regression guard for the ``sase bead work`` ProjectSpec-key defect.

    ``BeadProject.init`` is the exact call ``init_beads`` (the ``sase bead
    work`` store-materialization path) makes; a store whose key differs from
    its ``PROJECT_NAME`` must not persist the raw key as its issue prefix.
    """
    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd",
        lambda: "gh_bobs-org__bob-cli",
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda key, *_args, **_kwargs: (
            "bob-cli" if key == "gh_bobs-org__bob-cli" else key
        ),
    )

    with BeadProject.init(tmp_path) as project:
        issue = project.create("One", IssueType.PLAN)

    assert issue.id.startswith("bob-cli-")
    config = load_config(tmp_path / "sdd/beads")
    assert config["issue_prefix"] == "bob-cli"


def test_detect_prefix_with_trailing_vcs_component(tmp_path, monkeypatch):
    """Prefix should be project name, not the workspace root dir name (e.g. google3)."""
    monkeypatch.setenv("HOME", str(tmp_path))

    # Register project
    project_dir = tmp_path / ".sase" / "projects" / "yserve"
    project_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / "yserve" / "google3"
    (project_dir / "yserve.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

    # CWD is under a variant (primary need not exist on disk)
    variant = tmp_path / "workspaces" / "yserve_101" / "google3"
    variant.mkdir(parents=True)
    monkeypatch.chdir(variant)

    # root_dir is the workspace root dir (e.g. google3) — should NOT be the prefix
    assert _detect_prefix(variant) == "yserve"


def test_big_epic_phase_threshold_reads_positive_integer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bead_config,
        "load_merged_config",
        lambda: {"bead": {"big_epic_phase_threshold": 8}},
    )

    assert bead_config.get_big_epic_phase_threshold() == 8


@pytest.mark.parametrize(
    "merged",
    [
        {},
        {"bead": None},
        {"bead": {"big_epic_phase_threshold": None}},
        {"bead": {"big_epic_phase_threshold": True}},
        {"bead": {"big_epic_phase_threshold": False}},
        {"bead": {"big_epic_phase_threshold": 0}},
        {"bead": {"big_epic_phase_threshold": -1}},
        {"bead": {"big_epic_phase_threshold": 5.0}},
        {"bead": {"big_epic_phase_threshold": "5"}},
    ],
)
def test_big_epic_phase_threshold_falls_back_for_missing_or_malformed_values(
    monkeypatch: pytest.MonkeyPatch,
    merged: object,
) -> None:
    monkeypatch.setattr(bead_config, "load_merged_config", lambda: merged)

    assert bead_config.get_big_epic_phase_threshold() == 5


def test_big_epic_phase_threshold_falls_back_when_config_load_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load = MagicMock(side_effect=RuntimeError("bad config"))
    monkeypatch.setattr(bead_config, "load_merged_config", load)

    assert bead_config.get_big_epic_phase_threshold() == 5
