"""Execution tests for extracted comprehensive-update helpers."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.comprehensive_update import (
    ComprehensiveSaseUpdateResult,
    ComprehensiveUpdateResult,
    SaseUpdateResultStatus,
)
from sase.ace.tui.modals.plugins_browser_comprehensive_update_execution import (
    _execute_agents_leg,
    _execute_provider_leg,
    _execute_sase_leg,
    comprehensive_update_summary,
    run_scoped_update,
)
from sase.ace.tui.modals.plugins_browser_comprehensive_update_models import (
    ComprehensiveUpdatePreview,
    ComprehensiveUpdateRequest,
    DroppedProviderCandidate,
)
from sase.ace.tui.modals.plugins_browser_dev_update import DevUpdatePreview
from sase.ace.update_scope import UpdateLeg, UpdateScope
from sase.agent_clis.models import AgentCliNothingToUpdate, UpdateResultStatus
from sase.agents_sync.models import CachedIntegrationResult, CapturedIncomingHood


def _captured(
    project_key: str = "alpha",
    project: str = "Alpha",
    hood: str = "foo",
) -> CapturedIncomingHood:
    return CapturedIncomingHood(
        project_key=project_key,
        project=project,
        fetched_ref="refs/remotes/origin/main",
        fetched_sha="a" * 40,
        cache_id=f"{project_key}-{hood}",
        format_version=2,
        source_owner_kind="exact",
        source_username="alice",
        source_machine="zeus",
        top_hood=hood,
        hood_digest="b" * 64,
        run_count=2,
        family_count=1,
        cache_created_at=1.0,
    )


def test_run_scoped_update_continues_after_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    def providers(_preview: Any, **_kwargs: Any) -> tuple[tuple[Any, ...], str | None]:
        order.append("providers")
        return (), "provider failed"

    def sase(
        _preview: Any, _uv_tool: object | None, **_kwargs: Any
    ) -> ComprehensiveSaseUpdateResult:
        order.append("sase")
        return ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.ALREADY_CURRENT,
            "already current",
        )

    def agents(
        _preview: Any,
        **_kwargs: Any,
    ) -> tuple[tuple[CachedIntegrationResult, ...], str | None]:
        order.append("agents")
        return (
            CachedIntegrationResult(
                _captured(),
                "applied",
                hoods_imported=1,
            ),
        ), None

    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update_execution."
        "_execute_provider_leg",
        providers,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update_execution."
        "_execute_sase_leg",
        sase,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update_execution."
        "_execute_agents_leg",
        agents,
    )
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude",)),
        sase_preview=DevUpdatePreview(plan=None, subject="sase"),
    )

    result = run_scoped_update(preview, uv_tool=None)

    assert order == ["providers", "sase", "agents"]
    assert result.provider_error == "provider failed"
    assert result.agents_outcomes[0].captured.project_key == "alpha"
    assert result.selected_legs == preview.selected_legs
    assert result.has_failures is True


def test_comprehensive_summary_and_failures_include_agents_repos() -> None:
    result = ComprehensiveUpdateResult(
        sase=ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.ALREADY_CURRENT,
            "already current",
        ),
        agents_outcomes=(
            CachedIntegrationResult(
                _captured(),
                "applied",
                hoods_imported=1,
            ),
            CachedIntegrationResult(
                _captured("beta", "Beta", "bar"),
                "failed",
                diagnostics=("import failed",),
            ),
        ),
    )

    assert result.has_failures is True
    assert result.has_successful_agents_change is True
    assert result.fully_failed is False
    assert comprehensive_update_summary(result).endswith(
        "Cached agents: 1 applied, 1 failed"
    )


def test_agents_leg_integrates_exact_captured_items_without_widening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zulu = _captured("z", "Zulu", "zeta")
    alpha = _captured("a", "Alpha", "alpha")
    returned = (
        CachedIntegrationResult(zulu, "stale"),
        CachedIntegrationResult(alpha, "applied", hoods_imported=1),
    )
    calls: list[tuple[CapturedIncomingHood, ...]] = []

    def integrate(
        items: tuple[CapturedIncomingHood, ...],
    ) -> tuple[CachedIntegrationResult, ...]:
        calls.append(items)
        return returned

    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update_execution."
        "integrate_cached_agent_updates",
        integrate,
    )
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(()),
        sase_preview=None,
        sase_current=True,
        agents_updates=(zulu, alpha),
    )

    outcomes, error = _execute_agents_leg(preview)

    assert error is None
    assert calls == [(zulu, alpha)]
    assert outcomes == returned


def test_execute_provider_leg_preserves_dropped_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_pane._execute_agent_cli_updates",
        lambda _plan, **_kwargs: (),
    )
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude", "codex")),
        sase_preview=None,
        provider_plan=AgentCliNothingToUpdate(entries=(), all_clis=False),
        provider_dropped=(DroppedProviderCandidate("codex"),),
    )

    results, error = _execute_provider_leg(preview)

    assert error is None
    assert len(results) == 1
    assert results[0].name == "codex"
    assert results[0].status is UpdateResultStatus.SKIPPED


def test_execute_sase_leg_records_current_and_blockers() -> None:
    current = _execute_sase_leg(
        ComprehensiveUpdatePreview(
            request=ComprehensiveUpdateRequest(()),
            sase_preview=None,
            sase_current=True,
        ),
        uv_tool=None,
    )
    blocked = _execute_sase_leg(
        ComprehensiveUpdatePreview(
            request=ComprehensiveUpdateRequest(()),
            sase_preview=None,
            sase_blocker="not a uv tool install",
        ),
        uv_tool=None,
    )

    assert current.status is SaseUpdateResultStatus.ALREADY_CURRENT
    assert blocked.status is SaseUpdateResultStatus.SKIPPED
    assert blocked.message == "not a uv tool install"


def test_execute_agents_leg_skips_unselected_scope() -> None:
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest((), UpdateScope.SASE),
        sase_preview=None,
        agents_updates=(_captured(),),
    )

    outcomes, error = _execute_agents_leg(preview)

    assert outcomes == ()
    assert error is None


def test_run_scoped_update_records_unselected_sase_as_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update_execution."
        "_execute_sase_leg",
        lambda *_args, **_kwargs: pytest.fail("sase leg must not run"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update_execution."
        "_execute_agents_leg",
        lambda *_args, **_kwargs: pytest.fail("agents leg must not run"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update_execution."
        "_execute_provider_leg",
        lambda _preview, **_kwargs: ((), None),
    )
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude",), UpdateScope.PROVIDERS),
        sase_preview=DevUpdatePreview(plan=None, subject="sase"),
    )

    result = run_scoped_update(preview, uv_tool=None)

    assert result.sase.status is SaseUpdateResultStatus.SKIPPED
    assert result.sase.message == "not selected"
    assert result.selected_legs == frozenset({UpdateLeg.PROVIDERS})
    summary = comprehensive_update_summary(result)
    assert summary.startswith("Agent CLIs:")
    assert "SASE" not in summary
    assert "Cached agents" not in summary


def test_scoped_summary_omits_unselected_legs() -> None:
    result = ComprehensiveUpdateResult(
        sase=ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.SKIPPED,
            "not selected",
        ),
        provider_results=(),
        agents_outcomes=(
            CachedIntegrationResult(_captured(), "applied", hoods_imported=1),
        ),
        selected_legs=frozenset({UpdateLeg.AGENTS}),
    )

    assert comprehensive_update_summary(result) == "Cached agents: 1 applied"


def test_run_scoped_update_threads_reporter_and_reports_legs_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.ace.tui._session_reporter import session_reporter

    order: list[str] = []
    reporters: list[object] = []
    reporter = session_reporter(proc_type="comprehensive-update")

    def providers(_preview: Any, **kwargs: Any) -> tuple[tuple[Any, ...], str | None]:
        order.append("providers")
        reporters.append(kwargs.get("reporter"))
        kwargs["reporter"].phase("Updating agent CLIs")
        return (), "provider failed"

    def sase(
        _preview: Any, _uv_tool: object | None, **kwargs: Any
    ) -> ComprehensiveSaseUpdateResult:
        order.append("sase")
        reporters.append(kwargs.get("reporter"))
        kwargs["reporter"].phase("Resolving sase update")
        return ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.ALREADY_CURRENT,
            "already current",
        )

    def agents(
        _preview: Any, **kwargs: Any
    ) -> tuple[tuple[CachedIntegrationResult, ...], str | None]:
        order.append("agents")
        reporters.append(kwargs.get("reporter"))
        kwargs["reporter"].phase("Importing cached incoming agent hoods")
        return (
            CachedIntegrationResult(_captured(), "applied", hoods_imported=1),
        ), None

    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update_execution."
        "_execute_provider_leg",
        providers,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update_execution."
        "_execute_sase_leg",
        sase,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_comprehensive_update_execution."
        "_execute_agents_leg",
        agents,
    )
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude",)),
        sase_preview=DevUpdatePreview(plan=None, subject="sase"),
    )

    result = run_scoped_update(preview, uv_tool=None, reporter=reporter)

    assert order == ["providers", "sase", "agents"]
    assert reporters == [reporter, reporter, reporter]
    assert result.provider_error == "provider failed"
    assert result.has_failures is True
    output = reporter.proc.get_live_output()
    assert "==> Updating agent CLIs" in output
    assert "==> Resolving sase update" in output
    assert "==> Importing cached incoming agent hoods" in output


def test_provider_leg_uses_streaming_command_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.ace.tui._session_reporter import session_reporter

    reporter = session_reporter(proc_type="comprehensive-update")
    runners: list[object] = []

    def execute(_plan: Any, **kwargs: Any) -> tuple[Any, ...]:
        runners.append(kwargs.get("run_fn"))
        return ()

    monkeypatch.setattr(
        "sase.ace.tui.modals.plugins_browser_pane._execute_agent_cli_updates",
        execute,
    )
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude",)),
        sase_preview=None,
        provider_plan=AgentCliNothingToUpdate(entries=(), all_clis=False),
    )

    _execute_provider_leg(preview, reporter=reporter)

    assert runners and runners[0] is not None
    assert reporter.proc.phase == "Updating agent CLIs"
