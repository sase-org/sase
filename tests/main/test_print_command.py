"""Tests for root ``sase --print-command`` presentation and entry wiring."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import pytest

from sase.main.print_command import (
    _format_print_command,
    _quote_command_arg,
    write_print_command_header,
)


class _RecordingStream:
    encoding = "utf-8"

    def __init__(self, name: str, events: list[tuple[str, str]]) -> None:
        self.name = name
        self.events = events
        self.value = ""
        self.flushed = False

    def write(self, text: str) -> int:
        self.events.append((self.name, text))
        self.value += text
        return len(text)

    def flush(self) -> None:
        self.flushed = True
        self.events.append((self.name, "<flush>"))

    def isatty(self) -> bool:
        return False


class _TtyStream(_RecordingStream):
    def isatty(self) -> bool:
        return True


class _EncodedStream(_RecordingStream):
    def __init__(
        self, name: str, events: list[tuple[str, str]], *, encoding: str
    ) -> None:
        super().__init__(name, events)
        self.encoding = encoding

    def write(self, text: str) -> int:
        text.encode(self.encoding)
        return super().write(text)


@pytest.mark.parametrize(
    "arg",
    [
        "",
        "plain",
        "two words",
        "has'quote",
        'has"double',
        r"back\slash",
        "$dollar",
        "`ticks`",
        "*?[glob]",
        "semi;pipe|amp&",
        "snowman-\u2603",
    ],
)
def test_printable_quoting_round_trips_with_shlex(arg: str) -> None:
    assert shlex.split(_quote_command_arg(arg)) == [arg]


@pytest.mark.parametrize(
    "args",
    [
        ["", "two words", "has'quote", r"back\slash"],
        ["line\nbreak", "tab\tvalue", "carriage\rreturn", "esc\x1bvalue"],
        ["mix'\\\n\t\r\x1b", "snowman-\u2603"],
    ],
)
def test_control_character_quoting_round_trips_through_bash(
    tmp_path: Path, args: list[str]
) -> None:
    assert shutil.which("bash") is not None
    assert _shell_round_trip("bash", tmp_path, args) == args


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not on PATH")
def test_control_character_quoting_round_trips_through_zsh(tmp_path: Path) -> None:
    args = ["", "line\nbreak", "tab\tvalue", "carriage\rreturn", "esc\x1bvalue"]

    assert _shell_round_trip("zsh", tmp_path, args) == args


def test_format_print_command_keeps_header_to_one_physical_line() -> None:
    header = _format_print_command(["bead", "note", "line\n\t\r\x1b"])

    assert "\n" not in header
    assert "\t" not in header
    assert "\r" not in header
    assert "\x1b" not in header
    assert r"\n" in header
    assert r"\t" in header
    assert r"\r" in header
    assert r"\e" in header


def test_format_print_command_escapes_unencodable_text() -> None:
    assert _format_print_command(["snowman-\u2603"], encoding="ascii") == (
        r"> sase $'snowman-\u2603'"
    )


def test_write_plain_header_flushes() -> None:
    events: list[tuple[str, str]] = []
    stream = _RecordingStream("err", events)

    write_print_command_header(["bead", "show", "two words"], stream=stream)

    assert stream.value == "\u276f sase bead show 'two words'\n"
    assert stream.flushed is True
    assert events[-1] == ("err", "<flush>")


def test_write_header_styles_capable_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, str]] = []
    stream = _TtyStream("err", events)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    write_print_command_header(["bead"], stream=stream)

    assert "\x1b[2;36m\u276f\x1b[0m" in stream.value
    assert "\x1b[1msase\x1b[0m" in stream.value


@pytest.mark.parametrize(
    ("env_name", "env_value"),
    [("NO_COLOR", "1"), ("TERM", "dumb")],
)
def test_write_header_honors_color_disables(
    monkeypatch: pytest.MonkeyPatch, env_name: str, env_value: str
) -> None:
    events: list[tuple[str, str]] = []
    stream = _TtyStream("err", events)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv(env_name, env_value)

    write_print_command_header(["bead"], stream=stream)

    assert stream.value == "\u276f sase bead\n"


def test_write_header_uses_ascii_marker_and_escapes_for_ascii_stream() -> None:
    events: list[tuple[str, str]] = []
    stream = _EncodedStream("err", events, encoding="ascii")

    write_print_command_header(["snowman-\u2603"], stream=stream)

    assert stream.value == r"> sase $'snowman-\u2603'" + "\n"


def test_entry_prints_header_before_normal_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import agent_handler, entry

    events: list[tuple[str, str]] = []
    stdout = _RecordingStream("out", events)
    stderr = _RecordingStream("err", events)

    def handle_agent_command(args: object) -> NoReturn:
        del args
        print("agent stdout")
        print("agent stderr", file=sys.stderr)
        raise SystemExit(0)

    monkeypatch.setattr(agent_handler, "handle_agent_command", handle_agent_command)
    monkeypatch.setattr(sys, "argv", ["sase", "-p", "agent", "list"])
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 0
    assert events[0] == ("err", "\u276f sase agent list\n")
    assert ("out", "agent stdout") in events
    assert ("err", "agent stderr") in events


def test_entry_prints_header_before_bare_group_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import agent_handler, entry

    events: list[tuple[str, str]] = []
    stdout = _RecordingStream("out", events)
    stderr = _RecordingStream("err", events)

    def handle_agent_command(args: object) -> NoReturn:
        del args
        raise SystemExit(0)

    monkeypatch.setattr(agent_handler, "handle_agent_command", handle_agent_command)
    monkeypatch.setattr(sys, "argv", ["sase", "-p", "agent"])
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    with pytest.raises(SystemExit):
        entry.main()

    notice = "No subcommand provided for 'sase agent'; delegating to 'sase agent list'."
    assert events[0] == ("err", "\u276f sase agent\n")
    assert ("out", notice) in events


def test_entry_prints_header_before_bead_fast_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import bead_fast_path, entry

    events: list[tuple[str, str]] = []
    stdout = _RecordingStream("out", events)
    stderr = _RecordingStream("err", events)

    def try_handle_bead_fast_path(argv: list[str]) -> int:
        assert argv == ["dep", "list"]
        sys.stdout.write("bead stdout\n")
        sys.stderr.write("bead stderr\n")
        return 0

    monkeypatch.setattr(
        bead_fast_path, "try_handle_bead_fast_path", try_handle_bead_fast_path
    )
    monkeypatch.setattr(sys, "argv", ["sase", "-p", "bead", "dep", "list"])
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 0
    assert events[0] == ("err", "\u276f sase bead dep list\n")
    assert ("out", "bead stdout\n") in events
    assert ("err", "bead stderr\n") in events


def test_entry_prints_header_before_completion_fast_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import completion_fast_path, entry

    events: list[tuple[str, str]] = []
    stdout = _RecordingStream("out", events)
    stderr = _RecordingStream("err", events)

    def try_handle_completion_candidates(argv: list[str]) -> int:
        assert argv == ["bead", "-p", "sase"]
        sys.stdout.write("candidate\n")
        return 0

    monkeypatch.setattr(
        completion_fast_path,
        "try_handle_completion_candidates",
        try_handle_completion_candidates,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["sase", "-p", "completion", "candidates", "bead", "-p", "sase"],
    )
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 0
    assert events[0] == ("err", "\u276f sase completion candidates bead -p sase\n")
    assert ("out", "candidate\n") in events


def test_entry_prints_header_before_run_special_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import entry, query_handler

    events: list[tuple[str, str]] = []
    stderr = _RecordingStream("err", events)

    def handle_run_special_cases(argv: list[str]) -> NoReturn:
        assert argv == ["#demo"]
        sys.stderr.write("run stderr\n")
        raise SystemExit(7)

    monkeypatch.setattr(
        query_handler, "handle_run_special_cases", handle_run_special_cases
    )
    monkeypatch.setattr(sys, "argv", ["sase", "--print-command", "run", "#demo"])
    monkeypatch.setattr(sys, "stderr", stderr)

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 7
    assert events[0] == ("err", "\u276f sase run '#demo'\n")
    assert ("err", "run stderr\n") in events


def test_entry_prints_before_feature_flag_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import entry

    events: list[tuple[str, str]] = []
    stderr = _RecordingStream("err", events)
    monkeypatch.setattr(sys, "argv", ["sase", "-p", "-f", "bogus", "flag", "list"])
    monkeypatch.setattr(sys, "stderr", stderr)

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 2
    assert events[0] == ("err", "\u276f sase -f bogus flag list\n")
    assert "unknown feature flag 'bogus'" in stderr.value


def test_entry_rejects_invalid_print_option_before_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import entry

    events: list[tuple[str, str]] = []
    stderr = _RecordingStream("err", events)
    monkeypatch.setattr(sys, "argv", ["sase", "--print-command=yes", "bead"])
    monkeypatch.setattr(sys, "stderr", stderr)

    with pytest.raises(SystemExit) as exc:
        entry.main()

    assert exc.value.code == 2
    assert "\u276f" not in stderr.value
    assert "ignored explicit argument 'yes'" in stderr.value


def test_second_entry_call_without_print_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import agent_handler, entry

    events: list[tuple[str, str]] = []
    stderr = _RecordingStream("err", events)

    def handle_agent_command(args: object) -> NoReturn:
        del args
        raise SystemExit(0)

    monkeypatch.setattr(agent_handler, "handle_agent_command", handle_agent_command)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "argv", ["sase", "-p", "agent", "list"])
    with pytest.raises(SystemExit):
        entry.main()

    monkeypatch.setattr(sys, "argv", ["sase", "agent", "list"])
    with pytest.raises(SystemExit):
        entry.main()

    assert stderr.value == "\u276f sase agent list\n"


def _shell_round_trip(shell: str, tmp_path: Path, args: list[str]) -> list[str]:
    reporter = tmp_path / "argv_report.py"
    reporter.write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    rendered_args = " ".join(_quote_command_arg(arg) for arg in args)
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(reporter))}"
    if rendered_args:
        command = f"{command} {rendered_args}"
    result = subprocess.run(
        [shell, "-c", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)
