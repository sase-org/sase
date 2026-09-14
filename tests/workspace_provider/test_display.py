"""Tests for sase.workspace_provider.display (pager workspace path labels)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.workspace_provider.display import (
    WORKSPACE_ROOT_TOKEN,
    split_workspace_root,
    workspace_display_path,
)
from sase.workspace_provider.marker import CheckoutMarker


def _write_marker(checkout: Path, *, workspace_num: int) -> None:
    marker_dir = checkout / ".sase"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = CheckoutMarker(
        project_name="acme",
        project_key="acme-org/acme",
        workspace_num=workspace_num,
        primary_workspace_dir=str(checkout.parent),
        registry_path=str(checkout.parent / "registry.json"),
    )
    (marker_dir / "checkout.json").write_text(
        json.dumps(marker.to_dict()), encoding="utf-8"
    )


def _make_checkout(tmp_path: Path, *, workspace_num: int = 3) -> Path:
    checkout = tmp_path / "workspaces" / "acme-org" / "acme" / "acme_3"
    checkout.mkdir(parents=True)
    _write_marker(checkout, workspace_num=workspace_num)
    return checkout


class TestWorkspaceDisplayPath:
    def test_file_deep_inside_workspace_is_anchored_at_the_checkout(
        self, tmp_path: Path
    ) -> None:
        checkout = _make_checkout(tmp_path)
        target = checkout / "docs" / "notes.md"
        target.parent.mkdir(parents=True)
        target.write_text("hi\n", encoding="utf-8")

        assert workspace_display_path(target) == "~ws/acme_3/docs/notes.md"

    def test_nested_linked_repo_without_its_own_marker_anchors_at_the_workspace(
        self, tmp_path: Path
    ) -> None:
        checkout = _make_checkout(tmp_path)
        target = checkout / "sase" / "repos" / "linked" / "lib" / "x.py"
        target.parent.mkdir(parents=True)
        target.write_text("hi\n", encoding="utf-8")

        assert workspace_display_path(target) == "~ws/acme_3/sase/repos/linked/lib/x.py"

    def test_the_checkout_directory_itself_has_no_trailing_dot(
        self, tmp_path: Path
    ) -> None:
        checkout = _make_checkout(tmp_path)

        assert workspace_display_path(checkout) == "~ws/acme_3"
        assert workspace_display_path(str(checkout) + "/") == "~ws/acme_3"

    def test_a_primary_workspace_marker_falls_back_to_home_rendering(
        self, tmp_path: Path
    ) -> None:
        checkout = tmp_path / "workspaces" / "acme-org" / "acme" / "acme_0"
        checkout.mkdir(parents=True)
        _write_marker(checkout, workspace_num=0)
        target = checkout / "notes.md"
        target.write_text("hi\n", encoding="utf-8")

        assert (
            workspace_display_path(target, home_root=tmp_path)
            == "~/workspaces/acme-org/acme/acme_0/notes.md"
        )

    def test_an_unmarked_path_outside_home_root_is_unchanged(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "elsewhere" / "report.md"
        target.parent.mkdir(parents=True)

        assert workspace_display_path(target, home_root=tmp_path / "home") == str(
            target
        )

    def test_malformed_marker_json_falls_back_without_raising(
        self, tmp_path: Path
    ) -> None:
        checkout = tmp_path / "workspaces" / "acme-org" / "acme" / "acme_3"
        checkout.mkdir(parents=True)
        (checkout / ".sase").mkdir()
        (checkout / ".sase" / "checkout.json").write_text("not json", encoding="utf-8")
        target = checkout / "notes.md"
        target.write_text("hi\n", encoding="utf-8")

        assert (
            workspace_display_path(target, home_root=tmp_path)
            == "~/workspaces/acme-org/acme/acme_3/notes.md"
        )

    def test_tilde_prefixed_input_expands_before_lookup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        checkout = _make_checkout(tmp_path)
        (checkout / "notes.md").write_text("hi\n", encoding="utf-8")

        assert (
            workspace_display_path("~/workspaces/acme-org/acme/acme_3/notes.md")
            == "~ws/acme_3/notes.md"
        )

    def test_relative_and_non_path_strings_pass_through_unchanged(self) -> None:
        for value in ("notes.md", "../acme_3/x.md", "bead:acme-12", "stdin"):
            assert workspace_display_path(value) == value


class TestSplitWorkspaceRoot:
    def test_splits_an_intact_root_token(self) -> None:
        assert split_workspace_root("~ws/acme_3/x") == (
            f"{WORKSPACE_ROOT_TOKEN}/",
            "acme_3/x",
        )

    def test_a_lookalike_prefix_is_not_split(self) -> None:
        assert split_workspace_root("~wsx/y") == ("", "~wsx/y")

    def test_a_bare_root_token_without_a_slash_is_not_split(self) -> None:
        assert split_workspace_root("~ws") == ("", "~ws")

    def test_a_home_root_token_is_not_split(self) -> None:
        assert split_workspace_root("~/x") == ("", "~/x")

    def test_empty_string(self) -> None:
        assert split_workspace_root("") == ("", "")
