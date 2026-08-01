"""Stable-target marking behavior for non-PR Artifacts panes."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.actions.artifacts import ArtifactsMixin
from sase.ace.tui.actions.marking import MarkingMixin
from sase.ace.tui.widgets.artifacts import ArtifactEntryTarget


class _Navigator:
    def __init__(self, target: ArtifactEntryTarget) -> None:
        self.target = target
        self.applied_marks: list[set[ArtifactEntryTarget]] = []

    def selected_entry_target(self) -> ArtifactEntryTarget:
        return self.target

    def apply_entry_marks(self, marks: set[ArtifactEntryTarget]) -> None:
        self.applied_marks.append(set(marks))


class _MarkHarness(MarkingMixin, ArtifactsMixin):
    def __init__(self, pane_key: str, target: ArtifactEntryTarget) -> None:
        self.current_tab = "changespecs"
        self.current_artifacts_subtab = (
            "files" if pane_key in {"plans", "chats", "other"} else pane_key
        )
        self.current_files_subtab = (
            pane_key if pane_key in {"plans", "chats", "other"} else "plans"
        )
        self.marked_indices = {7}
        self._artifacts_marked_targets = {
            "commits": set(),
            "bugs": set(),
            "beads": set(),
            "plans": set(),
            "chats": set(),
            "other": set(),
        }
        self.navigator = _Navigator(target)
        self.footer_syncs = 0
        self.notifications: list[tuple[str, str]] = []

    def _artifacts_entry_navigator(self, subtab: str | None = None) -> _Navigator:
        del subtab
        return self.navigator

    def _sync_active_artifacts_entry_state(self) -> None:
        self.footer_syncs += 1

    def notify(
        self,
        message: str,
        *,
        severity: str = "information",
        **_kwargs: Any,
    ) -> None:
        self.notifications.append((message, severity))


@pytest.mark.parametrize(
    ("subtab", "target"),
    [
        ("commits", ("commit", "alpha", "a" * 40)),
        ("plans", ("plan", "alpha", "epic", "alpha-1")),
        ("chats", ("chat", "/tmp/chat.md")),
        ("bugs", ("bug", "alpha", "42")),
        ("other", ("file", "default:" + "a" * 24)),
    ],
)
def test_non_pr_artifact_mark_toggles_stable_target_without_touching_pr_marks(
    subtab: str,
    target: ArtifactEntryTarget,
) -> None:
    app = _MarkHarness(subtab, target)

    app.action_toggle_mark()

    assert app._artifacts_marked_targets[subtab] == {target}
    assert app.navigator.applied_marks[-1] == {target}
    assert app.marked_indices == {7}
    assert app.footer_syncs == 1

    app.action_toggle_mark()

    assert app._artifacts_marked_targets[subtab] == set()
    assert app.navigator.applied_marks[-1] == set()
    assert app.marked_indices == {7}
    assert app.footer_syncs == 2


@pytest.mark.parametrize(
    "subtab", ["commits", "beads", "plans", "chats", "bugs", "other"]
)
def test_clear_marks_is_scoped_to_the_active_artifacts_subtab(subtab: str) -> None:
    target = ("entry", subtab)
    app = _MarkHarness(subtab, target)
    app._artifacts_marked_targets = {
        name: {("entry", name)}
        for name in ("commits", "bugs", "beads", "plans", "chats", "other")
    }

    app.action_clear_marks()

    assert app._artifacts_marked_targets[subtab] == set()
    assert all(
        app._artifacts_marked_targets[name] == {("entry", name)}
        for name in ("commits", "bugs", "beads", "plans", "chats", "other")
        if name != subtab
    )
    assert app.navigator.applied_marks[-1] == set()
    assert app.notifications[-1][0] == "Cleared 1 mark(s)"


def test_project_scope_change_clears_every_non_pr_mark_set() -> None:
    app = _MarkHarness("plans", ("entry", "plans"))
    app._artifacts_marked_targets = {
        name: {("entry", name)}
        for name in ("commits", "bugs", "beads", "plans", "chats", "other")
    }

    app._clear_all_artifacts_marks()

    assert all(not marks for marks in app._artifacts_marked_targets.values())
    assert len(app.navigator.applied_marks) == 6
