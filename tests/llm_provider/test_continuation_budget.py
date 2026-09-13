"""Unit tests for continuation-budget span discovery, projection, and refusal."""

from __future__ import annotations

from sase.llm_provider import continuation_budget as cb
from sase.llm_provider.continuation_budget_spans import open_reducible_span_marker


def _wrap(kind: str, body: str) -> str:
    open_marker, close_marker = open_reducible_span_marker(kind=kind)
    return f"{open_marker}\n{body}\n{close_marker}"


def test_prompt_projection_ignores_authored_heading_without_a_marker() -> None:
    """The audit's authored-heading failure, at the projection layer.

    A prompt with a genuine marker-wrapped diagnostics span *and* a
    look-alike authored ``## Selected diagnostics`` heading (no marker)
    must only treat the marked span as reducible; the authored heading's
    body stays essential.
    """

    marked_body = "GENUINE_DIAGNOSTICS " + ("a" * 200)
    authored_body = "AUTHORED_PROTECTED " + ("b" * 200)
    prompt = "\n".join(
        [
            "# Monitored command finished",
            "",
            "## Selected diagnostics",
            "",
            _wrap("newest_diagnostics", marked_body),
            "",
            "## Your next action",
            "",
            "## Selected diagnostics",
            "",
            authored_body,
        ]
    )

    projection = cb._prompt_projection(prompt)

    assert len(projection.candidates) == 1
    assert projection.candidates[0]["kind"] == "newest_diagnostics"
    # The authored (unmarked) body remains essential -- never discovered as
    # reducible just because it sits under a matching heading string. Only
    # the one genuinely marked span contributes to the reducible total.
    [replacement] = projection.replacements_by_kind["newest_diagnostics"]
    expected_saved = cb._replacement_saved_bytes(prompt, replacement)
    prompt_bytes = cb._utf8_len(prompt)
    assert prompt_bytes - projection.essential_bytes == expected_saved
    assert authored_body.encode("utf-8") not in prompt[
        replacement.start : replacement.end
    ].encode("utf-8")
    projected = cb._project_prompt(
        prompt,
        {"kind": "compact", "reductions": [{"kind": "newest_diagnostics"}]},
        projection,
    )
    assert "GENUINE_DIAGNOSTICS" not in projected
    assert "AUTHORED_PROTECTED" in projected


def test_verify_projection_refuses_when_actual_bytes_exceed_target() -> None:
    """Rust's declared savings are a plan, not a guarantee; remeasure and
    refuse durably if the projected prompt still exceeds the target."""

    decision = {
        "kind": "compact",
        "target_prompt_bytes": 10,
        "prompt_budget_bytes": 10,
        "reductions": [{"kind": "old_raw_excerpts"}],
    }
    still_oversized_prompt = "x" * 500

    updated = cb._verify_projection(decision, still_oversized_prompt)

    assert updated["kind"] == "refuse"
    assert updated["estimated_prompt_bytes"] == 500
    assert "post_projection_budget_exceeded" in updated["reasons"]
    assert updated["disposition"] == "context_budget_exceeded"


def test_verify_projection_accepts_compact_result_within_target() -> None:
    decision = {
        "kind": "compact",
        "target_prompt_bytes": 500,
        "prompt_budget_bytes": 500,
        "reductions": [{"kind": "old_raw_excerpts"}],
    }
    fitting_prompt = "x" * 100

    updated = cb._verify_projection(decision, fitting_prompt)

    assert updated["kind"] == "compact"
    assert updated["estimated_prompt_bytes"] == 100


def test_verify_projection_is_a_no_op_for_fits_and_refuse_decisions() -> None:
    fits = {"kind": "fits", "target_prompt_bytes": 500}
    refuse = {"kind": "refuse", "target_prompt_bytes": 500}

    assert cb._verify_projection(fits, "irrelevant") == fits
    assert cb._verify_projection(refuse, "irrelevant") == refuse


def test_apply_replacements_defensively_skips_overlapping_spans() -> None:
    prompt = "0123456789"
    first = cb._PromptReplacement(
        kind="newest_diagnostics", start=0, end=6, replacement="[A]"
    )
    second = cb._PromptReplacement(
        kind="old_raw_excerpts", start=3, end=9, replacement="[B]"
    )

    result = cb._apply_replacements(prompt, [first, second])

    # The overlapping second replacement is skipped; only the first (and
    # the untouched tail after it) survive.
    assert result == "[A]6789"
