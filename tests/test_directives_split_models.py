"""Tests for split_prompt_for_models."""

from unittest.mock import patch

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import (
    extract_prompt_directives,
    split_prompt_for_models,
)
from sase.xprompt.models import XPrompt


def test_split_prompt_for_models_rejects_paren_multi_model() -> None:
    """Paren multi-argument %m is rejected with the migration syntax."""
    with pytest.raises(
        DirectiveError,
        match=r"%m\(opus,sonnet\) is no longer supported; "
        r"use %\{%m:opus \| %m:sonnet\} instead",
    ):
        split_prompt_for_models("%m(opus,sonnet)\nReview this code")


def test_split_prompt_for_models_two_models() -> None:
    """Two models produce two prompts, each with a single %model directive."""
    prompt = "%n:foo\n%{%model:opus | %model:sonnet}\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld_opus\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.cld_sonnet\n%model:sonnet\nReview this code"


def test_split_prompt_for_models_three_models() -> None:
    """Three models produce three prompts."""
    prompt = "%n:foo\n%{%model:opus | %model:sonnet | %model:haiku}\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 3
    assert result[0] == "%name:foo.cld_opus\n%model:opus\nDo work"
    assert result[1] == "%name:foo.cld_sonnet\n%model:sonnet\nDo work"
    assert result[2] == "%name:foo.cld_haiku\n%model:haiku\nDo work"


def test_split_prompt_for_models_single_model_returns_none() -> None:
    """Single model in parens returns None (not fan-out)."""
    assert split_prompt_for_models("%m(opus)\nDo work") is None


def test_split_prompt_for_models_scalar_alias_kwargs_are_not_a_fanout_axis() -> None:
    assert split_prompt_for_models("%m(opus, coder=sonnet)\nDo work") is None


def test_split_prompt_for_models_preserves_alias_kwargs_per_alt_branch() -> None:
    variants = split_prompt_for_models(
        "%{%m(opus, coder=sonnet) | %m(haiku, coder=opus)}\nDo work"
    )
    assert variants is not None

    directives = [extract_prompt_directives(variant)[1] for variant in variants]
    assert [item.model for item in directives] == ["opus", "haiku"]
    assert [dict(item.model_alias_overrides) for item in directives] == [
        {"coder": "sonnet"},
        {"coder": "opus"},
    ]


def test_split_prompt_for_models_no_directive_returns_none() -> None:
    """No model directive returns None."""
    assert split_prompt_for_models("Just a prompt") is None


def test_split_prompt_for_models_colon_syntax_returns_none() -> None:
    """Colon syntax is single model, returns None."""
    assert split_prompt_for_models("%m:opus\nDo work") is None


def test_split_prompt_for_models_preserves_other_directives() -> None:
    """Other directives in the prompt are preserved."""
    prompt = "%n:foo\n%auto\n%{%model:opus | %model:sonnet}\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld_opus\n%auto\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.cld_sonnet\n%auto\n%model:sonnet\nReview this code"


def test_split_prompt_for_models_with_provider_syntax() -> None:
    """Multi-model with provider/model syntax splits correctly."""
    prompt = "%n:foo\n%{%model:codex/o3 | %model:claude/opus}\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cdx\n%model:codex/o3\nReview this code"
    assert result[1] == "%name:foo.cld\n%model:claude/opus\nReview this code"


def test_split_prompt_for_models_quoted_provider_model_with_spaces_and_parens() -> None:
    """Fan-out preserves exact quoted provider/model values."""
    prompt = (
        '%n:foo\n%{%m("agy/Gemini 3.1 Pro (High)") | '
        '%m("agy/Gemini 3.5 Flash (High)")}\nReview this code'
    )
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2

    models = [extract_prompt_directives(variant)[1].model for variant in result]
    assert models == [
        "agy/Gemini 3.1 Pro (High)",
        "agy/Gemini 3.5 Flash (High)",
    ]
    assert all("Review this code" in variant for variant in result)


def test_split_prompt_for_models_spaces_in_args() -> None:
    """Spaces around model names in args are handled."""
    prompt = "%n:foo\n%{%model:opus | %model:sonnet}\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld_opus\n%model:opus\nDo work"
    assert result[1] == "%name:foo.cld_sonnet\n%model:sonnet\nDo work"


def test_split_prompt_for_models_after_xprompt_expansion() -> None:
    """Xprompt-expanded model branches are split by split_prompt_for_models."""
    from sase.xprompt.processor import process_xprompt_references

    # Simulate what happens when #swarm expands to %{%model:opus | %model:sonnet}
    with patch(
        "sase.xprompt.processor.process_xprompt_references",
        wraps=process_xprompt_references,
    ):
        expanded = "%n:foo\n%{%model:opus | %model:sonnet}\nReview this code"
        result = split_prompt_for_models(expanded)
        assert result is not None
        assert len(result) == 2
        assert result[0] == "%name:foo.cld_opus\n%model:opus\nReview this code"
        assert result[1] == "%name:foo.cld_sonnet\n%model:sonnet\nReview this code"


def test_split_prompt_for_models_requires_caller_expanded_xprompt_body() -> None:
    """The planner splits xprompt-injected model branches after caller expansion."""
    from sase.xprompt.processor import process_xprompt_references

    xprompts = {
        "_fanout": XPrompt(
            name="_fanout",
            content="%n:foo\n%{%model:opus | %model:sonnet}\nReview this code",
        ),
    }

    assert split_prompt_for_models("#_fanout", extra_xprompts=xprompts) is None

    with patch("sase.xprompt.processor.get_all_xprompts", return_value={}):
        expanded = process_xprompt_references("#_fanout", extra_xprompts=xprompts)

    result = split_prompt_for_models(expanded, extra_xprompts=xprompts)
    assert result is not None
    assert result == [
        "%name:foo.cld_opus\n%model:opus\nReview this code",
        "%name:foo.cld_sonnet\n%model:sonnet\nReview this code",
    ]


def test_split_prompt_for_models_xprompt_model_axis_composes_with_alts() -> None:
    """An expanded xprompt %model axis composes with raw %( alternative axes.

    Regression for the launch fan-out shape bug: planning the raw prompt sees
    only the two %( alternative axes — the launch-shaping xprompt
    (#m_opus_codex -> %{%model:opus | %model:#codex}) is still an unexpanded reference,
    so the model dimension is missing and the split yields 4 model-less
    variants. Expanding the xprompt before planning unlocks the model axis,
    and %{%model:opus | %model:#codex} joins the Cartesian product:
    2 alts x 2 alts x 2 models = 8 variants, split evenly across the raw
    opus/#codex branches.
    """
    from sase.xprompt.processor import process_xprompt_references

    catalog = {
        "codex": XPrompt(name="codex", content="gpt-5.6-sol"),
        "m_opus_codex": XPrompt(
            name="m_opus_codex",
            content="%{%model:opus | %model:#codex}",
        ),
    }
    prompt = (
        "%n:foo Describe this repo %(briefly, in detail). "
        "%(Don't trust the documentation!) #m_opus_codex"
    )

    # Raw planning sees only the two %( axes; the model dimension is absent
    # because #m_opus_codex is still an unexpanded reference.
    raw = split_prompt_for_models(prompt, extra_xprompts=catalog)
    assert raw is not None
    assert len(raw) == 4
    assert all("%model" not in variant for variant in raw)

    # Expanding the launch-shaping xprompt first unlocks the model axis.
    with patch("sase.xprompt.processor.get_all_xprompts", return_value={}):
        expanded = process_xprompt_references(prompt, extra_xprompts=catalog)
    result = split_prompt_for_models(expanded, extra_xprompts=catalog)
    assert result is not None
    assert len(result) == 8
    assert sum("%model:opus" in variant for variant in result) == 4
    assert sum("%model:#codex" in variant for variant in result) == 4


def test_split_prompt_for_models_brace_model_alt_same_as_paren_alt() -> None:
    """Brace model branches produce the same output as %alt(%model:...)."""
    via_m = split_prompt_for_models(
        "%n:foo\n%{%model:opus | %model:sonnet}\nReview this code"
    )
    via_alt = split_prompt_for_models(
        "%n:foo\n%alt(%model:opus,%model:sonnet)\nReview this code"
    )
    assert via_m == via_alt


# --- repeated scalar %model tests ---


def test_split_prompt_for_models_two_scalar_directives() -> None:
    """Two top-level %model:X scalars raise with a migration hint."""
    prompt = "%n:foo\n%model:opus\n%model:sonnet\nReview this code"
    with pytest.raises(
        DirectiveError,
        match=r"use %\{%m:opus \| %m:sonnet\} instead",
    ):
        split_prompt_for_models(prompt)


def test_split_prompt_for_models_alias_mix() -> None:
    """%m:opus + %model:sonnet (alias mix) raises with a migration hint."""
    prompt = "%n:foo\n%m:opus\n%model:sonnet\nReview this code"
    with pytest.raises(
        DirectiveError,
        match=r"use %\{%m:opus \| %m:sonnet\} instead",
    ):
        split_prompt_for_models(prompt)


def test_split_prompt_for_models_scalar_plus_paren() -> None:
    """Mixing scalar and paren multi-model syntax raises."""
    prompt = "%n:foo\n%model:opus\n%model(sonnet,haiku)\nReview this code"
    with pytest.raises(
        DirectiveError,
        match=r"use %\{%m:sonnet \| %m:haiku\} instead",
    ):
        split_prompt_for_models(prompt)


def test_split_prompt_for_models_identical_dupes_raise() -> None:
    """Two identical %model:opus directives are still duplicate misuse."""
    prompt = "%model:opus\n%model:opus\nReview this code"
    with pytest.raises(
        DirectiveError,
        match=r"use %\{%m:opus \| %m:opus\} instead",
    ):
        split_prompt_for_models(prompt)


def test_split_prompt_for_models_interleaved_duplicates() -> None:
    """Duplicates spread across non-adjacent lines raise."""
    prompt = "%n:foo\n%model:opus\nHeader line\n%model:sonnet\nBody"
    with pytest.raises(
        DirectiveError,
        match=r"use %\{%m:opus \| %m:sonnet\} instead",
    ):
        split_prompt_for_models(prompt)


def test_split_prompt_for_models_scalar_inside_fenced_block_ignored() -> None:
    """%model:X inside a fenced code block is neither collected nor stripped."""
    prompt = "%model:opus\n```\n%model:sonnet\n```\nReview"
    result = split_prompt_for_models(prompt)
    # Only the outer %model:opus counts — single unique model, no split.
    assert result is None
