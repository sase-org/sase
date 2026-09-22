"""Command-wiring tests for the live timeline in ``sase update`` (bead sase-158.4).

Split from ``test_update_command_live_timeline.py``: parser flags, module
preloading, JSON/quiet output modes, and the default session factory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import sase.main.update_handler_live as live_handler
from sase.main.parser import create_parser
from sase.main.update_handler import handle_update_command
from sase.update_progress import UpdateProgressSession
from sase.uv_tool.runner import parse_uv_output
from tests.main.update_command_helpers import (
    _UPGRADE_OUTPUT,
    _args,
    _console,
    _install,
    _text,
    _versions,
)

_SELF_UPDATE_MODULES = (
    "sase.update_progress.session",
    "sase.update_progress.render_live",
    "sase.update_progress.render_plain",
    "sase.main.update_render",
    "sase.main.update_restart",
    "rich.live",
    "rich.spinner",
)


def _session_factory(err: Console, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Build an injectable session factory writing its log under tmp_path."""

    def _factory(**kwargs: Any) -> UpdateProgressSession:
        kwargs.pop("err", None)
        return UpdateProgressSession(err, log_dir=tmp_path, clock=lambda: 0.0, **kwargs)

    return _factory


def test_verbose_flag_parses_short_and_long() -> None:
    short = create_parser().parse_args(["update", "-v"])
    long = create_parser().parse_args(["update", "--verbose"])

    assert short.verbose is True
    assert long.verbose is True


def test_self_update_modules_preloaded() -> None:
    import sys

    import sase.main.update_handler  # noqa: F401 - import populates sys.modules.

    for name in _SELF_UPDATE_MODULES:
        assert name in sys.modules, f"{name} must be preloaded before the code swap"


def test_live_json_includes_log_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    factory_runs: list[dict[str, Any]] = []

    def _factory(**kwargs: Any) -> UpdateProgressSession:
        factory_runs.append(dict(kwargs))
        kwargs.pop("err", None)
        return UpdateProgressSession(
            Console(stderr=True), log_dir=tmp_path, clock=lambda: 0.0, **kwargs
        )

    code = handle_update_command(
        _args(json=True),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        scheduler_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        progress_session_factory=_factory,
    )

    assert code == 0
    assert factory_runs and factory_runs[0]["verbose"] is False
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 4
    assert payload["log_path"] is not None
    assert Path(payload["log_path"]).is_file()
    assert "Upgrade sase" not in captured.out
    assert "Upgrade sase" not in captured.err


def test_verbose_with_quiet_stays_one_line(tmp_path: Path) -> None:
    out = _console()
    err = _console()
    code = handle_update_command(
        _args(quiet=True, verbose=True),
        console=out,
        err_console=err,
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        scheduler_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
        progress_session_factory=_session_factory(err, tmp_path),
    )

    assert code == 0
    assert len(_text(out).strip().splitlines()) == 1
    assert _text(err) == ""


def test_default_session_factory_logs_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.update_progress.log_sink as log_sink_mod

    monkeypatch.setattr(sys, "argv", ["sase", "update", "-v"])
    monkeypatch.setattr(log_sink_mod, "_default_log_dir", lambda: tmp_path)
    session = live_handler._default_progress_session(
        err=_console(), as_json=False, quiet=False, verbose=False
    )

    assert session.log_path is not None
    log_text = session.log_path.read_text(encoding="utf-8")
    assert "argv: sase update -v" in log_text
