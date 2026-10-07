"""Model directive argument completion.

Split from ``test_directive_arg_completion``; shared builders live in
``_directive_completion_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets._directive_completion_tokens import (
    extract_directive_arg_token_around_cursor,
)
from sase.ace.tui.widgets.directive_completion import ModelCompletionMetadata
from sase.macro.effort import EFFORT_LEVELS_ORDERED
from sase.macro.model_completion import ModelCompletionEntry

from ._directive_completion_helpers import (
    MODEL_CATALOG_PATCH,
    build_directive_arg_completion_candidates,
    model_entries,
    model_entries_with_providers,
    model_metadata,
)

__all__ = [
    "test_directive_arg_completion_builds_model_candidates_from_catalog",
    "test_directive_arg_completion_filters_leading_at_to_model_aliases",
    "test_directive_arg_completion_filters_model_candidates_by_short_alias",
    "test_directive_arg_completion_filters_provider_scope_in_paren_forms",
    "test_directive_arg_completion_filters_provider_scoped_models",
    "test_directive_arg_completion_marks_provider_candidates_as_directories",
    "test_model_alias_candidate_carries_resolution_and_provenance",
    "test_model_candidate_preserves_structured_advisory_metadata",
    "test_model_completion_keystroke_path_never_uses_override_lock",
    "test_provider_scoped_model_completion_has_no_shared_extension",
    "test_qualified_model_at_suffix_routes_to_effort_completion",
]


def test_directive_arg_completion_builds_model_candidates_from_catalog() -> None:
    with patch(MODEL_CATALOG_PATCH, return_value=model_entries()):
        candidates, shared = build_directive_arg_completion_candidates("model", "")

    assert [candidate.insertion for candidate in candidates] == [
        "claude-fable-5",
        "gpt-5.6-sol",
    ]
    assert shared == ""
    metadata = model_metadata(candidates[0])
    assert metadata.description == "Claude (fable)"
    assert metadata.provider == "claude"
    assert metadata.provider_display == "Claude"
    assert metadata.short_alias == "fable"


def test_model_candidate_preserves_structured_advisory_metadata() -> None:
    catalog = [
        ModelCompletionEntry(
            value="muse-contributor-1.1",
            display="muse-contributor-1.1",
            description="Muse (contrib) — ⚠ trains on your data",
            kind="model",
            provider="muse",
            provider_display="Muse",
            aliases=("contrib",),
            bucket="external",
            advisory_label="trains on your data",
            advisory_severity="warn",
        )
    ]

    with patch(MODEL_CATALOG_PATCH, return_value=catalog):
        candidates, shared = build_directive_arg_completion_candidates(
            "model",
            "contrib",
        )

    assert shared == ""
    metadata = model_metadata(candidates[0])
    assert metadata.provider_display == "Muse"
    assert metadata.description == "Muse (contrib) — ⚠ trains on your data"
    assert metadata.short_alias == "contrib"
    assert metadata.bucket == "external"
    assert metadata.advisory_label == "trains on your data"
    assert metadata.advisory_severity == "warn"


def test_directive_arg_completion_filters_model_candidates_by_short_alias() -> None:
    with patch(MODEL_CATALOG_PATCH, return_value=model_entries()):
        candidates, shared = build_directive_arg_completion_candidates("model", "fa")

    assert [candidate.insertion for candidate in candidates] == ["claude-fable-5"]
    assert shared == ""


def test_directive_arg_completion_filters_provider_scoped_models() -> None:
    with patch(MODEL_CATALOG_PATCH, return_value=model_entries_with_providers()):
        m_candidates, m_shared = build_directive_arg_completion_candidates(
            "m", "claude/"
        )
        model_candidates, model_shared = build_directive_arg_completion_candidates(
            "model", "claude/"
        )

    assert [candidate.insertion for candidate in m_candidates] == [
        "claude/claude-fable-5"
    ]
    assert [candidate.insertion for candidate in model_candidates] == [
        "claude/claude-fable-5"
    ]
    assert m_shared == ""
    assert model_shared == ""


def test_directive_arg_completion_filters_provider_scope_in_paren_forms() -> None:
    lines = [
        "%model(claude/)",
        "%model(opus, alias=claude/)",
    ]

    with patch(MODEL_CATALOG_PATCH, return_value=model_entries_with_providers()):
        insertions = []
        for line in lines:
            token = extract_directive_arg_token_around_cursor(line, line.index(")"))
            assert token is not None
            _start, _end, directive_name, partial = token
            candidates, shared = build_directive_arg_completion_candidates(
                directive_name, partial
            )
            insertions.append([candidate.insertion for candidate in candidates])
            assert shared == ""

    assert insertions == [
        ["claude/claude-fable-5"],
        ["claude/claude-fable-5"],
    ]


def test_directive_arg_completion_marks_provider_candidates_as_directories() -> None:
    with patch(MODEL_CATALOG_PATCH, return_value=model_entries_with_providers()):
        candidates, shared = build_directive_arg_completion_candidates("model", "cl")

    provider = next(
        candidate for candidate in candidates if candidate.insertion == "claude/"
    )
    assert provider.is_dir is True
    metadata = model_metadata(provider)
    assert metadata.kind == "provider"
    assert metadata.provider_display == "Claude"
    assert metadata.provider_model_count == 1
    assert shared == "aude"


def test_provider_scoped_model_completion_has_no_shared_extension() -> None:
    catalog = [
        ModelCompletionEntry(
            value="opus",
            display="opus",
            description="Claude",
            provider="claude",
        ),
        ModelCompletionEntry(
            value="sonnet",
            display="sonnet",
            description="Claude",
            provider="claude",
        ),
        ModelCompletionEntry(
            value="claude/",
            display="claude/",
            description="Claude",
            kind="provider",
            provider="claude",
            provider_model_count=2,
        ),
    ]

    with patch(MODEL_CATALOG_PATCH, return_value=catalog):
        candidates, shared = build_directive_arg_completion_candidates(
            "model", "claude/"
        )

    assert [candidate.insertion for candidate in candidates] == [
        "claude/opus",
        "claude/sonnet",
    ]
    assert shared == ""


def test_directive_arg_completion_filters_leading_at_to_model_aliases() -> None:
    catalog = [
        *model_entries(),
        ModelCompletionEntry(
            value="@default",
            display="@default",
            description="default model when a prompt has no %model",
            provider="claude",
            aliases=(),
            kind="implicit_alias",
        ),
    ]

    with patch(MODEL_CATALOG_PATCH, return_value=catalog):
        candidates, shared = build_directive_arg_completion_candidates("model", "@")

    assert [candidate.insertion for candidate in candidates] == ["@default"]
    assert all(candidate.insertion.startswith("@") for candidate in candidates)
    assert shared == ""


def test_qualified_model_at_suffix_routes_to_effort_completion() -> None:
    line = "%m:claude/opus@"
    token = extract_directive_arg_token_around_cursor(line, len(line))

    assert token == (len("%m:claude/opus@"), len(line), "effort", "")
    candidates, shared = build_directive_arg_completion_candidates("effort", "")
    assert [candidate.insertion for candidate in candidates] == list(
        EFFORT_LEVELS_ORDERED
    )
    assert shared == ""


def test_model_alias_candidate_carries_resolution_and_provenance() -> None:
    catalog = [
        ModelCompletionEntry(
            value="@medium",
            display="@medium",
            description="Medium phase worker model.",
            kind="implicit_alias",
            aliases=("medium",),
            alias_kind="role",
            target_provider="codex",
            target_model="gpt-5.6-sol",
            target_effort="high",
            provenance="configured",
            reference="large",
            reference_effort="medium",
            pool_available=2,
            pool_total=3,
            config_source="builtin",
        )
    ]

    with patch(MODEL_CATALOG_PATCH, return_value=catalog):
        candidates, _ = build_directive_arg_completion_candidates("model", "@")

    metadata = model_metadata(candidates[0])
    assert metadata == ModelCompletionMetadata(
        value="@medium",
        kind="implicit_alias",
        alias_kind="role",
        target_provider="codex",
        target_model="gpt-5.6-sol",
        target_effort="high",
        provenance="configured",
        reference="large",
        reference_effort="medium",
        pool_available=2,
        pool_total=3,
        description="Medium phase worker model.",
        config_source="builtin",
    )


def test_model_completion_keystroke_path_never_uses_override_lock() -> None:
    with (
        patch(MODEL_CATALOG_PATCH, return_value=model_entries()),
        patch(
            "sase.llm_provider.temporary_override.get_active_alias_overrides",
            side_effect=AssertionError("authoritative override load reached"),
        ),
        patch(
            "sase.llm_provider.temporary_override_state._locked_state",
            side_effect=AssertionError("override lock reached"),
        ),
    ):
        candidates, _ = build_directive_arg_completion_candidates("model", "")

    assert [candidate.insertion for candidate in candidates] == [
        "claude-fable-5",
        "gpt-5.6-sol",
    ]
