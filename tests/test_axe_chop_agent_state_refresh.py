"""Entry-point, config, and chop coverage for agent_state_refresh."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from sase.agents_sync.agent_state_refresh import AgentStateRefreshSummary
import sase.scripts.sase_chop_agent_state_refresh as refresh_chop
from sase.axe.config import load_axe_config


def _runtime(tmp_path: Path) -> SimpleNamespace:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    context = SimpleNamespace(state_dir=str(state_dir), result_file="")
    log = MagicMock()
    log.last_summary = None
    runtime = SimpleNamespace(context=context, log=log)
    summaries: list[str] = []

    def emit_summary(fields, reason=None):
        line = "agent_state_refresh: " + " ".join(f"{k}={v}" for k, v in fields.items())
        if reason:
            line += f" reason={reason}"
        summaries.append(line)
        builder = MagicMock()
        builder.counters = dict(fields)
        builder.status = "ok"
        builder.summary = line
        builder.reason = reason
        log.last_summary = None
        return builder

    runtime.emit_summary = emit_summary  # type: ignore[attr-defined]
    return runtime


def test_chop_reports_no_projects(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        refresh_chop,
        "run_agent_state_refresh",
        lambda **kwargs: AgentStateRefreshSummary(
            projects=0, reason="no_enabled_projects"
        ),
    )
    runtime = _runtime(tmp_path)
    result = refresh_chop._run(runtime)  # noqa: SLF001
    assert result.counters["projects"] == 0
    assert result.reason == "no_enabled_projects"


def test_chop_marks_errors_check_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        refresh_chop,
        "run_agent_state_refresh",
        lambda **kwargs: AgentStateRefreshSummary(
            projects=1,
            examined=1,
            failed=1,
            errors=1,
            selected_project="proj",
            reason="project_failed",
            diagnostics=("proj: boom",),
        ),
    )
    runtime = _runtime(tmp_path)
    result = refresh_chop._run(runtime)  # noqa: SLF001
    assert result.status == "check_error"
    assert result.counters["errors"] == 1


def test_chop_reports_bounded_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        refresh_chop,
        "run_agent_state_refresh",
        lambda **kwargs: AgentStateRefreshSummary(
            projects=1,
            examined=1,
            changed=1,
            selected_project="proj",
            pass_complete=True,
            next_cursor="cursor-1",
        ),
    )
    runtime = _runtime(tmp_path)
    result = refresh_chop._run(runtime)  # noqa: SLF001
    assert result.status != "check_error"
    assert result.counters["changed"] == 1


def test_builtin_chop_is_registered() -> None:
    from sase.chops.builtin import _BUILTIN_CHOPS

    assert "agent_state_refresh" in _BUILTIN_CHOPS


def test_entry_points_are_installed() -> None:
    from pathlib import Path as _Path

    text = (_Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert (
        'sase_job_agent_state_refresh = "sase.scripts.sase_chop_agent_state_refresh:main"'
        in text
    )
    assert (
        'sase_chop_agent_state_refresh = "sase.scripts.sase_chop_agent_state_refresh:main"'
        in text
    )


def test_default_config_checks_lane_contains_refresh_job() -> None:
    config = load_axe_config()
    assert "checks" in config.lumberjacks
    checks = config.lumberjacks["checks"]
    by_name = {chop.name: chop for chop in checks.chops}
    assert "agent_state_refresh" in by_name
    job = by_name["agent_state_refresh"]
    assert job.script_name == "sase_job_agent_state_refresh"
    assert job.timeout == 120
    assert checks.interval == 300
