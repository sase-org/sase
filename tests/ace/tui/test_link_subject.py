"""Tests for per-tab selected-entity resolution (bead:sase-ug.5)."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from sase.ace.tui._artifact_tab_model import ARTIFACTS_ACCENTS, ARTIFACTS_ICONS
from sase.ace.tui.relations.link_subject import (
    _CHOP_ACCENT,
    _CHOP_ICON,
    selected_link_subject,
)
from sase.ace.tui.widgets.bgcmd_list import BgCmdItem, ChopItem, LumberjackItem
from sase.core.artifact_entry_target import ArtifactEntryTarget


@dataclass
class _FakePane:
    target: ArtifactEntryTarget | None

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        return self.target


def _artifacts_app(target: ArtifactEntryTarget | None) -> Any:
    return SimpleNamespace(
        current_tab="artifacts",
        _artifacts_entry_navigator=lambda: (
            None if target is None else _FakePane(target)
        ),
    )


def test_artifacts_tab_resolves_the_selected_pane_row_to_a_ref() -> None:
    app = _artifacts_app(ArtifactEntryTarget("beads", ("alpha", "task", "sase-1")))
    subject = selected_link_subject(app)
    assert subject is not None
    assert subject.ref == "bead:sase-1"
    assert subject.target == ArtifactEntryTarget("beads", ("alpha", "task", "sase-1"))
    assert subject.accent == ARTIFACTS_ACCENTS["beads"]
    assert subject.icon == ARTIFACTS_ICONS["beads"]


def test_artifacts_tab_returns_none_with_no_pane_or_no_selection() -> None:
    assert selected_link_subject(_artifacts_app(None)) is None
    no_pane = SimpleNamespace(
        current_tab="artifacts", _artifacts_entry_navigator=lambda: None
    )
    assert selected_link_subject(no_pane) is None


def _agents_app(agent: Any) -> Any:
    return SimpleNamespace(current_tab="agents", _get_selected_agent=lambda: agent)


def test_agents_tab_resolves_the_selected_agent_to_a_ref() -> None:
    agent = SimpleNamespace(name="bob.athena.worker")
    subject = selected_link_subject(_agents_app(agent))
    assert subject is not None
    assert subject.ref == "agent:bob.athena.worker"
    assert subject.target == ArtifactEntryTarget("agents", ("bob.athena.worker",))
    assert subject.accent == ARTIFACTS_ACCENTS["agents"]
    assert subject.icon == ARTIFACTS_ICONS["agents"]


def test_agents_tab_returns_none_with_no_selection() -> None:
    assert selected_link_subject(_agents_app(None)) is None


def _axe_app(items: list[Any], current_idx: int, snapshots: dict[Any, Any]) -> Any:
    return SimpleNamespace(
        current_tab="axe",
        _axe_items=items,
        current_idx=current_idx,
        _axe_chop_snapshots=snapshots,
    )


def test_axe_tab_resolves_a_selected_chop_using_its_base_identity() -> None:
    items = [ChopItem(lumberjack_name="refresh_docs", chop_name="refresh_docs[sase]")]
    snapshot = SimpleNamespace(base_identity=("refresh_docs", "refresh_docs"))
    app = _axe_app(items, 0, {("refresh_docs", "refresh_docs[sase]"): snapshot})
    subject = selected_link_subject(app)
    assert subject is not None
    assert subject.ref == "chop:refresh_docs/refresh_docs"
    assert subject.target is None
    assert subject.accent == _CHOP_ACCENT
    assert subject.icon == _CHOP_ICON


def test_axe_tab_falls_back_to_the_chop_name_with_no_cached_snapshot() -> None:
    items = [ChopItem(lumberjack_name="refresh_docs", chop_name="refresh_docs")]
    app = _axe_app(items, 0, {})
    subject = selected_link_subject(app)
    assert subject is not None
    assert subject.ref == "chop:refresh_docs/refresh_docs"


def test_axe_tab_returns_none_for_lumberjack_and_bgcmd_rows() -> None:
    lumberjack_app = _axe_app([LumberjackItem(name="refresh_docs")], 0, {})
    bgcmd_app = _axe_app([BgCmdItem(slot=1)], 0, {})
    assert selected_link_subject(lumberjack_app) is None
    assert selected_link_subject(bgcmd_app) is None


def test_unrecognized_tab_returns_none() -> None:
    app = SimpleNamespace(current_tab="somewhere-else")
    assert selected_link_subject(app) is None
