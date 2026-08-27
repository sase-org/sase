"""Coverage for reusable terminal pager behavior."""

from __future__ import annotations

import io
import os
import signal
import subprocess
from collections.abc import Iterator

import pytest

from sase import cli_pager
from sase.cli_pager import PagerMode, page_or_print
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection


class _Stream:
    def __init__(self, *, tty: bool = False) -> None:
        self.tty = tty
        self.text = ""

    def isatty(self) -> bool:
        return self.tty

    def write(self, text: str) -> int:
        self.text += text
        return len(text)

    def flush(self) -> None:
        return None


class _Process:
    def __init__(self, *, returncode: int = 0, broken_pipe: bool = False) -> None:
        self.stdin = _BrokenPipeStdin() if broken_pipe else io.StringIO()
        self.returncode = returncode

    def wait(self) -> int:
        return self.returncode


class _BrokenPipeStdin:
    def write(self, _text: str) -> int:
        raise BrokenPipeError

    def close(self) -> None:
        raise BrokenPipeError


@pytest.fixture(autouse=True)
def clean_pager_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ("SASE_PAGER", "PAGER", "LESS", "TERM", "SASE_AGENT"):
        monkeypatch.delenv(name, raising=False)
    yield


def _streams(monkeypatch: pytest.MonkeyPatch, *, tty: bool) -> tuple[_Stream, _Stream]:
    stdout = _Stream(tty=tty)
    stderr = _Stream()
    monkeypatch.setattr(cli_pager.sys, "stdout", stdout)
    monkeypatch.setattr(cli_pager.sys, "stderr", stderr)
    return stdout, stderr


def _terminal(monkeypatch: pytest.MonkeyPatch, *, tty: bool = True) -> _Stream:
    stdout, _stderr = _streams(monkeypatch, tty=tty)
    monkeypatch.setenv("TERM", "xterm-256color")
    return stdout


def _capture_popen(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    broken_pipe: bool = False,
) -> list[tuple[list[str], dict[str, object]]]:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(argv: list[str], **kwargs: object) -> _Process:
        calls.append((argv, kwargs))
        return _Process(returncode=returncode, broken_pipe=broken_pipe)

    monkeypatch.setattr(cli_pager.subprocess, "Popen", fake_popen)
    return calls


def test_resolve_pager_argv_respects_env_order_and_splitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_PAGER", "less -S")
    monkeypatch.setenv("PAGER", "less -X")
    monkeypatch.setattr(cli_pager.shutil, "which", lambda _name: "/bin/less")
    assert cli_pager._resolve_pager_argv() == ["less", "-S"]

    monkeypatch.delenv("SASE_PAGER")
    assert cli_pager._resolve_pager_argv() == ["less", "-X"]

    monkeypatch.delenv("PAGER")
    assert cli_pager._resolve_pager_argv() == ["/bin/less"]


def test_empty_env_pager_disables_paging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_PAGER", " ")
    monkeypatch.setenv("PAGER", "less")
    monkeypatch.setattr(cli_pager.shutil, "which", lambda _name: "/bin/less")
    assert cli_pager._resolve_pager_argv() is None


def test_less_options_and_default_less_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _terminal(monkeypatch)
    monkeypatch.setenv("PAGER", "less -S")
    calls = _capture_popen(monkeypatch)

    page_or_print("short\n", mode=PagerMode.ALWAYS)

    argv, kwargs = calls[0]
    assert argv == ["less", "-S", "-R"]
    assert kwargs["env"]["LESS"] == "RX"  # type: ignore[index]


def test_auto_adds_quit_if_one_screen_and_does_not_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _terminal(monkeypatch)
    monkeypatch.setenv("PAGER", "less -RF")
    monkeypatch.setattr(
        cli_pager.shutil,
        "get_terminal_size",
        lambda fallback: os.terminal_size((10, 2)),
    )
    calls = _capture_popen(monkeypatch)

    page_or_print("one\ntwo\nthree\n", mode=PagerMode.AUTO)

    argv, kwargs = calls[0]
    assert argv == ["less", "-RF"]
    assert kwargs["env"]["LESS"] == "FRX"  # type: ignore[index]


@pytest.mark.parametrize(
    ("tty", "term", "agent", "text", "expected"),
    [
        (False, "xterm", False, "long\nlong\n", "long\nlong\n"),
        (True, None, False, "long\nlong\n", "long\nlong\n"),
        (True, "dumb", False, "long\nlong\n", "long\nlong\n"),
        (True, "xterm", True, "long\nlong\n", "long\nlong\n"),
        (True, "xterm", False, "fits\n", "fits\n"),
    ],
)
def test_auto_writes_direct_when_paging_conditions_fail(
    monkeypatch: pytest.MonkeyPatch,
    tty: bool,
    term: str | None,
    agent: bool,
    text: str,
    expected: str,
) -> None:
    stdout, _stderr = _streams(monkeypatch, tty=tty)
    if term is not None:
        monkeypatch.setenv("TERM", term)
    if agent:
        monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("PAGER", "less")
    monkeypatch.setattr(
        cli_pager.shutil,
        "get_terminal_size",
        lambda fallback: os.terminal_size((80, 24)),
    )
    calls = _capture_popen(monkeypatch)

    page_or_print(text, mode=PagerMode.AUTO)

    assert calls == []
    assert stdout.text == expected


def test_auto_pages_when_text_is_taller_than_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = _terminal(monkeypatch)
    monkeypatch.setenv("PAGER", "less")
    monkeypatch.setattr(
        cli_pager.shutil,
        "get_terminal_size",
        lambda fallback: os.terminal_size((10, 2)),
    )
    calls = _capture_popen(monkeypatch)

    page_or_print("one\ntwo\nthree\n", mode=PagerMode.AUTO)

    assert calls
    assert stdout.text == ""


def test_always_pages_fitting_text_but_not_redirected_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = _terminal(monkeypatch)
    monkeypatch.setenv("PAGER", "less")
    calls = _capture_popen(monkeypatch)

    page_or_print("fits\n", mode=PagerMode.ALWAYS)
    assert calls
    assert stdout.text == ""

    redirected, _stderr = _streams(monkeypatch, tty=False)
    page_or_print("fits\n", mode=PagerMode.ALWAYS)
    assert redirected.text == "fits\n"


def test_always_warns_once_when_no_pager_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout, stderr = _streams(monkeypatch, tty=True)
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(cli_pager.shutil, "which", lambda _name: None)

    page_or_print("body\n", mode=PagerMode.ALWAYS)

    assert stdout.text == "body\n"
    assert stderr.text == "warning: no pager configured or found; writing directly\n"


def test_auto_silent_when_no_pager_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    stdout, stderr = _streams(monkeypatch, tty=True)
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(cli_pager.shutil, "which", lambda _name: None)

    page_or_print("long\nlong\n", mode=PagerMode.AUTO)

    assert stdout.text == "long\nlong\n"
    assert stderr.text == ""


def test_row_estimate_strips_sgr_and_counts_wrapped_cells() -> None:
    assert cli_pager._estimated_display_rows("\x1b[31mabcd\x1b[0m", columns=2) == 2
    assert cli_pager._estimated_display_rows("abcdef", columns=3) == 2


def test_broken_pipe_and_nonzero_pager_exit_do_not_dump_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = _terminal(monkeypatch)
    monkeypatch.setenv("PAGER", "less")
    _capture_popen(monkeypatch, broken_pipe=True)
    page_or_print("body\n", mode=PagerMode.ALWAYS)
    assert stdout.text == ""

    stdout = _terminal(monkeypatch)
    _capture_popen(monkeypatch, returncode=1)
    page_or_print("body\n", mode=PagerMode.ALWAYS)
    assert stdout.text == ""


def test_oserror_starting_pager_falls_back_to_direct_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = _terminal(monkeypatch)
    monkeypatch.setenv("PAGER", "less")

    def fail_popen(_argv: list[str], **_kwargs: object) -> _Process:
        raise OSError("missing")

    monkeypatch.setattr(cli_pager.subprocess, "Popen", fail_popen)

    page_or_print("body\n", mode=PagerMode.ALWAYS)

    assert stdout.text == "body\n"


def test_sase_pager_env_runs_in_process_when_flag_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _terminal(monkeypatch)
    monkeypatch.setenv("SASE_PAGER", "sase pager")
    monkeypatch.setattr(cli_pager, "_link_pager_enabled", lambda: True)
    document = PagerDocument(
        sections=(
            PagerSection(
                identity="bead:sase-1",
                title="sase-1",
                kind="bead",
                body="body\n",
            ),
        ),
        title="sase-1",
        origin=PagerOrigin.BEAD,
    )
    calls: list[tuple[str, PagerDocument | None]] = []

    def fake_run_sase_pager(text: str, *, document: PagerDocument | None) -> None:
        calls.append((text, document))

    def fail_popen(_argv: list[str], **_kwargs: object) -> _Process:
        raise AssertionError("sase pager should run in-process")

    monkeypatch.setattr(cli_pager, "_run_sase_pager", fake_run_sase_pager)
    monkeypatch.setattr(cli_pager.subprocess, "Popen", fail_popen)

    page_or_print("body\n", mode=PagerMode.ALWAYS, document=document)

    assert calls == [("body\n", document)]


def test_sase_pager_startup_failure_falls_back_to_direct_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = _terminal(monkeypatch)
    monkeypatch.setenv("SASE_PAGER", "sase pager")
    monkeypatch.setattr(cli_pager, "_link_pager_enabled", lambda: True)

    def fail_run_sase_pager(_text: str, *, document: PagerDocument | None) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_pager, "_run_sase_pager", fail_run_sase_pager)

    page_or_print("body\n", mode=PagerMode.ALWAYS)

    assert stdout.text == "body\n"


def test_sase_pager_subprocess_env_does_not_recurse_when_flag_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _terminal(monkeypatch)
    monkeypatch.setenv("SASE_PAGER", "sase pager")
    monkeypatch.setattr(cli_pager, "_link_pager_enabled", lambda: False)
    calls = _capture_popen(monkeypatch)

    page_or_print("body\n", mode=PagerMode.ALWAYS)

    argv, kwargs = calls[0]
    assert argv == ["sase", "pager"]
    assert "SASE_PAGER" not in kwargs["env"]  # type: ignore[operator]


@pytest.mark.parametrize("raises", [False, True])
def test_sigint_handler_is_restored(
    monkeypatch: pytest.MonkeyPatch,
    raises: bool,
) -> None:
    _terminal(monkeypatch)
    monkeypatch.setenv("PAGER", "less")
    calls: list[object] = []

    def fake_signal(_sig: signal.Signals, handler: object) -> object:
        calls.append(handler)
        return "previous"

    def fake_popen(_argv: list[str], **_kwargs: object) -> _Process:
        if raises:
            raise OSError("missing")
        return _Process()

    monkeypatch.setattr(cli_pager.signal, "signal", fake_signal)
    monkeypatch.setattr(cli_pager.subprocess, "Popen", fake_popen)

    page_or_print("body\n", mode=PagerMode.ALWAYS)

    assert calls == [signal.SIG_IGN, "previous"]
