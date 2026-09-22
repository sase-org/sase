"""CLI coverage for ``sase bead read`` (audited bead reads)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.artifact_read_log import read_artifact_read_events
from sase.bead import cli as bead_cli
from sase.bead.bead_views import SASE_BEAD_SKIP_VIEW_LOG, bead_views_log_path
from sase.main.bead_fast_path import try_handle_bead_fast_path
from sase.main.parser import create_parser
from tests._conftest_environment import redirect_sase_home


def _read_args(*argv: str):
    return create_parser().parse_args(["bead", "read", *argv])


def _audit_rows(project: str) -> list:
    return list(read_artifact_read_events(project=project))


def test_read_parser_requires_reason() -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_parser().parse_args(["bead", "read", "sase-64"])
    assert excinfo.value.code == 2
    args = _read_args("sase-64", "-r", "Need the scope")
    assert args.reason == "Need the scope"
    args = create_parser().parse_args(["bead", "read", "sase-64", "--reason", "x"])
    assert args.reason == "x"


def test_read_output_matches_show(
    nested_store: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    issue = nested_store["phase"]
    show_args = create_parser().parse_args(
        ["bead", "show", issue.id, "--no-links", "--pager", "never"]
    )
    bead_cli.handle_bead_show(show_args)
    show_out = capsys.readouterr().out

    read_args = create_parser().parse_args(
        ["bead", "read", issue.id, "--no-links", "--pager", "never", "-r", "Need it"]
    )
    bead_cli.handle_bead_read(read_args)
    captured = capsys.readouterr()
    assert captured.out == show_out


def test_read_compact_and_json_match_show(
    nested_store: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    issue = nested_store["phase"]
    for output_format in ("compact", "json"):
        show_args = create_parser().parse_args(
            [
                "bead",
                "show",
                issue.id,
                "--format",
                output_format,
                "--no-links",
                "--pager",
                "never",
            ]
        )
        bead_cli.handle_bead_show(show_args)
        show_out = capsys.readouterr().out
        read_args = create_parser().parse_args(
            [
                "bead",
                "read",
                issue.id,
                "--format",
                output_format,
                "--no-links",
                "--pager",
                "never",
                "-r",
                "Need it",
            ]
        )
        bead_cli.handle_bead_read(read_args)
        captured = capsys.readouterr()
        assert captured.out == show_out


def test_read_audits_full_id_with_trimmed_reason(
    nested_store: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    issue = nested_store["phase"]
    args = create_parser().parse_args(
        [
            "bead",
            "read",
            issue.id,
            "--no-links",
            "--pager",
            "never",
            "-r",
            "  Need it  ",
        ]
    )
    bead_cli.handle_bead_read(args)
    capsys.readouterr()
    from sase.main.init_memory.config import project_memory_name
    from sase.project_aliases import resolve_project_alias_ref

    project = resolve_project_alias_ref(project_memory_name(Path.cwd()))
    rows = _audit_rows(project)
    assert len(rows) == 1
    assert rows[0].ref == f"bead:{issue.id}"
    assert rows[0].reason == "Need it"


def test_read_expansion_audits_each_bead_once(
    nested_store: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    root = nested_store["root"]
    args = create_parser().parse_args(
        [
            "bead",
            "read",
            f"{root.id}..",
            "--no-links",
            "--pager",
            "never",
            "-r",
            "Need it",
        ]
    )
    bead_cli.handle_bead_read(args)
    capsys.readouterr()
    from sase.main.init_memory.config import project_memory_name
    from sase.project_aliases import resolve_project_alias_ref

    project = resolve_project_alias_ref(project_memory_name(Path.cwd()))
    rows = _audit_rows(project)
    refs = [row.ref for row in rows]
    assert len(refs) >= 2
    assert len(set(refs)) == len(refs)


def test_read_whitespace_reason_prints_nothing_and_exits_1(
    nested_store: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    issue = nested_store["phase"]
    args = create_parser().parse_args(
        ["bead", "read", issue.id, "--no-links", "--pager", "never", "-r", "   "]
    )
    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_read(args)
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "sase bead read:" in captured.err


def test_read_unresolved_ids_print_resolved_and_exit_1(
    nested_store: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    issue = nested_store["phase"]
    args = create_parser().parse_args(
        [
            "bead",
            "read",
            issue.id,
            "no-such-bead-xyz",
            "--no-links",
            "--pager",
            "never",
            "-r",
            "Need it",
        ]
    )
    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_read(args)
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert issue.id in captured.out or "Root Phase" in captured.out
    from sase.main.init_memory.config import project_memory_name
    from sase.project_aliases import resolve_project_alias_ref

    project = resolve_project_alias_ref(project_memory_name(Path.cwd()))
    rows = _audit_rows(project)
    assert [row.ref for row in rows] == [f"bead:{issue.id}"]


def test_read_writes_no_viewed_row_but_show_does(
    nested_store: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sase.bead.attribution as attribution

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(attribution, "acting_agent_name", lambda: "tester.host.0oa")
    monkeypatch.delenv(SASE_BEAD_SKIP_VIEW_LOG, raising=False)
    from sase.main.init_memory.config import project_memory_name
    from sase.project_aliases import resolve_project_alias_ref

    project = resolve_project_alias_ref(project_memory_name(Path.cwd()))
    issue = nested_store["phase"]
    read_args = create_parser().parse_args(
        ["bead", "read", issue.id, "--no-links", "--pager", "never", "-r", "Need it"]
    )
    bead_cli.handle_bead_read(read_args)
    capsys.readouterr()
    assert not bead_views_log_path(project).exists()

    show_args = create_parser().parse_args(
        ["bead", "show", issue.id, "--no-links", "--pager", "never"]
    )
    with pytest.raises(SystemExit) as excinfo:
        bead_cli.handle_bead_show(show_args)
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"sase bead read {issue.id}" in captured.err
    assert not bead_views_log_path(project).exists()


def test_read_outside_agent_run_prints_not_recorded_note(
    nested_store: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.delenv("SASE_AGENT", raising=False)
    issue = nested_store["phase"]
    args = create_parser().parse_args(
        ["bead", "read", issue.id, "--no-links", "--pager", "never", "-r", "Need it"]
    )
    bead_cli.handle_bead_read(args)
    captured = capsys.readouterr()
    assert "not recorded as a graph edge" in captured.err


def test_fast_path_does_not_handle_read() -> None:
    assert try_handle_bead_fast_path(["read", "sase-64", "-r", "x"]) is None


def test_bead_read_ref_accepts_bare_and_canonical_ids() -> None:
    from sase.bead.bead_reads import bead_read_ref

    assert bead_read_ref("sase-64.1") == "bead:sase-64.1"
    assert bead_read_ref("bead:sase-64.1") == "bead:sase-64.1"


def test_view_log_opt_out_bypasses_agent_guard(
    nested_store: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import sase.bead.attribution as attribution
    from sase.main.init_memory.config import project_memory_name
    from sase.project_aliases import resolve_project_alias_ref

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(attribution, "acting_agent_name", lambda: "tester.host.0oa")
    monkeypatch.setenv(SASE_BEAD_SKIP_VIEW_LOG, "1")
    project = resolve_project_alias_ref(project_memory_name(Path.cwd()))
    issue = nested_store["phase"]
    show_args = create_parser().parse_args(
        ["bead", "show", issue.id, "--no-links", "--pager", "never"]
    )
    bead_cli.handle_bead_show(show_args)
    captured = capsys.readouterr()
    assert captured.out != ""
    assert not bead_views_log_path(project).exists()


def test_sase_bead_wrapper_exports_view_log_opt_out() -> None:
    from pathlib import Path as _Path

    text = _Path("tools/sase_bead").read_text(encoding="utf-8")
    assert "SASE_BEAD_SKIP_VIEW_LOG" in text
    assert "export SASE_BEAD_SKIP_VIEW_LOG=1" in text
