"""Pure helpers for the host-owned link-follow reveal lens."""

from __future__ import annotations

from sase.ace.link_reveal import (
    LinkReveal,
    is_link_reveal_active,
    make_link_reveal,
    minimal_widening_query,
)
from sase.ace.query_record import QueryRecord
from sase.core.artifact_entry_target import ArtifactEntryTarget


class _Probe:
    def __init__(self, matching: dict[str, bool], *, default: bool = False) -> None:
        self.matching = matching
        self.default = default

    def matches(self, query: str) -> bool:
        return self.matching.get(query, self.default)


def test_minimal_widening_drops_excluding_status_term() -> None:
    probe = _Probe(
        {
            "project:demo -status:closed": False,
            "project:demo": True,
            "-status:closed": False,
        }
    )
    assert (
        minimal_widening_query("project:demo -status:closed", probe)
        == "project:demo limit:all"
    )


def test_minimal_widening_drops_since_for_old_row() -> None:
    probe = _Probe({"since:24h": False, "": True})
    assert minimal_widening_query("since:24h", probe) == "limit:all"


def test_minimal_widening_returns_none_when_row_already_matches() -> None:
    probe = _Probe({"project:demo": True})
    assert minimal_widening_query("project:demo", probe) is None


def test_minimal_widening_returns_none_for_boolean_grammar() -> None:
    probe = _Probe({})
    query = "status:open AND project:demo"
    assert minimal_widening_query(query, probe) is None


def test_minimal_widening_preserves_quoted_values() -> None:
    probe = _Probe(
        {
            'title:"my plan" -status:closed': False,
            'title:"my plan"': True,
            "-status:closed": False,
        }
    )
    assert (
        minimal_widening_query('title:"my plan" -status:closed', probe)
        == 'title:"my plan" limit:all'
    )


def test_is_link_reveal_active_true_immediately_after_reveal() -> None:
    reveal = make_link_reveal(
        pane_id="beads",
        ref="bead:sase-123",
        origin_source="status:open",
        origin_canonical="status:open",
        origin_target=ArtifactEntryTarget("beads", ("demo", "task", "sase-1")),
        revealed_canonical="limit:all",
    )
    assert is_link_reveal_active(reveal, pane_id="beads", current_canonical="limit:all")


def test_is_link_reveal_active_false_after_user_query_edit() -> None:
    reveal = make_link_reveal(
        pane_id="beads",
        ref="bead:sase-123",
        origin_source="status:open",
        origin_canonical="status:open",
        origin_target=None,
        revealed_canonical="limit:all",
    )
    assert not is_link_reveal_active(
        reveal, pane_id="beads", current_canonical="status:open project:demo"
    )


def test_is_link_reveal_active_false_after_prev_query() -> None:
    reveal = make_link_reveal(
        pane_id="beads",
        ref="bead:sase-123",
        origin_source="status:open",
        origin_canonical="status:open",
        origin_target=None,
        revealed_canonical="limit:all",
    )
    assert not is_link_reveal_active(
        reveal, pane_id="beads", current_canonical="status:open"
    )


def test_is_link_reveal_active_false_after_profile_digest_change() -> None:
    reveal = LinkReveal(
        pane_id="beads",
        ref="bead:sase-123",
        origin=QueryRecord(
            source="status:open",
            canonical="status:open",
            profile_digest="stale-digest",
        ),
        origin_target=None,
        revealed_canonical="limit:all",
    )
    assert not is_link_reveal_active(
        reveal, pane_id="beads", current_canonical="limit:all"
    )
