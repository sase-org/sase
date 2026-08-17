"""Tests for the pre-argparse ``sase completion candidates`` fast path."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sase.completion.candidates.protocol import Candidate
from sase.main import completion_fast_path
from sase.main.completion_fast_path import try_handle_completion_candidates


def _stub_candidates_for(monkeypatch: pytest.MonkeyPatch, result: list[Candidate]):
    calls: list[dict[str, object]] = []

    def fake(kind: str, prefix: str, *, project: str | None, limit: int):
        calls.append(
            {"kind": kind, "prefix": prefix, "project": project, "limit": limit}
        )
        return result

    monkeypatch.setattr("sase.completion.candidates.providers.candidates_for", fake)
    return calls


def test_fast_path_prints_wire_lines_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _stub_candidates_for(
        monkeypatch, [Candidate("sase-1", "Fix the thing"), Candidate("sase-2")]
    )

    assert try_handle_completion_candidates(["bead"]) == 0

    assert capsys.readouterr().out == "sase-1\tFix the thing\nsase-2\n"
    assert calls == [{"kind": "bead", "prefix": "", "project": None, "limit": 200}]


def test_fast_path_prints_nothing_for_no_candidates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_candidates_for(monkeypatch, [])

    assert try_handle_completion_candidates(["bead"]) == 0

    assert capsys.readouterr().out == ""


def test_fast_path_parses_prefix_positional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_candidates_for(monkeypatch, [])

    assert try_handle_completion_candidates(["bead", "sase-o"]) == 0

    assert calls == [
        {"kind": "bead", "prefix": "sase-o", "project": None, "limit": 200}
    ]


@pytest.mark.parametrize(
    "argv",
    [
        ["project", "-l", "5"],
        ["project", "--limit", "5"],
        ["project", "--limit=5"],
    ],
)
def test_fast_path_parses_limit_flag_forms(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub_candidates_for(monkeypatch, [])

    assert try_handle_completion_candidates(argv) == 0

    assert calls == [{"kind": "project", "prefix": "", "project": None, "limit": 5}]


@pytest.mark.parametrize(
    "argv",
    [
        ["bead", "-p", "sase"],
        ["bead", "--project", "sase"],
        ["bead", "--project=sase"],
    ],
)
def test_fast_path_parses_project_flag_forms(
    argv: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub_candidates_for(monkeypatch, [])

    assert try_handle_completion_candidates(argv) == 0

    assert calls == [{"kind": "bead", "prefix": "", "project": "sase", "limit": 200}]


def test_fast_path_defers_on_empty_argv() -> None:
    assert try_handle_completion_candidates([]) is None


@pytest.mark.parametrize(
    "argv",
    [
        ["-h"],
        ["--help"],
        ["bead", "-h"],
        ["bead", "sase-o", "--help"],
    ],
)
def test_fast_path_defers_on_help_flag(argv: list[str]) -> None:
    assert try_handle_completion_candidates(argv) is None


@pytest.mark.parametrize(
    "argv",
    [
        ["bead", "prefix", "extra"],
        ["bead", "-l"],
        ["bead", "-l", "not-a-number"],
        ["bead", "--limit=not-a-number"],
        ["bead", "-p"],
        ["bead", "--unknown-flag"],
    ],
)
def test_fast_path_defers_on_malformed_argv(argv: list[str]) -> None:
    assert try_handle_completion_candidates(argv) is None


def test_fast_path_guard_only_triggers_for_exact_completion_candidates_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only ``sys.argv[1:3] == ["completion", "candidates"]`` takes the fast path."""
    from sase.main import entry

    calls: list[list[str]] = []
    monkeypatch.setattr(
        completion_fast_path,
        "try_handle_completion_candidates",
        lambda argv: calls.append(argv) or 0,
    )

    monkeypatch.setattr(sys, "argv", ["sase", "completion", "candidates", "bead", "x"])
    with pytest.raises(SystemExit) as exc_info:
        entry.main()
    assert exc_info.value.code == 0
    assert calls == [["bead", "x"]]

    calls.clear()
    for argv in (
        ["sase", "--help"],
        ["sase", "completion", "--help"],
        ["sase", "completions", "candidates"],
        ["sase", "completion"],
    ):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit):
            entry.main()
    assert calls == []


def test_end_to_end_help_reaches_argparse_and_prints_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.main import entry

    monkeypatch.setattr(sys, "argv", ["sase", "completion", "candidates", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        entry.main()

    assert exc_info.value.code == 0
    assert "usage: sase completion candidates" in capsys.readouterr().out


def test_end_to_end_missing_kind_reaches_argparse_and_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.main import entry

    monkeypatch.setattr(sys, "argv", ["sase", "completion", "candidates"])

    with pytest.raises(SystemExit) as exc_info:
        entry.main()

    assert exc_info.value.code == 2
    assert "the following arguments are required: KIND" in capsys.readouterr().err


def test_end_to_end_unknown_kind_exits_cleanly_with_no_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from sase.main import entry

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setattr(sys, "argv", ["sase", "completion", "candidates", "bogus-kind"])

    with pytest.raises(SystemExit) as exc_info:
        entry.main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
