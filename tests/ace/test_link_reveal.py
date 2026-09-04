"""Pure helpers for the host-owned link-follow reveal lens."""

from __future__ import annotations

from sase.ace.link_reveal import (
    LinkReveal,
    build_identity_reveal_query,
    is_link_reveal_active,
    make_link_reveal,
    minimal_widening_query,
)
from sase.ace.query_profile import (
    beads_query_schema,
    compile_query_profile,
    files_query_schema,
    patches_query_schema,
    plans_query_schema,
    procs_query_schema,
    stitches_query_schema,
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


def test_build_identity_reveal_query_quotes_each_pane() -> None:
    cases = (
        (beads_query_schema(), {"fields": {"id": "sase-123"}}, "id:sase-123"),
        (
            stitches_query_schema(),
            {"fields": {"sha": "abcdef1234567890"}},
            "sha:abcdef1234567890",
        ),
        (files_query_schema(), {"fields": {"id": "logical-1"}}, "id:logical-1"),
        (
            plans_query_schema(),
            {"fields": {"path": "docs/my plan.md"}},
            'path:"docs/my plan.md"',
        ),
        (patches_query_schema(), {"fields": {"name": "my-cl"}}, "name:my-cl"),
    )
    for schema, row, expected in cases:
        profile = compile_query_profile(schema)
        assert build_identity_reveal_query(profile, row) == expected


def test_build_identity_reveal_query_none_when_dialect_lacks_field() -> None:
    profile = compile_query_profile(procs_query_schema())
    assert profile.identity_field is None
    assert build_identity_reveal_query(profile, {"fields": {"name": "job"}}) is None


def test_build_identity_reveal_query_none_when_row_has_no_value() -> None:
    profile = compile_query_profile(beads_query_schema())
    assert build_identity_reveal_query(profile, {"fields": {"status": "open"}}) is None
