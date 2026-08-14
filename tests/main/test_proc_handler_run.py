"""Behavior tests for the ``sase proc run`` handler."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from sase.sessions import SessionIdentity
from tests.main.proc_handler_helpers import (
    NOOP,
    dispatch,
    proc_home,
    use_sessions,
)

__all__ = ["proc_home"]


def test_run_without_a_command_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``sase proc run`` with nothing after ``--`` explains the syntax."""
    assert dispatch(["proc", "run"]) == 2

    assert "pass it after --" in capsys.readouterr().err


def test_run_prints_the_id_and_the_follow_hint(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A detached submit reports the new id plus how to watch it."""
    assert dispatch(["proc", "run", "-c", str(tmp_path), "--", *NOOP]) == 0

    out = capsys.readouterr().out.splitlines()
    assert len(out[0]) == 12
    assert out[1] == f"monitor with: sase proc show {out[0][:6]} --follow"


def test_run_quiet_prints_only_the_proc_id(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``--quiet`` is the scriptable form."""
    assert dispatch(["proc", "run", "-q", "-c", str(tmp_path), "--", *NOOP]) == 0

    assert len(capsys.readouterr().out.strip()) == 12


def test_run_json_emits_the_created_proc(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``--json`` describes the submitted proc with its label and tags."""
    exit_code = dispatch(
        [
            "proc",
            "run",
            "-j",
            "-l",
            "Nightly",
            "-t",
            "docs",
            "-c",
            str(tmp_path),
            "--",
            *NOOP,
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["proc"]["label"] == "Nightly"
    assert payload["proc"]["tags"] == ["docs"]
    assert payload["proc"]["origin"] == "cli"


def test_run_derives_a_label_from_the_command(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Without ``--label`` the command itself names the proc."""
    dispatch(["proc", "run", "-j", "-c", str(tmp_path), "--", "echo", "hi"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["proc"]["label"] == "echo hi"


def test_run_truncates_a_very_long_derived_label(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A derived label stays short enough to render in one table column."""
    dispatch(["proc", "run", "-j", "-c", str(tmp_path), "--", "echo", "x" * 200])

    label = json.loads(capsys.readouterr().out)["proc"]["label"]
    assert len(label) == 72
    assert label.endswith("\u2026")


def test_run_rejects_a_missing_working_directory(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A bad ``--cwd`` fails before anything is spawned."""
    missing = tmp_path / "nope"

    assert dispatch(["proc", "run", "-c", str(missing), "--", "true"]) == 1

    assert "is not an existing directory" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("script", "expected"),
    [("raise SystemExit(0)", 0), ("raise SystemExit(3)", 3)],
)
def test_run_wait_streams_output_and_propagates_the_exit_code(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    script: str,
    expected: int,
) -> None:
    """``--wait`` mirrors the proc's output and its exit status."""
    exit_code = dispatch(
        [
            "proc",
            "run",
            "-w",
            "-c",
            str(tmp_path),
            "--",
            sys.executable,
            "-c",
            f"print('streamed', flush=True); {script}",
        ]
    )

    assert exit_code == expected
    assert "streamed" in capsys.readouterr().out


def test_run_wait_reports_a_signalled_command_like_a_shell(
    tmp_path: Path,
) -> None:
    """A child killed by a signal exits ``128 + N`` instead of a negative code."""
    exit_code = dispatch(
        [
            "proc",
            "run",
            "-w",
            "-c",
            str(tmp_path),
            "--",
            sys.executable,
            "-c",
            "import os, signal; os.kill(os.getpid(), signal.SIGTERM)",
        ]
    )

    assert exit_code == 128 + 15


def test_run_wait_json_keeps_stdout_parseable(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``--json --wait`` streams the log to stderr and finishes on stdout."""
    exit_code = dispatch(
        [
            "proc",
            "run",
            "-j",
            "-w",
            "-c",
            str(tmp_path),
            "--",
            sys.executable,
            "-c",
            "print('streamed', flush=True)",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "streamed" in captured.err
    assert json.loads(captured.out)["proc"]["status"] == "success"


def test_run_wait_json_quiet_still_emits_only_the_envelope(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``--quiet`` must not prepend a bare ID to ``--json --wait`` output."""
    exit_code = dispatch(
        ["proc", "run", "-j", "-w", "-q", "-c", str(tmp_path), "--", *NOOP]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["proc"]["status"] == "success"


def test_run_attributes_the_proc_to_the_resolved_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """With no explicit reference a proc lands in the newest live session."""
    identity = SessionIdentity(
        session_id="20260725T120000Z-99",
        kind="ace",
        pid=os.getpid(),
        started_at="2026-07-25T12:00:00Z",
        project="sase",
        workspace_num=16,
    )
    use_sessions(monkeypatch, [identity])

    dispatch(["proc", "run", "-j", "-c", str(tmp_path), "--", *NOOP])

    payload = json.loads(capsys.readouterr().out)
    assert payload["proc"]["session_id"] == identity.session_id
    assert payload["proc"]["session_label"] == "ace\u00b7sase#16"
    assert payload["proc"]["session_live"] is True


def test_run_session_none_leaves_the_proc_unattributed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--session none`` opts out of session attribution entirely."""
    identity = SessionIdentity(
        session_id="20260725T120000Z-99",
        kind="ace",
        pid=os.getpid(),
        started_at="2026-07-25T12:00:00Z",
    )
    use_sessions(monkeypatch, [identity])

    dispatch(["proc", "run", "-j", "-s", "none", "-c", str(tmp_path), "--", *NOOP])

    assert json.loads(capsys.readouterr().out)["proc"]["session_id"] is None


def test_run_detached_creates_a_global_detached_kind(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--detached`` uses first-class global ownership, not session-none command."""
    identity = SessionIdentity(
        session_id="20260725T120000Z-99",
        kind="ace",
        pid=os.getpid(),
        started_at="2026-07-25T12:00:00Z",
    )
    use_sessions(monkeypatch, [identity])

    assert (
        dispatch(
            [
                "proc",
                "run",
                "--detached",
                "--json",
                "--cwd",
                str(tmp_path),
                "--",
                *NOOP,
            ]
        )
        == 0
    )

    proc = json.loads(capsys.readouterr().out)["proc"]
    assert proc["kind"] == "detached"
    assert proc["detached"] is True
    assert proc["session_id"] is None
    assert proc["session_label"] is None
