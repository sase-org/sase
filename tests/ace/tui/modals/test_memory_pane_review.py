"""Tests for the review-watermark presentation helpers (`watermark-tui`).

Covers the pure ``memory_pane_review`` builders: review-state wire
normalization, the header chip states, the unreviewed-row predicate,
the newest-commit fallback, the mark toast, the hub badge count and
labels, and the badge compute over an injected history service. No
git, no workers, no app.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.modals.config_hub_pane import _compute_memory_badge
from sase.ace.tui.modals.memory_pane_review import (
    ScopeReview,
    changeset_is_unreviewed,
    entries_by_scope,
    feed_newest_commit,
    mark_reviewed_toast,
    memory_badge_count,
    memory_badge_label,
    review_chip,
    review_entries,
)

_T0 = 1790486400


def _wire(
    scope_key: str = "project:sase",
    *,
    new_count: int = 2,
    watermark_time: int = _T0,
    newest_commit: str = "n" * 40,
    watermark: dict[str, Any] | None = "default",
) -> dict[str, Any]:
    stamp: dict[str, Any] | None
    if watermark == "default":
        stamp = {
            "commit": "w" * 40,
            "committer_time": watermark_time,
            "marked_at": _T0,
        }
    else:
        stamp = watermark
    return {
        "scopes": [
            {
                "scope_key": scope_key,
                "watermark": stamp,
                "new_count": new_count,
                "newest_commit": newest_commit,
            }
        ]
    }


def _view(
    scope_key: str = "project:sase",
    commit: str = "c" * 40,
    committer_time: int = _T0 + 100,
) -> SimpleNamespace:
    return SimpleNamespace(
        scope_key=scope_key, commit=commit, committer_time=committer_time
    )


def test_review_entries_normalizes_wire() -> None:
    (entry,) = review_entries(_wire())
    assert entry == ScopeReview(
        scope_key="project:sase",
        new_count=2,
        watermark_time=_T0,
        has_watermark=True,
        newest_commit="n" * 40,
    )


def test_review_entries_treats_missing_watermark_as_never_marked() -> None:
    (entry,) = review_entries(_wire(watermark=None))
    assert entry.has_watermark is False
    assert entry.watermark_time == 0


def test_review_entries_rejects_garbage() -> None:
    assert review_entries(None) == ()
    assert review_entries({}) == ()
    assert review_entries({"scopes": None}) == ()
    assert review_entries({"scopes": [{"scope_key": ""}]}) == ()


def test_review_chip_names_exact_new_count() -> None:
    assert review_chip(review_entries(_wire(new_count=1))) == "● 1 new"
    assert review_chip(review_entries(_wire(new_count=3))) == "● 3 new"


def test_review_chip_sums_across_scopes() -> None:
    wire = _wire(new_count=2)
    other = _wire(scope_key="home", new_count=1, newest_commit="m" * 40)["scopes"][0]
    wire["scopes"].append(other)
    assert review_chip(review_entries(wire)) == "● 3 new"


def test_review_chip_points_at_m_when_never_marked() -> None:
    assert (
        review_chip(review_entries(_wire(watermark=None)))
        == "not reviewed yet · m to mark"
    )


def test_review_chip_confirms_fully_reviewed() -> None:
    assert review_chip(review_entries(_wire(new_count=0))) == "✓ nothing new"


def test_review_chip_omits_when_unavailable() -> None:
    assert review_chip(()) == ""


def test_unreviewed_dots_everything_until_first_mark() -> None:
    indexed = entries_by_scope(review_entries(_wire(watermark=None)))
    assert changeset_is_unreviewed(_view(), indexed) is True


def test_unreviewed_dots_only_newer_than_watermark() -> None:
    indexed = entries_by_scope(review_entries(_wire()))
    assert changeset_is_unreviewed(_view(committer_time=_T0 + 1), indexed) is True
    assert changeset_is_unreviewed(_view(committer_time=_T0), indexed) is False
    assert changeset_is_unreviewed(_view(committer_time=_T0 - 1), indexed) is False


def test_unreviewed_never_dots_unknown_or_undated() -> None:
    indexed = entries_by_scope(review_entries(_wire()))
    assert changeset_is_unreviewed(_view(scope_key="home"), indexed) is False
    assert changeset_is_unreviewed(_view(committer_time=0), indexed) is False
    assert changeset_is_unreviewed(_view(), {}) is False


def test_feed_newest_commit_prefers_latest_time() -> None:
    views = (
        _view(commit="a" * 40, committer_time=_T0 + 10),
        _view(commit="b" * 40, committer_time=_T0 + 50),
        _view(commit="c" * 40, scope_key="home", committer_time=_T0 + 99),
    )
    assert feed_newest_commit(views, "project:sase") == "b" * 40
    assert feed_newest_commit(views, "missing") == ""
    assert feed_newest_commit((), "project:sase") == ""


def test_mark_toast_singular_and_label() -> None:
    assert (
        mark_reviewed_toast("project:sase", 1)
        == "marked 1 changeset reviewed · project:sase"
    )
    assert (
        mark_reviewed_toast("all scopes", 4)
        == "marked 4 changesets reviewed · all scopes"
    )


def test_memory_badge_hides_at_zero_or_without_watermark() -> None:
    assert memory_badge_count(review_entries(_wire(new_count=3)), "project:sase") == 3
    assert (
        memory_badge_count(review_entries(_wire(new_count=0)), "project:sase") is None
    )
    assert (
        memory_badge_count(review_entries(_wire(watermark=None)), "project:sase")
        is None
    )
    assert memory_badge_count(review_entries(_wire()), "home") is None
    assert memory_badge_count((), "project:sase") is None


def test_memory_badge_label_prefixes_count() -> None:
    assert memory_badge_label("Memory", 3) == "●3 Memory"
    assert memory_badge_label("Memory", None) == "Memory"
    assert memory_badge_label("Memory", 0) == "Memory"


def _fake_history(
    wire: dict[str, Any] | BaseException | None,
    *,
    token: Any = ("tok",),
    scope_key: str = "project:sase",
) -> SimpleNamespace:
    def _review_state(_scopes: list[Any]) -> dict[str, Any]:
        if isinstance(wire, BaseException):
            raise wire
        assert isinstance(wire, dict)
        return wire

    service = SimpleNamespace(
        project_scope=lambda _root: SimpleNamespace(
            scope_key=scope_key, repo_root="/tmp/sase"
        ),
        review_state=_review_state,
    )
    return SimpleNamespace(service=service, change_token=lambda _scope: token)


def test_compute_memory_badge_returns_count_and_token() -> None:
    history = _fake_history(_wire(new_count=2))
    assert _compute_memory_badge("/tmp/sase", history) == (2, ("tok",))


def test_compute_memory_badge_hides_unreviewed_and_failed() -> None:
    assert _compute_memory_badge("/tmp/sase", _fake_history(_wire(watermark=None))) == (
        None,
        ("tok",),
    )
    assert _compute_memory_badge("/tmp/sase", _fake_history(_wire(new_count=0))) == (
        None,
        ("tok",),
    )
    assert _compute_memory_badge(
        "/tmp/sase", _fake_history(RuntimeError("store gone"))
    ) == (None, ("tok",))


def test_compute_memory_badge_hides_without_project_scope() -> None:
    history = SimpleNamespace(
        service=SimpleNamespace(
            project_scope=lambda _root: (_ for _ in ()).throw(RuntimeError("NO VCS")),
        ),
        change_token=lambda _scope: None,
    )
    assert _compute_memory_badge("/tmp/elsewhere", history) == (None, None)
