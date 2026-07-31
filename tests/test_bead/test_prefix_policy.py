"""Tests for bead issue-prefix derivation policy."""

from __future__ import annotations

import pytest

from sase.bead import prefix_policy
from sase.bead.config import save_config


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("bob-cli", True),
        ("beads", True),
        ("", False),
        ("bob cli", False),
        ("bob.cli", False),
        ("bob/cli", False),
        ("bob\\cli", False),
        ("bob--cli", False),
        ("bob-cli-", False),
    ],
)
def test_is_safe_bead_prefix(prefix: str, expected: bool) -> None:
    assert prefix_policy._is_safe_bead_prefix(prefix) is expected


def test_stale_key_prefix_report_flags_leaked_key(tmp_path, monkeypatch) -> None:
    beads_dir = tmp_path / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    save_config(
        beads_dir,
        {"issue_prefix": "gh_bobs-org__bob-cli", "next_counter": 1, "owner": ""},
    )
    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd",
        lambda: "gh_bobs-org__bob-cli",
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda _key, *_args, **_kwargs: "bob-cli",
    )
    assert prefix_policy.stale_key_prefix_report(beads_dir) == (
        "gh_bobs-org__bob-cli",
        "bob-cli",
    )


def test_stale_key_prefix_report_ignores_deliberately_custom_prefix(
    tmp_path, monkeypatch
) -> None:
    beads_dir = tmp_path / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    save_config(beads_dir, {"issue_prefix": "beads", "next_counter": 1, "owner": ""})
    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd",
        lambda: "gh_bobs-org__bob-cli",
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda _key, *_args, **_kwargs: "bob-cli",
    )
    assert prefix_policy.stale_key_prefix_report(beads_dir) is None


def test_stale_key_prefix_report_none_when_label_matches_key(
    tmp_path, monkeypatch
) -> None:
    beads_dir = tmp_path / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    save_config(beads_dir, {"issue_prefix": "sase", "next_counter": 1, "owner": ""})
    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd", lambda: "sase"
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda key, *_args, **_kwargs: key,
    )
    assert prefix_policy.stale_key_prefix_report(beads_dir) is None


def test_stale_key_prefix_report_none_for_unsafe_label(tmp_path, monkeypatch) -> None:
    beads_dir = tmp_path / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    save_config(
        beads_dir,
        {"issue_prefix": "gh_bobs-org__bob-cli", "next_counter": 1, "owner": ""},
    )
    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd",
        lambda: "gh_bobs-org__bob-cli",
    )
    monkeypatch.setattr(
        "sase.project_display_names.project_display_name_for",
        lambda _key, *_args, **_kwargs: "bob cli",
    )
    assert prefix_policy.stale_key_prefix_report(beads_dir) is None


def test_stale_key_prefix_report_none_without_inferred_project(
    tmp_path, monkeypatch
) -> None:
    beads_dir = tmp_path / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    save_config(
        beads_dir,
        {"issue_prefix": "gh_bobs-org__bob-cli", "next_counter": 1, "owner": ""},
    )
    monkeypatch.setattr(
        "sase.bead.prefix_policy.infer_project_name_from_cwd", lambda: None
    )
    assert prefix_policy.stale_key_prefix_report(beads_dir) is None
