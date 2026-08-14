"""Tests for the shared tab quick-start widget."""

from __future__ import annotations

from typing import Literal

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui import artifact_tabs
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.widgets.tab_quickstart import (
    _CARD_CONTENT_WIDTH,
    _KEY_DESCRIPTION_GAP,
    TabQuickStart,
)


def _fixed_only_descriptors() -> tuple[artifact_tabs.ArtifactsTabDescriptor, ...]:
    return artifact_tabs._assign_artifacts_digit_shortcuts(
        (
            artifact_tabs._fixed_descriptor("stitches"),
            artifact_tabs._fixed_descriptor("patches"),
            artifact_tabs._fixed_descriptor("beads"),
            artifact_tabs._fixed_descriptor("files"),
        )
    )


def _one_provider_descriptors() -> tuple[artifact_tabs.ArtifactsTabDescriptor, ...]:
    return artifact_tabs._assign_artifacts_digit_shortcuts(
        (
            artifact_tabs._fixed_descriptor("stitches"),
            artifact_tabs._fixed_descriptor("patches"),
            artifact_tabs._fixed_descriptor("beads"),
            artifact_tabs.ArtifactsTabDescriptor(
                id="ref:plan",
                label="Plan",
                accent=artifact_tabs.ARTIFACTS_ACCENTS["ref:plan"],
                pane_id="artifacts-plans-pane",
                provider_kind="plan",
                provider_spec={},
            ),
            artifact_tabs._fixed_descriptor("files"),
        )
    )


@pytest.fixture(autouse=True)
def _stub_artifacts_subtabs(monkeypatch: pytest.MonkeyPatch) -> None:
    # render_content() is exercised without AcePage here, so without a stub
    # it would hit real provider discovery and be host-dependent.
    monkeypatch.setattr(
        artifact_tabs, "resolve_artifacts_subtabs", _fixed_only_descriptors
    )


def _section_plain(sections: dict[str, Text], selector: str) -> str:
    return sections[selector].plain


def _card_plain(
    tab: Literal["agents", "patches"],
    registry_config: dict[str, object] | None = None,
) -> str:
    registry = load_keymap_registry(registry_config or {})
    prefix = "agent" if tab == "agents" else "patch"
    sections = TabQuickStart.render_content(registry, tab=tab)
    return _section_plain(sections, f"#{prefix}-quickstart-card")


def _long_key_registry_config() -> dict[str, object]:
    long_binding_pairs = {
        "start_agent_home": "ctrl+shift+f24,ctrl+shift+f23",
        "open_config_center": "ctrl+shift+f22,ctrl+shift+f21",
        "show_help": "ctrl+shift+f20,ctrl+shift+f19",
        "open_command_palette": "ctrl+shift+f18,ctrl+shift+f17",
    }
    return {"keymaps": {"app": long_binding_pairs}}


def test_tab_quickstart_uses_active_keymap_registry() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "start_agent_home": "f2",
                    "open_config_center": "f3",
                    "next_tab": "f4",
                    "open_command_palette": "f7",
                    "edit_query": "f8",
                    "show_help": "f6",
                },
                "modes": {
                    "leader_mode": {
                        "prefix": "g",
                        "keys": {"edit_query": "f5", "show_help": "f9"},
                    }
                },
            }
        }
    )

    sections = TabQuickStart.render_content(registry, tab="agents")
    card = _section_plain(sections, "#agent-quickstart-card")
    hero = _section_plain(sections, "#agent-quickstart-hero")

    for key in ("f2", "f3", "f4", "f5", "f6", "f7"):
        assert key in card
    assert "f8" not in card
    assert "f9" not in card
    assert " ] " in card
    assert "Launch your first agent" in card
    assert "The full tour of this tab" in card
    assert "tool calls, and artifact files" in hero


def test_artifacts_quickstart_advertises_every_subtab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = load_keymap_registry({})

    agents = TabQuickStart.render_content(registry, tab="agents")
    patches = TabQuickStart.render_content(registry, tab="patches")
    agents_card = _section_plain(agents, "#agent-quickstart-card")
    artifacts_card = _section_plain(patches, "#patch-quickstart-card")

    assert "Jump: Stitch · Patch · Bead · File." in artifacts_card
    assert "Cycle Artifacts: Stitch · Patch · Bead · File." in artifacts_card
    assert "File: previous / next version." in artifacts_card
    assert "Cycle Artifacts" not in agents_card
    assert _section_plain(agents, "#agent-quickstart-hero") != _section_plain(
        patches, "#patch-quickstart-hero"
    )
    assert _section_plain(agents, "#agent-quickstart-footer") != _section_plain(
        patches, "#patch-quickstart-footer"
    )

    monkeypatch.setattr(
        artifact_tabs, "resolve_artifacts_subtabs", _one_provider_descriptors
    )
    provider_patches = TabQuickStart.render_content(registry, tab="patches")
    provider_card = _section_plain(provider_patches, "#patch-quickstart-card")

    assert "Jump: Stitch · Patch · Bead · Plan · File." in provider_card
    assert "Cycle Artifacts: Stitch · Patch · Bead · Plan · File." in provider_card


def test_artifacts_quickstart_uses_configured_subtab_keys() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "cycle_artifacts_subtab_reverse": "f8",
                    "cycle_artifacts_subtab": "f9",
                    "edit_query": "f10",
                    "files_prev_version": "f11",
                    "files_next_version": "f12",
                }
            }
        }
    )

    sections = TabQuickStart.render_content(registry, tab="patches")
    card = _section_plain(sections, "#patch-quickstart-card")

    assert "f8" in card
    assert "f9" in card
    assert "f10" in card
    assert "f11" in card
    assert "f12" in card


def test_tab_quickstart_no_match_callout_is_prs_only() -> None:
    registry = load_keymap_registry({})

    agents = TabQuickStart.render_content(
        registry,
        tab="agents",
        no_match_total=3,
    )
    empty_prs = TabQuickStart.render_content(
        registry,
        tab="patches",
        no_match_total=0,
    )
    no_match_prs = TabQuickStart.render_content(
        registry,
        tab="patches",
        no_match_total=3,
    )

    assert _section_plain(agents, "#agent-quickstart-callout") == ""
    assert _section_plain(empty_prs, "#patch-quickstart-callout") == ""
    callout = _section_plain(no_match_prs, "#patch-quickstart-callout")
    assert "No PRs match this query" in callout
    assert "3 exist" in callout
    assert "/ edits the query" in callout


def test_tab_quickstart_card_lines_fit_content_width() -> None:
    registry_configs = ({}, _long_key_registry_config())

    for registry_config in registry_configs:
        for tab in ("agents", "patches"):
            card = _card_plain(tab, registry_config)
            for line in card.splitlines():
                assert cell_len(line) <= _CARD_CONTENT_WIDTH, line


def test_tab_quickstart_wrapped_descriptions_use_hanging_indent() -> None:
    card = _card_plain("patches")
    lines = card.splitlines()
    admin_line_idx = next(
        idx for idx, line in enumerate(lines) if "SASE Admin Center" in line
    )
    continuation = lines[admin_line_idx + 1]
    expected_indent = (
        TabQuickStart._keycap_width(("1", "2", "3", "4")) + _KEY_DESCRIPTION_GAP
    )

    assert continuation.startswith(" " * expected_indent)
    assert continuation.strip() == "updates."
    assert all(line.startswith(" ") for line in lines if line)


def test_tab_quickstart_card_has_no_trailing_newline() -> None:
    for tab in ("agents", "patches"):
        assert not _card_plain(tab).endswith("\n")


def test_tab_quickstart_refresh_before_children_composed_is_safe() -> None:
    """A caller can reach ``is_mounted`` before ``compose()`` attaches children.

    Reproduces the observed race: an external onboarding refresh queries this
    widget by id (mounted at the DOM level) and immediately calls
    ``refresh_content()``/``set_keymap_registry()`` before this widget's own
    composed ``Static`` children are queryable, raising
    ``NoMatches("#agent-quickstart-callout")``.
    """
    widget = TabQuickStart(tab="agents")
    widget._is_mounted = True  # simulate mounted-but-not-yet-composed

    widget.refresh_content()

    registry = load_keymap_registry({})
    widget.set_keymap_registry(registry)
