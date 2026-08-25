"""Multi-ID ``sase bead show`` coverage."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json

import pytest
from rich.cells import cell_len

from sase.bead import cli as bead_cli
from sase.bead.cli_detail import render_issue_detail_json, resolve_issue_detail
from sase.bead.model import BeadLink, Issue, IssueType
from sase.main.parser import create_parser
from tests.test_bead.cli_show_style_test_helpers import strip_sgr


def _issues() -> dict[str, Issue]:
    return {
        "sase-1": Issue(id="sase-1", title="First", issue_type=IssueType.TASK),
        "sase-2": Issue(id="sase-2", title="Second", issue_type=IssueType.TASK),
        "sase-3": Issue(id="sase-3", title="Third", issue_type=IssueType.TASK),
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

        def get_epic_children(self, _issue_id: str) -> list[Issue]:
            return []

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


def test_show_parser_yields_ids_for_one_and_many() -> None:
    parser = create_parser()

    assert parser.parse_args(["bead", "show", "sase-1"]).ids == ["sase-1"]
    assert parser.parse_args(["bead", "show", "sase-1", "sase-2"]).ids == [
        "sase-1",
        "sase-2",
    ]


def test_full_single_bead_matches_existing_detail_rendering(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues = _issues()
    out = _show(
        monkeypatch,
        capsys,
        ["sase-1"],
        "--pager",
        "never",
        issues=issues,
    )

    with _view(issues) as view:
        expected = render_issue_detail_json(
            resolve_issue_detail(view, "sase-1"),
            include_links=True,
        )
    json_out = _show(
        monkeypatch,
        capsys,
        ["sase-1"],
        "--format",
        "json",
        "--pager",
        "never",
        issues=issues,
    )

    assert "── 1/" not in out
    assert json_out == expected


def test_full_multi_bead_dividers_order_width_and_rich_invariance(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    flags = ["--wrap", "40", "--pager", "never"]
    plain = _show(
        monkeypatch,
        capsys,
        ["sase-2", "sase-1", "sase-3"],
        *flags,
        "--style",
        "plain",
        "--color",
        "never",
    )
    rich = _show(
        monkeypatch,
        capsys,
        ["sase-2", "sase-1", "sase-3"],
        *flags,
        "--style",
        "rich",
        "--color",
        "always",
    )

    assert ["── 1/3 ", "── 2/3 ", "── 3/3 "] == [
        line[:7] for line in plain.splitlines() if line.startswith("── ")
    ]
    divider_lines = [line for line in plain.splitlines() if line.startswith("── ")]
    assert all(cell_len(line) == 40 for line in divider_lines)
    assert plain.index("sase-2") < plain.index("sase-1") < plain.index("sase-3")
    assert strip_sgr(rich) == plain


def test_duplicate_shorthand_collapses_after_resolution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _show(
        monkeypatch,
        capsys,
        ["sase-3", "sase-1", "1"],
        "--pager",
        "never",
    )

    assert "── 1/2 " in out
    assert "── 2/2 " in out
    assert out.count("sase-1 · First") == 1
    assert out.index("sase-3") < out.index("sase-1")


def test_compact_multi_bead_rows_are_aligned_in_argv_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = _show(
        monkeypatch,
        capsys,
        ["sase-2", "sase-1", "sase-3"],
        "--format",
        "compact",
        "--pager",
        "never",
    )
    lines = out.splitlines()
    row_ids = ["sase-2", "sase-1", "sase-3"]

    assert [
        issue_id for line in lines for issue_id in _issues() if issue_id in line
    ] == [
        *row_ids,
    ]
    assert (
        len(
            {
                line.index(issue_id)
                for line, issue_id in zip(lines, row_ids, strict=True)
            }
        )
        == 1
    )


def test_json_shape_follows_single_vs_multi_invocation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    single = json.loads(
        _show(
            monkeypatch,
            capsys,
            ["sase-1"],
            "--format",
            "json",
            "--pager",
            "never",
        )
    )
    multi = json.loads(
        _show(
            monkeypatch,
            capsys,
            ["sase-2", "sase-1"],
            "--format",
            "json",
            "--pager",
            "never",
        )
    )

    assert isinstance(single, dict)
    assert single["issue"]["id"] == "sase-1"
    assert isinstance(multi, list)
    assert [entry["issue"]["id"] for entry in multi] == ["sase-2", "sase-1"]


def test_one_missing_id_keeps_resolved_stdout_and_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_view(monkeypatch, _issues())
    args = create_parser().parse_args(
        [
            "bead",
            "show",
            "sase-1",
            "missing",
            "sase-2",
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
    assert "sase-1 · First" in captured.out
    assert "sase-2 · Second" in captured.out
    assert captured.err == "Error: issue not found: missing\n"


def test_single_and_all_missing_ids_write_only_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_view(monkeypatch, _issues())
    one = create_parser().parse_args(["bead", "show", "missing"])
    with pytest.raises(SystemExit) as one_exc:
        bead_cli.handle_bead_show(one)
    captured = capsys.readouterr()
    assert one_exc.value.code == 1
    assert captured.out == ""
    assert captured.err == "Error: issue not found: missing\n"

    many = create_parser().parse_args(["bead", "show", "missing-a", "missing-b"])
    with pytest.raises(SystemExit) as many_exc:
        bead_cli.handle_bead_show(many)
    captured = capsys.readouterr()
    assert many_exc.value.code == 1
    assert captured.out == ""
    assert captured.err == (
        "Error: issue not found: missing-a\nError: issue not found: missing-b\n"
    )


def test_no_links_suppresses_json_links_for_every_bead_in_batch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issues = _issues()
    issues["sase-1"].links.append(BeadLink("plan:one.md", "implements", "one"))
    issues["sase-2"].links.append(BeadLink("plan:two.md", "implements", "two"))

    payload = json.loads(
        _show(
            monkeypatch,
            capsys,
            ["sase-1", "sase-2"],
            "--format",
            "json",
            "--no-links",
            "--pager",
            "never",
            issues=issues,
        )
    )

    assert all("artifact_links" not in entry for entry in payload)
    assert all("links" not in entry["issue"] for entry in payload)
