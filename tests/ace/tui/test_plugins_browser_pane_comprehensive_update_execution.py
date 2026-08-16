"""Execution and completion tests for comprehensive Updates-pane flows."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.comprehensive_update import (
    ComprehensiveSaseUpdateResult,
    ComprehensiveUpdateResult,
    SaseUpdateResultStatus,
)
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugins_browser_comprehensive_update import (
    ComprehensiveUpdateActionsMixin,
    ComprehensiveUpdateRequest,
    _comprehensive_update_summary,
    _ComprehensiveUpdatePreview,
)
from sase.agents_sync.models import CachedIntegrationResult, CapturedIncomingHood
from tests.ace.tui._proc_submit_signature_helpers import (
    assert_session_worker_submit_signature,
)


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


class _Reporter:
    def phase(self, _label: str) -> None:
        pass

    def section(self, _title: str) -> None:
        pass

    def log(self, _text: str, *, stream: str = "stdout") -> None:
        del stream


class _SubmitApp:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.submitted: tuple[tuple[Any, ...], dict[str, Any]] | None = None

    def _submit_session_worker(self, *args: Any, **kwargs: Any) -> object:
        assert_session_worker_submit_signature(args, kwargs)
        self.submitted = (args, kwargs)
        return None if self.reject else object()


class _ExecutionHarness(ComprehensiveUpdateActionsMixin):
    def __init__(self) -> None:
        self.app = _SubmitApp()
        self.order: list[str] = []

    def _execute_provider_leg(
        self, _preview: Any
    ) -> tuple[tuple[Any, ...], str | None]:
        self.order.append("providers")
        return (), "provider failed"

    def _execute_comprehensive_sase_leg(
        self, _preview: Any
    ) -> ComprehensiveSaseUpdateResult:
        self.order.append("sase")
        return ComprehensiveSaseUpdateResult(
            SaseUpdateResultStatus.ALREADY_CURRENT,
            "already current",
        )

    def _execute_agents_leg(
        self, _preview: Any
    ) -> tuple[tuple[CachedIntegrationResult, ...], str | None]:
        self.order.append("agents")
        return (
            CachedIntegrationResult(
                _captured(),
                "applied",
                hoods_imported=1,
            ),
        ), None

    def _on_comprehensive_update_complete(self, _completion: Any) -> None:
        pass


def test_comprehensive_task_claims_both_scopes_and_continues_after_provider_failure() -> (
    None
):
    harness = _ExecutionHarness()
    preview = _ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude",)),
        sase_preview=pbp._DevUpdatePreview(plan=None, subject="sase"),
    )

    assert harness._submit_comprehensive_update_task(preview) is True
    assert harness.app.submitted is not None
    args, kwargs = harness.app.submitted
    assert kwargs["exclusive_scopes"] == (
        "sase-update",
        "agent-cli-update",
        "agents-sync",
    )
    assert kwargs["dedup_key"] == "comprehensive-update"
    assert (
        kwargs["duplicate_message"]
        == "A SASE, agent CLI, or agents-repository update is already running."
    )

    task_result = args[1]()
    assert harness.order == ["providers", "sase", "agents"]
    assert task_result.success is False
    assert task_result.payload is not None
    assert task_result.payload.provider_error == "provider failed"
    assert task_result.payload.agents_outcomes[0].captured.project_key == "alpha"


def test_comprehensive_task_reports_submit_collision() -> None:
    harness = _ExecutionHarness()
    harness.app = _SubmitApp(reject=True)
    preview = _ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude",)),
        sase_preview=pbp._DevUpdatePreview(plan=None, subject="sase"),
    )

    assert harness._submit_comprehensive_update_task(preview) is False
    assert harness.app.submitted is not None


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
    assert _comprehensive_update_summary(result).endswith(
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
    preview = _ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(()),
        sase_preview=None,
        sase_current=True,
        agents_updates=(zulu, alpha),
    )
    harness = ComprehensiveUpdateActionsMixin.__new__(ComprehensiveUpdateActionsMixin)

    outcomes, error = harness._execute_agents_leg(preview)

    assert error is None
    assert calls == [(zulu, alpha)]
    assert outcomes == returned


def test_comprehensive_completion_refreshes_both_shared_indicators() -> None:
    class _App:
        def __init__(self) -> None:
            self.updates_refreshes = 0
            self.agents_refreshes = 0
            self.agent_list_refreshes: list[str] = []

        def _schedule_updates_indicator_revalidation(self) -> None:
            self.updates_refreshes += 1

        def _schedule_agents_sync_indicator_revalidation(self) -> None:
            self.agents_refreshes += 1

        def _schedule_agents_async_refresh(self, *, source: str) -> None:
            self.agent_list_refreshes.append(source)

    class _Harness(ComprehensiveUpdateActionsMixin):
        def __init__(self) -> None:
            self.app = _App()
            self._agent_cli_results: dict[str, object] = {}
            self.is_mounted = False
            self._loading = False
            self.messages: list[str] = []

        def _notify(self, message: str, **_kwargs: object) -> None:
            self.messages.append(message)

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
        ),
    )
    harness = _Harness()

    harness._on_comprehensive_update_complete(
        SimpleNamespace(payload=result, error=None, message="done")
    )

    assert harness.app.updates_refreshes == 1
    assert harness.app.agents_refreshes == 1
    assert harness.app.agent_list_refreshes == ["comprehensive_cached_agents"]
