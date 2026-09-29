"""Pre-start ceiling refusal: ``sase tool run`` refuses what cannot fit."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_list
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.routing import (
    inline_refusal,
    monitor_start_form,
    read_sync_ceiling,
)


def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_MONITOR_ARTIFACTS_DIR",
        "SASE_PROC_ID",
        "SASE_PROC_LOG_PATH",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_AGENT",
        "SASE_BEAD_ID",
        "SASE_BEAD",
        "SASE_WORKSPACE_NUM",
        "SASE_PROVIDER_SYNC_CEILING_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _write_catalog(tmp_path: Path) -> dict[str, Path]:
    markers = {
        "slow": tmp_path / "slow.marker",
        "endless": tmp_path / "endless.marker",
        "quick": tmp_path / "quick.marker",
        "plain": tmp_path / "plain.marker",
    }
    (tmp_path / "sase").mkdir(exist_ok=True)
    (tmp_path / "sase" / "sase.yml").write_text(
        yaml.dump(
            {
                "tools": {
                    "slow": {
                        "argv": ["sh", "-c", f"touch {markers['slow']}"],
                        "args": "deny",
                        "duration_class": "long",
                    },
                    "endless": {
                        "argv": ["sh", "-c", f"touch {markers['endless']}"],
                        "args": "deny",
                        "duration_class": "unbounded",
                    },
                    "quick": {
                        "argv": ["sh", "-c", f"touch {markers['quick']}"],
                        "args": "deny",
                        "duration_class": "short",
                    },
                    "plain": {
                        "argv": ["sh", "-c", f"touch {markers['plain']}"],
                        "args": "deny",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    clear_config_cache()
    return markers


def _request(*words: str) -> ToolRunCliRequest:
    return ToolRunCliRequest(
        quiet=False, verbose=False, tail_lines=200, words=tuple(words)
    )


def _agent_with_ceiling(monkeypatch: pytest.MonkeyPatch, ceiling: str) -> None:
    monkeypatch.setenv("SASE_AGENT", "fixture-agent")
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", ceiling)


def test_long_refused_under_matching_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    markers = _write_catalog(tmp_path)
    _agent_with_ceiling(monkeypatch, "600")
    code = execute_tool_run(_request("slow"))
    assert code == 2
    captured = capsys.readouterr()
    assert "refused before starting slow" in captured.err
    assert "duration class is long" in captured.err
    assert "SASE_PROVIDER_SYNC_CEILING_SECONDS=600" in captured.err
    assert "Nothing was started" in captured.err
    assert "sase monitor start -p verify" in captured.err
    assert "-n" in captured.err
    assert "-f" in captured.err
    assert "<ref>" in captured.err
    assert "verification.command" in captured.err
    assert not markers["slow"].exists()
    assert not tool_run_list({"schema_version": 1, "limit": 10}).get("runs")


def test_unbounded_refused_under_any_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    markers = _write_catalog(tmp_path)
    _agent_with_ceiling(monkeypatch, "14400")
    code = execute_tool_run(_request("endless"))
    assert code == 2
    captured = capsys.readouterr()
    assert "has no upper bound" in captured.err
    assert "Nothing was started" in captured.err
    assert not markers["endless"].exists()
    assert not tool_run_list({"schema_version": 1, "limit": 10}).get("runs")


def test_long_runs_under_roomier_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    markers = _write_catalog(tmp_path)
    _agent_with_ceiling(monkeypatch, "1800")
    code = execute_tool_run(_request("slow"))
    assert code == 0
    capsys.readouterr()
    assert markers["slow"].exists()


def test_short_and_undeclared_run_under_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    markers = _write_catalog(tmp_path)
    _agent_with_ceiling(monkeypatch, "600")
    assert execute_tool_run(_request("quick")) == 0
    capsys.readouterr()
    assert execute_tool_run(_request("plain")) == 0
    capsys.readouterr()
    assert markers["quick"].exists()
    assert markers["plain"].exists()


def test_adhoc_never_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _write_catalog(tmp_path)
    _agent_with_ceiling(monkeypatch, "600")
    marker = tmp_path / "adhoc.marker"
    code = execute_tool_run(_request("--", "sh", "-c", f"touch {marker}"))
    assert code == 0
    capsys.readouterr()
    assert marker.exists()


def test_no_agent_identity_runs_despite_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    markers = _write_catalog(tmp_path)
    monkeypatch.setenv("SASE_PROVIDER_SYNC_CEILING_SECONDS", "600")
    code = execute_tool_run(_request("slow"))
    assert code == 0
    capsys.readouterr()
    assert markers["slow"].exists()


@pytest.mark.parametrize("ceiling", ["abc", "0", "-5", ""])
def test_malformed_ceiling_fails_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    ceiling: str,
) -> None:
    _clean_env(monkeypatch, tmp_path)
    markers = _write_catalog(tmp_path)
    _agent_with_ceiling(monkeypatch, ceiling)
    code = execute_tool_run(_request("slow"))
    assert code == 0
    capsys.readouterr()
    assert markers["slow"].exists()


def test_missing_binding_fails_open_with_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    markers = _write_catalog(tmp_path)
    _agent_with_ceiling(monkeypatch, "600")

    def _boom(request: object) -> dict[str, object]:
        raise RuntimeError("core too old")

    monkeypatch.setattr("sase.tool.routing.tool_run_duration_fit", _boom)
    code = execute_tool_run(_request("slow"))
    assert code == 0
    captured = capsys.readouterr()
    assert "duration fit unavailable" in captured.err
    assert markers["slow"].exists()


def test_read_sync_ceiling_accepts_only_positive_integers() -> None:
    env = {"SASE_PROVIDER_SYNC_CEILING_SECONDS": "600"}
    assert read_sync_ceiling(env) == 600
    for raw in ("abc", "0", "-5", "", "  ", "6.5"):
        assert read_sync_ceiling({"SASE_PROVIDER_SYNC_CEILING_SECONDS": raw}) is None
    assert read_sync_ceiling({}) is None


def test_monitor_start_form_matches_handoff_refusal() -> None:
    # The shared builder must keep the -H agent refusal byte-identical.
    assert (
        monitor_start_form(("check",), reason="hand off tool run")
        == "sase monitor start -p verify --reason 'hand off tool run' "
        "-- sase tool run check"
    )
    assert (
        monitor_start_form(("--", "printf", "hi"), reason="hand off tool run")
        == "sase monitor start -p verify --reason 'hand off tool run' "
        "-- sase tool run -- printf hi"
    )


def test_refusal_monitor_forms_reparse_to_tool_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.tool.argv import resolve_run_argv

    _clean_env(monkeypatch, tmp_path)
    _write_catalog(tmp_path)
    _agent_with_ceiling(monkeypatch, "600")
    resolved = resolve_run_argv(["slow"])
    message = inline_refusal(resolved)
    assert message is not None
    forms = [
        line.strip()
        for line in message.splitlines()
        if line.strip().startswith("sase monitor start")
    ]
    assert len(forms) == 2
    for form in forms:
        assert "-- sase tool run slow" in form
        argv = shlex.split(form.rsplit(" -- ", 1)[1])
        assert argv == ["sase", "tool", "run", "slow"]
