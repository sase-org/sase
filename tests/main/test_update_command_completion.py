"""Tests for the unconditional completion refresh on ``sase update``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.completion.install import CompletionRefreshReport, RefreshShellOutcome
from sase.main.update_handler import handle_update_command
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet, parse_uv_output
from tests.main.update_command_helpers import (
    _UPGRADE_OUTPUT,
    _args,
    _console,
    _install,
    _text,
    _versions,
)


def _refresh_ok() -> CompletionRefreshReport:
    return CompletionRefreshReport(
        attempted=True,
        outcomes=(
            RefreshShellOutcome(
                shell="zsh",
                ok=True,
                detail="refreshed /tmp/_sase",
                target="/tmp/_sase",
            ),
        ),
    )


def test_update_skips_refresh_on_dry_run(tmp_path: Path) -> None:
    calls: list[int] = []

    def _refresh() -> CompletionRefreshReport:
        calls.append(1)
        return _refresh_ok()

    out = _console()
    code = handle_update_command(
        _args(dry_run=True),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        refresh_completions_fn=_refresh,
    )

    assert code == 0
    assert calls == []
    assert "Refreshing installed shell completions" not in _text(out)


def test_update_skips_refresh_when_upgrade_fails(tmp_path: Path) -> None:
    calls: list[int] = []

    def _refresh() -> CompletionRefreshReport:
        calls.append(1)
        return _refresh_ok()

    def _run(argv: list[str]) -> UvChangeSet:
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="No solution found")

    err = _console()
    code = handle_update_command(
        _args(),
        console=_console(),
        err_console=err,
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        refresh_completions_fn=_refresh,
    )

    assert code == 1
    assert calls == []
    assert "Refreshing installed shell completions" not in _text(err)


def test_update_refreshes_completions_after_success(tmp_path: Path) -> None:
    calls: list[int] = []

    def _refresh() -> CompletionRefreshReport:
        calls.append(1)
        return _refresh_ok()

    out = _console()
    code = handle_update_command(
        _args(),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        refresh_completions_fn=_refresh,
    )

    assert code == 0
    assert calls == [1]
    text = _text(out)
    assert "Refreshing installed shell completions" in text
    assert "refreshed /tmp/_sase" in text


def test_update_refresh_failure_is_not_fatal(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom() -> CompletionRefreshReport:
        raise RuntimeError("zcompile exploded")

    code = handle_update_command(
        _args(json=True),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        refresh_completions_fn=_boom,
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] is True
    refresh = payload["completion_refresh"]
    assert refresh["attempted"] is True
    assert refresh["shells"][0]["ok"] is False
    assert "zcompile exploded" in refresh["shells"][0]["detail"]


def test_update_default_refresh_runs_installed_child_process(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install = _install(tmp_path)
    executable = install.sase_dir / "bin" / "sase"
    marker = tmp_path / "child-ran"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text(' '.join(sys.argv[1:]))\n"
        "print(json.dumps({'attempted': True, 'shells': ["
        "{'shell': 'zsh', 'ok': True, 'detail': 'child refreshed', "
        "'target': '/tmp/_sase'}]}))\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    code = handle_update_command(
        _args(json=True),
        probe_fn=lambda: install,
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert marker.read_text(encoding="utf-8") == "completion refresh --json"
    payload = json.loads(capsys.readouterr().out)
    refresh = payload["completion_refresh"]
    assert refresh["shells"] == [
        {
            "detail": "child refreshed",
            "ok": True,
            "shell": "zsh",
            "target": "/tmp/_sase",
        }
    ]


def test_update_default_refresh_reports_malformed_child_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install = _install(tmp_path)
    executable = install.sase_dir / "bin" / "sase"
    executable.write_text(
        "#!/usr/bin/env python3\nprint('not json')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    code = handle_update_command(
        _args(json=True),
        probe_fn=lambda: install,
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    refresh = payload["completion_refresh"]
    assert refresh["shells"][0]["ok"] is False
    assert "malformed JSON" in refresh["shells"][0]["detail"]
