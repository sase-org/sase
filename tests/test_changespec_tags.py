from __future__ import annotations

from collections.abc import Callable

import pytest

from sase.ace.changespec import ChangeSpec
from sase.integrations.changespec_tags import list_changespec_xprompt_tags


def _cs(
    name: str,
    status: str,
    project: str,
    *,
    archive: bool = False,
) -> ChangeSpec:
    suffix = "-archive" if archive else ""
    return ChangeSpec(
        name=name,
        description="",
        parent=None,
        cl=None,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path=f"/home/user/.sase/projects/{project}/{project}{suffix}.gp",
        line_number=1,
    )


@pytest.fixture
def set_changespecs(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[list[ChangeSpec]], None]:
    def _set(changespecs: list[ChangeSpec]) -> None:
        monkeypatch.setattr(
            "sase.integrations.changespec_tags.find_all_changespecs",
            lambda: changespecs,
        )

    return _set


def test_lists_active_changespec_tags_and_sorts_deterministically(
    monkeypatch: pytest.MonkeyPatch,
    set_changespecs: Callable[[list[ChangeSpec]], None],
) -> None:
    set_changespecs(
        [
            _cs("zeta", "Mailed", "beta"),
            _cs("ready", "Ready", "alpha"),
            _cs("draft", "Draft", "alpha"),
            _cs("wip", "WIP", "alpha"),
        ]
    )

    def detect(project_file: str) -> str:
        return "hg" if "/alpha/" in project_file else "git"

    monkeypatch.setattr(
        "sase.integrations.changespec_tags.detect_workflow_type", detect
    )

    listing = list_changespec_xprompt_tags()

    assert [
        (entry.project, entry.name, entry.status, entry.tag)
        for entry in listing.entries
    ] == [
        ("alpha", "draft", "Draft", "#hg:draft"),
        ("alpha", "ready", "Ready", "#hg:ready"),
        ("alpha", "wip", "WIP", "#hg:wip"),
        ("beta", "zeta", "Mailed", "#git:zeta"),
    ]
    assert listing.skipped == []


def test_excludes_terminal_statuses_after_suffix_normalization(
    monkeypatch: pytest.MonkeyPatch,
    set_changespecs: Callable[[list[ChangeSpec]], None],
) -> None:
    set_changespecs(
        [
            _cs("submitted", "Submitted", "proj"),
            _cs("archived", "Archived (proj_1)", "proj"),
            _cs("reverted", "Reverted - (!: READY TO MAIL)", "proj"),
            _cs("active", "Ready (proj_2)", "proj"),
        ]
    )
    monkeypatch.setattr(
        "sase.integrations.changespec_tags.detect_workflow_type",
        lambda project_file: "gh",
    )

    listing = list_changespec_xprompt_tags()

    assert [(entry.name, entry.status, entry.tag) for entry in listing.entries] == [
        ("active", "Ready", "#gh:active")
    ]


def test_filters_by_exact_project_before_workflow_detection(
    monkeypatch: pytest.MonkeyPatch,
    set_changespecs: Callable[[list[ChangeSpec]], None],
) -> None:
    set_changespecs(
        [
            _cs("keep", "Ready", "target"),
            _cs("skip", "Ready", "target-extra"),
            _cs("other", "Ready", "other"),
        ]
    )
    seen_files: list[str] = []

    def detect(project_file: str) -> str:
        seen_files.append(project_file)
        return "hg"

    monkeypatch.setattr(
        "sase.integrations.changespec_tags.detect_workflow_type", detect
    )

    listing = list_changespec_xprompt_tags("target")

    assert [entry.name for entry in listing.entries] == ["keep"]
    assert seen_files == ["/home/user/.sase/projects/target/target.gp"]


def test_detects_workflow_using_main_file_for_archive_changespec(
    monkeypatch: pytest.MonkeyPatch,
    set_changespecs: Callable[[list[ChangeSpec]], None],
) -> None:
    set_changespecs([_cs("active-in-archive", "Ready", "proj", archive=True)])
    seen_files: list[str] = []

    def detect(project_file: str) -> str:
        seen_files.append(project_file)
        return "git"

    monkeypatch.setattr(
        "sase.integrations.changespec_tags.detect_workflow_type", detect
    )

    listing = list_changespec_xprompt_tags()

    assert [entry.tag for entry in listing.entries] == ["#git:active-in-archive"]
    assert seen_files == ["/home/user/.sase/projects/proj/proj.gp"]


def test_records_workflow_detection_failure_and_keeps_other_entries(
    monkeypatch: pytest.MonkeyPatch,
    set_changespecs: Callable[[list[ChangeSpec]], None],
) -> None:
    set_changespecs(
        [
            _cs("bad", "Ready", "alpha"),
            _cs("good", "Ready", "beta"),
        ]
    )

    def detect(project_file: str) -> str:
        if "/alpha/" in project_file:
            raise ValueError("no plugin")
        return "hg"

    monkeypatch.setattr(
        "sase.integrations.changespec_tags.detect_workflow_type", detect
    )

    listing = list_changespec_xprompt_tags()

    assert [entry.tag for entry in listing.entries] == ["#hg:good"]
    assert listing.skipped == [
        "alpha/bad: could not detect workflow type: no plugin",
    ]
