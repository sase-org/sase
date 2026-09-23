"""Pure context-rewrite helpers for the plan-then-commit reveal engine."""

from __future__ import annotations

from sase.ace.link_reveal_context import (
    RevealContext,
    _resolve_reveal_limit,
    explain_hidden,
    render_reveal_query,
)
from sase.ace.query_profile import (
    agents_query_schema,
    beads_query_schema,
    compile_query_profile,
)


class _Probe:
    def __init__(self, matching: dict[str, bool], *, default: bool = False) -> None:
        self.matching = matching
        self.default = default

    def matches(self, query: str) -> bool:
        return self.matching.get(query, self.default)


def test_render_flat_single_alternative_keeps_limit() -> None:
    profile = compile_query_profile(beads_query_schema())
    context = RevealContext(
        alternatives=(("id", "alpha-1.*"),),
        label="epic alpha-1",
        member_count=2,
    )
    assert (
        render_reveal_query(
            context, profile, current_query="-status:closed limit:100", page_size=100
        )
        == "id:alpha-1.* limit:100"
    )


def test_render_flat_epic_includes_both_terms() -> None:
    profile = compile_query_profile(beads_query_schema())
    context = RevealContext(
        alternatives=(("id", "alpha-1"), ("id", "alpha-1.*")),
        label="epic alpha-1",
        member_count=3,
    )
    assert (
        render_reveal_query(
            context, profile, current_query="-status:closed limit:100", page_size=100
        )
        == "id:alpha-1 id:alpha-1.* limit:100"
    )


def test_render_boolean_joins_with_or() -> None:
    profile = compile_query_profile(agents_query_schema())
    context = RevealContext(
        alternatives=(("name", "foo"), ("name", "foo.*")),
        label="foo hood",
        member_count=2,
    )
    assert (
        render_reveal_query(
            context, profile, current_query="status:RUNNING limit:100", page_size=100
        )
        == "(name:foo OR name:foo.*) limit:100"
    )


def test_render_boolean_single_alternative_has_no_parens() -> None:
    profile = compile_query_profile(agents_query_schema())
    context = RevealContext(alternatives=(("name", "foo"),), label="agent foo")
    assert (
        render_reveal_query(
            context, profile, current_query="status:RUNNING limit:100", page_size=100
        )
        == "name:foo limit:100"
    )


def test_render_keeps_star_bare() -> None:
    profile = compile_query_profile(beads_query_schema())
    context = RevealContext(alternatives=(("id", "sase-16n.*"),), label="epic sase-16n")
    rendered = render_reveal_query(
        context, profile, current_query="limit:100", page_size=100
    )
    assert rendered == "id:sase-16n.* limit:100"
    assert "*" in rendered
    assert '"sase-16n.*"' not in rendered


def test_limit_policy_raises_to_page_multiple() -> None:
    assert _resolve_reveal_limit("-status:closed limit:40", 120, 100) == 200
    assert _resolve_reveal_limit("-status:closed limit:100", 2, 100) == 100
    assert _resolve_reveal_limit("-status:closed limit:100", None, 100) == 100


def test_limit_policy_unlimited_stays_unlimited() -> None:
    assert _resolve_reveal_limit("limit:all", 500, 100) is None
    assert _resolve_reveal_limit("status:open", 500, 100) is None


def test_explain_hidden_lists_excluding_terms() -> None:
    profile = compile_query_profile(beads_query_schema())
    probe = _Probe(
        {"-status:closed": False, "": True},
        default=True,
    )
    reason = explain_hidden(probe, "-status:closed limit:100", profile)
    assert reason.kind == "filtered"
    assert reason.terms == ("-status:closed",)


def test_explain_hidden_reports_past_limit() -> None:
    profile = compile_query_profile(beads_query_schema())
    probe = _Probe({"-status:closed": True, "": True}, default=True)
    reason = explain_hidden(probe, "-status:closed limit:100", profile)
    assert reason.kind == "limited"
    assert reason.cap == 100


def test_explain_hidden_boolean_has_no_terms() -> None:
    profile = compile_query_profile(agents_query_schema())
    probe = _Probe({}, default=False)
    reason = explain_hidden(probe, "status:RUNNING AND name:hidden", profile)
    assert reason.kind == "filtered_boolean"
    assert reason.terms == ()


def test_explain_hidden_unloaded_when_probe_missing() -> None:
    profile = compile_query_profile(beads_query_schema())
    reason = explain_hidden(None, "-status:closed limit:100", profile)
    assert reason.kind == "unloaded"
