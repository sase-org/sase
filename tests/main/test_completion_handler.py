"""Tests for the ``sase completion`` handler."""

from __future__ import annotations

import json
from argparse import Namespace
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.completion.snapshot import current_structural_view
from sase.completion.install import (
    DetectedShell,
    InstallResult,
    InstallStep,
    ShellInstallStatus,
    TargetChoice,
)
from sase.main.completion_handler import (
    _handle_completion_install,
    _handle_completion_list,
    handle_completion_command,
)
from sase.main.parser import create_parser


def _console() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, highlight=False, color_system=None, width=80), buf


def test_list_renders_all_three_generators() -> None:
    console, buf = _console()
    args = create_parser().parse_args(["completion", "list"])

    assert _handle_completion_list(args, console=console) == 0
    text = buf.getvalue()
    assert "SHELL" in text
    assert "GENERATOR" in text
    assert "STATUS" in text
    assert "PATH" in text
    assert "ZWC" in text
    assert "STAMP" in text
    assert "zsh" in text
    assert "yes" in text
    assert "not installed" in text
    assert "bash" in text
    assert "fish" in text


def test_list_json_payload(capsys: pytest.CaptureFixture[str]) -> None:
    args = create_parser().parse_args(["completion", "list", "--json"])

    assert handle_completion_command(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    shells = {row["shell"]: row for row in payload["shells"]}
    expected = {
        "generator": True,
        "path": None,
        "stamp_version": None,
        "status": "not installed",
        "zwc": "n/a",
    }
    assert shells["zsh"] == {**expected, "shell": "zsh"}
    assert shells["bash"] == {**expected, "shell": "bash"}
    assert shells["fish"] == {**expected, "shell": "fish"}


def test_list_accepts_injected_rows_for_later_columns() -> None:
    console, buf = _console()
    rows = (
        ShellInstallStatus("zsh", True, "installed", "/tmp/_sase", "fresh", "0.16.0"),
        ShellInstallStatus("bash", True, "stale", "/tmp/sase", "n/a", "0.15.0"),
    )
    args = create_parser().parse_args(["completion", "list"])

    assert _handle_completion_list(args, console=console, rows=rows) == 0
    text = buf.getvalue()
    assert "installed" in text
    assert "fresh" in text
    assert "bash" in text
    assert "0.15.0" in text


def test_spec_prints_structural_snapshot(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = create_parser().parse_args(["completion", "spec"])

    assert handle_completion_command(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == current_structural_view()
    assert payload["prog"] == "sase"
    names = {child["name"] for child in payload["root"]["subcommands"]}
    assert "completion" in names


def test_spec_and_shells_write_output_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_path = tmp_path / "spec.json"
    bash_path = tmp_path / "sase.bash"
    fish_path = tmp_path / "sase.fish"
    zsh_path = tmp_path / "_sase"
    spec_args = create_parser().parse_args(["completion", "spec", "-o", str(spec_path)])
    bash_args = create_parser().parse_args(["completion", "bash", "-o", str(bash_path)])
    fish_args = create_parser().parse_args(["completion", "fish", "-o", str(fish_path)])
    zsh_args = create_parser().parse_args(["completion", "zsh", "-o", str(zsh_path)])

    assert handle_completion_command(spec_args) == 0
    assert handle_completion_command(bash_args) == 0
    assert handle_completion_command(fish_args) == 0
    assert handle_completion_command(zsh_args) == 0
    assert capsys.readouterr().out == ""
    assert (
        json.loads(spec_path.read_text(encoding="utf-8")) == current_structural_view()
    )
    bash_text = bash_path.read_text(encoding="utf-8")
    assert "complete -o default -F _sase sase" in bash_text
    fish_text = fish_path.read_text(encoding="utf-8")
    assert "complete -c sase -e" in fish_text
    zsh_text = zsh_path.read_text(encoding="utf-8")
    assert zsh_text.startswith("#compdef sase\n")
    assert "_arguments -C -s -S" in zsh_text


def test_shell_emitters_print_scripts(capsys: pytest.CaptureFixture[str]) -> None:
    for child, needle in (
        ("bash", "complete -o default -F _sase sase"),
        ("fish", "complete -c sase -e"),
        ("zsh", "#compdef sase"),
    ):
        args = create_parser().parse_args(["completion", child])
        assert handle_completion_command(args) == 0
        script = capsys.readouterr().out
        assert needle in script


def test_write_output_reports_unwritable_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "no-such-dir" / "_sase"
    args = create_parser().parse_args(["completion", "zsh", "-o", str(missing)])

    assert handle_completion_command(args) == 1
    assert "cannot write" in capsys.readouterr().err


def test_install_dispatch_renders_detected_shell_and_zstyle() -> None:
    console, buf = _console()
    result = InstallResult(
        shell=DetectedShell("zsh", "explicit", None, None),
        target=TargetChoice(Path("/tmp/zfunc"), "--target"),
        script=Path("/tmp/zfunc/_sase"),
        steps=(
            InstallStep("detect", "ok", "explicit"),
            InstallStep("write", "ok", "/tmp/zfunc/_sase"),
        ),
        stamp=None,
        registered=True,
        fpath_hint=None,
        ok=True,
        exit_code=0,
    )

    args = create_parser().parse_args(["completion", "install", "zsh"])
    assert (
        _handle_completion_install(
            args, console=console, install_fn=lambda **_kwargs: result
        )
        == 0
    )
    text = buf.getvalue()
    assert "Detected shell: zsh" in text
    assert "explicit" in text
    assert "zstyle ':completion:*' menu select" in text


def test_dispatch_unknown_subcommand_exits_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert handle_completion_command(Namespace(completion_subcommand="nope")) == 2
    assert "Usage: sase completion" in capsys.readouterr().err


def test_candidates_handler_prints_provider_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sase.completion.candidates.providers as providers

    calls: list[dict[str, object]] = []

    def fake_candidates_for(kind, prefix, *, project, limit):
        calls.append(
            {"kind": kind, "prefix": prefix, "project": project, "limit": limit}
        )
        from sase.completion.candidates.protocol import Candidate

        return [Candidate("sase-1", "Fix the thing")]

    monkeypatch.setattr(providers, "candidates_for", fake_candidates_for)
    args = create_parser().parse_args(
        ["completion", "candidates", "bead", "sase-", "-l", "5", "-p", "sase"]
    )

    assert handle_completion_command(args) == 0

    assert capsys.readouterr().out == "sase-1\tFix the thing\n"
    assert calls == [{"kind": "bead", "prefix": "sase-", "project": "sase", "limit": 5}]


def test_candidates_handler_prints_nothing_for_no_candidates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sase.completion.candidates.providers as providers

    monkeypatch.setattr(providers, "candidates_for", lambda *a, **k: [])
    args = create_parser().parse_args(["completion", "candidates", "project"])

    assert handle_completion_command(args) == 0
    assert capsys.readouterr().out == ""
