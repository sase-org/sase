"""The Files sub-tab's default-off beta flag and its hidden routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui import artifact_tabs
from sase.ace.tui._artifact_tab_model import ARTIFACTS_FILES_PANE_DISABLED_HINT
from sase.ace.tui.artifact_tabs import is_disabled_artifacts_pane
from sase.ace.tui.widgets.artifacts.entry_navigation import LinkRequestState
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.feature_flags import override_flags
from sase.feature_flags.registry import FeatureFlag, feature_flag_definitions


@pytest.fixture
def provider_inventory(monkeypatch: pytest.MonkeyPatch):
    provider = artifact_tabs.ArtifactsTabDescriptor(
        id="ref:plan",
        label="Plans",
        accent="#000000",
        pane_id="plans-pane",
        provider_kind="plan",
    )
    monkeypatch.setattr(artifact_tabs, "provider_source_token", lambda: ("test",))
    monkeypatch.setattr(
        artifact_tabs,
        "load_project_provider_records",
        lambda *, project=None: SimpleNamespace(records=(), issues=()),
    )
    monkeypatch.setattr(
        artifact_tabs,
        "provider_descriptors",
        lambda _records, _issues: (provider,),
    )
    artifact_tabs.reset_artifacts_subtabs_cache()
    yield
    artifact_tabs.reset_artifacts_subtabs_cache()


def test_default_strip_hides_files_and_numbers_remaining_panes_positionally(
    provider_inventory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with override_flags(
        artifacts_agent_pane_retired=True,
        artifacts_files_pane=False,
    ):
        descriptors = artifact_tabs.resolve_artifacts_subtabs()
        assert [item.id for item in descriptors] == [
            "stitches",
            "patches",
            "beads",
            "ref:plan",
        ]
        assert [item.digit_shortcut for item in descriptors] == ["1", "2", "3", "4"]
        assert artifact_tabs.normalize_artifacts_subtab("files") == "stitches"
        assert artifact_tabs.normalize_artifacts_subtab("other") == "stitches"
        assert is_disabled_artifacts_pane("files")
        assert not is_disabled_artifacts_pane("stitches")

        monkeypatch.setattr(
            artifact_tabs,
            "provider_descriptors",
            lambda _records, _issues: (),
        )
        artifact_tabs.reset_artifacts_subtabs_cache()
        fixed = artifact_tabs.resolve_artifacts_subtabs()
        assert [item.id for item in fixed] == ["stitches", "patches", "beads"]
        assert [item.digit_shortcut for item in fixed] == ["1", "2", "3"]


def test_registry_definition_is_a_default_off_beta_with_generated_bead() -> None:
    definition = feature_flag_definitions()[FeatureFlag.artifacts_files_pane]

    assert definition.kind == "beta"
    assert definition.default is False
    assert definition.bead == "sase-1nu"


def test_enabled_strip_renders_files_last_with_the_highest_digit(
    provider_inventory,
) -> None:
    with override_flags(
        artifacts_agent_pane_retired=True,
        artifacts_files_pane=True,
    ):
        descriptors = artifact_tabs.resolve_artifacts_subtabs()
        assert [item.id for item in descriptors] == [
            "stitches",
            "patches",
            "beads",
            "ref:plan",
            "files",
        ]
        assert descriptors[-1].digit_shortcut == str(len(descriptors))
        assert artifact_tabs.normalize_artifacts_subtab("files") == "files"
        assert not is_disabled_artifacts_pane("files")


async def test_disabled_files_action_and_entry_request_keep_the_current_pane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.testing import AcePage

    with override_flags(
        artifacts_agent_pane_retired=True,
        artifacts_files_pane=False,
    ):
        async with AcePage(initial_tab="patches") as page:
            app = page.app
            notices: list[tuple[str, str | None]] = []
            monkeypatch.setattr(
                app,
                "notify",
                lambda message, *, severity=None, **_kwargs: notices.append(
                    (message, severity)
                ),
            )
            before = (app.current_tab, app.current_artifacts_subtab)
            target = ArtifactEntryTarget("files", ("some-file.md",))
            assert app._request_artifacts_entry(target) is LinkRequestState.MISSING
            assert (app.current_tab, app.current_artifacts_subtab) == before

            app.action_show_artifacts_files()
            assert (app.current_tab, app.current_artifacts_subtab) == before
            assert notices == [(ARTIFACTS_FILES_PANE_DISABLED_HINT, "warning")]


def test_disabled_file_link_toasts_without_switching_or_recording_a_trail() -> None:
    from sase.ace.tui.actions._link_follow_types import (
        LinkTrailHop,
        _link_follow_outcomes,
    )
    from tests.ace.tui._link_follow_helpers import _App, _Pane

    target = ArtifactEntryTarget("files", ("linked.md",))
    app = _App(chips=(), panes={"files": _Pane(targets=(target,))})
    app.current_tab = "agents"
    app.current_artifacts_pane_key = "stitches"
    origin = LinkTrailHop(
        tab="agents",
        pane_key=None,
        origin=None,
        query_source=None,
    )
    _link_follow_outcomes.clear()

    with override_flags(artifacts_files_pane=False):
        app._follow_artifacts_target("file:linked.md", target, origin)

    assert app.current_tab == "agents"
    assert app.current_artifacts_pane_key == "stitches"
    assert app._link_trail == []
    assert app._link_follow_transaction is None
    assert _link_follow_outcomes["missing"] == 1
    assert app.notification_details[-1][2] == "Cannot follow linked.md"
    assert app.notifications[-1] == (ARTIFACTS_FILES_PANE_DISABLED_HINT, "warning")
