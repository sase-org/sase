"""Tests for the typed prompt-history project-filter Rust facade.

These exercise the real ``sase_core_rs`` binding end to end (compile, seed,
match) rather than mocking the core behavior.
"""

from __future__ import annotations

from sase.core.prompt_history_filter_facade import (
    build_prompt_history_seed,
    compile_prompt_history_query,
    match_prompt_history_rows,
)
from sase.core.prompt_history_filter_wire import (
    PromptHistoryProjectIdentity,
    PromptHistoryRowFacts,
)

_CATALOG = [
    PromptHistoryProjectIdentity(
        key="gh_sase-org__sase",
        label="sase",
        aliases=["sase-main"],
        raw_refs=["sase-org/sase"],
    ),
    PromptHistoryProjectIdentity(key="sase-core"),
]


def test_compile_resolves_alias_and_raw_ref_to_canonical_key() -> None:
    for value in ["sase", "sase-main", "sase-org/sase", "gh_sase-org__sase"]:
        compiled = compile_prompt_history_query(f"project:{value} fix", _CATALOG)
        assert compiled.project_key == "gh_sase-org__sase", value
        assert compiled.project_label == "sase"
        assert compiled.text == "fix"
        assert compiled.valid is True
        assert compiled.diagnostic is None


def test_compile_plain_query_has_no_project_scope() -> None:
    compiled = compile_prompt_history_query("fix parser", _CATALOG)

    assert compiled.has_project_scope is False
    assert compiled.text == "fix parser"


def test_compile_malformed_qualifier_is_invalid_with_diagnostic() -> None:
    compiled = compile_prompt_history_query("project:", _CATALOG)

    assert compiled.valid is False
    assert compiled.diagnostic is not None


def test_build_prompt_history_seed_resolves_ref_and_keeps_modifier_order() -> None:
    seed = build_prompt_history_seed(
        raw_ref="sase-org/sase",
        remainder_text="%m:opus fix parser",
        catalog=_CATALOG,
    )

    assert seed.seed_text == "project:sase %m:opus fix parser"
    assert seed.hint is None


def test_build_prompt_history_seed_unresolved_ref_keeps_text_with_hint() -> None:
    seed = build_prompt_history_seed(
        raw_ref="totally-unknown-agent",
        remainder_text="fix parser",
        catalog=_CATALOG,
    )

    assert seed.seed_text == "fix parser"
    assert seed.hint == "Project scope unavailable; searching all loaded prompts"


def test_match_prompt_history_rows_scopes_by_resolved_project_key() -> None:
    compiled = compile_prompt_history_query("project:sase fix", _CATALOG)
    rows = [
        PromptHistoryRowFacts(
            index=0,
            canonical_text="fix parser",
            display_text="fix parser",
            segment_project_keys=["gh_sase-org__sase"],
            segment_raw_refs=[None],
        ),
        PromptHistoryRowFacts(
            index=1,
            canonical_text="fix the core",
            display_text="fix the core",
            segment_project_keys=["sase-core"],
            segment_raw_refs=[None],
        ),
    ]

    assert match_prompt_history_rows(compiled, rows) == frozenset({0})
