from __future__ import annotations

from pathlib import Path

from sase.doctor import checks_tools
from sase.doctor.runner import DoctorContext


def _context(env: dict[str, str]) -> DoctorContext:
    return DoctorContext(
        cwd=Path("/repo"),
        project=None,
        sase_home=Path("/home/user/.sase"),
        env=env,
    )


def test_editor_check_ok_for_visual_command_with_args(monkeypatch) -> None:
    monkeypatch.setattr(
        checks_tools.shutil,
        "which",
        lambda command: "/usr/bin/code" if command == "code" else None,
    )

    check = checks_tools._check_editor(_context({"VISUAL": "code --wait"}))

    assert check.status == "OK"
    assert check.summary == "$VISUAL resolves to code"
    assert check.data["command"] == ("code", "--wait")
    assert check.data["resolution_status"] == "resolved"


def test_editor_check_warns_for_missing_configured_head(monkeypatch) -> None:
    monkeypatch.setattr(checks_tools.shutil, "which", lambda _command: None)

    check = checks_tools._check_editor(_context({"EDITOR": "missing-editor --wait"}))

    assert check.status == "WARN"
    assert check.summary == "$EDITOR command head was not found: missing-editor"
    assert check.next_steps == (
        "Install `missing-editor` or update $EDITOR to an executable editor command.",
    )
    assert check.data["resolution_status"] == "missing"


def test_editor_check_warns_for_shell_style_config(monkeypatch) -> None:
    monkeypatch.setattr(checks_tools.shutil, "which", lambda _command: None)

    check = checks_tools._check_editor(_context({"EDITOR": "$HOME/bin/editor --wait"}))

    assert check.status == "WARN"
    assert check.summary == (
        "$EDITOR is a shell-style command that doctor cannot verify"
    )
    assert check.data["resolution_status"] == "unverified_shell"


def test_editor_check_warns_when_no_editor_resolves(monkeypatch) -> None:
    monkeypatch.setattr(checks_tools.shutil, "which", lambda _command: None)

    check = checks_tools._check_editor(_context({}))

    assert check.status == "WARN"
    assert check.summary == "fallback editor command head was not found: vim"
    assert check.next_steps == ("Install `nvim` or `vim`, or set $VISUAL/$EDITOR.",)


def test_optional_tools_include_mpv_for_video_artifact_playback(monkeypatch) -> None:
    monkeypatch.setattr(checks_tools.shutil, "which", lambda _tool: None)

    check = checks_tools._check_optional_tools()

    rows = {row["id"]: row for row in check.data["tools"]}
    assert "tmux" not in rows
    assert rows["mpv"]["commands"] == ("mpv",)
    assert rows["mpv"]["feature"] == "terminal video artifact playback"
    assert "terminal video artifact playback: install mpv" in check.details
