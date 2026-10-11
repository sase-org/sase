"""Chrome rule stays hidden while the time band is showing."""

from __future__ import annotations

from textual.widgets import Static

from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.history.models import SectionTimeState, committed_pin_for_ordinal
from sase.pager.history.provider import clear_history_provider_factories
from tests.pager._app_helpers import pager_view

_NOW = 1790769600
_V2_TIME = 1790085780
_IDENTITY = "note:project:demo/garden"


async def test_time_band_signature_match_keeps_chrome_rule_hidden() -> None:
    """A no-op band paint must re-hide the rule after trail/subject updates.

    Visual goldens flaked when inject called ``_update_subject`` (paints the
    band, hides the rule) then ``_update_trail`` (re-shows the rule because
    the trail snapshot signature changed) and ``_update_time_band`` returned
    early on a matching signature without restoring the hide.
    """
    clear_history_provider_factories()
    try:
        pin = committed_pin_for_ordinal(
            _IDENTITY, 2, commit="1" * 40, blob_oid="a" * 40
        )
        section = PagerSection(
            identity=_IDENTITY,
            title="garden.md",
            kind="file",
            body="# Garden\n",
            subject_ref=_IDENTITY,
            version_pin=pin,
        )
        document = PagerDocument(
            sections=(section,), title="garden.md", origin=PagerOrigin.FILE
        )
        app = SasePager(document)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            view = pager_view(app)
            view._time_band_now_epoch = _NOW
            state = SectionTimeState(
                provider_key="fixture",
                subject_id=_IDENTITY,
                scope_key="project",
                status="live",
                visible_ordinals=(1, 2),
                current_pin=pin,
                timeline=(
                    {
                        "ordinal": 2,
                        "commit": "1" * 40,
                        "blob_oid": "a" * 40,
                        "committer_time": _V2_TIME,
                        "class": "promoted",
                    },
                    {
                        "ordinal": 1,
                        "commit": "0" * 40,
                        "blob_oid": "b" * 40,
                        "committer_time": _V2_TIME - 86400,
                        "class": "created",
                    },
                ),
            )
            view._history_states[section.identity] = state
            view._history_supported[section.identity] = True
            view._update_subject()
            time_widget = view.query_one("#pager-time", Static)
            rule = view.query_one("#pager-chrome-rule", Static)
            assert not time_widget.has_class("hidden")
            assert rule.has_class("hidden")
            rule.remove_class("hidden")
            view._update_time_band()
            assert rule.has_class("hidden")
            view._update_trail()
            assert rule.has_class("hidden")
    finally:
        clear_history_provider_factories()
