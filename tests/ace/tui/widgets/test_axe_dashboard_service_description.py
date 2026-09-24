"""Service proc description panel on the Services dashboard."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets import axe_dashboard
from sase.ace.tui.widgets.axe_dashboard import AxeDashboard
from sase.ace.tui.widgets.axe_description_banner import AxeDescriptionBanner
from sase.service.status import ServiceEnablement, ServiceStatusProc


def _proc(description: str | None) -> ServiceStatusProc:
    return ServiceStatusProc(
        name="scheduler",
        source="builtin",
        declared_by="builtin",
        mode="daemon",
        available=True,
        enablement=ServiceEnablement(
            enabled=True, provenance="builtin", summary="enabled"
        ),
        desired="running",
        state="running",
        summary="running",
        restarts=0,
        description=description,
    )


def _dashboard(
    banner: AxeDescriptionBanner, captured: dict[str, object]
) -> AxeDashboard:
    status = axe_dashboard._AxeStatusSection.__new__(axe_dashboard._AxeStatusSection)
    output = axe_dashboard._AxeOutputSection.__new__(axe_dashboard._AxeOutputSection)

    def _capture_update(content: object) -> None:
        captured["content"] = content

    output.update = _capture_update  # type: ignore[assignment]
    status.update_service_proc_display = lambda **_kw: None  # type: ignore[assignment]

    dashboard = AxeDashboard.__new__(AxeDashboard)

    def _query_one(selector: str, _cls: type) -> object:
        if "status" in selector:
            return status
        if "description" in selector:
            return banner
        return output

    dashboard.query_one = _query_one  # type: ignore[assignment]
    dashboard._description_expanded = lambda: True  # type: ignore[assignment]
    dashboard._description_max_lines = lambda: 10  # type: ignore[assignment]
    dashboard._description_keys = lambda: ("d", "e")  # type: ignore[assignment]
    return dashboard


def test_service_proc_display_shows_split_description() -> None:
    banner = AxeDescriptionBanner()
    captured: dict[str, object] = {}
    dashboard = _dashboard(banner, captured)

    dashboard.update_service_proc_display(
        snapshot=None,
        proc=_proc("Run automation\n\nDoes things."),
        name="scheduler",
        output="",
    )

    assert banner.display is True
    shown = banner._shown
    assert shown is not None
    assert shown.summary == "Run automation"
    assert shown.body == "Does things."
    output_text = captured["content"]
    assert isinstance(output_text, Text)
    assert " — Run automation" not in output_text.plain


def test_service_proc_display_hides_panel_when_proc_missing() -> None:
    banner = AxeDescriptionBanner()
    banner.show_service_proc("scheduler", "Run automation", "Body")
    assert banner.display is True
    captured: dict[str, object] = {}
    dashboard = _dashboard(banner, captured)

    dashboard.update_service_proc_display(
        snapshot=None,
        proc=None,
        name="scheduler",
        output="",
    )

    assert banner.display is False
