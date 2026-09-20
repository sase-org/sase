"""Services-tab phase closure: health pill, chrome, gear, chip, surface token."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.tui._proc_observer_models import (
    ObservedProc,
    ProcProjection,
    gear_eligible_count,
)
from sase.ace.tui._service_health import derive_service_health
from sase.ace.tui.actions.event_refresh._surface_tokens import (
    SurfaceTokenRoots,
    probe_surface_tokens,
    surface_token_drifted,
)
from sase.ace.tui.widgets import KeybindingFooter
from sase.ace.tui.widgets.axe_info_panel import AxeInfoPanel, format_uptime
from sase.ace.tui.widgets.bgcmd_list import (
    _service_proc_chip,
    service_enablement_chip,
)
from sase.service.status import ServiceEnablement
from sase.core.time import local_now


def _enablement(enabled: bool = True, summary: str = "enabled") -> ServiceEnablement:
    return ServiceEnablement(enabled=enabled, provenance="x", summary=summary)


def _proc(
    name: str = "p",
    *,
    state: str = "running",
    desired: str = "running",
    enabled: bool = True,
    available: bool = True,
    reason: str | None = None,
    summary: str = "enabled",
) -> Any:
    return SimpleNamespace(
        name=name,
        state=state,
        desired=desired,
        available=available,
        unavailable_reason=reason,
        restarts=0,
        enablement=_enablement(enabled, summary),
    )


def _snap(*procs: Any, host: str = "running", token: str = "t") -> Any:
    return SimpleNamespace(
        host=SimpleNamespace(state=host), procs=procs, change_token=token
    )


# --- health derivation -----------------------------------------------------


def test_health_healthy_counts_running_over_desired() -> None:
    health = derive_service_health(_snap(_proc("a"), _proc("b")))
    assert (health.running, health.desired, health.healthy) == (2, 2, True)


def test_health_disabled_procs_omitted() -> None:
    health = derive_service_health(
        _snap(_proc("a"), _proc("b", state="stopped", desired="stopped", enabled=False))
    )
    assert (health.running, health.desired, health.healthy) == (1, 1, True)


def test_health_host_down_is_unhealthy() -> None:
    health = derive_service_health(_snap(_proc("a"), host="stopped"))
    assert not health.healthy
    assert health.summary == "host stopped"


def test_health_failed_proc_names_offender() -> None:
    health = derive_service_health(
        _snap(_proc("a"), _proc("telegram_receiver", state="failed"))
    )
    assert not health.healthy
    assert health.summary == "telegram_receiver failed"
    assert (health.running, health.desired) == (1, 2)


def test_health_unavailable_is_counted_and_unhealthy() -> None:
    health = derive_service_health(
        _snap(_proc("a", state="stopped", desired="stopped", available=False))
    )
    assert (health.running, health.desired) == (0, 1)
    assert not health.healthy


def test_health_no_snapshot_is_healthy_empty() -> None:
    health = derive_service_health(None)
    assert (health.running, health.desired, health.healthy) == (0, 0, True)


# --- footer ----------------------------------------------------------------


def _footer() -> KeybindingFooter:
    footer = KeybindingFooter()
    footer.end_startup_stopwatch()
    return footer


def test_footer_healthy_pill() -> None:
    footer = _footer()
    footer.set_service_health(derive_service_health(_snap(_proc("a"), _proc("b"))))
    text = str(footer._get_status_text())
    assert "SVC" in text
    assert "2/2" in text
    assert "RUNNING" not in text
    assert "⚙" not in text


def test_footer_unhealthy_pill_is_loud() -> None:
    footer = _footer()
    footer.set_service_health(derive_service_health(_snap(_proc("a"), host="stopped")))
    text = str(footer._get_status_text())
    assert "SVC" in text
    assert "!" in text


def test_footer_flag_off_keeps_legacy_grammar() -> None:
    footer = _footer()
    footer.set_service_health(None)
    assert "STOPPED" in str(footer._get_status_text())
    footer._axe_running = True
    assert "RUNNING" in str(footer._get_status_text())


def test_footer_signature_changes_with_health() -> None:
    footer = _footer()
    footer.set_service_health(derive_service_health(_snap(_proc("a"))))
    before = footer._status_signature()
    footer.set_service_health(derive_service_health(_snap(_proc("a", state="failed"))))
    assert footer._status_signature() != before


# --- host chrome -----------------------------------------------------------


def test_format_uptime_units() -> None:
    assert format_uptime(45) == "45s"
    assert format_uptime(12 * 60 + 5) == "12m"
    assert format_uptime(3 * 3600 + 10) == "3h"
    assert format_uptime(4 * 86400 + 10) == "4d"
    assert format_uptime(-5) == "0s"


class _Panel(AxeInfoPanel):
    """Panel that records rendered text instead of needing a running app."""

    last: str = ""

    def update(self, content: Any = "", **_kw: Any) -> None:  # type: ignore[override]
        self.last = str(content)


def _panel_text(panel: _Panel) -> str:
    panel._update_display()
    return panel.last


def _host(**kw: Any) -> Any:
    return SimpleNamespace(state="running", started_at=None, platform_unit=None, **kw)


def test_chrome_running_with_unit_and_detached() -> None:
    panel = _Panel()
    host = SimpleNamespace(
        state="running", started_at=time.time() - 3 * 3600, platform_unit="systemd"
    )
    panel.update_host_chrome(host, enabled=True)  # type: ignore[arg-type]
    out = _panel_text(panel)
    assert "host" in out and "running" in out and "3h" in out and "systemd" in out
    panel.update_host_chrome(_host(), enabled=True)
    assert "detached" in _panel_text(panel)


def test_chrome_stopped_and_flag_off_and_loading() -> None:
    panel = _Panel()
    panel.update_host_chrome(SimpleNamespace(state="stopped"), enabled=True)  # type: ignore[arg-type]
    assert "press !x to start" in _panel_text(panel)
    panel.update_host_chrome(None, enabled=True)
    assert "stopped" in _panel_text(panel)
    panel.update_host_chrome(None, enabled=False)
    assert "host" not in _panel_text(panel)
    panel.update_host_chrome(_host(), enabled=True)
    panel._loading = True
    assert "host" not in _panel_text(panel)


# --- gear ------------------------------------------------------------------


def _row(proc_id: str, **kw: Any) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="",
        started_at=local_now(),
        **kw,
    )


def test_gear_excludes_monitor_and_sessionless_service_rows() -> None:
    from sase.ace.tui._proc_observer_models import MONITOR_PROC_ORIGIN

    rows = (
        _row("ordinary", session_id="s"),
        _row("monitor", origin=MONITOR_PROC_ORIGIN, session_id="s"),
        _row("receiver", service=SimpleNamespace(), session_id=None),  # type: ignore[arg-type]
    )
    projection = ProcProjection(
        rows=rows, active_count=3, active_monitor_count=1, session_id="s"
    )
    assert gear_eligible_count(projection) == 1
    assert len(projection.active_rows()) == 3  # inventory unchanged


# --- chip ------------------------------------------------------------------


def test_enablement_chip_variants() -> None:
    assert service_enablement_chip(_enablement()) is None
    assert service_enablement_chip(_enablement(False, "disabled here")) == (
        "disabled here"
    )
    layer = service_enablement_chip(_enablement(False, "disabled by " + "x" * 80))
    assert layer is not None and layer.endswith("…") and len(layer) <= 32


def test_proc_chip_states() -> None:
    assert _service_proc_chip(_proc()) is None
    assert _service_proc_chip(_proc(enabled=False, summary="disabled here"))[0] == (  # type: ignore[index]
        "disabled here"
    )
    assert _service_proc_chip(_proc(available=False, reason="no bin"))[0] == (  # type: ignore[index]
        "unavailable: no bin"
    )
    assert _service_proc_chip(_proc(available=False))[0] == "unavailable"  # type: ignore[index]


# --- surface token ---------------------------------------------------------


def _roots(tmp_path: Path) -> SurfaceTokenRoots:
    svc = tmp_path / "service"
    return SurfaceTokenRoots(
        projects_root=tmp_path / "projects",
        axe_root=tmp_path / "axe",
        notifications_path=tmp_path / "n.jsonl",
        procs_path=tmp_path / "procs.jsonl",
        service_dir=svc,
        service_state_path=svc / "state.json",
        service_status_path=svc / "status.json",
    )


def test_axe_token_drifts_on_service_files_and_is_stable_when_absent(
    tmp_path: Path,
) -> None:
    roots = _roots(tmp_path)
    first = probe_surface_tokens(roots).axe
    assert not first.indeterminate
    assert not surface_token_drifted(probe_surface_tokens(roots).axe, first)
    for name in ("status.json", "state.json"):
        before = probe_surface_tokens(roots).axe
        (tmp_path / "service").mkdir(exist_ok=True)
        (tmp_path / "service" / name).write_text("{}", encoding="utf-8")
        assert surface_token_drifted(probe_surface_tokens(roots).axe, before)


def test_procs_session_state_marker_defaults_uninitialized() -> None:
    from sase.ace.tui.modals.config_center_session import ProcsSessionState

    state = ProcsSessionState(query="")
    assert state.query_initialized is False
