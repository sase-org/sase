"""Direct tests for pane-free, scope-aware comprehensive update previews."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.ace.tui.modals.plugins_browser_comprehensive_update import (
    ComprehensiveUpdateActionsMixin,
    ComprehensiveUpdateRequest,
)
from sase.ace.tui.modals.plugins_browser_comprehensive_update_models import (
    ComprehensiveUpdatePreview,
)
from sase.ace.tui.modals.plugins_browser_comprehensive_update_preview import (
    build_comprehensive_update_preview,
    comprehensive_confirm_copy,
    _comprehensive_current_message,
    _comprehensive_dropped_message,
    comprehensive_preview_sections,
    plan_captured_providers,
)
from sase.ace.tui.modals.plugins_browser_dev_update import DevUpdatePreview
from sase.ace.tui.update_preview_inputs import (
    UpdatePreviewInputs,
    collect_update_preview_inputs,
)
from sase.ace.update_scope import ALL_LEGS, UpdateLeg, UpdateScope
from sase.agents_sync.models import (
    CapturedIncomingHood,
    ProjectSyncStatus,
    SyncStatusSnapshot,
)
from sase.updates import UpdateSourceStatus, UpdateStatus
from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason
from tests.ace.tui._plugins_browser_pane_helpers import _agent_cli_statuses

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


def _captured() -> CapturedIncomingHood:
    return CapturedIncomingHood(
        project_key="alpha",
        project="Alpha",
        fetched_ref="refs/remotes/origin/main",
        fetched_sha="a" * 40,
        cache_id="alpha-foo",
        format_version=2,
        source_owner_kind="exact",
        source_username="alice",
        source_machine="zeus",
        top_hood="foo",
        hood_digest="b" * 64,
        run_count=1,
        family_count=1,
        cache_created_at=1.0,
    )


def _agents_snapshot() -> SyncStatusSnapshot:
    captured = _captured()
    return SyncStatusSnapshot(
        100.0,
        (
            ProjectSyncStatus(
                "alpha",
                "Alpha",
                "ready",
                pending_updates=(captured,),
            ),
        ),
    )


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
    plan, dropped, error = plan_captured_providers(
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
    assert UpdateScope.AGENTS.legs == frozenset({UpdateLeg.AGENTS})


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

    agents_only = collect_update_preview_inputs(
        cached_status=None, legs={UpdateLeg.AGENTS}
    )
    assert probes == []
    assert collects == []
    assert agents_only.uv_tool is None
    assert agents_only.agent_cli_statuses == ()

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
        f"{_PREVIEW_MOD}.get_agents_sync_status",
        lambda **_kwargs: _agents_snapshot(),
    )
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
    assert preview.agents_runnable is True
    assert make_calls
    assert _section_titles(preview) == [
        "SASE, core & plugins",
        "Agent CLIs",
        "Cached agent hoods",
    ]


def test_build_preview_sase_scope_omits_other_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.get_agents_sync_status",
        lambda **_kwargs: pytest.fail("agents leg must not run"),
    )
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.make_sase_dev_update_preview",
        lambda _receipt, **_kwargs: DevUpdatePreview(plan=None, subject="sase"),
    )
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.plan_captured_providers",
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
    assert preview.agents_updates == ()
    assert [section.title for section in sections] == ["SASE, core & plugins"]
    assert all("skip" not in section.summary.lower() for section in sections)


def test_build_preview_providers_scope_omits_other_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.get_agents_sync_status",
        lambda **_kwargs: pytest.fail("agents leg must not run"),
    )
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
    assert preview.agents_runnable is False
    assert _section_titles(preview) == ["Agent CLIs"]


def test_build_preview_agents_scope_omits_other_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.get_agents_sync_status",
        lambda **_kwargs: _agents_snapshot(),
    )
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.make_sase_dev_update_preview",
        lambda *_args, **_kwargs: pytest.fail("sase leg must not run"),
    )
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.plan_captured_providers",
        lambda *_args, **_kwargs: pytest.fail("provider leg must not run"),
    )

    preview = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest((), UpdateScope.AGENTS),
        _inputs(),
    )

    assert preview.agents_runnable is True
    assert preview.sase_preview is None
    assert preview.provider_plan is None
    assert _section_titles(preview) == ["Cached agent hoods"]


def test_cached_current_status_skips_sase_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.make_sase_dev_update_preview",
        lambda *_args, **_kwargs: pytest.fail("cached current must skip planner"),
    )
    monkeypatch.setattr(
        f"{_PREVIEW_MOD}.get_agents_sync_status",
        lambda **_kwargs: _agents_snapshot(),
    )

    preview = build_comprehensive_update_preview(
        ComprehensiveUpdateRequest(()),
        _inputs(cached_status=_current_status()),
    )

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
            "snapshot-gated SASE, provider, and agents-repository",
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
        (
            UpdateScope.AGENTS,
            "Import published agents",
            "Confirm the cached agent hoods to import",
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
    assert "agent hoods" in _comprehensive_current_message(UpdateScope.AGENTS)
    assert _comprehensive_dropped_message(UpdateScope.EVERYTHING, "gone") == (
        "No captured updates remain: available components are current; "
        "no longer present: gone."
    )
    assert _comprehensive_dropped_message(UpdateScope.PROVIDERS, "gone").startswith(
        "No captured provider updates remain"
    )


class _ConfirmHarness(ComprehensiveUpdateActionsMixin):
    def __init__(self) -> None:
        self.screens: list[PluginActionConfirmModal] = []
        self.notes: list[tuple[str, str]] = []
        self._incoming_commits_enabled = True
        self.app = SimpleNamespace(
            push_screen=lambda modal, _cb: self.screens.append(modal)
        )

    def _comprehensive_update_incoming_commits_loader(
        self, preview: object
    ) -> object | None:
        return object() if getattr(preview, "sase_runnable", False) else None

    def _notify(self, message: str, *, severity: str = "information") -> None:
        self.notes.append((message, severity))


def test_confirm_modal_includes_only_selected_sections() -> None:
    provider_plan, dropped, error = plan_captured_providers(
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
        agents_updates=(_captured(),),
    )
    harness = _ConfirmHarness()
    harness._on_comprehensive_update_preview(preview)

    assert len(harness.screens) == 1
    modal = harness.screens[0]
    assert modal._title == "Update providers"
    assert [section.title for section in modal._variants[0].sections] == ["Agent CLIs"]
    assert modal._incoming_commits_loader is None
    assert modal._incoming_commits_empty_message is None


def test_noop_without_admin_center_points_at_updates_tab() -> None:
    harness = _ConfirmHarness()
    harness._on_comprehensive_update_preview(
        _manual_provider_preview(scope=UpdateScope.PROVIDERS)
    )

    assert harness.screens == []
    assert harness.notes
    message, severity = harness.notes[0]
    assert severity == "warning"
    assert "Admin Center Updates tab" in message


def test_noop_with_subtab_keeps_agent_clis_toast() -> None:
    class _PaneHarness(_ConfirmHarness):
        def __init__(self) -> None:
            super().__init__()
            self.switched: list[str] = []

        def _switch_to_subtab(self, subtab: str) -> None:
            self.switched.append(subtab)

    harness = _PaneHarness()
    harness._on_comprehensive_update_preview(_manual_provider_preview())

    assert harness.switched == ["agent-clis"]
    assert "Agent CLIs" in harness.notes[0][0]


def test_scoped_current_noop_names_sase() -> None:
    preview = ComprehensiveUpdatePreview(
        request=ComprehensiveUpdateRequest((), UpdateScope.SASE),
        sase_preview=None,
        sase_current=True,
    )
    harness = _ConfirmHarness()
    harness._on_comprehensive_update_preview(preview)

    assert harness.screens == []
    assert harness.notes == [
        (
            "SASE, core, and plugins in the captured update are already current.",
            "information",
        )
    ]
