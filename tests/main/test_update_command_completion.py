"""Both-states tests for the flagged completion refresh on ``sase update``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.completion.install import CompletionRefreshReport, RefreshShellOutcome
from sase.feature_flags import FeatureFlag, current_flags, override_flags
from sase.main.update_handler import handle_update_command
from sase.uv_tool.runner import parse_uv_output
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


def test_update_skips_refresh_when_flag_disabled(tmp_path: Path) -> None:
    calls: list[int] = []

    def _refresh() -> CompletionRefreshReport:
        calls.append(1)
        return _refresh_ok()

    out = _console()
    with override_flags(completion_refresh_on_update=False):
        assert (
            current_flags().enabled(FeatureFlag.completion_refresh_on_update) is False
        )
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
    assert calls == []
    assert "Refreshing installed shell completions" not in _text(out)


def test_update_refreshes_when_flag_enabled(tmp_path: Path) -> None:
    calls: list[int] = []

    def _refresh() -> CompletionRefreshReport:
        calls.append(1)
        return _refresh_ok()

    out = _console()
    with override_flags(completion_refresh_on_update=True):
        assert current_flags().enabled(FeatureFlag.completion_refresh_on_update) is True
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

    with override_flags(completion_refresh_on_update=True):
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
