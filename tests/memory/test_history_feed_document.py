"""Builder goldens for the memory changes feed pager document (no git/core).

Covers the sase-1dr.10 feed: one section per day, subject labels that
resolve to ``subject@version`` diff targets, folded consequences,
collapsed regen-only groups with in-place expansion, interleaved home
changesets with the ``⌂`` tag, and the empty-feed notice.
"""

from __future__ import annotations

import datetime
from typing import Any

from sase.memory.history.feed_document import (
    FEED_SUBJECT_KIND,
    _FeedSubject,
    _build_feed_section,
    _feed_subject_target,
    build_feed_document,
    parse_feed_subject_target,
    resolve_feed_subject,
)
from sase.pager.document import PagerOrigin, section_target_spans
from sase.pager.history.diff import FOLD_TARGET_KIND, FOLD_TOKEN

_DAY_ONE = 1790486400
_DAY_TWO = 1790400000


def _expected_day_title(epoch: int) -> str:
    return datetime.datetime.fromtimestamp(epoch).strftime("%a %b %d")


def _authored(
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


def _changeset(
    commit: str = "d" * 40,
    committer_time: int = _DAY_ONE,
    subject: str = "feat(tabs): something",
    scope_key: str = "project:sase",
    bead: str = "sase-1bu.7",
    agent: str = "athena.sase-1bu.7",
    authored: list[dict[str, Any]] | None = None,
    consequences: list[dict[str, Any]] | None = None,
    regen_only: bool = False,
    boilerplate: bool = False,
) -> dict[str, Any]:
    return {
        "scope_key": scope_key,
        "commit": commit,
        "committer_time": committer_time,
        "provenance": {"subject": subject, "bead": bead, "agent": agent},
        "boilerplate": boilerplate,
        "regen_only": regen_only,
        "authored": authored if authored is not None else [_authored()],
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


def _feed() -> dict[str, Any]:
    return {
        "changesets": [
            _changeset(),
            _changeset(
                commit="e" * 40,
                committer_time=_DAY_ONE + 600,
                subject="feat(home): tweak",
                scope_key="home",
                bead="",
                agent="",
                authored=[],
                consequences=[],
            ),
            _changeset(
                commit="f" * 40,
                committer_time=_DAY_TWO,
                subject="chore: regen",
                bead="",
                agent="",
                authored=[],
                consequences=[],
                regen_only=True,
            ),
        ],
        "hidden_changeset_count": 0,
    }


def _targets_by_kind(section: Any, origin: Any) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for span in section_target_spans(section, origin):
        grouped.setdefault(span.kind, []).append(span)
    return grouped


def test_feed_builds_one_section_per_day() -> None:
    result = build_feed_document(_feed(), "project:sase + home")

    assert len(result.document.sections) == 2
    first, second = result.document.sections
    assert first.identity.startswith("history-feed:")
    assert first.title == _expected_day_title(_DAY_ONE)
    assert second.title == _expected_day_title(_DAY_TWO)
    assert result.document.origin is PagerOrigin.FILE


def test_feed_title_carries_scopes_and_counts() -> None:
    result = build_feed_document(_feed(), "project:sase + home")

    assert "project:sase + home" in result.document.title
    assert "3 changesets" in result.document.title


def test_feed_subject_rows_are_versioned_labels() -> None:
    result = build_feed_document(_feed(), "project:sase")
    section = result.document.sections[0]
    grouped = _targets_by_kind(section, result.document.origin)

    subjects = grouped[FEED_SUBJECT_KIND]
    assert len(subjects) == 1
    assert subjects[0].text == "glossary/artifact"
    parsed = parse_feed_subject_target(str(subjects[0].target))
    assert parsed is not None
    assert parsed.scope_key == "project:sase"
    assert parsed.selector == "sase/memory/glossary/artifact.md"
    assert parsed.revision == "v3"


def test_feed_provenance_rows_are_resolver_labels() -> None:
    result = build_feed_document(_feed(), "project:sase")
    section = result.document.sections[0]
    grouped = _targets_by_kind(section, result.document.origin)

    provenance = {span.text: span.target for span in grouped["artifact_ref"]}
    assert provenance["sase-1bu.7"] == "bead:sase-1bu.7"
    assert provenance["athena.sase-1bu.7"] == "agent:athena.sase-1bu.7"
    assert provenance["d" * 7] == f"commit:{'d' * 40}"


def test_feed_folds_consequences_and_tags_home() -> None:
    result = build_feed_document(_feed(), "project:sase + home")
    body = result.document.sections[0].plain_text

    assert "⟳ AGENTS.md" in body
    assert "⌂" in body


def test_feed_collapses_regen_only_into_expandable_count() -> None:
    result = build_feed_document(_feed(), "project:sase")

    assert len(result.folds) == 1
    fold = result.folds[0]
    assert fold.fold_index == 0
    assert fold.hidden_count == 1
    collapsed = result.document.sections[1].plain_text
    assert "1 regenerated-only changeset hidden" in collapsed
    assert FOLD_TOKEN in collapsed
    grouped = _targets_by_kind(result.document.sections[1], result.document.origin)
    assert [span.target for span in grouped[FOLD_TARGET_KIND]] == [0]
    # The collapsed group hides its rows until expanded.
    assert "chore: regen" not in collapsed


def test_feed_regen_group_expands_in_place_without_core() -> None:
    result = build_feed_document(_feed(), "project:sase")
    document = result.document
    assert document.expand_fold_fn is not None
    fold = result.folds[0]

    expanded_section = document.expand_fold_fn(fold.section_identity, fold.fold_index)

    assert expanded_section is not None
    assert expanded_section.identity == fold.section_identity
    assert "chore: regen" in expanded_section.plain_text
    assert FOLD_TOKEN not in expanded_section.plain_text
    # Expanding twice, or expanding an unknown fold, is a no-op.
    assert document.expand_fold_fn(fold.section_identity, fold.fold_index) is None
    assert document.expand_fold_fn("history-feed:nope", 0) is None
    assert document.expand_fold_fn(fold.section_identity, 7) is None


def test_feed_all_flag_pre_expands_regen_groups() -> None:
    result = build_feed_document(_feed(), "project:sase", expanded_regen="all")

    assert result.folds == ()
    assert "chore: regen" in result.document.sections[1].plain_text


def test_feed_empty_window_shows_a_notice_section() -> None:
    result = build_feed_document({"changesets": []}, "project:sase")

    assert len(result.document.sections) == 1
    assert "no memory changes" in result.document.sections[0].plain_text
    assert result.folds == ()


def test_feed_subject_target_round_trip() -> None:
    subject = _FeedSubject(
        scope_key="home",
        selector="home/sase/memory/tui.md",
        revision="v2",
        display="tui",
    )

    parsed = parse_feed_subject_target(_feed_subject_target(subject))

    assert parsed is not None
    assert parsed.scope_key == "home"
    assert parsed.selector == "home/sase/memory/tui.md"
    assert parsed.revision == "v2"
    assert parse_feed_subject_target("bead:sase-1bu.7") is None
    assert parse_feed_subject_target("{not json") is None
    assert parse_feed_subject_target('{"kind": "other"}') is None


def test_resolve_feed_subject_routes_scope_and_revision(
    monkeypatch: Any,
) -> None:
    import sase.memory.history.feed_document as feed_mod

    captured: dict[str, Any] = {}

    class _FakeDocument:
        pass

    def _fake_build(
        *,
        scope: Any,
        subject: str,
        initial_revision: str,
        view: str,
        service: Any,
        title: Any = None,
        compare_base: Any = None,
    ) -> Any:
        captured.update(
            scope=scope,
            subject=subject,
            initial_revision=initial_revision,
            view=view,
        )
        return _FakeDocument()

    monkeypatch.setattr(
        "sase.memory.history.pager_provider.build_history_document", _fake_build
    )
    scope = object()
    ref = _feed_subject_target(
        _FeedSubject(
            scope_key="project:sase",
            selector="sase/memory/note.md",
            revision="v2",
            display="note",
        )
    )

    target = resolve_feed_subject(feed_mod, {"project:sase": scope}, ref)

    assert target is not None
    assert target.document is not None
    assert captured["scope"] is scope
    assert captured["subject"] == "sase/memory/note.md"
    assert captured["initial_revision"] == "v2"
    assert captured["view"] == "diff"


def test_resolve_feed_subject_declines_unknown_refs() -> None:
    assert resolve_feed_subject(object(), {}, "bead:sase-1bu.7") is None
    ref = _feed_subject_target(
        _FeedSubject(scope_key="nope", selector="x.md", revision="v1", display="x")
    )
    assert resolve_feed_subject(object(), {}, ref) is None


def test_feed_pager_wires_resolve_refresh_and_all_flag(
    monkeypatch: Any,
) -> None:
    """The no-selector pager path feeds hidden changesets and rebuilds."""
    import argparse
    from types import SimpleNamespace

    from sase.memory.history import cli_history_command

    captured: dict[str, Any] = {}

    class _FakePager:
        def __init__(self, document: Any, **kwargs: Any) -> None:
            captured["document"] = document
            captured.update(kwargs)

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr("sase.pager.app.SasePager", _FakePager)

    class _FakeService:
        def __init__(self) -> None:
            self.calls: list[bool] = []

        def feed(
            self,
            scopes: Any,
            *,
            since: Any = None,
            limit: Any = None,
            include_hidden: bool = False,
        ) -> dict[str, Any]:
            self.calls.append(include_hidden)
            return _feed()

    service = _FakeService()
    scopes = [SimpleNamespace(scope_key="project:sase", scope_kind="project")]
    args = argparse.Namespace(all=False, limit=None, since=None)

    cli_history_command._handle_feed_pager(service, scopes, args)  # noqa: SLF001

    assert captured.get("ran") is True
    document = captured["document"]
    assert "project:sase" in document.title
    # Regen-only data stays client-side so the count line can expand.
    assert service.calls == [True]
    assert "chore: regen" not in document.sections[1].plain_text
    resolve = captured["resolve_ref_fn"]
    refresh = captured["refresh_document_fn"]
    assert callable(resolve) and callable(refresh)
    # Unknown refs delegate past the feed envelope (fail-open dead end here).
    assert resolve("bead:sase-1bu.7") is not None
    rebuilt = refresh()
    assert rebuilt is not None
    assert [section.identity for section in rebuilt.sections] == [
        section.identity for section in document.sections
    ]


def test_feed_pager_all_flag_pre_expands_regen(
    monkeypatch: Any,
) -> None:
    import argparse
    from types import SimpleNamespace

    from sase.memory.history import cli_history_command

    captured: dict[str, Any] = {}

    class _FakePager:
        def __init__(self, document: Any, **kwargs: Any) -> None:
            captured["document"] = document

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr("sase.pager.app.SasePager", _FakePager)

    class _FakeService:
        def feed(self, scopes: Any, **kwargs: Any) -> dict[str, Any]:
            return _feed()

    cli_history_command._handle_feed_pager(  # noqa: SLF001
        _FakeService(),
        [SimpleNamespace(scope_key="project:sase", scope_kind="project")],
        argparse.Namespace(all=True, limit=None, since=None),
    )

    assert captured.get("ran") is True
    assert "chore: regen" in captured["document"].sections[1].plain_text


def test_build_feed_section_collapses_and_expands() -> None:
    day = [
        _changeset(committer_time=_DAY_ONE),
        _changeset(
            commit="f" * 40,
            committer_time=_DAY_ONE,
            subject="chore: regen",
            bead="",
            agent="",
            authored=[],
            consequences=[],
            regen_only=True,
        ),
    ]

    section, folds = _build_feed_section("2026-09-27", "Sun Sep 27", day)

    assert section.identity == "history-feed:2026-09-27"
    assert len(folds) == 1
    expanded, expanded_folds = _build_feed_section(
        "2026-09-27", "Sun Sep 27", day, regen_expanded=True
    )
    assert expanded_folds == ()
    assert "chore: regen" in expanded.plain_text
