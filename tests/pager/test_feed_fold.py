"""In-place expansion for caller-owned document folds (feed regen groups)."""

from __future__ import annotations

from sase.memory.history.feed_document import build_feed_document
from sase.pager.app import SasePager
from sase.pager.history.diff import FOLD_TARGET_KIND

from ._app_helpers import pager_screen

_FEED = {
    "changesets": [
        {
            "scope_key": "project:sase",
            "commit": "d" * 40,
            "committer_time": 1790486400,
            "provenance": {
                "subject": "feat(tabs): something",
                "bead": "sase-1bu.7",
                "agent": "athena.sase-1bu.7",
            },
            "boilerplate": False,
            "regen_only": False,
            "authored": [],
            "consequences": [],
        },
        {
            "scope_key": "project:sase",
            "commit": "f" * 40,
            "committer_time": 1790400000,
            "provenance": {"subject": "chore: regen", "bead": "", "agent": ""},
            "boilerplate": False,
            "regen_only": True,
            "authored": [],
            "consequences": [],
        },
    ],
    "hidden_changeset_count": 0,
}


async def test_feed_regen_fold_expands_in_place_without_trail() -> None:
    result = build_feed_document(_FEED, "project:sase")
    assert len(result.folds) == 1
    app = SasePager(result.document)
    async with app.run_test(size=(100, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        assert screen._back_trail == []
        labels = [
            label
            for label in screen._label_layer.labels
            if label.target.kind == FOLD_TARGET_KIND
        ]
        assert len(labels) == 1
        section_index = labels[0].section_index
        before = screen.document.sections[section_index].plain_text
        assert "chore: regen" not in before

        screen._activate_label(labels[0])
        await pilot.pause()

        after = screen.document.sections[section_index].plain_text
        assert "chore: regen" in after
        # In-place recompose: no trail entry, same document identity otherwise.
        assert screen._back_trail == []
        assert len(screen.document.sections) == len(result.document.sections)


async def test_feed_regen_fold_without_hook_is_a_noop() -> None:
    result = build_feed_document(_FEED, "project:sase")
    plain = result.document
    from dataclasses import replace

    hookless = replace(plain, expand_fold_fn=None)
    app = SasePager(hookless)
    async with app.run_test(size=(100, 24)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        labels = [
            label
            for label in screen._label_layer.labels
            if label.target.kind == FOLD_TARGET_KIND
        ]
        assert len(labels) == 1
        before = screen.document.sections[labels[0].section_index].plain_text

        screen._activate_label(labels[0])
        await pilot.pause()

        assert screen.document.sections[labels[0].section_index].plain_text == before
        assert screen._back_trail == []
