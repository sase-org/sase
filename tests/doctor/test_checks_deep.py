"""Tests for Phase 4 doctor deep checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.axe.status_models import (
    AxeLumberjackStatus,
    AxeOrchestratorStatus,
    AxeProcessObservation,
    AxeRunnerOccupancy,
    AxeStatusCollectionError,
    AxeStatusIssue,
    AxeStatusSnapshot,
)
from sase.doctor.checks_deep_agent_index import check_agent_index_verify
from sase.doctor.checks_deep_axe import check_axe_state
from sase.doctor.checks_deep_providers import check_provider_cli_versions
from sase.doctor.checks_deep_terminal import (
    check_kitty_graphics,
    check_tmux_version,
    check_truecolor,
)
from sase.doctor.checks_deep_xprompt_lsp import check_xprompt_lsp
from sase.doctor.runner import DoctorContext
from sase.integrations import xprompt_lsp


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        env={},
    )


def _axe_snapshot(
    *,
    state: str = "not_started",
    health: str = "healthy",
    summary: str = "AXE has not been started.",
    lumberjacks: tuple[AxeLumberjackStatus, ...] = (),
    issues: tuple[AxeStatusIssue, ...] = (),
    collection_error: AxeStatusCollectionError | None = None,
) -> AxeStatusSnapshot:
    missing = AxeProcessObservation(pid=None, live=None)
    return AxeStatusSnapshot(
        schema_version=1,
        generated_at="2026-07-23T12:00:00+00:00",
        state=state,  # type: ignore[arg-type]
        health=health,  # type: ignore[arg-type]
        summary=summary,
        exit_code=2 if health == "error" else (1 if health == "unhealthy" else 0),
        desired_state=None,
        orchestrator=AxeOrchestratorStatus(
            state="stopped",
            coherence="coherent",
            live_pids=(),
            lifecycle_lock_held=False,
            lock_holder=missing,
            orchestrator_pid_file=missing,
            legacy_pid_file=missing,
        ),
        maintenance=None,
        hook_runners=AxeRunnerOccupancy(current=0, maximum=3),
        agent_runners=AxeRunnerOccupancy(current=0, maximum=3),
        lumberjacks=lumberjacks,
        latest_lifecycle_event=None,
        issues=issues,
        collection_error=collection_error,
    )


def _lumberjack_row(
    *,
    state: str,
    errors: int = 0,
    heartbeat_age: int | None = None,
) -> AxeLumberjackStatus:
    return AxeLumberjackStatus(
        name="hooks",
        state=state,  # type: ignore[arg-type]
        stale_threshold_seconds=60,
        configured=True,
        interval_seconds=5,
        configured_chops=("hook_checks",),
        recorded_pid=123,
        reported_state="running",
        process_live=True,
        started_at="2026-07-23T11:00:00+00:00",
        start_age_seconds=3600,
        heartbeat_at="2026-07-23T11:58:59+00:00",
        heartbeat_age_seconds=heartbeat_age,
        cycles_run=1,
        errors_encountered=errors,
        uptime_seconds=3600,
    )


def test_agent_index_verify_warns_on_drift(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_agent_index.default_agent_artifact_index_path",
        lambda: tmp_path / "index.sqlite",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_agent_index.sase_projects_dir",
        lambda: tmp_path / "projects",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_agent_index.verify_agent_artifact_index",
        lambda *_args: SimpleNamespace(
            ok=False,
            schema_version=3,
            index_path="/tmp/index.sqlite",
            projects_root="/tmp/projects",
            indexed_rows=1,
            source_rows=2,
            stale_rows=0,
            missing_rows=1,
            extra_rows=0,
            corrupt_rows=0,
        ),
    )

    check = check_agent_index_verify()

    assert check.status == "WARN"
    assert "missing_rows=1" in check.summary
    assert check.next_steps == ("Run `sase agent index gc`.",)


def test_provider_cli_versions_reports_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_providers.llm_registry.get_llm_metadata_payload",
        lambda: {
            "providers": {
                "codex": {
                    "autodetect_cli_name": "codex",
                    "known_model_names": [],
                }
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_providers._resolve_executable",
        lambda _command: "/usr/bin/codex",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_providers._run_version_probe",
        lambda _executable: {
            "probe_status": "ok",
            "detail": "codex 1.2.3",
            "version": "codex 1.2.3",
            "returncode": 0,
        },
    )

    check = check_provider_cli_versions(_context(tmp_path))

    assert check.status == "OK"
    assert "1/1" in check.summary
    assert check.data["providers"][0]["version"] == "codex 1.2.3"


def test_provider_cli_versions_flags_grok_identity_mismatch(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_providers.llm_registry.get_llm_metadata_payload",
        lambda: {
            "providers": {
                "grok": {
                    "autodetect_cli_name": "grok",
                    "known_model_names": [],
                }
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_providers._resolve_executable",
        lambda _command: "/usr/local/bin/grok",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_providers._run_version_probe",
        lambda _executable: {
            "probe_status": "ok",
            "detail": "grok-dev 0.9.0",
            "version": "grok-dev 0.9.0",
            "returncode": 0,
        },
    )
    # grok-dev's `--version` still starts with "grok", so this pins that a
    # loose substring match would wrongly accept it — only the real
    # `grok X.Y.Z (<hash>) [<channel>]` shape passes.

    check = check_provider_cli_versions(_context(tmp_path))

    assert check.status == "WARN"
    row = check.data["providers"][0]
    assert row["probe_status"] == "identity_mismatch"
    assert "does not identify as Grok Build" in row["detail"]
    assert "SASE_GROK_PATH" in row["detail"]
    assert any("identity_mismatch" in detail for detail in check.details)


def test_provider_cli_versions_accepts_real_grok_build(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_providers.llm_registry.get_llm_metadata_payload",
        lambda: {
            "providers": {
                "grok": {
                    "autodetect_cli_name": "grok",
                    "known_model_names": [],
                }
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_providers._resolve_executable",
        lambda _command: "/home/user/.grok/bin/grok",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_providers._run_version_probe",
        lambda _executable: {
            "probe_status": "ok",
            "detail": "grok 1.0.3 (1a29d5bc12) [stable]",
            "version": "grok 1.0.3 (1a29d5bc12) [stable]",
            "returncode": 0,
        },
    )

    check = check_provider_cli_versions(_context(tmp_path))

    assert check.status == "OK"
    assert check.data["providers"][0]["probe_status"] == "ok"


def test_axe_state_ok_when_no_lumberjack_status_files(monkeypatch) -> None:
    state_dir = Path("/nonexistent/sase-test-axe-state")
    snapshot = _axe_snapshot(
        lumberjacks=(_lumberjack_row(state="not_reporting"),),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_axe.collect_axe_status_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_axe.load_axe_config",
        lambda: SimpleNamespace(
            zombie_timeout_seconds=7200,
            lumberjack_log_max_bytes=1024,
        ),
    )
    monkeypatch.setattr("sase.axe.state.axe_state_dir", lambda: state_dir)

    check = check_axe_state()

    assert check.status == "OK"
    assert "1 configured" in check.summary


def test_axe_state_warns_on_stale_heartbeat(monkeypatch, tmp_path: Path) -> None:
    issue = AxeStatusIssue(
        code="lumberjack_stale_heartbeat",
        severity="warning",
        subject="hooks",
        summary=(
            "Configured lumberjack `hooks` has a stale heartbeat (61s; threshold 60s)."
        ),
        suggested_command="sase doctor --deep",
    )
    snapshot = _axe_snapshot(
        state="degraded",
        health="unhealthy",
        summary="AXE is degraded and requires operator attention.",
        lumberjacks=(_lumberjack_row(state="stale_heartbeat", heartbeat_age=61),),
        issues=(issue,),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_axe.collect_axe_status_snapshot",
        lambda: snapshot,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_axe.load_axe_config",
        lambda: SimpleNamespace(
            zombie_timeout_seconds=7200,
            lumberjack_log_max_bytes=1024,
        ),
    )
    monkeypatch.setattr("sase.axe.state.axe_state_dir", lambda: tmp_path)

    check = check_axe_state()

    assert check.status == "WARN"
    assert any("stale heartbeat" in detail for detail in check.details)
    assert check.data["lumberjacks"][0]["heartbeat_stale"] is True


def test_axe_state_warns_on_pinned_logs_and_orphan_temps(
    monkeypatch,
    tmp_path: Path,
) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "axe.log").write_bytes(b"0123456789")
    (logs_dir / ".axe.log.abcd.tmp").write_bytes(b"orphan")
    monkeypatch.setattr(
        "sase.doctor.checks_deep_axe.collect_axe_status_snapshot",
        lambda: _axe_snapshot(state="running", summary="AXE is running and healthy."),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_axe.load_axe_config",
        lambda: SimpleNamespace(
            zombie_timeout_seconds=7200,
            lumberjack_log_max_bytes=10,
        ),
    )
    monkeypatch.setattr("sase.axe.state.axe_state_dir", lambda: tmp_path)
    monkeypatch.setattr("sase.doctor.checks_deep_axe._ORPHAN_TEMP_WARN_COUNT", 1)

    check = check_axe_state()

    assert check.status == "WARN"
    assert any("pinned at" in detail for detail in check.details)
    assert any("orphan log-rotation temp litter" in detail for detail in check.details)
    assert check.data["pinned_logs"] == (str(logs_dir / "axe.log"),)
    assert check.data["orphan_log_temp_count"] == 1


def test_axe_state_maps_collection_error_to_error(monkeypatch, tmp_path: Path) -> None:
    collection_error = AxeStatusCollectionError(
        code="config_read_failed",
        message="broken config",
    )
    issue = AxeStatusIssue(
        code="collection_error",
        severity="error",
        subject="collection",
        summary="AXE status collection failed [config_read_failed]: broken config",
        suggested_command="sase doctor --deep",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_axe.collect_axe_status_snapshot",
        lambda: _axe_snapshot(
            state="error",
            health="error",
            summary="AXE status collection failed: broken config",
            issues=(issue,),
            collection_error=collection_error,
        ),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_axe.load_axe_config",
        lambda: (_ for _ in ()).throw(RuntimeError("broken config")),
    )
    monkeypatch.setattr("sase.axe.state.axe_state_dir", lambda: tmp_path)

    check = check_axe_state()

    assert check.status == "ERROR"
    assert check.data["health"] == "error"
    assert check.data["collection_error"]["code"] == "config_read_failed"


def test_axe_state_keeps_historical_errors_as_deep_only_warning(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_axe.collect_axe_status_snapshot",
        lambda: _axe_snapshot(
            state="running",
            summary="AXE is running and healthy.",
            lumberjacks=(_lumberjack_row(state="running", errors=3),),
        ),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_axe.load_axe_config",
        lambda: SimpleNamespace(
            zombie_timeout_seconds=7200,
            lumberjack_log_max_bytes=1024,
        ),
    )
    monkeypatch.setattr("sase.axe.state.axe_state_dir", lambda: tmp_path)

    check = check_axe_state()

    assert check.status == "WARN"
    assert check.data["health"] == "healthy"
    assert any("cumulative historical" in detail for detail in check.details)


def test_xprompt_lsp_ok_when_env_override_resolves(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_xprompt_lsp.xprompt_lsp.resolve_xprompt_lsp_command",
        lambda **_kwargs: ("/opt/sase/bin/sase-xprompt-lsp",),
    )

    check = check_xprompt_lsp(
        DoctorContext(
            cwd=tmp_path,
            project=None,
            sase_home=tmp_path / ".sase",
            env={
                xprompt_lsp.SASE_XPROMPT_LSP_CMD_ENV: "/opt/sase/bin/sase-xprompt-lsp"
            },
        )
    )

    assert check.status == "OK"
    assert check.summary == "xprompt LSP server resolves via SASE_XPROMPT_LSP_CMD"
    assert check.data["command"] == ("/opt/sase/bin/sase-xprompt-lsp",)


def test_xprompt_lsp_warns_when_resolver_fails(monkeypatch, tmp_path: Path) -> None:
    def fail_resolve(**_kwargs: object) -> tuple[str, ...]:
        raise xprompt_lsp.XPromptLspLaunchError("xprompt LSP binary not found")

    monkeypatch.setattr(
        "sase.doctor.checks_deep_xprompt_lsp.xprompt_lsp.resolve_xprompt_lsp_command",
        fail_resolve,
    )

    check = check_xprompt_lsp(_context(tmp_path))

    assert check.status == "WARN"
    assert "does not resolve" in check.summary
    assert check.data["resolved"] is False
    assert "SASE_XPROMPT_LSP_CMD" in check.next_steps[0]


def test_xprompt_lsp_warns_on_cargo_fallback(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_xprompt_lsp.xprompt_lsp.resolve_xprompt_lsp_command",
        lambda **_kwargs: (
            "cargo",
            "run",
            "--manifest-path",
            "/repo/sase-core/Cargo.toml",
            "-p",
            "sase_xprompt_lsp",
            "--",
        ),
    )

    check = check_xprompt_lsp(_context(tmp_path))

    assert check.status == "WARN"
    assert "slow cargo fallback" in check.summary
    assert check.data["cargo_fallback"] is True


def test_kitty_graphics_ok_with_supported_terminal_and_kitten(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_terminal.shutil.which",
        lambda command: "/usr/bin/kitten" if command == "kitten" else None,
    )

    check = check_kitty_graphics(
        DoctorContext(
            cwd=tmp_path,
            project=None,
            sase_home=tmp_path / ".sase",
            env={"TERM": "xterm-kitty", "KITTY_WINDOW_ID": "1"},
        )
    )

    assert check.status == "OK"
    assert check.data["supported"] is True
    assert check.data["kitten_resolved_path"] == "/usr/bin/kitten"


def test_kitty_graphics_warns_when_terminal_or_kitten_missing(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_terminal.shutil.which", lambda _command: None
    )

    check = check_kitty_graphics(_context(tmp_path))

    assert check.status == "WARN"
    assert any("Inline image/PDF/Markdown" in detail for detail in check.details)
    assert any("Install `kitten`" in step for step in check.next_steps)


def test_tmux_version_skips_when_tmux_is_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_terminal.shutil.which", lambda _command: None
    )

    check = check_tmux_version(_context(tmp_path))

    assert check.status == "SKIP"
    assert check.data["resolved_path"] is None


def test_tmux_version_warns_below_passthrough_floor(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_terminal.shutil.which",
        lambda command: "/usr/bin/tmux" if command == "tmux" else None,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_terminal._run_tmux_version_probe",
        lambda _path: {
            "probe_status": "ok",
            "detail": "tmux 3.2a",
            "version": "tmux 3.2a",
            "returncode": 0,
        },
    )

    check = check_tmux_version(_context(tmp_path))

    assert check.status == "WARN"
    assert "older than the passthrough floor" in check.summary
    assert "tmux 3.2a is older" in check.summary
    assert "tmux tmux" not in check.summary
    assert check.data["parsed_version"] == (3, 2)


def test_tmux_version_ok_at_passthrough_floor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep_terminal.shutil.which",
        lambda command: "/usr/bin/tmux" if command == "tmux" else None,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep_terminal._run_tmux_version_probe",
        lambda _path: {
            "probe_status": "ok",
            "detail": "tmux 3.3a",
            "version": "tmux 3.3a",
            "returncode": 0,
        },
    )

    check = check_tmux_version(
        DoctorContext(
            cwd=tmp_path,
            project=None,
            sase_home=tmp_path / ".sase",
            env={"TMUX": "/tmp/tmux-1000/default,123,0"},
        )
    )

    assert check.status == "OK"
    assert "tmux 3.3a supports kitty graphics passthrough" in check.summary
    assert "tmux tmux" not in check.summary
    assert check.data["inside_tmux"] is True
    assert check.data["parsed_version"] == (3, 3)


def test_truecolor_skips_without_terminal_environment(tmp_path: Path) -> None:
    check = check_truecolor(_context(tmp_path))

    assert check.status == "SKIP"
    assert "unavailable" in check.summary


def test_truecolor_ok_when_terminal_advertises_24_bit_color(tmp_path: Path) -> None:
    check = check_truecolor(
        DoctorContext(
            cwd=tmp_path,
            project=None,
            sase_home=tmp_path / ".sase",
            env={"TERM": "xterm-256color", "COLORTERM": "truecolor"},
        )
    )

    assert check.status == "OK"
    assert check.data["truecolor"] is True


def test_truecolor_warns_when_interactive_terminal_lacks_marker(
    tmp_path: Path,
) -> None:
    check = check_truecolor(
        DoctorContext(
            cwd=tmp_path,
            project=None,
            sase_home=tmp_path / ".sase",
            env={"TERM": "xterm-256color"},
        )
    )

    assert check.status == "WARN"
    assert "does not advertise truecolor" in check.summary
    assert "COLORTERM=truecolor" in check.next_steps[0]
