"""Pure projection coverage for Update panel state."""

from __future__ import annotations

from sase.ace.tui.update_panel_state import (
    _PROVIDER_DETAIL_LIMIT,
    _PROVIDER_NAME_LIMIT,
    build_update_panel_state,
)
from sase.ace.tui.stale_running_code import RunningCodeRoot, RunningCodeState
from sase.ace.tui.widgets.update_accents import (
    AGENT_CLI_ACCENT,
    UPDATE_CAUTION_ACCENT,
    UPDATE_GLYPH,
    UPDATES_ACCENT,
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
    installed: str = "1.0.0",
    latest: str = "1.1.0",
) -> ProviderUpdateCandidate:
    return ProviderUpdateCandidate(
        provider,
        display_name,
        installed,
        latest,
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


def test_everything_current_projects_three_up_to_date_rows() -> None:
    state = build_update_panel_state(
        _status(checked_at=_NOW),
        now=_NOW,
    )

    assert [row.scope for row in state.rows] == [
        "everything",
        "sase",
        "providers",
    ]
    assert [row.key for row in state.rows] == ["e", "s", "p"]
    assert all(row.chip.kind == "current" for row in state.rows)
    assert all(row.chip.text == "✓ up to date" for row in state.rows)
    assert all(row.details == () for row in state.rows)
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

    state = build_update_panel_state(status, now=_NOW)
    everything, sase, providers = state.rows

    assert everything.chip.kind == "available"
    assert everything.chip.text == f"{UPDATE_GLYPH} 6 available"
    assert everything.chip.count == 6
    assert everything.details == (
        "sase 1 · sase-core 1 · plugins 2 · core rebuild · providers 2",
    )
    assert everything.accent == "$primary"
    assert everything.chip.core_rebuild is True

    assert sase.chip.kind == "available"
    assert sase.chip.text == f"{UPDATE_GLYPH} 4 available"
    assert sase.details == ("sase 1 · sase-core 1 · plugins 2 · core rebuild",)
    assert sase.accent == UPDATES_ACCENT
    assert sase.chip.core_rebuild is True

    assert providers.chip.kind == "available"
    assert providers.chip.text == f"{UPDATE_GLYPH} 2 available"
    assert providers.details == (
        "• Claude Code  1.0.0 → 1.1.0",
        "• Codex CLI    1.0.0 → 1.1.0",
    )
    assert providers.accent == AGENT_CLI_ACCENT


def test_core_rebuild_keeps_sase_accent_and_marks_rebuild() -> None:
    status = _status(components=(_component("sase-core", role="core"),))
    state = build_update_panel_state(status, now=_NOW)
    sase = state.rows[1]

    assert sase.accent == UPDATES_ACCENT
    assert sase.chip.core_rebuild is True
    assert sase.details == ("sase-core 1 · core rebuild",)
    assert state.rows[0].details == ("sase-core 1 · core rebuild",)
    assert state.rows[0].chip.count == 1
    assert state.rows[0].chip.core_rebuild is True
    assert state.rows[2].chip.core_rebuild is False


def test_failed_provider_source_uses_error_as_detail() -> None:
    status = _status(
        components=(_component("sase"),),
        agent_cli_error="npm registry down",
    )
    state = build_update_panel_state(status, now=_NOW)
    everything, _sase, providers = state.rows

    assert providers.chip.kind == "failed"
    assert providers.chip.text == "! check failed"
    assert providers.details == ("npm registry down",)
    assert everything.chip.kind == "failed"
    assert everything.details == ("npm registry down",)


def test_never_checked_app_renders_unknown_rows_and_stale_subtitle() -> None:
    state = build_update_panel_state(None, now=_NOW)

    assert len(state.rows) == 3
    assert all(row.chip.kind == "unknown" for row in state.rows)
    assert all(row.chip.text == "· not checked yet" for row in state.rows)
    assert all(row.details == () for row in state.rows)
    assert state.freshness_label == "never checked — press r"
    assert state.stale is True
    assert state.rows[1].accent == UPDATES_ACCENT


def test_provider_details_carry_installed_to_latest_per_candidate() -> None:
    status = _status(
        providers=(
            _candidate("claude", "Claude Code", installed="2.1.0", latest="2.2.0"),
            _candidate("gemini", "Gemini CLI", installed="0.9.1", latest="1.4.0"),
        ),
    )
    providers = build_update_panel_state(status, now=_NOW).rows[2]

    assert providers.chip.count == 2
    assert providers.details == (
        "• Claude Code  2.1.0 → 2.2.0",
        "• Gemini CLI   0.9.1 → 1.4.0",
    )


def test_manual_only_provider_is_marked_by_name_without_aggregate_clause() -> None:
    status = _status(
        providers=(
            _candidate("claude", "Claude Code"),
            _candidate("codex", "Codex CLI", manual_only=True),
        ),
    )
    providers = build_update_panel_state(status, now=_NOW).rows[2]

    assert providers.details == (
        "• Claude Code  1.0.0 → 1.1.0",
        "• Codex CLI    1.0.0 → 1.1.0 · manual steps",
    )
    assert not any("needs manual steps" in line for line in providers.details)
    assert not any("need manual steps" in line for line in providers.details)


def test_missing_installed_version_renders_unknown() -> None:
    status = _status(
        providers=(_candidate("gemini", "Gemini CLI", installed="", latest="1.4.0"),),
    )
    providers = build_update_panel_state(status, now=_NOW).rows[2]

    assert providers.details == ("• Gemini CLI  unknown → 1.4.0",)


def test_provider_details_are_capped_with_overflow_line() -> None:
    names = ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel")
    status = _status(providers=tuple(_candidate(name.lower(), name) for name in names))
    providers = build_update_panel_state(status, now=_NOW).rows[2]

    assert providers.chip.count == 8
    assert len(providers.details) == _PROVIDER_DETAIL_LIMIT + 1
    assert providers.details[0].startswith("• Alpha    ")
    assert providers.details[_PROVIDER_DETAIL_LIMIT - 1].startswith("• Foxtrot")
    assert providers.details[-1] == "• +2 more providers"


def test_single_hidden_provider_uses_singular_overflow_noun() -> None:
    names = ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf")
    status = _status(providers=tuple(_candidate(name.lower(), name) for name in names))
    providers = build_update_panel_state(status, now=_NOW).rows[2]

    assert providers.details[-1] == "• +1 more provider"


def test_long_provider_name_is_truncated_and_columns_stay_aligned() -> None:
    long_name = "An Extremely Long Provider Display Name"
    status = _status(
        providers=(
            _candidate("long", long_name),
            _candidate("codex", "Codex CLI"),
        ),
    )
    providers = build_update_panel_state(status, now=_NOW).rows[2]

    truncated = long_name[: _PROVIDER_NAME_LIMIT - 1] + "…"
    assert providers.details == (
        f"• {truncated}  1.0.0 → 1.1.0",
        f"• {'Codex CLI'.ljust(_PROVIDER_NAME_LIMIT)}  1.0.0 → 1.1.0",
    )
    assert len({line.index("1.0.0") for line in providers.details}) == 1


def test_failed_provider_source_projects_no_per_provider_lines() -> None:
    status = _status(
        providers=(_candidate("claude", "Claude Code", manual_only=True),),
        agent_cli_error="npm registry down",
    )
    providers = build_update_panel_state(status, now=_NOW).rows[2]

    assert providers.chip.kind == "failed"
    assert providers.details == ("npm registry down",)


def test_everything_summary_combines_both_legs_with_manual_parenthetical() -> None:
    status = _status(
        components=(_component("sase"), _component("github", role="plugin")),
        providers=(
            _candidate("claude", "Claude Code", manual_only=True),
            _candidate("codex", "Codex CLI"),
        ),
    )
    everything = build_update_panel_state(status, now=_NOW).rows[0]

    assert everything.details == ("sase 1 · plugins 1 · providers 2 (1 manual)",)


def test_everything_summary_omits_manual_parenthetical_at_zero() -> None:
    status = _status(
        components=(_component("sase"),),
        providers=(_candidate("codex", "Codex CLI"),),
    )
    everything = build_update_panel_state(status, now=_NOW).rows[0]

    assert everything.details == ("sase 1 · providers 1",)


def test_everything_summary_omits_a_leg_without_work() -> None:
    providers_only = build_update_panel_state(
        _status(providers=(_candidate("codex", "Codex CLI", manual_only=True),)),
        now=_NOW,
    ).rows[0]
    sase_only = build_update_panel_state(
        _status(components=(_component("sase"),)),
        now=_NOW,
    ).rows[0]

    assert providers_only.details == ("providers 1 (1 manual)",)
    assert sase_only.details == ("sase 1",)


def test_everything_failed_source_takes_precedence_over_summary() -> None:
    status = _status(
        components=(_component("sase"),),
        providers=(_candidate("codex", "Codex CLI"),),
        plugin_error="registry down",
    )
    everything = build_update_panel_state(status, now=_NOW).rows[0]

    assert everything.chip.kind == "failed"
    assert everything.details == ("registry down",)


def test_stale_uses_thirty_minute_threshold() -> None:
    fresh = build_update_panel_state(
        _status(checked_at=820.0),
        now=_NOW,
    )
    stale = build_update_panel_state(
        _status(checked_at=100.0),
        now=_NOW,
    )
    exact = build_update_panel_state(
        _status(checked_at=_NOW - 30 * 60),
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
        now=_NOW,
    )
    hours = build_update_panel_state(
        _status(checked_at=_NOW - 2 * 3600),
        now=_NOW,
    )
    days = build_update_panel_state(
        _status(checked_at=_NOW - 3 * 86400),
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
    idle = build_update_panel_state(status, now=_NOW)
    busy = build_update_panel_state(
        status,
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
    state = build_update_panel_state(status, now=_NOW)
    sase = state.rows[1]

    assert sase.chip.kind == "failed"
    assert sase.details == ("registry down",)
    assert sase.chip.count == 2


def test_unknown_sources_do_not_claim_current() -> None:
    status = _status(core_known=False, plugin_known=False, agent_cli_known=False)
    state = build_update_panel_state(status, now=_NOW)

    assert [row.chip.kind for row in state.rows] == [
        "unknown",
        "unknown",
        "unknown",
    ]


def test_stale_running_code_adds_restart_row_with_commit_preview() -> None:
    state = build_update_panel_state(
        _status(checked_at=_NOW),
        now=_NOW,
        running_code=RunningCodeState(
            roots=(
                RunningCodeRoot(
                    label="sase",
                    git_root="/repo/sase",
                    imported_sha="1" * 40,
                    current_sha="2" * 40,
                    git_dir="/repo/sase/.git",
                    head_path="/repo/sase/.git/refs/heads/main",
                    packed_refs_path="/repo/sase/.git/packed-refs",
                    token=object(),  # type: ignore[arg-type]
                    incoming=None,
                ),
            )
        ),
    )

    restart, everything, *_rest = state.rows
    assert restart.scope == "restart"
    assert restart.key == "x"
    assert restart.chip.kind == "stale"
    assert restart.chip.text == "↻ code changed"
    assert restart.details == ("sase: 111111111..222222222",)
    assert restart.accent == UPDATE_CAUTION_ACCENT
    assert restart.chip.core_rebuild is False
    assert everything.scope == "everything"
    assert state.stale is True


def test_sase_accent_stays_lime_without_core_update() -> None:
    status = _status(components=(_component("sase"),))
    state = build_update_panel_state(status, now=_NOW)
    everything, sase, providers = state.rows

    assert sase.accent == UPDATES_ACCENT
    assert sase.chip.core_rebuild is False
    assert everything.chip.core_rebuild is False
    assert providers.chip.core_rebuild is False
    assert sase.chip.text == f"{UPDATE_GLYPH} 1 available"


def test_core_rebuild_never_marks_providers_or_failed_rows() -> None:
    status = _status(
        components=(_component("sase-core", role="core"),),
        providers=(_candidate("claude", "Claude Code"),),
    )
    state = build_update_panel_state(status, now=_NOW)
    everything, sase, providers = state.rows

    assert sase.chip.core_rebuild is True
    assert everything.chip.core_rebuild is True
    assert providers.chip.core_rebuild is False

    failed = build_update_panel_state(
        _status(
            components=(_component("sase-core", role="core"),), plugin_error="down"
        ),
        now=_NOW,
    )
    assert all(row.chip.core_rebuild is False for row in failed.rows)
