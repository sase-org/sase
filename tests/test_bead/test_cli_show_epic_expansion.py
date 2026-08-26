"""``<epic-id>..`` expansion coverage for ``sase bead show``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json

import pytest

from sase.agent.names import _registry as name_registry
from sase.bead import cli as bead_cli
from sase.bead.model import Issue, IssueType
from sase.main.parser import create_parser


def _issues() -> dict[str, Issue]:
    return {
        "sase-e1": Issue(id="sase-e1", title="Epic One", issue_type=IssueType.PLAN),
        # Inserted out of numeric order to prove sorting isn't luck-of-created_at.
        "sase-e1.10": Issue(
            id="sase-e1.10",
            title="Phase Ten",
            issue_type=IssueType.PHASE,
            parent_id="sase-e1",
        ),
        "sase-e1.9": Issue(
            id="sase-e1.9",
            title="Phase Nine",
            issue_type=IssueType.PHASE,
            parent_id="sase-e1",
        ),
        "sase-e2": Issue(id="sase-e2", title="Epic Two", issue_type=IssueType.PLAN),
        "sase-e2.1": Issue(
            id="sase-e2.1",
            title="Phase Alpha",
            issue_type=IssueType.PHASE,
            parent_id="sase-e2",
        ),
        "sase-e2.2": Issue(
            id="sase-e2.2",
            title="Child Epic",
            issue_type=IssueType.PLAN,
            parent_id="sase-e2",
        ),
        "sase-e3": Issue(id="sase-e3", title="Epic Three", issue_type=IssueType.PLAN),
        "sase-e4": Issue(id="sase-e4", title="Epic Four", issue_type=IssueType.PLAN),
        "sase-e4.1": Issue(
            id="sase-e4.1",
            title="Phase Only",
            issue_type=IssueType.PHASE,
            parent_id="sase-e4",
        ),
    }


@contextmanager
def _view(issues: dict[str, Issue]) -> Iterator[object]:
    class _View:
        def show(self, issue_id: str) -> Issue:
            if issue_id in issues:
                return issues[issue_id]
            matches = [
                issue
                for issue in issues.values()
                if issue.id.rsplit("-", maxsplit=1)[-1] == issue_id
            ]
            if len(matches) == 1:
                return matches[0]
            if matches:
                raise ValueError(f"ambiguous issue id: {issue_id}")
            raise KeyError(issue_id)

        def get_epic_children(self, issue_id: str) -> list[Issue]:
            if issue_id in issues:
                canonical = issue_id
            elif issue_id.startswith("sase-"):
                # An unrecognized full-form ID resolves to itself, same as
                # the real store's resolve_id -- so the children query
                # legitimately comes back empty instead of raising.
                canonical = issue_id
            else:
                matches = [
                    issue
                    for issue in issues.values()
                    if issue.id.rsplit("-", maxsplit=1)[-1] == issue_id
                ]
                if not matches:
                    raise KeyError(issue_id)
                canonical = matches[0].id
            return [issue for issue in issues.values() if issue.parent_id == canonical]

        def list_issues(self) -> list[Issue]:
            return list(issues.values())

    yield _View()


def _install_view(
    monkeypatch: pytest.MonkeyPatch,
    issues: dict[str, Issue],
) -> None:
    monkeypatch.setattr("sase.bead.cli_query.get_read_view", lambda: _view(issues))
    monkeypatch.setattr("sase.bead.cli_query.design_paths_are_relative", lambda: False)
    monkeypatch.setattr("sase.bead.cli_query.resolve_bead_page_url", lambda _id: None)
    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_creator_url",
        lambda _name: None,
    )


def _show(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ids: list[str],
    *flags: str,
    issues: dict[str, Issue] | None = None,
) -> str:
    _install_view(monkeypatch, issues or _issues())
    args = create_parser().parse_args(["bead", "show", *ids, *flags])
    bead_cli.handle_bead_show(args)
    return capsys.readouterr().out


def test_expansion_renders_target_then_children_including_child_epics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _show(
        monkeypatch,
        capsys,
        ["e2.."],
        "--format",
        "compact",
        "--pager",
        "never",
    )
    lines = [line for line in out.splitlines() if line.strip()]

    assert len(lines) == 3
    assert "sase-e2" in lines[0] and "sase-e2." not in lines[0]
    assert "sase-e2.1" in lines[1]
    assert "sase-e2.2" in lines[2]


def test_children_ordered_by_numeric_suffix_not_insertion_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _show(
        monkeypatch,
        capsys,
        ["sase-e1.."],
        "--format",
        "compact",
        "--pager",
        "never",
    )
    lines = [line for line in out.splitlines() if line.strip()]

    ids_in_order = []
    for line in lines:
        # Check the longer, more specific IDs first: "sase-e1" is a
        # substring of both children, so it must be checked last.
        for issue_id in ("sase-e1.9", "sase-e1.10", "sase-e1"):
            if issue_id in line:
                ids_in_order.append(issue_id)
                break
    assert ids_in_order == ["sase-e1", "sase-e1.9", "sase-e1.10"]


def test_epic_with_no_children_renders_alone(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _show(
        monkeypatch,
        capsys,
        ["e3.."],
        "--format",
        "compact",
        "--pager",
        "never",
    )

    assert "sase-e3" in out
    assert "sase-e1" not in out
    assert "sase-e2" not in out


@pytest.mark.parametrize("token", ["..", "tt..."])
def test_malformed_expansion_token_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    token: str,
) -> None:
    _install_view(monkeypatch, _issues())
    args = create_parser().parse_args(
        ["bead", "show", token, "--format", "compact", "--pager", "never"]
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(args)

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert captured.out == ""
    assert captured.err == (
        f"Error: invalid ID expansion: {token!r} "
        "(expected <epic-id>.., for example sase-tt..)\n"
    )


def test_nonexistent_shorthand_stem_reports_issue_not_found_and_keeps_others(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_view(monkeypatch, _issues())
    args = create_parser().parse_args(
        [
            "bead",
            "show",
            "e2",
            "nope..",
            "--format",
            "compact",
            "--pager",
            "never",
        ]
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(args)

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert "sase-e2" in captured.out
    assert captured.err == "Error: issue not found: nope\n"


def test_nonexistent_full_form_stem_reports_issue_not_found(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_view(monkeypatch, _issues())
    args = create_parser().parse_args(
        ["bead", "show", "sase-nope..", "--format", "compact", "--pager", "never"]
    )

    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(args)

    captured = capsys.readouterr()
    assert excinfo.value.code == 1
    assert captured.out == ""
    assert captured.err == "Error: issue not found: sase-nope\n"


def test_positional_dedup_applies_after_expansion(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _show(
        monkeypatch,
        capsys,
        ["e1.9", "e1.."],
        "--format",
        "compact",
        "--pager",
        "never",
    )
    lines = [line for line in out.splitlines() if line.strip()]

    assert out.count("sase-e1.9") == 1
    ids_in_order = []
    for line in lines:
        # Check the longer, more specific IDs first: "sase-e1" is a
        # substring of both children, so it must be checked last.
        for issue_id in ("sase-e1.9", "sase-e1.10", "sase-e1"):
            if issue_id in line:
                ids_in_order.append(issue_id)
                break
    assert ids_in_order == ["sase-e1.9", "sase-e1", "sase-e1.10"]


def test_json_array_shape_for_one_child_and_no_children(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    one_child = json.loads(
        _show(
            monkeypatch,
            capsys,
            ["e4.."],
            "--format",
            "json",
            "--pager",
            "never",
        )
    )
    no_children = json.loads(
        _show(
            monkeypatch,
            capsys,
            ["e3.."],
            "--format",
            "json",
            "--pager",
            "never",
        )
    )

    assert isinstance(one_child, list)
    assert [entry["issue"]["id"] for entry in one_child] == ["sase-e4", "sase-e4.1"]
    assert isinstance(no_children, list)
    assert [entry["issue"]["id"] for entry in no_children] == ["sase-e3"]


def test_show_holds_registry_load_session_open_while_resolving_creator_urls(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues = _issues()
    issues["sase-e1"].created_by = "alice"
    _install_view(monkeypatch, issues)
    observed: list[bool] = []

    def _fake_creator_url(_name: str) -> str | None:
        observed.append(name_registry._LOAD_SESSION_ACTIVE.get())
        return None

    monkeypatch.setattr(
        "sase.bead.cli_query.resolve_bead_creator_url",
        _fake_creator_url,
    )
    args = create_parser().parse_args(["bead", "show", "sase-e1", "--pager", "never"])

    bead_cli.handle_bead_show(args)
    capsys.readouterr()

    assert observed == [True]
    assert name_registry._LOAD_SESSION_ACTIVE.get() is False
