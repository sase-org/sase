"""Pure projection coverage for Update panel state."""

from __future__ import annotations

from sase.ace.tui.update_panel_state import build_update_panel_state
from sase.ace.tui.widgets.update_accents import (
    AGENT_CLI_ACCENT,
    AGENTS_SYNC_ACCENT,
    CORE_UPDATE_ACCENT,
    UPDATES_ACCENT,
)
from sase.agents_sync.models import (
    CapturedIncomingHood,
    ProjectSyncStatus,
    SyncStatusSnapshot,
)
from sase.updates import (
    OutdatedComponent,
    ProviderUpdateCandidate,
    UpdateSourceStatus,
    UpdateStatus,
)
from sase.updates.status import ComponentRole

_NOW = 1_000.0


def _component(
    name: str,
    *,
    role: ComponentRole = "host",
) -> OutdatedComponent:
    return OutdatedComponent(
        display_name=name,
        role=role,
        installed_version="1.0.0",
        latest_version="1.1.0",
        distribution_name=name,
    )


def _candidate(
    provider: str,
    display_name: str,
    *,
    manual_only: bool = False,
) -> ProviderUpdateCandidate:
    return ProviderUpdateCandidate(
        provider,
        display_name,
        "1.0.0",
        "1.1.0",
        manual_only=manual_only,
    )


def _status(
    *,
    checked_at: float = 100.0,
    components: tuple[OutdatedComponent, ...] = (),
    providers: tuple[ProviderUpdateCandidate, ...] = (),
    core_error: str | None = None,
    plugin_error: str | None = None,
    agent_cli_error: str | None = None,
    core_known: bool = True,
    plugin_known: bool = True,
    agent_cli_known: bool = True,
) -> UpdateStatus:
    def source(
        *,
        known: bool,
        error: str | None,
    ) -> UpdateSourceStatus:
        if error is not None:
            return UpdateSourceStatus.failure(error)
        if known:
            return UpdateSourceStatus.success(checked_at)
        return UpdateSourceStatus()

    return UpdateStatus(
        checked_at=checked_at,
        components=components,
        provider_candidates=providers,
        core_source=source(known=core_known, error=core_error),
        plugin_source=source(known=plugin_known, error=plugin_error),
        agent_cli_source=source(known=agent_cli_known, error=agent_cli_error),
    )


def _captured(machine: str, hood: str = "foo") -> CapturedIncomingHood:
    return CapturedIncomingHood(
        project_key="proj",
        project="sase",
        fetched_ref="refs/remotes/origin/main",
        fetched_sha="a" * 40,
        cache_id=f"cache-{machine}-{hood}",
        format_version=2,
        source_owner_kind="exact",
        source_username="alice",
        source_machine=machine,
        top_hood=hood,
        hood_digest="b" * 64,
        run_count=1,
        family_count=1,
        cache_created_at=1.0,
    )


def _agents(
    *machines: str,
    checked_at: float = 100.0,
    error: str | None = None,
) -> SyncStatusSnapshot:
    pending = tuple(_captured(machine, hood=machine) for machine in machines)
    return SyncStatusSnapshot(
        checked_at,
        (
            ProjectSyncStatus(
                "proj",
                "sase",
                "error" if error else "ready",
                error=error,
                pending_updates=pending,
            ),
        ),
    )


def test_everything_current_projects_four_up_to_date_rows() -> None:
    state = build_update_panel_state(
        _status(checked_at=_NOW),
        SyncStatusSnapshot(_NOW),
        now=_NOW,
    )

    assert [row.scope for row in state.rows] == [
        "everything",
        "sase",
        "providers",
        "agents",
    ]
    assert [row.key for row in state.rows] == ["e", "s", "p", "a"]
    assert all(row.chip.kind == "current" for row in state.rows)
    assert all(row.chip.text == "✓ up to date" for row in state.rows)
    assert all(row.detail is None for row in state.rows)
    assert all(row.chip.count == 0 for row in state.rows)
    assert state.freshness_label == "just now"
    assert state.stale is False
    assert state.rechecking is False


def test_mixed_counts_sum_into_everything_and_show_breakdowns() -> None:
    status = _status(
        components=(
            _component("sase"),
            _component("sase-core", role="core"),
            _component("github", role="plugin"),
            _component("telegram", role="plugin"),
        ),
        providers=(
            _candidate("claude", "Claude Code"),
            _candidate("codex", "Codex CLI"),
        ),
    )
    snapshot = _agents("zeus", "hera")

    state = build_update_panel_state(status, snapshot, now=_NOW)
    everything, sase, providers, agents = state.rows

    assert everything.chip.kind == "available"
    assert everything.chip.text == "↑ 8 available"
    assert everything.chip.count == 8
    assert everything.detail is None
    assert everything.accent == "$primary"

    assert sase.chip.kind == "available"
    assert sase.chip.text == "↑ 4 available"
    assert sase.detail == "sase 1 · sase-core 1 · plugins 2 · core rebuild"
    assert sase.accent == CORE_UPDATE_ACCENT

    assert providers.chip.kind == "available"
    assert providers.chip.text == "↑ 2 available"
    assert providers.detail == "Claude Code, Codex CLI"
    assert providers.accent == AGENT_CLI_ACCENT

    assert agents.chip.kind == "available"
    assert agents.chip.text == "⇅ 2 available"
    assert agents.detail == "hera, zeus"
    assert agents.accent == AGENTS_SYNC_ACCENT


def test_core_rebuild_switches_sase_accent_without_host_plugins() -> None:
    status = _status(components=(_component("sase-core", role="core"),))
    state = build_update_panel_state(status, SyncStatusSnapshot(100.0), now=_NOW)
    sase = state.rows[1]

    assert sase.accent == CORE_UPDATE_ACCENT
    assert sase.detail == "sase-core 1 · core rebuild"
    assert state.rows[0].chip.count == 1


def test_failed_provider_source_uses_error_as_detail() -> None:
    status = _status(
        components=(_component("sase"),),
        agent_cli_error="npm registry down",
    )
    state = build_update_panel_state(status, SyncStatusSnapshot(100.0), now=_NOW)
    everything, _sase, providers, _agents = state.rows

    assert providers.chip.kind == "failed"
    assert providers.chip.text == "! check failed"
    assert providers.detail == "npm registry down"
    assert everything.chip.kind == "failed"
    assert everything.detail == "npm registry down"


def test_never_checked_app_renders_unknown_rows_and_stale_subtitle() -> None:
    state = build_update_panel_state(None, None, now=_NOW)

    assert len(state.rows) == 4
    assert all(row.chip.kind == "unknown" for row in state.rows)
    assert all(row.chip.text == "· not checked yet" for row in state.rows)
    assert all(row.detail is None for row in state.rows)
    assert state.freshness_label == "never checked — press r"
    assert state.stale is True
    assert state.rows[1].accent == UPDATES_ACCENT


def test_none_agents_snapshot_leaves_other_rows_known() -> None:
    status = _status(checked_at=_NOW, components=(_component("sase"),))
    state = build_update_panel_state(status, None, now=_NOW)
    everything, sase, providers, agents = state.rows

    assert sase.chip.kind == "available"
    assert providers.chip.kind == "current"
    assert agents.chip.kind == "unknown"
    assert everything.chip.kind == "available"
    assert everything.chip.count == 1
    assert state.freshness_label == "just now"
    assert state.stale is False


def test_manual_only_providers_append_caveat_and_truncate_names() -> None:
    status = _status(
        providers=(
            _candidate("claude", "Claude Code", manual_only=True),
            _candidate("codex", "Codex CLI"),
            _candidate("gemini", "Gemini CLI"),
            _candidate("opencode", "OpenCode"),
            _candidate("cursor", "Cursor"),
        ),
    )
    state = build_update_panel_state(status, SyncStatusSnapshot(100.0), now=_NOW)
    providers = state.rows[2]

    assert providers.chip.count == 5
    assert providers.detail == (
        "Claude Code, Codex CLI, Gemini CLI, OpenCode, +1 more · 1 needs manual steps"
    )


def test_stale_uses_newer_snapshot_and_thirty_minute_threshold() -> None:
    fresh = build_update_panel_state(
        _status(checked_at=100.0),
        SyncStatusSnapshot(820.0),
        now=_NOW,
    )
    stale = build_update_panel_state(
        _status(checked_at=100.0),
        SyncStatusSnapshot(100.0),
        now=_NOW,
    )
    exact = build_update_panel_state(
        _status(checked_at=_NOW - 30 * 60),
        None,
        now=_NOW,
    )

    assert fresh.freshness_label == "3m ago"
    assert fresh.stale is False
    assert stale.freshness_label == "15m ago"
    assert stale.stale is False
    assert exact.freshness_label == "30m ago"
    assert exact.stale is False

    past = build_update_panel_state(
        _status(checked_at=_NOW - 30 * 60 - 1),
        None,
        now=_NOW,
    )
    hours = build_update_panel_state(
        _status(checked_at=_NOW - 2 * 3600),
        None,
        now=_NOW,
    )
    days = build_update_panel_state(
        _status(checked_at=_NOW - 3 * 86400),
        None,
        now=_NOW,
    )

    assert past.stale is True
    assert past.freshness_label == "30m ago"
    assert hours.freshness_label == "2h ago"
    assert hours.stale is True
    assert days.freshness_label == "3d ago"
    assert days.stale is True


def test_rechecking_flag_does_not_change_row_projection() -> None:
    status = _status(components=(_component("sase"),))
    idle = build_update_panel_state(status, SyncStatusSnapshot(100.0), now=_NOW)
    busy = build_update_panel_state(
        status,
        SyncStatusSnapshot(100.0),
        now=_NOW,
        rechecking=True,
    )

    assert busy.rechecking is True
    assert idle.rechecking is False
    assert busy.rows == idle.rows
    assert busy.freshness_label == idle.freshness_label


def test_failed_sase_source_hides_component_breakdown() -> None:
    status = _status(
        components=(_component("sase"), _component("github", role="plugin")),
        plugin_error="registry down",
    )
    state = build_update_panel_state(status, SyncStatusSnapshot(100.0), now=_NOW)
    sase = state.rows[1]

    assert sase.chip.kind == "failed"
    assert sase.detail == "registry down"
    assert sase.chip.count == 2


def test_unknown_sources_do_not_claim_current() -> None:
    status = _status(core_known=False, plugin_known=False, agent_cli_known=False)
    state = build_update_panel_state(status, None, now=_NOW)

    assert [row.chip.kind for row in state.rows] == [
        "unknown",
        "unknown",
        "unknown",
        "unknown",
    ]
