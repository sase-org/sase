"""Shared helpers and bead corpus for CLI show-style tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import re
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import (
    BeadTier,
    BeadNote,
    CloseRecord,
    Dependency,
    Issue,
    IssueType,
    PhaseSize,
    ReopenCause,
    Resolution,
    Status,
    TaskPlusOneEvidence,
)
from tests.main.parser_cli_helpers import parse_sase_args

STRIP_SGR = re.compile(r"\x1b\[[0-9;]*m")
GOLDEN = Path(__file__).parent / "golden"

CorpusBuilder = Callable[[], tuple[dict[str, Issue], str]]


def strip_sgr(text: str) -> str:
    return STRIP_SGR.sub("", text)


@contextmanager
def _multi_issue_view(issues: dict[str, Issue]) -> Iterator[object]:
    class _View:
        def show(self, issue_id: str) -> Issue:
            try:
                return issues[issue_id]
            except KeyError:
                raise KeyError(issue_id) from None

        def get_epic_children(self, issue_id: str) -> list[Issue]:
            return [
                candidate
                for candidate in issues.values()
                if candidate.parent_id == issue_id
            ]

        def list_issues(self) -> list[Issue]:
            return list(issues.values())

    yield _View()


def install_view(
    monkeypatch: pytest.MonkeyPatch,
    issues: dict[str, Issue],
) -> None:
    monkeypatch.setattr(
        "sase.bead.cli_query.get_read_view",
        lambda: _multi_issue_view(issues),
    )
    monkeypatch.setattr("sase.bead.cli_query.design_paths_are_relative", lambda: False)
    monkeypatch.setattr("sase.bead.cli_query.resolve_bead_page_url", lambda _id: None)
    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_creator_url", lambda _id: None
    )


def render(
    issue_id: str,
    issues: dict[str, Issue],
    *,
    style: str,
    color: str,
    wrap: str | None = None,
    format_: str = "full",
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> str:
    install_view(monkeypatch, issues)
    argv = [
        "bead",
        "show",
        issue_id,
        "--format",
        format_,
        "--style",
        style,
        "--color",
        color,
    ]
    if wrap is not None:
        argv.extend(["--wrap", wrap])
    args = parse_sase_args(argv)
    bead_cli.handle_bead_show(args)
    return capsys.readouterr().out


def read_golden(name: str) -> str:
    return (GOLDEN / "cli" / name).read_text(encoding="utf-8")


def build_minimal_task() -> tuple[dict[str, Issue], str]:
    issue = Issue(id="bd-task", title="Minimal Task", issue_type=IssueType.TASK)
    return {issue.id: issue}, issue.id


def build_closed_with_resolution() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-closed",
        title="Closed Phase",
        issue_type=IssueType.PHASE,
        status=Status.CLOSED,
        resolution=Resolution.DONE,
        close_reason="Landed in main",
        closed_at="2026-01-01T00:00:00",
        created_at="2025-12-01T00:00:00",
        size=PhaseSize.MEDIUM,
        owner="owner@example.com",
    )
    return {issue.id: issue}, issue.id


def build_legacy_closed_without_resolution() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-legacy-closed",
        title="Legacy Closed Task",
        issue_type=IssueType.TASK,
        status=Status.CLOSED,
    )
    return {issue.id: issue}, issue.id


def build_deps_and_blockers() -> tuple[dict[str, Issue], str]:
    target = Issue(
        id="bd-target",
        title="Target Task",
        issue_type=IssueType.TASK,
        dependencies=[
            Dependency(
                issue_id="bd-target",
                depends_on_id="bd-dep",
                created_at="2026-01-01T00:00:00",
            )
        ],
    )
    dep = Issue(id="bd-dep", title="Dependency Task", issue_type=IssueType.TASK)
    blocked = Issue(
        id="bd-blocked",
        title="Blocked Task",
        issue_type=IssueType.TASK,
        dependencies=[
            Dependency(
                issue_id="bd-blocked",
                depends_on_id="bd-target",
                created_at="2026-01-01T00:00:00",
            )
        ],
    )
    return {i.id: i for i in (target, dep, blocked)}, target.id


def build_dangling_refs() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-dangling",
        title="Dangling Refs Task",
        issue_type=IssueType.TASK,
        parent_id="bd-missing-parent",
        dependencies=[
            Dependency(
                issue_id="bd-dangling",
                depends_on_id="bd-missing-dep",
                created_at="2026-01-01T00:00:00",
            )
        ],
    )
    return {issue.id: issue}, issue.id


def build_patch() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-plan",
        title="Plan With Patch",
        issue_type=IssueType.PLAN,
        changespec_name="my_changespec",
        changespec_bug_id="BUG-42",
    )
    return {issue.id: issue}, issue.id


def build_with_refs() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-refs",
        title="Task With Refs",
        issue_type=IssueType.TASK,
        refs=["research:202607/report.md"],
    )
    return {issue.id: issue}, issue.id


def build_markdown_description() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-markdown",
        title="Task With Markdown Description",
        issue_type=IssueType.TASK,
        description=(
            "# Heading\n\n"
            "Some *emphasis* and a list:\n\n"
            "- one\n"
            "- two\n\n"
            "```python\n"
            "def foo(x):\n"
            "    return x + 1\n"
            "```\n"
        ),
    )
    return {issue.id: issue}, issue.id


def build_with_notes() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-notes",
        title="Task With Notes",
        issue_type=IssueType.TASK,
        notes=[
            BeadNote(
                id="note-1",
                timestamp="2026-07-31T12:00:00Z",
                author="agent.alpha",
                text="First note body.",
            ),
            BeadNote(
                id="note-2",
                timestamp="2026-08-01T11:30:00Z",
                author="owner@example.com",
                text=("Follow-up with code:\n\n```python\nprint('done')\n```"),
            ),
        ],
    )
    return {issue.id: issue}, issue.id


def build_cjk_emoji_title() -> tuple[dict[str, Issue], str]:
    issue = Issue(
        id="bd-cjk",
        title="修复错误 🐛 emoji title",
        issue_type=IssueType.TASK,
    )
    return {issue.id: issue}, issue.id


REOPENED_TASK_ID = "bd-reopened"
REOPENING_REPORTER = "claude.probe"
REOPENING_TIMESTAMP = "2026-07-31T17:04:11Z"


def build_reopened_task() -> tuple[dict[str, Issue], str]:
    """A task closed twice, reopened by a ``+1`` and then by ``sase bead open``."""

    issue = Issue(
        id=REOPENED_TASK_ID,
        title="Flaky retry test in CI",
        issue_type=IssueType.TASK,
        status=Status.READY,
        size=PhaseSize.SMALL,
        owner="owner@example.com",
        created_at="2026-07-14T00:00:00Z",
        plus_one_evidence=[
            TaskPlusOneEvidence(
                timestamp="2026-07-20T08:00:00Z",
                reporter="axe.scout",
                note="Seen once before the first close.",
            ),
            TaskPlusOneEvidence(
                timestamp=REOPENING_TIMESTAMP,
                reporter=REOPENING_REPORTER,
                note="Saw the same flake in CI run 4821 with a clean worktree.",
            ),
        ],
        close_history=[
            CloseRecord(
                closed_at="2026-07-16T11:00:00Z",
                reopened_at="2026-07-18T12:00:00Z",
                reopened_via=ReopenCause.OPEN,
            ),
            CloseRecord(
                closed_at="2026-07-30T09:12:04Z",
                reopened_at=REOPENING_TIMESTAMP,
                reopened_via=ReopenCause.PLUS_ONE,
                close_reason=(
                    "Not reproducible on main; the retry shim already covers this."
                ),
                resolution=Resolution.CANCELED,
                reopened_by=REOPENING_REPORTER,
            ),
        ],
    )
    return {issue.id: issue}, issue.id


CORPUS: list[tuple[str, CorpusBuilder]] = [
    ("minimal_task", build_minimal_task),
    ("closed_with_resolution", build_closed_with_resolution),
    ("legacy_closed_without_resolution", build_legacy_closed_without_resolution),
    ("deps_and_blockers", build_deps_and_blockers),
    ("dangling_refs", build_dangling_refs),
    ("patch", build_patch),
    ("with_refs", build_with_refs),
    ("markdown_description", build_markdown_description),
    ("with_notes", build_with_notes),
    ("cjk_emoji_title", build_cjk_emoji_title),
    ("reopened_task", build_reopened_task),
]


def build_epic_with_children() -> tuple[dict[str, Issue], str]:
    epic = Issue(
        id="epic-1",
        title="Root Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        created_at="2025-12-01T00:00:00",
    )
    phase = Issue(
        id="epic-1.1",
        title="Build Alpha",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        size=PhaseSize.MEDIUM,
    )
    child_epic = Issue(
        id="epic-1.2",
        title="Nested Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        parent_id=epic.id,
        status=Status.IN_PROGRESS,
    )
    return {i.id: i for i in (epic, phase, child_epic)}, epic.id
