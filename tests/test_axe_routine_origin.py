"""Declaring-source (origin) wire contract for AXE routines and jobs.

Wire entries expose their declaring layer as ``source``
(``builtin`` | ``plugin`` | ``user``) plus a ``declared_by`` ``name:path``
label; Python projects those origins onto runtime configs and surfaces
them through the ``sase axe routine list`` CLI and the Services
routine/job detail panels — without inferring anything from names or
provenance.

Layered-declaration coverage lives in
:mod:`tests.test_axe_routine_origin_layers`; collector and display-apply
coverage lives in :mod:`tests.test_axe_routine_origin_collector`.
"""

from __future__ import annotations

import argparse
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.config import AxeConfig, LumberjackConfig, load_axe_config
from sase.axe.config_backend import (
    AxeConfigComposition,
    AxeEntityOrigin,
    AxeInventoryEntry,
)


def _entry_payload(
    *,
    kind: str = "lumberjack",
    lumberjack: str = "hooks",
    chop: str | None = None,
    source: Any = "user",
    declared_by: Any = "user:/conf/sase.yml",
    generated: bool = False,
) -> dict[str, Any]:
    selector: dict[str, Any] = {
        "kind": kind,
        "lumberjack": lumberjack,
        "chop": chop,
    }
    payload: dict[str, Any] = {
        "selector": selector,
        "key_path": ["axe", "lumberjacks", lumberjack],
        "path": f"axe.lumberjacks.{lumberjack}",
        "effective": {},
        "enabled": True,
        "mutable": True,
        "generated": generated,
        "base_selector": None,
        "target_key": None,
        "field_provenance": [],
        "contributions": [],
    }
    payload["source"] = source
    payload["declared_by"] = declared_by
    return payload


def _composition(entries: list[AxeInventoryEntry]) -> AxeConfigComposition:
    return AxeConfigComposition(
        schema_version=1,
        effective_config={},
        provenance=(),
        entries=tuple(entries),
        diagnostics=(),
        layer_inputs=(),
    )


def test_inventory_entry_parses_required_origin() -> None:
    """Wire entries expose their declaring source and layer label."""
    entry = AxeInventoryEntry.from_wire(
        _entry_payload(source="builtin", declared_by="default")
    )
    assert entry.source == "builtin"
    assert entry.declared_by == "default"
    assert entry.origin == AxeEntityOrigin(source="builtin", declared_by="default")


def test_inventory_entry_rejects_unknown_source() -> None:
    """A source outside the closed set names the entry and the values."""
    with pytest.raises(ValueError, match="axe.lumberjacks.hooks") as exc_info:
        AxeInventoryEntry.from_wire(_entry_payload(source="custom"))
    message = str(exc_info.value)
    assert "builtin|plugin|user" in message
    assert "'custom'" in message


def test_inventory_entry_without_origin_names_stale_binding() -> None:
    """Entries from a pre-contract binding fail with a rebuild hint."""
    payload = _entry_payload()
    del payload["source"]
    del payload["declared_by"]
    with pytest.raises(ValueError, match="sase_core_rs binding predates") as exc_info:
        AxeInventoryEntry.from_wire(payload)
    assert "axe.lumberjacks.hooks" in str(exc_info.value)


def test_inventory_entry_rejects_empty_declared_by() -> None:
    """An empty layer label is malformed, not a silent default."""
    with pytest.raises(ValueError, match="declared_by"):
        AxeInventoryEntry.from_wire(_entry_payload(declared_by=""))


def test_composition_origin_maps_cover_routines_and_generated_jobs() -> None:
    """Routine and job maps derive from inventory, incl. generated rows."""
    routine = AxeInventoryEntry.from_wire(
        _entry_payload(lumberjack="checks", source="builtin", declared_by="default")
    )
    base = AxeInventoryEntry.from_wire(
        {
            **_entry_payload(
                kind="chop",
                lumberjack="checks",
                chop="audit",
                source="builtin",
                declared_by="default",
            ),
            "key_path": ["axe", "lumberjacks", "checks", "chops", "audit"],
            "path": "axe.lumberjacks.checks.chops.audit",
        }
    )
    generated = AxeInventoryEntry.from_wire(
        {
            **_entry_payload(
                kind="chop",
                lumberjack="checks",
                chop="audit@proj",
                source="builtin",
                declared_by="default",
                generated=True,
            ),
            "key_path": [
                "axe",
                "lumberjacks",
                "checks",
                "chops",
                "audit@proj",
            ],
            "path": "axe.lumberjacks.checks.chops.audit@proj",
            "base_selector": {
                "kind": "chop",
                "lumberjack": "checks",
                "chop": "audit",
            },
        }
    )
    composition = _composition([routine, base, generated])

    assert composition.routine_origins() == {
        "checks": AxeEntityOrigin(source="builtin", declared_by="default")
    }
    assert composition.chop_origins() == {
        ("checks", "audit"): AxeEntityOrigin(source="builtin", declared_by="default"),
        # Generated runtime jobs resolve under their instance name with
        # the base job's inherited origin.
        ("checks", "audit@proj"): AxeEntityOrigin(
            source="builtin", declared_by="default"
        ),
    }


def test_load_axe_config_converts_malformed_wire_to_degraded_error() -> None:
    """A malformed composition degrades; it never assigns a panel."""
    from sase.axe.config import AxeConfigError

    with patch(
        "sase.axe.config._effective_axe_composition",
        side_effect=ValueError("invalid axe inventory origin for `x`"),
    ):
        with pytest.raises(AxeConfigError) as exc_info:
            load_axe_config()
    assert exc_info.value.diagnostics[0].code == "axe_config_origin_invalid"


def test_resolve_chop_origin_prefers_instance_then_base_then_routine() -> None:
    """Generated instances resolve their own inherited entry first."""
    from sase.axe._config_targets import _resolve_chop_origin

    instance = AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
    base = AxeEntityOrigin(source="builtin", declared_by="default")
    routine = AxeEntityOrigin(source="user", declared_by="user:/conf/sase.yml")
    maps = {
        ("hooks", "fast@proj"): instance,
        ("hooks", "fast"): base,
    }
    assert (
        _resolve_chop_origin(
            lumberjack_name="hooks",
            base_name="fast",
            instance_id="fast@proj",
            routine_origin=routine,
            chop_origins=maps,
        )
        == instance
    )
    # An unmapped instance of a mapped base job inherits the base origin.
    assert (
        _resolve_chop_origin(
            lumberjack_name="hooks",
            base_name="fast",
            instance_id="other",
            routine_origin=routine,
            chop_origins=maps,
        )
        == base
    )
    # With neither instance nor base mapped, the parent routine's origin
    # is the fallback.
    assert (
        _resolve_chop_origin(
            lumberjack_name="hooks",
            base_name="slow",
            instance_id="other",
            routine_origin=routine,
            chop_origins=maps,
        )
        == routine
    )
    assert (
        _resolve_chop_origin(
            lumberjack_name="hooks",
            base_name="fast",
            instance_id="other",
            routine_origin=None,
            chop_origins=None,
        )
        is None
    )


def test_parse_lumberjacks_applies_origin_maps() -> None:
    """Projection carries inventory origins onto runtime configs."""
    from sase.axe._config_targets import parse_lumberjacks

    configs = parse_lumberjacks(
        {
            "hooks": {
                "description": "Run hooks",
                "interval": 60,
                "chops": [{"name": "fast", "description": "Fast job"}],
            }
        },
        routine_origins={
            "hooks": AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
        },
        chop_origins={
            ("hooks", "fast"): AxeEntityOrigin(
                source="plugin", declared_by="plugin:acme"
            )
        },
    )
    assert configs["hooks"].source == "plugin"
    assert configs["hooks"].declared_by == "plugin:acme"
    assert configs["hooks"].chops[0].source == "plugin"
    assert configs["hooks"].chops[0].declared_by == "plugin:acme"


def test_parse_lumberjacks_without_maps_keeps_neutral_defaults() -> None:
    """Synthetic parses without a composition stay constructible."""
    from sase.axe._config_targets import parse_lumberjacks

    configs = parse_lumberjacks(
        {
            "hooks": {
                "description": "Run hooks",
                "interval": 60,
                "chops": [{"name": "fast", "description": "Fast job"}],
            }
        }
    )
    assert configs["hooks"].source == "user"
    assert configs["hooks"].declared_by == ""
    assert configs["hooks"].chops[0].source == "user"


@patch("sase.axe.cli.load_axe_config")
def test_routine_list_shows_declaring_source(
    mock_load: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    """``sase axe routine list`` reports each routine's origin."""
    from sase.axe.cli import handle_axe_lumberjack_list

    mock_load.return_value = AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run hooks",
                interval=60,
                source="plugin",
                declared_by="plugin:acme",
            )
        }
    )
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_list(argparse.Namespace())
    assert exc_info.value.code == 0
    assert "source: plugin (plugin:acme)" in capsys.readouterr().out


def _capture_overview(snap: Any, *, width: int | None) -> Any:
    """Render the routine overview through a bare section instance."""
    from rich.text import Text

    from sase.ace.tui.widgets import axe_dashboard

    rendered: dict[str, object] = {}

    def _capture(content: Text) -> None:
        rendered["content"] = content

    section = axe_dashboard._AxeOutputSection.__new__(axe_dashboard._AxeOutputSection)
    section.update = _capture  # type: ignore[assignment]
    section.update_lumberjack_overview(snap, width=width)
    return rendered["content"]


def test_lumberjack_overview_shows_declaring_source() -> None:
    """Routine detail uses the service-proc ``Source:`` wording."""
    from sase.ace.tui.actions.axe_display._data import LumberjackSnapshot
    from sase.axe.state import LumberjackMetrics, LumberjackStatus

    rendered = _capture_overview(
        LumberjackSnapshot(
            name="hooks",
            status=LumberjackStatus(
                name="hooks",
                pid=1,
                started_at="2026-05-11T00:00:00",
                status="running",
                interval=60,
                cycles_run=3,
                errors_encountered=0,
            ),
            metrics=LumberjackMetrics(chops_executed=2),
            log_tail="",
            chops=[],
            source="builtin",
            declared_by="default",
        ),
        width=100,
    )
    assert "Source: builtin (default)" in rendered.plain


def test_lumberjack_overview_omits_source_without_origin() -> None:
    """Synthetic snapshots never claim an arbitrary source panel."""
    from sase.ace.tui.actions.axe_display._data import LumberjackSnapshot
    from sase.axe.state import LumberjackMetrics, LumberjackStatus

    rendered = _capture_overview(
        LumberjackSnapshot(
            name="hooks",
            status=LumberjackStatus(
                name="hooks",
                pid=1,
                started_at="2026-05-11T00:00:00",
                status="running",
                interval=60,
            ),
            metrics=None,
            log_tail="",
            chops=[],
        ),
        width=100,
    )
    assert "Source:" not in rendered.plain


def test_chop_run_shows_config_origin_beside_execution_source() -> None:
    """Job detail keeps configuration origin apart from run source."""
    from rich.text import Text

    from sase.ace.tui.widgets._axe_dashboard_output import AxeOutputSection
    from sase.axe.state import ChopRunEntry

    captured: dict[str, Text] = {}

    class _Section:
        def update(self, content: Text) -> None:
            captured["content"] = content

    entry = ChopRunEntry(
        run_id="20260511T100100_000000",
        lumberjack_name="hooks",
        chop_name="fast",
        started_at="2026-05-11T10:01:00",
        finished_at="2026-05-11T10:02:01",
        duration_ms=61000,
        status="success",
        source="manual",
    )
    AxeOutputSection.update_chop_run(
        _Section(),  # type: ignore[arg-type]
        "hooks",
        "fast",
        entry,
        "",
        width=70,
        source="user",
        declared_by="user:/conf/sase.yml",
    )
    plain = captured["content"].plain
    assert "Source: user (user:/conf/sase.yml)" in plain
    # Execution source still surfaces on its own card chip.
    assert "manual" in plain


def test_render_origin_detail_line_returns_none_without_source() -> None:
    """No origin means no line rather than a guessed panel claim."""
    from sase.ace.tui.widgets._axe_dashboard_output import (
        render_origin_detail_line,
    )

    assert render_origin_detail_line("", "") is None
    line = render_origin_detail_line("plugin", "plugin:acme")
    assert line is not None
    assert line.plain == "  Source: plugin (plugin:acme)"
