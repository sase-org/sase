"""Usage-error tests for the ``sase monitor start`` handler."""

from __future__ import annotations

import sys

import pytest

from tests.main.monitor_handler_helpers import dispatch, monitor_home

__all__ = ["monitor_home"]


def test_start_reaches_the_handler_through_the_real_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A real ``sase monitor start`` invocation dispatches through ``entry.main()``.

    ``-c/--command``'s default dest is ``command``, which collides with the
    root parser's ``dest="command"`` used for top-level routing -- calling
    the handler directly (as ``dispatch()`` does) can't catch that, since it
    skips ``entry.py``'s ``if args.command == "monitor":`` check entirely.
    """
    from sase.main import entry

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sase",
            "monitor",
            "start",
            "-c",
            "true",
            "-r",
            "verify",
            "-t",
            "30s",
            "-s",
            "TESTING",
            "-S",
            "TESTED",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        entry.main()

    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "Unknown command" not in err
    assert "SASE_AGENT_NAME is unset" in err


def test_start_requires_a_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An omitted command remainder is a usage error."""
    assert dispatch(["monitor", "start", "-a", "acme"]) == 2
    assert "command is required" in capsys.readouterr().err


def test_start_requires_agent_when_none_is_given_or_inferable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No ``-a/--agent`` and no ``SASE_AGENT_NAME`` is a usage error."""
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-r",
                "verify",
                "-t",
                "30s",
                "-s",
                "TESTING",
                "-S",
                "TESTED",
            ]
        )
        == 2
    )
    assert "SASE_AGENT_NAME is unset" in capsys.readouterr().err


def test_start_rejects_an_empty_reason(capsys: pytest.CaptureFixture[str]) -> None:
    """An empty ``-r/--reason`` is rejected before touching the engine."""
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-r",
                "  ",
                "-t",
                "30s",
                "-a",
                "acme",
                "-s",
                "TESTING",
                "-S",
                "TESTED",
            ]
        )
        == 2
    )
    assert "-r/--reason must not be empty" in capsys.readouterr().err


def test_start_rejects_an_invalid_timeout(capsys: pytest.CaptureFixture[str]) -> None:
    """A malformed ``-t/--timeout`` is rejected with a helpful message."""
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-r",
                "verify",
                "-t",
                "banana",
                "-a",
                "acme",
                "-s",
                "TESTING",
                "-S",
                "TESTED",
            ]
        )
        == 2
    )
    assert "invalid -t/--timeout value" in capsys.readouterr().err


def test_start_rejects_an_invalid_idle_timeout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A malformed ``-i/--idle-timeout`` is rejected with a helpful message."""
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-r",
                "verify",
                "-t",
                "30s",
                "-i",
                "banana",
                "-a",
                "acme",
                "-s",
                "TESTING",
                "-S",
                "TESTED",
            ]
        )
        == 2
    )
    assert "invalid -i/--idle-timeout value" in capsys.readouterr().err


def test_start_requires_start_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An omitted ``-s/--start-status`` is a usage error that names the pair."""
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-r",
                "verify",
                "-t",
                "30s",
                "-a",
                "acme",
                "-S",
                "TESTED",
            ]
        )
        == 2
    )
    err = capsys.readouterr().err
    assert "-s/--start-status is required" in err
    assert "TESTING" in err
    assert "TESTED" in err
    assert "Max 20 characters" in err


def test_start_requires_stop_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An omitted ``-S/--stop-status`` is a usage error that names the pair."""
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-r",
                "verify",
                "-t",
                "30s",
                "-a",
                "acme",
                "-s",
                "TESTING",
            ]
        )
        == 2
    )
    err = capsys.readouterr().err
    assert "-S/--stop-status is required" in err
    assert "TESTING" in err
    assert "TESTED" in err
    assert "Max 20 characters" in err


def test_start_requires_both_status_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Omitting both status flags reports the start-status teaching text first."""
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-r",
                "verify",
                "-t",
                "30s",
                "-a",
                "acme",
            ]
        )
        == 2
    )
    err = capsys.readouterr().err
    assert "-s/--start-status is required" in err
    assert "pair it with -S/--stop-status" in err


def test_start_rejects_empty_and_multiline_status_labels(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Empty and multi-line status labels are usage errors, not silent defaults."""
    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-r",
                "verify",
                "-t",
                "30s",
                "-a",
                "acme",
                "-s",
                "   ",
                "-S",
                "TESTED",
            ]
        )
        == 2
    )
    assert "-s/--start-status" in capsys.readouterr().err

    assert (
        dispatch(
            [
                "monitor",
                "start",
                "-c",
                "true",
                "-r",
                "verify",
                "-t",
                "30s",
                "-a",
                "acme",
                "-s",
                "TESTING",
                "-S",
                "TEST\nED",
            ]
        )
        == 2
    )
    assert "-S/--stop-status" in capsys.readouterr().err
