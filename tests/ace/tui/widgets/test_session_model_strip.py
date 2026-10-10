from __future__ import annotations

from rich.cells import cell_len

from sase.ace.tui.widgets.prompt_panel._session_model_strip import (
    expanded_session_model_summary,
    fit_session_model_strip,
)
from sase.core.agent_models import (
    AgentModelIdentity,
    AgentModelSummary,
)


def _summary(
    *models: tuple[str | None, str],
    latest: int = -1,
    unknown: int = 0,
) -> AgentModelSummary:
    identities = tuple(
        AgentModelIdentity(provider=provider, model=model) for provider, model in models
    )
    return AgentModelSummary(
        models=identities,
        latest=identities[latest] if identities else None,
        unknown_turn_count=unknown,
    )


def _assert_cell_bounded(text: str, width: int) -> None:
    assert all(cell_len(line) <= width for line in text.splitlines())


def test_all_models_fit_across_two_rows_without_omissions() -> None:
    fit = fit_session_model_strip(
        _summary(("codex", "alpha"), ("claude", "beta"), ("agy", "gamma")),
        width=24,
        max_rows=2,
    )

    assert fit.rows == 2
    assert fit.omitted_count == 0
    assert all(name in fit.text.plain for name in ("alpha", "beta", "gamma"))
    _assert_cell_bounded(fit.text.plain, 24)


def test_provider_collisions_are_qualified_before_fitting() -> None:
    fit = fit_session_model_strip(
        _summary(("codex", "shared"), ("claude", "shared")),
        width=80,
        max_rows=1,
    )

    assert "codex/shared" in fit.text.plain
    assert "claude/shared" in fit.text.plain
    assert fit.omitted_count == 0


def test_overflow_keeps_latest_then_earliest_models_in_first_use_order() -> None:
    fit = fit_session_model_strip(
        _summary(
            ("codex", "alpha"),
            ("claude", "beta-version-long"),
            ("agy", "gamma"),
            latest=2,
        ),
        width=31,
        max_rows=1,
    )

    assert fit.omitted_count == 1
    assert "+1 more" in fit.text.plain
    assert "gamma" in fit.text.plain
    assert fit.text.plain.index("alpha") < fit.text.plain.index("gamma")
    _assert_cell_bounded(fit.text.plain, 31)


def test_unknown_metadata_is_separate_from_model_overflow() -> None:
    fit = fit_session_model_strip(
        _summary(("codex", "alpha"), ("claude", "beta"), latest=1, unknown=12),
        width=80,
        max_rows=2,
    )

    assert "12 unknown" in fit.text.plain
    assert fit.omitted_count == 0
    expanded = expanded_session_model_summary(_summary(("codex", "alpha"), unknown=2))
    assert "2 turns have no recorded model" in expanded.plain
    assert "codex/alpha" in expanded.plain


def test_long_and_wide_model_names_are_cell_bounded_and_source_is_unchanged() -> None:
    source = _summary(("codex", "漢字-model-with-a-long-version-2026"), latest=0)
    fit = fit_session_model_strip(source, width=18, max_rows=1)

    assert fit.rows == 1
    assert "…" in fit.text.plain
    assert fit.omitted_count == 0
    assert source.models[0].model == "漢字-model-with-a-long-version-2026"
    _assert_cell_bounded(fit.text.plain, 18)


def test_no_known_models_shows_unknown_without_fabricating_default() -> None:
    fit = fit_session_model_strip(_summary(unknown=3), width=30, max_rows=1)

    assert "Models: unknown" == fit.text.plain
    assert "default" not in fit.text.plain
