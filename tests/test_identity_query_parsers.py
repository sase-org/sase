"""Identity-field tokens round-trip through the flat pane parsers."""

from __future__ import annotations

from sase.ace.tui.widgets.artifacts.files_filtering import (
    parse_files_filter_query,
    to_query_string as files_query,
)
from sase.bead.filter_query import (
    parse_bead_filter_query,
    to_query_string as bead_query,
)
from sase.plan_search.filter_query import (
    parse_plan_filter_query,
    to_query_string as plan_query,
)
from sase.vcs_log.filter_query import (
    parse_commit_filter_query,
    to_query_string as stitch_query,
)


def test_bead_id_token_round_trips() -> None:
    values = parse_bead_filter_query('id:sase-1 -id:"sase 2"')
    assert values.ids == ("sase-1",)
    assert values.excluded_ids == ("sase 2",)
    rendered = bead_query(values)
    assert "id:sase-1" in rendered
    assert '-id:"sase 2"' in rendered
    assert parse_bead_filter_query(rendered).ids == values.ids


def test_file_id_token_round_trips() -> None:
    values = parse_files_filter_query("id:logical-1")
    assert values.ids == ("logical-1",)
    assert files_query(values) == "id:logical-1"


def test_plan_path_token_round_trips() -> None:
    values = parse_plan_filter_query('path:"docs/my plan.md"')
    assert values.paths == ("docs/my plan.md",)
    assert plan_query(values) == 'path:"docs/my plan.md"'


def test_stitch_sha_token_round_trips() -> None:
    values = parse_commit_filter_query("sha:abcdef1")
    assert values.shas == ("abcdef1",)
    assert "sha:abcdef1" in stitch_query(values)
