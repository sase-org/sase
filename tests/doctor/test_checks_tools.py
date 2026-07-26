"""Tests for doctor tool checks."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.doctor import checks_tools
from sase.doctor.runner import DoctorContext


def _context(env: dict[str, str] | None = None) -> DoctorContext:
    return DoctorContext(
        cwd=Path("/repo"),
        project=None,
        sase_home=Path("/home/user/.sase"),
        env={} if env is None else env,
    )


def test_tmux_check_warns_without_blocking_agent_runtime(monkeypatch) -> None:
    monkeypatch.setattr(checks_tools.shutil, "which", lambda _command: None)

    check = checks_tools._check_tmux()

    assert check.status == "WARN"
    assert "`sase ace --tmux` exits with code 2" in check.details[0]
    assert check.next_steps == ("Install `tmux` or run ACE without `--tmux`.",)
    assert check.data["required_for_agents"] is False


def test_tmux_check_ok_when_command_resolves(monkeypatch) -> None:
    monkeypatch.setattr(checks_tools.shutil, "which", lambda _command: "/usr/bin/tmux")

    check = checks_tools._check_tmux()

    assert check.status == "OK"
    assert check.data["resolved_path"] == "/usr/bin/tmux"


def test_clipboard_check_warns_with_wayland_next_step(monkeypatch) -> None:
    monkeypatch.setattr(
        checks_tools,
        "clipboard_available",
        lambda **_kwargs: False,
    )

    check = checks_tools._check_clipboard(
        _context({"WAYLAND_DISPLAY": "wayland-0"}),
        platform="linux",
    )

    assert check.status == "WARN"
    assert check.summary == "no Linux clipboard helper is available"
    assert check.next_steps == ("Install `wl-clipboard` for the `wl-copy` command.",)
    assert check.data["command_heads"] == ("wl-copy",)


def test_clipboard_check_warns_with_linux_fallback_next_steps(monkeypatch) -> None:
    monkeypatch.setattr(
        checks_tools,
        "clipboard_available",
        lambda **_kwargs: False,
    )

    check = checks_tools._check_clipboard(_context({}), platform="linux")

    assert check.status == "WARN"
    assert check.next_steps == (
        "Install `wl-clipboard`, `xclip`, or `xsel`, and ensure WAYLAND_DISPLAY or DISPLAY is set for graphical clipboard sessions.",
    )
    assert check.data["command_heads"] == ("wl-copy", "xclip", "xsel")


def test_clipboard_check_warns_with_macos_next_step(monkeypatch) -> None:
    monkeypatch.setattr(
        checks_tools,
        "clipboard_available",
        lambda **_kwargs: False,
    )

    check = checks_tools._check_clipboard(_context({}), platform="darwin")

    assert check.status == "WARN"
    assert check.next_steps == ("Ensure `pbcopy` is available on PATH.",)
    assert check.data["command_heads"] == ("pbcopy",)


def test_clipboard_check_ok_when_helper_available(monkeypatch) -> None:
    monkeypatch.setattr(
        checks_tools,
        "clipboard_available",
        lambda **_kwargs: True,
    )

    check = checks_tools._check_clipboard(_context({}), platform="darwin")

    assert check.status == "OK"
    assert check.next_steps == ()


def test_fzf_check_warns_when_command_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(checks_tools.shutil, "which", lambda _command: None)

    check = checks_tools._check_fzf()

    assert check.status == "WARN"
    assert check.summary == "fzf is not installed or not on PATH"
    assert "Prompt pickers and editor prompt history require `fzf`." in check.details
    assert check.next_steps == (
        "Install `fzf` to enable prompt pickers and prompt-history editing.",
    )
    assert check.data["resolved_path"] is None


def test_fzf_check_ok_when_command_resolves(monkeypatch) -> None:
    monkeypatch.setattr(checks_tools.shutil, "which", lambda _command: "/usr/bin/fzf")

    check = checks_tools._check_fzf()

    assert check.status == "OK"
    assert check.summary == "fzf is available for prompt pickers and prompt history"
    assert check.data["resolved_path"] == "/usr/bin/fzf"


def test_optional_tools_warns_with_affected_features(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_tools.shutil.which",
        lambda command: "/usr/bin/bat" if command == "bat" else None,
    )

    check = checks_tools._check_optional_tools()

    assert check.status == "WARN"
    assert check.title == "Optional feature tools"
    rows = {row["id"]: row for row in check.data["tools"]}
    assert "tmux" not in rows
    assert rows["bat"]["available"] is True
    assert any("terminal image artifact display" in detail for detail in check.details)
    assert rows["prettier"]["feature"] == (
        "prompt and generated skill Markdown formatting; missing Prettier can "
        "inflate skill-drift reports"
    )
    assert any(
        "missing Prettier can inflate skill-drift reports" in detail
        for detail in check.details
    )
    assert rows["dict"]["feature"] == "prompt word definitions (K on a plain word)"
    assert rows["aspell"]["feature"] == (
        "prompt spell checking and fix suggestions (K on a plain word)"
    )


def test_optional_aspell_requires_english_dictionary(monkeypatch) -> None:
    monkeypatch.setattr(
        checks_tools.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "aspell" else None,
    )
    monkeypatch.setattr(
        checks_tools.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="de\nfr\n",
            stderr="",
        ),
    )

    check = checks_tools._check_optional_tools()

    rows = {row["id"]: row for row in check.data["tools"]}
    assert rows["aspell"]["available"] is False
    assert rows["aspell"]["english_dictionary_available"] is False
    assert rows["aspell"]["dictionaries"] == ("de", "fr")
    assert any(
        "aspell found but no English dictionary — install aspell-en" in detail
        for detail in check.details
    )


def test_optional_aspell_accepts_english_dictionary(monkeypatch) -> None:
    monkeypatch.setattr(
        checks_tools.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "aspell" else None,
    )
    monkeypatch.setattr(
        checks_tools.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="de\nen_US\nen-variant_0\n",
            stderr="",
        ),
    )

    check = checks_tools._check_optional_tools()

    rows = {row["id"]: row for row in check.data["tools"]}
    assert rows["aspell"]["available"] is True
    assert rows["aspell"]["english_dictionary_available"] is True
