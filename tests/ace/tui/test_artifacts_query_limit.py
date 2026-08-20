"""Host-owned ``limit:`` on every Artifacts dialect."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sase.ace.config import get_ace_page_size
from sase.ace.query import QueryParseError, parse_query_for_profile
from sase.ace.query.limit_token import apply_limit, ensure_limit
from sase.ace.query.types import StringMatch
from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.widgets.artifacts.files_filtering import (
    FilesFilterQueryError,
    parse_files_filter_query,
    to_query_string as files_to_query_string,
)
from sase.bead.filter_query import (
    BeadFilterQueryError,
    default_bead_filter_values,
    parse_bead_filter_query,
    to_query_string as beads_to_query_string,
)
from sase.plan_search.filter_query import (
    PlanFilterQueryError,
    parse_plan_filter_query,
    to_query_string as plans_to_query_string,
)


def test_default_bead_filter_includes_page_size_limit() -> None:
    values = default_bead_filter_values()
    page_size = get_ace_page_size()
    assert values.excluded_statuses == ("closed",)
    assert values.limit == page_size
    assert beads_to_query_string(values) == f"-status:closed limit:{page_size}"


def test_default_plan_and_file_queries_are_limit_only() -> None:
    page_size = get_ace_page_size()
    plans = parse_plan_filter_query(ensure_limit("", page_size))
    files = parse_files_filter_query(ensure_limit("", page_size))
    assert plans.limit == page_size
    assert files.limit == page_size
    assert plans_to_query_string(plans) == f"limit:{page_size}"
    assert files_to_query_string(files) == f"limit:{page_size}"
    assert plans.is_empty
    assert files.is_empty


@pytest.mark.parametrize(
    ("parse", "error_type"),
    [
        (parse_bead_filter_query, BeadFilterQueryError),
        (parse_plan_filter_query, PlanFilterQueryError),
        (parse_files_filter_query, FilesFilterQueryError),
    ],
)
def test_flat_dialects_accept_limit_and_reject_invalid_tokens(
    parse: object,
    error_type: type[Exception],
) -> None:
    values = parse("limit:40")  # type: ignore[operator]
    assert values.limit == 40
    with pytest.raises(error_type, match="may not be negated"):
        parse("-limit:10")  # type: ignore[operator]
    with pytest.raises(error_type, match="only appear once"):
        parse("limit:10 limit:20")  # type: ignore[operator]
    with pytest.raises(error_type, match="non-negative integer or 'all'"):
        parse("limit:foo")  # type: ignore[operator]


def test_limit_all_is_unlimited_and_omitted_from_canonical_text() -> None:
    values = parse_bead_filter_query("-status:closed limit:all")
    assert values.limit is None
    assert beads_to_query_string(values) == "-status:closed"


def test_explicit_user_limit_is_not_rewritten_by_ensure_limit() -> None:
    query = "-status:closed limit:40"
    assert ensure_limit(query, 100) == query


def test_apply_limit_caps_matched_rows_and_flags_truncation() -> None:
    matched = tuple(f"row-{index}" for index in range(5))
    sliced, truncated = apply_limit(matched, 2)
    assert sliced == ("row-0", "row-1")
    assert truncated is True


def test_patches_parse_strips_limit_before_boolean_eval() -> None:
    profile = compiled_profile_for_builtin_pane("patches")
    assert profile is not None
    expr = parse_query_for_profile("!!! limit:100", profile)
    assert isinstance(expr, StringMatch)
    assert expr.is_error_suffix is True
    with pytest.raises(QueryParseError, match="may not be negated"):
        parse_query_for_profile("-limit:10", profile)


def test_files_limit_does_not_become_a_membership_field() -> None:
    values = parse_files_filter_query("kind:image limit:25")
    membership = replace(values, limit=None)
    assert files_to_query_string(membership) == "kind:image"
    assert files_to_query_string(values) == "kind:image limit:25"
