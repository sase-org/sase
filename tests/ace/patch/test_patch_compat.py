"""Canonical Patch compatibility coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.changespec import ChangeSpec, CommitEntry
from sase.ace.changespec.models import ChangeSpec as LegacyModelPatch
from sase.ace.patch import Patch, Stitch
from sase.ace.patch.models import HookStatusLine, MentorEntry
from sase.ace.patch.parser import parse_patch_project_file
from sase.workflows.commit_utils.entries import (
    add_commit_entry_with_id,
    get_next_commit_number,
)


def _patch_kwargs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "name": "demo",
        "description": "Demo patch",
        "parent": None,
        "status": "WIP",
        "file_path": "demo.sase",
        "line_number": 1,
    }
    values.update(overrides)
    return values


def test_canonical_and_legacy_model_imports_are_identical() -> None:
    assert ChangeSpec is Patch
    assert LegacyModelPatch is Patch
    assert CommitEntry is Stitch


def test_patch_accepts_stitches_and_exposes_commits_alias() -> None:
    stitches = [Stitch(number=1, note="Initial stitch")]
    patch = Patch(**_patch_kwargs(stitches=stitches))

    assert patch.stitches is stitches
    assert patch.commits is stitches

    replacement = [Stitch(number=2, note="Follow-up")]
    patch.commits = replacement
    assert patch.stitches is replacement

    patch.stitches = stitches
    assert patch.commits is stitches


def test_patch_rejects_conflicting_stitches_and_commits() -> None:
    with pytest.raises(ValueError, match="commits and stitches"):
        Patch(
            **_patch_kwargs(
                commits=[Stitch(number=1, note="legacy")],
                stitches=[Stitch(number=2, note="canonical")],
            )
        )


def test_stitch_reference_aliases() -> None:
    hook_line = HookStatusLine(
        stitch_id="2a", timestamp="260808_120000", status="PASSED"
    )
    assert hook_line.commit_entry_num == "2a"
    hook_line.commit_entry_num = "3"
    assert hook_line.stitch_id == "3"

    mentor_entry = MentorEntry(stitch_id="4", profiles=["default"])
    assert mentor_entry.entry_id == "4"
    mentor_entry.stitch_id = "5a"
    assert mentor_entry.entry_id == "5a"

    with pytest.raises(ValueError, match="commit_entry_num and stitch_id"):
        HookStatusLine(
            commit_entry_num="1",
            stitch_id="2",
            timestamp="260808_120000",
            status="FAILED",
        )


def test_parser_accepts_patch_and_changespec_headings_and_stitch_sections(
    tmp_path: Path,
) -> None:
    project = tmp_path / "mixed.sase"
    project.write_text(
        "## Patch\n"
        "NAME: canonical\n"
        "DESCRIPTION:\n"
        "  Canonical spelling\n"
        "STATUS: WIP\n"
        "STITCHES:\n"
        "  (1) First stitch\n"
        "\n\n"
        "## ChangeSpec\n"
        "NAME: legacy\n"
        "DESCRIPTION:\n"
        "  Legacy spelling\n"
        "STATUS: WIP\n"
        "COMMITS:\n"
        "  (1) First commit\n",
        encoding="utf-8",
    )

    patches = parse_patch_project_file(str(project))

    assert [patch.name for patch in patches] == ["canonical", "legacy"]
    assert all(isinstance(patch, Patch) for patch in patches)
    assert patches[0].stitches is not None
    assert patches[0].stitches[0].note == "First stitch"
    assert patches[1].stitches is not None
    assert patches[1].stitches[0].note == "First commit"


def test_new_history_section_uses_stitches_header(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project.sase"
    project.write_text(
        "NAME: demo\nDESCRIPTION:\n  Demo\nSTATUS: WIP\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.ace.deltas.refresh_deltas_after_commits_change",
        lambda *_args, **_kwargs: True,
    )

    ok, entry_id = add_commit_entry_with_id(str(project), "demo", "Initial")

    assert ok
    assert entry_id == "1"
    assert "STITCHES:\n  (1) Initial\n" in project.read_text(encoding="utf-8")


def test_existing_commits_header_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project.sase"
    project.write_text(
        "NAME: demo\nDESCRIPTION:\n  Demo\nCOMMITS:\n  (1) Existing\nSTATUS: WIP\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.ace.deltas.refresh_deltas_after_commits_change",
        lambda *_args, **_kwargs: True,
    )

    assert (
        get_next_commit_number(
            project.read_text(encoding="utf-8").splitlines(True),
            "demo",
        )
        == 2
    )
    ok, entry_id = add_commit_entry_with_id(str(project), "demo", "Second")

    content = project.read_text(encoding="utf-8")
    assert ok
    assert entry_id == "2"
    assert "COMMITS:\n  (1) Existing\n  (2) Second\n" in content
    assert "STITCHES:" not in content
