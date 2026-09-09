"""Compact provider-usage top-bar presentation tests."""

from __future__ import annotations

from copy import deepcopy

from rich.cells import cell_len

from sase.ace.tui.widgets._provider_usage_indicator import (
    build_usage_indicator_segment,
    usage_indicator_presentations,
)
from sase.llm_provider.usage.hints import CapacityHint, indicator_usage_items
from tests._usage_view_helpers import usage_provider, usage_window


def _constraint(window: dict[str, object], attention: str) -> dict[str, object]:
    return {
        "attention": attention,
        "freshness": window["freshness"],
        "observed_at": window["observed_at"],
        "remaining_percent": window["remaining_percent"],
        "reset_passed": window["reset_passed"],
        "used_percent": window["used_percent"],
        "vendor_state": window["vendor_state"],
        "window_key": window["key"],
    }


def _window(
    *,
    key: str,
    label: str,
    used_percent: float,
    duration_seconds: float | None,
    applicability: dict[str, object],
) -> dict[str, object]:
    window = usage_window(
        key=key,
        label=label,
        used_percent=used_percent,
        remaining_percent=max(0.0, 100.0 - used_percent),
        applicability=applicability,
    )
    window["duration_seconds"] = duration_seconds
    return window


def _provider(
    name: str,
    window: dict[str, object],
    *,
    kind: str = "low",
) -> dict[str, object]:
    return usage_provider(
        name,
        used_percent=window["used_percent"],
        remaining_percent=window["remaining_percent"],
        attention={"kind": kind, "provider": name, "window_key": window["key"]},
        scope=window["applicability"],  # type: ignore[arg-type]
        windows=[window],
        known_constraints=[_constraint(window, kind)],
    )


def _presentations(
    *providers: dict[str, object],
) -> tuple[object, ...]:
    names = {str(provider["provider"]) for provider in providers}
    hints = indicator_usage_items(providers, eligible=names)
    return usage_indicator_presentations(hints, providers)


def test_compact_grok_weekly_account_allowance_with_additional_count() -> None:
    grok = _provider(
        "grok",
        _window(
            key="included_weekly",
            label="Grok included weekly allowance",
            used_percent=86.0,
            duration_seconds=604_800.0,
            applicability={"kind": "account"},
        ),
        kind="rejected",
    )
    codex = _provider(
        "codex",
        _window(
            key="primary",
            label="Codex",
            used_percent=88.0,
            duration_seconds=18_000.0,
            applicability={"kind": "account"},
        ),
    )
    claude = _provider(
        "claude",
        _window(
            key="weekly:opus",
            label="Claude weekly Opus",
            used_percent=94.0,
            duration_seconds=None,
            applicability={"kind": "models", "model_ids": ["opus"]},
        ),
    )
    before = deepcopy(grok)

    segment = build_usage_indicator_segment(_presentations(grok, codex, claude))

    assert segment.plain.strip() == "! GROK 14% left · wk/all +2"
    assert cell_len(segment.plain.strip()) == 27
    assert grok == before


def test_compact_labels_use_structured_period_and_scope() -> None:
    cases = [
        (
            "grok",
            _window(
                key="included_monthly",
                label="Grok included monthly allowance",
                used_percent=86.0,
                duration_seconds=None,
                applicability={"kind": "account"},
            ),
            "! GROK 14% left · mo/all",
        ),
        (
            "claude",
            _window(
                key="weekly:opus",
                label="Claude weekly Opus",
                used_percent=94.0,
                duration_seconds=None,
                applicability={"kind": "models", "model_ids": ["opus"]},
            ),
            "! CLAUDE 6% left · wk/opus",
        ),
        (
            "codex",
            _window(
                key="codex:primary",
                label="Codex",
                used_percent=88.0,
                duration_seconds=18_000.0,
                applicability={"kind": "account"},
            ),
            "! CODEX 12% left · 5h/all",
        ),
        (
            "claude",
            _window(
                key="session",
                label="Claude five-hour session",
                used_percent=90.0,
                duration_seconds=None,
                applicability={"kind": "product", "product": "claude"},
            ),
            "! CLAUDE 10% left · 5h/scope?",
        ),
        (
            "codex",
            _window(
                key="fast:primary",
                label="Fast",
                used_percent=88.0,
                duration_seconds=18_000.0,
                applicability={"kind": "unknown", "vendor_label": "Fast"},
            ),
            "! CODEX 12% left · Fast/5h/scope?",
        ),
    ]

    for provider_name, window, expected in cases:
        segment = build_usage_indicator_segment(
            _presentations(_provider(provider_name, window))
        )

        assert segment.plain.strip() == expected


def test_compact_subpercent_remaining_uses_core_left_label() -> None:
    grok = _provider(
        "grok",
        _window(
            key="included_weekly",
            label="Grok included weekly allowance",
            used_percent=99.5,
            duration_seconds=604_800.0,
            applicability={"kind": "account"},
        ),
    )

    segment = build_usage_indicator_segment(_presentations(grok))

    assert segment.plain.strip() == "! GROK <1% left · wk/all"


def test_collection_problem_keeps_question_marker_and_usage_label() -> None:
    codex = usage_provider(
        "codex",
        used_percent=None,
        remaining_percent=None,
        collection_status="error",
        attention={
            "kind": "collection_problem",
            "provider": "codex",
            "window_key": None,
        },
        windows=[],
    )

    segment = build_usage_indicator_segment(_presentations(codex))

    assert segment.plain.strip() == "? CODEX usage"


def test_missing_window_uses_original_hint_without_fabricating_scope() -> None:
    hint = CapacityHint(
        kind="low",
        label="12% left · Vendor supplied all models",
        provider="codex",
        window_key="missing",
        scope="Vendor supplied all models",
        remaining_percent=12.0,
    )
    provider = usage_provider(
        "codex",
        windows=[
            _window(
                key="different",
                label="Codex",
                used_percent=50.0,
                duration_seconds=18_000.0,
                applicability={"kind": "account"},
            )
        ],
    )

    segment = build_usage_indicator_segment(
        usage_indicator_presentations((hint,), (provider,))
    )

    assert segment.plain.strip() == "! CODEX 12% left · Vendor supplied all models"


def test_budget_ladder_hides_percentage_and_scope_together() -> None:
    grok = _provider(
        "grok",
        _window(
            key="included_weekly",
            label="Grok included weekly allowance",
            used_percent=86.0,
            duration_seconds=604_800.0,
            applicability={"kind": "account"},
        ),
        kind="rejected",
    )
    codex = _provider(
        "codex",
        _window(
            key="primary",
            label="Codex",
            used_percent=88.0,
            duration_seconds=18_000.0,
            applicability={"kind": "account"},
        ),
    )
    presentations = _presentations(grok, codex)
    normal = build_usage_indicator_segment(presentations)

    assert (
        build_usage_indicator_segment(
            presentations, budget=normal.cell_len
        ).plain.strip()
        == "! GROK 14% left · wk/all +1"
    )
    disclosed = build_usage_indicator_segment(presentations, budget=normal.cell_len - 1)

    assert disclosed.plain.strip() == "! GROK +1"
    assert "left" not in disclosed.plain
    assert "wk/all" not in disclosed.plain


def test_total_count_and_micro_candidates_use_total_not_additional_count() -> None:
    lead = _provider(
        "verylongcustomprovider",
        _window(
            key="primary",
            label="VeryLongCustomProvider included weekly allowance",
            used_percent=86.0,
            duration_seconds=604_800.0,
            applicability={"kind": "account"},
        ),
        kind="rejected",
    )
    codex = _provider(
        "codex",
        _window(
            key="primary",
            label="Codex",
            used_percent=88.0,
            duration_seconds=18_000.0,
            applicability={"kind": "account"},
        ),
    )
    grok = _provider(
        "grok",
        _window(
            key="included_weekly",
            label="Grok included weekly allowance",
            used_percent=88.0,
            duration_seconds=604_800.0,
            applicability={"kind": "account"},
        ),
    )
    presentations = _presentations(lead, codex, grok)
    total = build_usage_indicator_segment(presentations, budget=11)
    micro = build_usage_indicator_segment(presentations, budget=3)

    assert total.plain.strip() == "! usage 3"
    assert micro.plain.strip() == "!3"
