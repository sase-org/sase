"""Direct tests for pane-free, scope-aware comprehensive update previews."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.ace.tui.modals.plugins_browser_comprehensive_update_models import (
    ComprehensiveUpdatePreview,
    ComprehensiveUpdateRequest,
)
from sase.ace.tui.modals.plugins_browser_comprehensive_update_preview import (
    build_comprehensive_update_preview,
    comprehensive_confirm_copy,
    _comprehensive_current_message,
    _comprehensive_dropped_message,
    comprehensive_preview_sections,
    handle_comprehensive_noop,
    _plan_captured_providers,
)
from sase.ace.tui.modals.plugins_browser_dev_update import DevUpdatePreview
from sase.ace.tui.update_preview_inputs import (
    UpdatePreviewInputs,
    collect_update_preview_inputs,
)
from sase.ace.update_scope import ALL_LEGS, UpdateLeg, UpdateScope
from sase.dev_update.models import DevUpdatePlan
from sase.updates import UpdateSourceStatus, UpdateStatus
from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason
from tests.ace.tui._plugins_browser_pane_helpers import _agent_cli_statuses
from tests.ace.tui._plugins_browser_pane_update_helpers import _dev_plan

_PREVIEW_MOD = "sase.ace.tui.modals.plugins_browser_comprehensive_update_preview"
_INPUTS_MOD = "sase.ace.tui.update_preview_inputs"


def _inputs(**overrides: object) -> UpdatePreviewInputs:
    values: dict[str, object] = {
        "uv_tool": None,
        "agent_cli_statuses": (),
        "agent_cli_error": None,
        "offline": False,
        "cached_status": None,
    }
    values.update(overrides)
    return UpdatePreviewInputs(**values)  # type: ignore[arg-type]


def _current_status() -> UpdateStatus:
    return UpdateStatus(
        checked_at=1.0,
        components=(),
        core_source=UpdateSourceStatus.success(1.0),
        plugin_source=UpdateSourceStatus.success(1.0),
    )


def _fresh_current_dev_plan() -> DevUpdatePlan:
    plan = _dev_plan(status="skipped")
    package = replace(
        plan.packages[0],
        reason="already current",
        latest_version=plan.packages[0].current_version,
        ahead=0,
        behind=0,
        fetch_error=None,
    )
    root = replace(
        plan.roots[0],
        reason="already current",
        ahead=0,
        behind=0,
        fetch_error=None,
    )
    return replace(plan, packages=(package,), roots=(root,), reconcile_steps=())


def _section_titles(preview: ComprehensiveUpdatePreview) -> list[str]:
    return [section.title for section in comprehensive_preview_sections(preview)]


def _manual_provider_preview(
    *, scope: UpdateScope = UpdateScope.EVERYTHING
) -> ComprehensiveUpdatePreview:
    claude, codex, _qwen = _agent_cli_statuses()
    current_claude = replace(
        claude,
        latest_version=claude.installed_version,
        update_available=False,
    )
    plan, dropped, error = _plan_captured_providers(
        ("claude", "codex"),
        (current_claude, codex),
        offline=False,
    )
    return ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude", "codex"), scope),
        sase_preview=None,
        sase_current=scope is UpdateScope.EVERYTHING,
        provider_plan=plan,
        provider_dropped=dropped,
        provider_error=error,
    )


def test_update_scope_legs() -> None:
    assert UpdateScope.EVERYTHING.legs == ALL_LEGS
    assert UpdateScope.SASE.legs == frozenset({UpdateLeg.SASE})
    assert UpdateScope.PROVIDERS.legs == frozenset({UpdateLeg.PROVIDERS})


def test_collect_update_preview_inputs_skips_unneeded_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes: list[str] = []
    collects: list[dict[str, object]] = []

    monkeypatch.setattr(
        f"{_INPUTS_MOD}.probe_uv_tool",
        lambda: probes.append("sase") or object(),
    )

    def _collect(**kwargs: object) -> tuple[()]:
        collects.append(dict(kwargs))
        return ()

    monkeypatch.setattr(f"{_INPUTS_MOD}.collect_agent_cli_statuses", _collect)

    collect_update_preview_inputs(cached_status=None, legs={UpdateLeg.SASE})
    assert probes == ["sase"]
    assert collects == []

    collect_update_preview_inputs(cached_status=None, legs={UpdateLeg.PROVIDERS})
    assert collects == [{"refresh": False, "offline": False}]


def test_collect_update_preview_inputs_captures_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("registry down")

    monkeypatch.setattr(f"{_INPUTS_MOD}.collect_agent_cli_statuses", _boom)

    inputs = collect_update_preview_inputs(
        cached_status=None, legs={UpdateLeg.PROVIDERS}
    )

    assert inputs.agent_cli_statuses == ()
    assert inputs.agent_cli_error == "registry down"


def test_build_preview_everything_plans_selected_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_calls: list[object] = []
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.make_sase_dev_update_preview",
        lambda receipt, **_kwargs: (
            make_calls.append(receipt) or DevUpdatePreview(plan=None, subject="sase")
        ),
    )

    preview = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest(("claude",)),
        _inputs(agent_cli_statuses=_agent_cli_statuses()),
    )

    assert preview.selected_legs == ALL_LEGS
    assert preview.sase_runnable is True
    assert preview.provider_runnable is True
    assert make_calls
    assert _section_titles(preview) == [
        "SASE, core & plugins",
        "Agent CLIs",
    ]


def test_build_preview_sase_scope_omits_other_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.make_sase_dev_update_preview",
        lambda _receipt, **_kwargs: DevUpdatePreview(plan=None, subject="sase"),
    )
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}._plan_captured_providers",
        lambda *_args, **_kwargs: pytest.fail("provider leg must not run"),
    )

    preview = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest(("claude",), UpdateScope.SASE),
        _inputs(),
    )
    sections = comprehensive_preview_sections(preview)

    assert preview.selected_legs == frozenset({UpdateLeg.SASE})
    assert preview.sase_runnable is True
    assert preview.provider_plan is None
    assert [section.title for section in sections] == ["SASE, core & plugins"]
    assert all("skip" not in section.summary.lower() for section in sections)


def test_build_preview_providers_scope_omits_other_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.make_sase_dev_update_preview",
        lambda *_args, **_kwargs: pytest.fail("sase leg must not run"),
    )

    preview = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest(("claude",), UpdateScope.PROVIDERS),
        _inputs(agent_cli_statuses=_agent_cli_statuses()),
    )

    assert preview.sase_runnable is False
    assert preview.sase_current is False
    assert preview.provider_runnable is True
    assert _section_titles(preview) == ["Agent CLIs"]


def test_cached_current_status_still_runs_sase_planner_for_editables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _dev_plan()
    make_calls: list[tuple[object, dict[str, object]]] = []

    def _make(receipt: object, **kwargs: object) -> DevUpdatePreview:
        make_calls.append((receipt, dict(kwargs)))
        return DevUpdatePreview(plan=plan, subject="sase")

    monkeypatch.setattr(f"{_PREVIEW_MOD}.make_sase_dev_update_preview", _make)

    preview = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest(()),
        _inputs(cached_status=_current_status()),
    )

    assert make_calls == [(None, {"already_refreshed_roots": frozenset()})]
    assert preview.sase_current is False
    assert preview.sase_runnable is True
    assert preview.sase_preview is not None
    assert preview.sase_preview.plan is plan


def test_fresh_current_sase_plan_reports_current_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.make_sase_dev_update_preview",
        lambda _receipt, **_kwargs: DevUpdatePreview(
            plan=_fresh_current_dev_plan(),
            subject="sase",
        ),
    )

    preview = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest((), UpdateScope.SASE),
        _inputs(cached_status=_current_status()),
    )
    notes: list[tuple[str, str]] = []

    handle_comprehensive_noop(
        preview,
        notify=lambda message, *, severity="information": notes.append(
            (message, severity)
        ),
    )

    assert preview.sase_current is True
    assert preview.sase_runnable is False
    assert preview.sase_blocker is None
    assert notes == [
        (
            "SASE, core, and plugins in the captured update are already current.",
            "information",
        )
    ]


def test_non_currency_sase_noop_keeps_blocking_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.make_sase_dev_update_preview",
        lambda _receipt, **_kwargs: DevUpdatePreview(
            plan=_dev_plan(status="skipped"),
            subject="sase",
        ),
    )

    preview = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest((), UpdateScope.SASE),
        _inputs(cached_status=_current_status()),
    )

    assert preview.sase_current is False
    assert preview.sase_runnable is False
    assert preview.sase_blocker == "sase-github: checkout has local changes"


def test_cached_current_managed_only_preview_keeps_current_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_calls: list[object] = []
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.make_sase_dev_update_preview",
        lambda receipt, **_kwargs: (
            make_calls.append(receipt) or DevUpdatePreview(plan=None, subject="sase")
        ),
    )

    preview = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest((), UpdateScope.SASE),
        _inputs(cached_status=_current_status()),
    )

    assert make_calls == [None]
    assert preview.sase_current is True
    assert preview.sase_runnable is False
    assert preview.sase_preview is None


def test_missing_or_failed_cache_does_not_claim_sase_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.make_sase_dev_update_preview",
        lambda _receipt, **_kwargs: DevUpdatePreview(plan=None, subject="sase"),
    )
    failed = UpdateStatus(
        checked_at=1.0,
        components=(),
        core_source=UpdateSourceStatus.failure("core down"),
        plugin_source=UpdateSourceStatus.success(1.0),
    )

    missing = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest((), UpdateScope.SASE),
        _inputs(),
    )
    failed_preview = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest((), UpdateScope.SASE),
        _inputs(cached_status=failed),
    )

    assert missing.sase_current is False
    assert failed_preview.sase_current is False
    assert missing.sase_runnable is True
    assert failed_preview.sase_runnable is True


def test_not_uv_tool_install_blocks_sase_leg() -> None:
    preview = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest((), UpdateScope.SASE),
        _inputs(
            uv_tool=NotUvToolInstall(
                reason=NotUvToolReason.UV_MISSING,
                sys_prefix=Path("/venv"),
                expected_sase_dir=Path("/t/sase"),
                receipt_path=Path("/t/sase/uv-receipt.toml"),
            )
        ),
    )

    assert preview.sase_runnable is False
    assert preview.sase_blocker is not None


@pytest.mark.parametrize(
    ("scope", "title", "intro_fragment"),
    [
        (
            UpdateScope.EVERYTHING,
            "Update everything",
            "snapshot-gated SASE and provider",
        ),
        (
            UpdateScope.SASE,
            "Update SASE, core & plugins",
            "Confirm the SASE, core, and plugin work below.",
        ),
        (
            UpdateScope.PROVIDERS,
            "Update providers",
            "Confirm the exact provider update commands below",
        ),
    ],
)
def test_comprehensive_confirm_copy(
    scope: UpdateScope, title: str, intro_fragment: str
) -> None:
    got_title, intro, panel_title = comprehensive_confirm_copy(scope)
    assert got_title == title
    assert intro_fragment in intro
    if scope is UpdateScope.EVERYTHING:
        assert panel_title == "Confirm comprehensive update"
    else:
        assert panel_title == title


def test_scoped_noop_messages_name_the_scope() -> None:
    assert _comprehensive_current_message(UpdateScope.EVERYTHING) == (
        "Everything in the captured comprehensive update is already current."
    )
    assert "SASE, core, and plugins" in _comprehensive_current_message(UpdateScope.SASE)
    assert "providers" in _comprehensive_current_message(UpdateScope.PROVIDERS)
    assert _comprehensive_dropped_message(UpdateScope.EVERYTHING, "gone") == (
        "No captured updates remain: available components are current; "
        "no longer present: gone."
    )
    assert _comprehensive_dropped_message(UpdateScope.PROVIDERS, "gone").startswith(
        "No captured provider updates remain"
    )


def test_confirm_modal_includes_only_selected_sections() -> None:
    provider_plan, dropped, error = _plan_captured_providers(
        ("claude",),
        _agent_cli_statuses(),
        offline=False,
    )
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest(("claude",), UpdateScope.PROVIDERS),
        sase_preview=DevUpdatePreview(plan=None, subject="sase"),
        provider_plan=provider_plan,
        provider_dropped=dropped,
        provider_error=error,
    )

    assert _section_titles(preview) == ["Agent CLIs"]
    title, intro, panel_title = comprehensive_confirm_copy(preview.request.scope)
    assert title == "Update providers"
    assert intro
    assert panel_title == title


def test_noop_without_admin_center_points_at_updates_tab() -> None:
    notes: list[tuple[str, str]] = []

    handle_comprehensive_noop(
        _manual_provider_preview(scope=UpdateScope.PROVIDERS),
        notify=lambda message, *, severity="information": notes.append(
            (message, severity)
        ),
    )

    assert notes
    message, severity = notes[0]
    assert severity == "warning"
    assert "Admin Center Updates tab" in message


def test_scoped_current_noop_names_sase() -> None:
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest((), UpdateScope.SASE),
        sase_preview=None,
        sase_current=True,
    )
    notes: list[tuple[str, str]] = []

    handle_comprehensive_noop(
        preview,
        notify=lambda message, *, severity="information": notes.append(
            (message, severity)
        ),
    )

    assert notes == [
        (
            "SASE, core, and plugins in the captured update are already current.",
            "information",
        )
    ]
