"""Tests for ``sase artifact open``."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

import pytest

from sase.artifact_cli.open import handle_open
from tests.main.artifact_cli_reference_helpers import (
    artifact_file,
    resolved_reference,
)


def test_open_text_falls_back_without_bat_and_preserves_safe_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "-leading name.txt"
    path.write_text("text", encoding="utf-8")
    result = resolved_reference(path, file=artifact_file(path))
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "sase.artifact_cli.open.resolve_cli_reference",
        lambda _value: result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.subprocess.run",
        lambda command, **_kwargs: (
            commands.append(list(command)) or subprocess.CompletedProcess(command, 0)
        ),
    )

    assert handle_open(argparse.Namespace(reference=result.input)) == 0
    assert commands == [
        [
            sys.executable,
            "-m",
            "sase",
            "pager",
            "--",
            str(path.resolve()),
        ]
    ]


@pytest.mark.parametrize(
    "reference",
    [
        "bead:sase-9z",
        "agent:alice.athena.9w",
    ],
)
def test_open_entity_pages_use_text_viewer(
    tmp_path: Path,
    reference: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "README.md"
    path.write_text("# Entity\n", encoding="utf-8")
    result = resolved_reference(path, reference=reference)
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "sase.artifact_cli.open.resolve_cli_reference",
        lambda _value: result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.subprocess.run",
        lambda command, **_kwargs: (
            commands.append(list(command)) or subprocess.CompletedProcess(command, 0)
        ),
    )

    assert handle_open(argparse.Namespace(reference=reference)) == 0
    assert commands == [
        [
            sys.executable,
            "-m",
            "sase",
            "pager",
            "--",
            str(path.resolve()),
        ]
    ]


@pytest.mark.parametrize(
    ("kind", "mime_type", "suffix", "viewer"),
    [
        ("image", "image/png", ".png", "kitten"),
        ("file", "video/mp4", ".mp4", "mpv"),
        ("pdf", "application/pdf", ".pdf", "xdg-open"),
        ("file", "application/octet-stream", ".bin", "xdg-open"),
    ],
)
def test_open_selects_bounded_media_and_external_viewers(
    tmp_path: Path,
    kind: str,
    mime_type: str,
    suffix: str,
    viewer: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / f"artifact with spaces{suffix}"
    path.write_bytes(b"data")
    result = resolved_reference(
        path,
        file=artifact_file(path, kind=kind, mime_type=mime_type),
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "sase.artifact_cli.open.resolve_cli_reference",
        lambda _value: result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.shutil.which",
        lambda _command: "/usr/bin/viewer",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.subprocess.run",
        lambda command, **_kwargs: (
            commands.append(list(command)) or subprocess.CompletedProcess(command, 0)
        ),
    )

    assert handle_open(argparse.Namespace(reference=result.input)) == 0
    [command] = commands
    assert command[0] == viewer
    boundary = command.index("--")
    assert command[boundary + 1 :] == [str(path.resolve())]
    if viewer == "mpv":
        assert "--no-config" in command
    if viewer == "kitten":
        assert "--place" in command


def test_open_reports_missing_viewer_and_nonzero_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "artifact.pdf"
    result = resolved_reference(
        path,
        file=artifact_file(path, kind="pdf", mime_type="application/pdf"),
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.resolve_cli_reference",
        lambda _value: result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.shutil.which",
        lambda _command: None,
    )

    assert handle_open(argparse.Namespace(reference=result.input)) == 1
    error = capsys.readouterr().err
    assert "xdg-open" in error
    assert str(path) in error

    monkeypatch.setattr(
        "sase.artifact_cli.open.shutil.which",
        lambda _command: "/usr/bin/xdg-open",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 9),
    )
    assert handle_open(argparse.Namespace(reference=result.input)) == 1
    error = capsys.readouterr().err
    assert "exit code 9" in error
    assert str(path) in error


def test_open_bug_uses_tracker_url_and_commit_has_show_hint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bug = resolved_reference(
        None,
        reference="bug:sase#123",
        locator="gh_sase-org__sase#123",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.resolve_cli_reference",
        lambda _value: bug,
    )
    monkeypatch.setattr(
        "sase.ace.tui.external_issues.issue_url_for_number",
        lambda project, number: f"https://tracker/{project}/{number}",
    )
    opened: list[str] = []
    monkeypatch.setattr(
        "sase.artifact_cli.open.webbrowser.open",
        lambda url: opened.append(url) or True,
    )

    assert handle_open(argparse.Namespace(reference=bug.input)) == 0
    assert opened == ["https://tracker/gh_sase-org__sase/123"]

    commit = resolved_reference(
        None,
        reference="commit:sase@0123456789abcdef0123456789abcdef01234567",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.open.resolve_cli_reference",
        lambda _value: commit,
    )
    assert handle_open(argparse.Namespace(reference=commit.input)) == 2
    assert "sase artifact show" in capsys.readouterr().err
