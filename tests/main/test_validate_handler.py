"""Tests for the top-level ``sase validate`` command."""

from __future__ import annotations

import argparse
import subprocess
import sys

import pytest

from sase.main import entry
from sase.main import validate_handler
from sase.main.parser import create_parser
from sase.main.validate_handler import _run_validate_command


def _completed(
    command: list[str],
    returncode: int,
    *,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def test_parser_registers_validate_command() -> None:
    parser = create_parser()

    args = parser.parse_args(["validate"])

    assert args.command == "validate"


def test_validate_suppresses_successful_child_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert capture_output is True
        assert text is True
        assert check is False
        calls.append(command)
        return _completed(command, 0, stdout="success stdout\n", stderr="success err\n")

    monkeypatch.setattr(validate_handler.subprocess, "run", fake_run)

    exit_code = _run_validate_command()

    assert exit_code == 0
    assert calls == [
        [sys.executable, "-m", "sase", "doctor", "-C", "plugins.required"],
        [sys.executable, "-m", "sase", "init", "memory", "--check"],
        [sys.executable, "-m", "sase", "init", "repo", "--check"],
        [sys.executable, "-m", "sase", "init", "skills", "--check"],
        [sys.executable, "-m", "sase", "doctor", "-C", "config.file_hooks"],
        [sys.executable, "-m", "sase", "plan", "links", "validate"],
        [sys.executable, "-m", "sase", "agent", "prompts", "validate"],
    ]
    captured = capsys.readouterr()
    assert captured.out == (
        "SASE validation\n"
        "  ok     doctor plugins.required\n"
        "  ok     init memory --check\n"
        "  ok     init repo --check\n"
        "  ok     init skills --check\n"
        "  ok     doctor config.file_hooks\n"
        "  ok     plan links validate\n"
        "  ok     agent prompts validate\n"
    )
    assert captured.err == ""


def test_validate_runs_both_checks_when_first_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[list[str]] = []
    results = [
        (0, "plugins success stdout\n", "plugins success stderr\n"),
        (2, "init stdout\n", "init stderr\n"),
        (0, "repo success stdout\n", "repo success stderr\n"),
        (0, "skills success stdout\n", "skills success stderr\n"),
        (0, "file hooks success stdout\n", "file hooks success stderr\n"),
        (0, "sdd success stdout\n", "sdd success stderr\n"),
        (0, "prompts success stdout\n", "prompts success stderr\n"),
    ]

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        returncode, stdout, stderr = results.pop(0)
        return _completed(command, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(validate_handler.subprocess, "run", fake_run)

    exit_code = _run_validate_command()

    assert exit_code == 1
    assert calls == [
        [sys.executable, "-m", "sase", "doctor", "-C", "plugins.required"],
        [sys.executable, "-m", "sase", "init", "memory", "--check"],
        [sys.executable, "-m", "sase", "init", "repo", "--check"],
        [sys.executable, "-m", "sase", "init", "skills", "--check"],
        [sys.executable, "-m", "sase", "doctor", "-C", "config.file_hooks"],
        [sys.executable, "-m", "sase", "plan", "links", "validate"],
        [sys.executable, "-m", "sase", "agent", "prompts", "validate"],
    ]
    out = capsys.readouterr().out
    assert "  ok     doctor plugins.required\n" in out
    assert "  fail   init memory --check\n" in out
    assert "  ok     init repo --check\n" in out
    assert "  ok     init skills --check\n" in out
    assert "  ok     doctor config.file_hooks\n" in out
    assert "  ok     plan links validate\n" in out
    assert "  ok     agent prompts validate\n" in out
    assert "init memory --check failed (exit 2)" in out
    assert "stdout:\ninit stdout\n" in out
    assert "stderr:\ninit stderr\n" in out
    assert "sdd success stdout" not in out
    assert "sdd success stderr" not in out
    assert "run `sase doctor -v` or `sase doctor -j`" in out


def test_validate_prints_output_for_each_failed_check(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = [
        (0, "", ""),
        (1, "", "init broken\n"),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (3, "sdd broken\n", ""),
        (0, "", ""),
    ]

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        returncode, stdout, stderr = results.pop(0)
        return _completed(command, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(validate_handler.subprocess, "run", fake_run)

    exit_code = _run_validate_command()

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "  fail   init memory --check\n" in out
    assert "  ok     init repo --check\n" in out
    assert "  ok     init skills --check\n" in out
    assert "  ok     doctor config.file_hooks\n" in out
    assert "  fail   plan links validate\n" in out
    assert "  ok     agent prompts validate\n" in out
    assert "init memory --check failed (exit 1)" in out
    assert "stderr:\ninit broken\n" in out
    assert "plan links validate failed (exit 3)" in out
    assert "stdout:\nsdd broken\n" in out
    assert "run `sase doctor -v` or `sase doctor -j`" in out


def test_validate_aggregates_prompt_archive_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = [
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (4, "prompt archive broken\n", ""),
    ]

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        returncode, stdout, stderr = results.pop(0)
        return _completed(command, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(validate_handler.subprocess, "run", fake_run)

    assert _run_validate_command() == 1
    out = capsys.readouterr().out
    assert "  fail   agent prompts validate\n" in out
    assert "agent prompts validate failed (exit 4)" in out
    assert "stdout:\nprompt archive broken\n" in out


def test_validate_skips_unavailable_prompt_archive_context(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = [
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (
            validate_handler.PROMPT_ARCHIVE_CONTEXT_UNAVAILABLE_EXIT_CODE,
            "Prompt archive validation skipped: context unavailable: "
            "project 'sase' was not found\n",
            "",
        ),
    ]

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        returncode, stdout, stderr = results.pop(0)
        return _completed(command, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(validate_handler.subprocess, "run", fake_run)

    assert _run_validate_command() == 0
    out = capsys.readouterr().out
    assert "  skip   agent prompts validate\n" in out
    assert "agent prompts validate skipped (exit 69)" in out
    assert "project 'sase' was not found" in out
    assert "run `sase doctor -v` or `sase doctor -j`" not in out


def test_validate_prints_warnings_section_for_passing_checks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    results = [
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (
            0,
            "SASE initialization check\n"
            "\n"
            "Up to date:\n"
            "  ok   init skills  provider skill files are current\n"
            "\n"
            "Warnings:\n"
            "  init skills: 5 provider skill files out of sync with rendered "
            "sources; redeploy is deferred until land. Rerun `sase init skills` "
            "after landing.\n",
            "",
        ),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
    ]

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        returncode, stdout, stderr = results.pop(0)
        return _completed(command, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(validate_handler.subprocess, "run", fake_run)

    exit_code = _run_validate_command()

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "  ok     init skills --check\n" in out
    assert "Warnings:\n" in out
    assert (
        "  init skills: 5 provider skill files out of sync with rendered "
        "sources; redeploy is deferred until land. Rerun `sase init skills` "
        "after landing.\n"
    ) in out
    # The failure detail dump must stay distinct from the passing-check
    # warnings summary: no "failed"/"skipped" framing, no support hint.
    assert "failed (exit" not in out
    assert "run `sase doctor -v` or `sase doctor -j`" not in out


def test_entry_dispatches_validate_command(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_handle(args: argparse.Namespace) -> None:
        seen.append(args.command)
        raise SystemExit(7)

    monkeypatch.setattr(sys, "argv", ["sase", "validate"])
    monkeypatch.setattr(validate_handler, "handle_validate_command", fake_handle)

    with pytest.raises(SystemExit) as excinfo:
        entry.main()

    assert excinfo.value.code == 7
    assert seen == ["validate"]
