"""Shared fixtures for the Changes-lens test modules."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

DAY_ONE = 1790486400
DAY_TWO = 1790400000


def make_authored(
    subject_id: str = "note:project:sase/glossary/artifact",
    ordinal: int = 3,
    class_name: str = "authored",
    path: str = "sase/memory/glossary/artifact.md",
) -> dict[str, Any]:
    return {
        "subject_id": subject_id,
        "ordinal": ordinal,
        "class": class_name,
        "summary": {
            "section_paths": ["Definition"],
            "words_added": 20,
            "words_removed": 3,
        },
        "path": path,
        "commit": "d" * 40,
    }


def make_changeset(
    commit: str = "d" * 40,
    committer_time: int = DAY_ONE,
    subject: str = "feat(tabs): something",
    scope_key: str = "project:sase",
    bead: str = "sase-1bu.7",
    agent: str = "athena.sase-1bu.7",
    authored: list[dict[str, Any]] | None = None,
    consequences: list[dict[str, Any]] | None = None,
    regen_only: bool = False,
) -> dict[str, Any]:
    return {
        "scope_key": scope_key,
        "commit": commit,
        "committer_time": committer_time,
        "provenance": {"subject": subject, "bead": bead, "agent": agent},
        "regen_only": regen_only,
        "authored": authored if authored is not None else [make_authored()],
        "consequences": consequences
        if consequences is not None
        else [
            {
                "subject_id": "instructions:project:sase/.",
                "ordinal": 12,
                "class": "rendered",
                "summary": {},
                "path": "AGENTS.md",
            }
        ],
    }


def make_feed(*changesets: dict[str, Any]) -> dict[str, Any]:
    if not changesets:
        return {
            "changesets": [
                make_changeset(),
                make_changeset(
                    commit="e" * 40,
                    committer_time=DAY_ONE + 600,
                    subject="feat(home): tweak",
                    scope_key="home",
                    bead="",
                    agent="",
                    authored=[],
                    consequences=[],
                ),
                make_changeset(
                    commit="f" * 40,
                    committer_time=DAY_TWO,
                    subject="chore: regen",
                    bead="",
                    agent="",
                    authored=[],
                    consequences=[],
                    regen_only=True,
                ),
            ]
        }
    return {"changesets": list(changesets)}


def prepare_changes_panel(monkeypatch, feed=None, review=None, mark_error=None):  # noqa: ANN001, ANN202
    """Mount ``MemoryPane`` with one note and a stub feed-backed history.

    *review* is the ``review_state`` wire the stub service returns (``{}``
    when ``None``: no chip, no dots). The stub records ``mark_reviewed``
    calls on ``history.marked`` (raising *mark_error* instead when set)
    and advances its own watermark so the confirm refetch reads zeros.
    Reach it later through ``panel._ace_history()``.
    """
    from textual.screen import Screen
    from textual.widgets import Static

    from sase.ace.tui.modals.memory_pane import MemoryPane
    from tests.ace.tui.modals.memory_panel_test_helpers import (
        MemoryPanelTestApp,
        install_fixed_load,
        memory_note,
        scope_ref,
        scope_snapshot,
    )

    ref = scope_ref("sase", "sase")
    snapshots = {
        "sase": scope_snapshot(ref, (memory_note("gotchas"), memory_note("zebra")))
    }
    install_fixed_load(monkeypatch, (ref,), snapshots)
    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)
    payload = make_feed() if feed is None else feed
    sase_scope = SimpleNamespace(scope_key="project:sase", repo_root="/tmp")
    home_scope = SimpleNamespace(scope_key="home", repo_root="/tmp")

    review_box: dict[str, Any] = {"wire": review}
    marked: list[tuple[str, str]] = []
    review_calls: list[list[str]] = []

    class _FakeHistory:
        def __init__(self) -> None:
            self.marked = marked
            self.review_calls = review_calls
            self.review_box = review_box
            self.mark_error = mark_error
            self.service = SimpleNamespace(
                review_state=self._review_state,
                mark_reviewed=self._mark_reviewed,
            )

        def _review_state(self, scopes):  # noqa: ANN001, ANN202
            self.review_calls.append(
                [str(getattr(scope, "scope_key", "") or "") for scope in scopes]
            )
            wire = self.review_box["wire"]
            if isinstance(wire, BaseException):
                raise wire
            if not isinstance(wire, dict):
                return {}
            return wire

        def _mark_reviewed(self, scope, through_commit, **_kwargs):  # noqa: ANN001, ANN202
            if self.mark_error is not None:
                raise self.mark_error
            key = str(getattr(scope, "scope_key", "") or "")
            through = str(through_commit or "")
            self.marked.append((key, through))
            # Mirror core: the watermark advances to the through commit,
            # so its stamp is that changeset's committer time.
            stamp = 0
            for changeset in payload.get("changesets", ()):
                if str(changeset.get("commit", "")) == through:
                    try:
                        stamp = int(changeset.get("committer_time", 0) or 0)
                    except (TypeError, ValueError):
                        stamp = 0
                    break
            wire = self.review_box["wire"]
            if isinstance(wire, dict):
                entries = []
                seen = False
                for raw in wire.get("scopes", ()):
                    entry = dict(raw)
                    if str(entry.get("scope_key", "")) == key:
                        entry["new_count"] = 0
                        entry["watermark"] = {
                            "commit": through,
                            "committer_time": stamp,
                            "marked_at": stamp,
                        }
                        seen = True
                    entries.append(entry)
                if not seen:
                    entries.append(
                        {
                            "scope_key": key,
                            "watermark": {
                                "commit": through,
                                "committer_time": stamp,
                                "marked_at": stamp,
                            },
                            "new_count": 0,
                            "newest_commit": through,
                        }
                    )
                self.review_box["wire"] = {"scopes": entries}
            return {"scope_key": key}

        def scope_for_ref(self, _ref):
            return sase_scope

        def feed(self, _scopes):
            return dict(payload)

        def version_body(self, _scope, _selector, version):
            return {
                "body": f"body {version}\n",
                "body_missing": False,
                "blob_oid": f"blob-{version}",
            }

        def comparison(self, _scope, _selector, _base, _target):
            return {"ops": []}

    history = _FakeHistory()
    monkeypatch.setattr(panel, "_ace_history", lambda: history)
    import sase.ace.tui.modals.memory_panel_history as history_module

    monkeypatch.setattr(
        history_module,
        "history_scopes_for_ring",
        lambda _ring, _svc: [sase_scope, home_scope],
    )

    pushed: list = []

    class _FakePager(Screen):
        def __init__(self, document: object, **_kwargs: object) -> None:
            super().__init__()
            self.document = document
            pushed.append(self)

        def compose(self):  # noqa: ANN202
            yield Static("pager")

    import sase.pager.screen as pager_screen_module
    import sase.pager.syntax_policy as syntax_policy_module

    monkeypatch.setattr(pager_screen_module, "PagerScreen", _FakePager)
    monkeypatch.setattr(
        syntax_policy_module,
        "pager_syntax_session_from_config",
        lambda: SimpleNamespace(syntax_enabled=False),
    )
    return panel, app, pushed


def rail_texts(panel) -> list[str]:  # noqa: ANN001, ANN202
    from tests.ace.tui.modals.memory_panel_test_helpers import note_row_text

    count = int(panel._note_list().option_count)
    return [note_row_text(panel, index) for index in range(count)]
