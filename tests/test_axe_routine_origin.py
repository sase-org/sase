"""Declaring-source (origin) contract for AXE routines and jobs.

Phase ``python_origin`` of the routine-source nav-sections epic: the Rust
core reports the first declaring layer of every inventory entry as
``source`` (``builtin`` | ``plugin`` | ``user``) plus a ``declared_by``
``name:path`` label, and Python exposes that origin through the cached
config, the ``sase axe routine list`` CLI, and the Services routine/job
detail panels — without inferring anything from names or provenance.
"""

from __future__ import annotations

import argparse
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.config import (
    AxeConfig,
    ChopConfig,
    LumberjackConfig,
    load_axe_config,
)
from sase.axe.config_backend import (
    AxeConfigComposition,
    AxeEntityOrigin,
    AxeInventoryEntry,
)
from sase.config.core import ConfigLayer


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


@pytest.fixture
def _reset_axe_config_cache() -> Any:
    """Isolate the token-keyed axe composition cache per test."""
    import sase.axe.config as axe_config

    axe_config._keyed_config_cache_token = None
    axe_config._keyed_config_cache_value = None
    yield
    axe_config._keyed_config_cache_token = None
    axe_config._keyed_config_cache_value = None


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


# --- Binding-backed composition tests -------------------------------------
# These drive the real Rust composition, so they require a sase_core_rs
# built from a sase-core checkout past sase-core-revision.txt (the
# declaring-source contract). The guarded `just check` flow rebuilds the
# extension from the linked checkout before running tests.


def _config_layer(
    name: str, routine: str, body: dict[str, Any], *, path: str | None = None
) -> ConfigLayer:
    return ConfigLayer(
        name=name,
        path=path,
        exists=True,
        list_strategy="concatenate",
        data={"axe": {"lumberjacks": {routine: body}}},
    )


def _routine_body(
    description: str = "Do things",
    interval: int = 60,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "description": description,
        "interval": interval,
        "chops": [{"name": "fast", "description": "Fast job"}],
    }
    if extra:
        body.update(extra)
    return body


def _load_with_layers(layers: list[ConfigLayer]) -> AxeConfig:
    with patch("sase.axe.config.load_config_layers", return_value=layers):
        return load_axe_config()


def test_user_override_keeps_builtin_origin(
    _reset_axe_config_cache: Any,
) -> None:
    """A builtin routine with a user interval override stays builtin."""
    config = _load_with_layers(
        [
            _config_layer("default", "checks", _routine_body()),
            _config_layer(
                "user",
                "checks",
                {"interval": 5},
                path="/conf/sase.yml",
            ),
        ]
    )
    routine = config.lumberjacks["checks"]
    assert routine.interval == 5
    assert routine.source == "builtin"
    assert routine.declared_by == "default"
    assert routine.chops[0].source == "builtin"


def test_plugin_declaration_overridden_by_user_stays_plugin(
    _reset_axe_config_cache: Any,
) -> None:
    """A plugin routine with user overrides remains plugin."""
    config = _load_with_layers(
        [
            _config_layer("plugin:acme", "hooks", _routine_body()),
            _config_layer(
                "user",
                "hooks",
                {"interval": 5},
                path="/conf/sase.yml",
            ),
        ]
    )
    routine = config.lumberjacks["hooks"]
    assert routine.source == "plugin"
    assert routine.declared_by == "plugin:acme"
    assert routine.chops[0].source == "plugin"
    assert routine.chops[0].declared_by == "plugin:acme"


def test_overlay_and_local_declarations_are_user(
    _reset_axe_config_cache: Any,
) -> None:
    """Overlay and project-local declarations read as user origin."""
    config = _load_with_layers(
        [
            _config_layer(
                "overlay:work.yml",
                "overtime",
                _routine_body(),
                path="/conf/work.yml",
            ),
            _config_layer(
                "local",
                "oncall",
                _routine_body(),
                path="/proj/sase/sase.yml",
            ),
        ]
    )
    assert config.lumberjacks["overtime"].source == "user"
    assert (
        config.lumberjacks["overtime"].declared_by == "overlay:work.yml:/conf/work.yml"
    )
    assert config.lumberjacks["oncall"].source == "user"
    assert config.lumberjacks["oncall"].declared_by == "local:/proj/sase/sase.yml"


def test_job_added_under_builtin_routine_has_own_origin(
    _reset_axe_config_cache: Any,
) -> None:
    """A user job under a builtin routine is user; the routine is builtin."""
    config = _load_with_layers(
        [
            _config_layer("default", "checks", _routine_body()),
            _config_layer(
                "user",
                "checks",
                {
                    "chops": {
                        "mine": {
                            "description": "My extra job",
                            "script": "mine-script",
                        }
                    }
                },
                path="/conf/sase.yml",
            ),
        ]
    )
    routine = config.lumberjacks["checks"]
    assert routine.source == "builtin"
    by_name = {chop.name: chop for chop in routine.chops}
    assert by_name["fast"].source == "builtin"
    assert by_name["mine"].source == "user"
    assert by_name["mine"].declared_by == "user:/conf/sase.yml"


def test_project_local_routine_matches_scheduler_effective_config(
    _reset_axe_config_cache: Any,
) -> None:
    """Project-local routines are visible to the scheduler as user.

    The scheduler loads through the same ``load_axe_config`` path, so a
    local declaration the scheduler runs also labels user here.
    """
    from sase.main.axe_handler import load_axe_config_with_overrides

    layers = [
        _config_layer("default", "checks", _routine_body()),
        _config_layer(
            "local",
            "oncall",
            _routine_body(),
            path="/proj/sase/sase.yml",
        ),
    ]
    with patch("sase.axe.config.load_config_layers", return_value=layers):
        config = load_axe_config()
    assert config.lumberjacks["oncall"].source == "user"

    with patch("sase.axe.config.load_config_layers", return_value=layers):
        scheduled = load_axe_config_with_overrides(argparse.Namespace())
    assert set(scheduled.lumberjacks) == set(config.lumberjacks)
    assert scheduled.lumberjacks["oncall"].source == "user"


def test_config_token_change_invalidates_origin_map(
    _reset_axe_config_cache: Any,
) -> None:
    """New layer data recomposes origins; stale maps never linger."""
    first = _load_with_layers(
        [_config_layer("user", "hooks", _routine_body(), path="/conf/sase.yml")]
    )
    assert first.lumberjacks["hooks"].source == "user"

    second = _load_with_layers(
        [
            _config_layer("default", "hooks", _routine_body()),
            _config_layer("user", "hooks", {"interval": 5}, path="/conf/sase.yml"),
        ]
    )
    assert second.lumberjacks["hooks"].source == "builtin"
    assert second.lumberjacks["hooks"].interval == 5


def test_collector_returns_origin_maps_from_cached_config(
    _reset_axe_config_cache: Any,
) -> None:
    """The off-thread collector maps every routine/job to its origin."""
    from types import SimpleNamespace

    from sase.ace.tui.actions.axe_display import collect_axe_status_data
    from sase.ace.tui.actions.axe_display._data import AxeStatusReadCache

    config = SimpleNamespace(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run hooks",
                interval=60,
                source="plugin",
                declared_by="plugin:acme",
                chops=[
                    ChopConfig(
                        name="fast",
                        description="Fast job",
                        source="plugin",
                        declared_by="plugin:acme",
                    )
                ],
            )
        },
        chop_script_dirs=[],
    )
    with (
        patch(
            "sase.service.control.persisted_or_current_status",
            return_value=SimpleNamespace(
                host=SimpleNamespace(state="stopped"), procs=(), change_token=""
            ),
        ),
        patch("sase.axe.config.load_axe_config", return_value=config),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_status",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_metrics",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run_index",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_bgcmd_slots",
            return_value={},
        ),
    ):
        data = collect_axe_status_data(
            cache=AxeStatusReadCache(),
            include_full_snapshots=True,
            tail_chop_keys=frozenset(),
            tail_service_name=None,
        )
    assert data.lumberjack_names == ["hooks"]
    assert data.routine_origins == {
        "hooks": AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
    }
    assert data.chop_origins == {
        ("hooks", "fast"): AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
    }
    assert data.lumberjack_snapshots["hooks"].source == "plugin"
    assert data.chop_snapshots[("hooks", "fast")].source == "plugin"


def test_collector_header_payload_preserves_origin_maps() -> None:
    """Header-only ticks carry full maps so apply never drops origins."""
    from sase.ace.tui.actions.axe_display import collect_axe_status_data
    from sase.ace.tui.actions.axe_display._data import AxeStatusReadCache
    from tests.ace.tui._axe_collector_helpers import (
        FakeAxeConfig,
        lumberjack_config,
        patch_service_status,
    )

    raw = lumberjack_config("hooks", ["fast"])
    raw.source = "builtin"
    raw.declared_by = "default"
    raw.chops[0].source = "builtin"
    raw.chops[0].declared_by = "default"
    config = FakeAxeConfig({"hooks": raw})
    with (
        patch_service_status(),
        patch("sase.axe.config.load_axe_config", return_value=config),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_status",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_metrics",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_bgcmd_slots",
            return_value={},
        ),
    ):
        data = collect_axe_status_data(
            cache=AxeStatusReadCache(),
            include_full_snapshots=False,
            tail_chop_keys=frozenset(),
            tail_service_name=None,
        )
    assert data.lumberjack_names == ["hooks"]
    assert data.routine_origins["hooks"].source == "builtin"
    assert data.chop_origins[("hooks", "fast")].source == "builtin"


def _apply_payload(
    *,
    names: list[str],
    origins: dict[str, AxeEntityOrigin],
    chop_origins: dict[tuple[str, str], AxeEntityOrigin] | None = None,
    full: bool = True,
) -> Any:
    """Build a minimal collector payload carrying names plus origins."""
    from sase.ace.tui.actions.axe_display._data import AxeCollectedData

    return AxeCollectedData(
        axe_running=False,
        axe_output="",
        lumberjack_names=names,
        bgcmd_slots=[],
        lumberjack_statuses={},
        lumberjack_metrics={},
        lumberjack_log_tails={},
        bgcmd_details={},
        lumberjack_chop_names={name: [] for name in names},
        routine_origins=origins,
        chop_origins=chop_origins or {},
        chop_snapshots={},
        lumberjack_snapshots={},
        include_full_snapshots=full,
    )


class _ApplyFake:
    """Minimal harness driving the collector apply path without Textual."""

    def __init__(self) -> None:
        from sase.ace.tui.actions.axe_display import AxeDisplayMixin

        self._apply = AxeDisplayMixin._apply_axe_status_data
        self._settle = AxeDisplayMixin._settle_bgcmd_slots
        self._reconcile = AxeDisplayMixin._reconcile_chop_run_offsets
        self._slot_visible = AxeDisplayMixin._bgcmd_slot_visible
        self.current_tab = "services"
        self.current_idx = 0
        self.refresh_interval = 10
        self.axe_running = False
        self._countdown_remaining = 10
        self._axe_output = ""
        self._axe_pinned_to_bottom = False
        self._axe_cmds_hidden = False
        self._axe_current_view: Any = "axe"
        self._bgcmd_slots: list[Any] = []
        self._bgcmd_pending_slots: dict[Any, Any] = {}
        self._bgcmd_dismissed: set[str] = set()
        self._bgcmd_focus_slot = None
        self._axe_lumberjack_names: list[str] = []
        self._axe_routine_origins: dict[str, AxeEntityOrigin] = {}
        self._axe_chop_origins: dict[tuple[str, str], AxeEntityOrigin] = {}
        self._axe_lumberjack_idx = None
        self._axe_items: list[Any] = []
        self._axe_chop_selection = None
        self._axe_first_load_done = True
        self._axe_lumberjack_statuses: dict[str, Any] = {}
        self._axe_lumberjack_metrics: dict[str, Any] = {}
        self._axe_lumberjack_log_tails: dict[str, str] = {}
        self._axe_bgcmd_details: dict[Any, Any] = {}
        self._axe_lumberjack_chop_names: dict[str, list[str]] = {}
        self._axe_chop_snapshots: dict[Any, Any] = {}
        self._axe_chop_run_offsets: dict[Any, Any] = {}
        self._axe_lumberjack_snapshots: dict[str, Any] = {}
        self._axe_tailed_chops: set[Any] = set()
        self._axe_degraded_status = None
        self._service_status = None
        self._service_status_error = None
        self._service_log_tails: dict[str, str] = {}
        self._service_tailed_names: set[str] = set()

    # Bound-mixin helpers the apply path reaches for.
    def _set_axe_starting(self, *_a: Any) -> None:
        return None

    def _set_axe_restarting(self, *_a: Any) -> None:
        return None

    def _set_axe_stopping(self, *_a: Any) -> None:
        return None

    def _settle_bgcmd_slots(self, slots: Any) -> Any:
        return self._settle(self, slots)  # type: ignore[arg-type]

    def _bgcmd_slot_visible(self, slot: Any, info: Any) -> bool:
        return self._slot_visible(self, slot, info)  # type: ignore[arg-type]

    def _reconcile_chop_run_offsets(self, snapshots: Any) -> None:
        self._reconcile(self, snapshots)  # type: ignore[arg-type]

    def _update_axe_keybinding(self) -> None:
        return None

    def _update_bgcmd_count(self) -> None:
        return None

    def _build_axe_items(self) -> None:
        return None

    def _refresh_axe_display(self) -> None:
        return None

    def apply(self, data: Any) -> None:
        self._apply(self, data)  # type: ignore[arg-type]


def test_apply_sets_names_and_origins_atomically() -> None:
    """One collect lands names and origins together, never half-applied."""
    app = _ApplyFake()
    app.apply(
        _apply_payload(
            names=["hooks"],
            origins={
                "hooks": AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
            },
            chop_origins={
                ("hooks", "fast"): AxeEntityOrigin(
                    source="plugin", declared_by="plugin:acme"
                )
            },
        )
    )
    assert app._axe_lumberjack_names == ["hooks"]
    assert app._axe_routine_origins == {
        "hooks": AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
    }
    assert app._axe_chop_origins == {
        ("hooks", "fast"): AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
    }


def test_apply_replaces_stale_origins_on_config_change() -> None:
    """A removed routine's origin leaves with its name (header-safe)."""
    app = _ApplyFake()
    app.apply(
        _apply_payload(
            names=["hooks", "checks"],
            origins={
                "hooks": AxeEntityOrigin(source="plugin", declared_by="plugin:acme"),
                "checks": AxeEntityOrigin(source="builtin", declared_by="default"),
            },
        )
    )
    # Header-only tick after the user deletes a routine: the payload
    # carries the fresh complete maps, so no stale origin survives.
    app.apply(
        _apply_payload(
            names=["hooks"],
            origins={
                "hooks": AxeEntityOrigin(source="plugin", declared_by="plugin:acme")
            },
            full=False,
        )
    )
    assert app._axe_lumberjack_names == ["hooks"]
    assert set(app._axe_routine_origins) == {"hooks"}


@pytest.mark.asyncio
async def test_targeted_chop_refresh_preserves_origin() -> None:
    """The `y` fast path re-reads runs, never the chop's origin."""
    from sase.ace.tui.actions.axe_display import (
        AxeDisplayMixin,
        ChopSnapshot,
    )
    from sase.ace.tui.widgets.bgcmd_list import ChopItem, LumberjackItem

    class _TargetedFake(AxeDisplayMixin):
        def __init__(self) -> None:
            self.current_tab: Any = "services"
            self.current_idx = 1
            self._axe_current_view: Any = "axe"
            self._axe_lumberjack_names = ["hooks"]
            self._axe_lumberjack_idx = 0
            self._axe_items: list[Any] = [
                LumberjackItem(name="hooks"),
                ChopItem(lumberjack_name="hooks", chop_name="fast"),
            ]
            self._axe_chop_selection = None
            self._axe_chop_snapshots = {
                ("hooks", "fast"): ChopSnapshot(
                    lumberjack_name="hooks",
                    chop_name="fast",
                    description="",
                    runs=[],
                    source="builtin",
                    declared_by="default",
                )
            }
            self._axe_chop_run_offsets = {}
            self._axe_lumberjack_snapshots = {}
            self._axe_tailed_chops: set[Any] = set()
            self._axe_targeted_refresh_running = False
            self._axe_targeted_refresh_pending = False
            self._axe_targeted_refresh_scheduled = False

        def _refresh_axe_display(self) -> None:  # type: ignore[override]
            return None

    app = _TargetedFake()
    with patch(
        "sase.ace.tui.actions.axe_display._data.read_chop_run_index",
        return_value=[],
    ):
        await app._refresh_selected_axe_item_async()  # type: ignore[attr-defined]
    snap = app._axe_chop_snapshots[("hooks", "fast")]
    assert snap.source == "builtin"
    assert snap.declared_by == "default"
