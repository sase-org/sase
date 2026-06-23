"""Tests for split_prompt_for_models."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import split_prompt_for_models
from sase.xprompt.models import XPrompt
from tests._agent_names_fixtures import make_agent as _make_agent


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


def test_split_prompt_for_models_no_directive_returns_none() -> None:
    """No model directive returns None."""
    assert split_prompt_for_models("Just a prompt") is None


def test_split_prompt_for_models_colon_syntax_returns_none() -> None:
    """Colon syntax is single model, returns None."""
    assert split_prompt_for_models("%m:opus\nDo work") is None


def test_split_prompt_for_models_preserves_other_directives() -> None:
    """Other directives in the prompt are preserved."""
    prompt = "%n:foo\n%approve\n%{%model:opus | %model:sonnet}\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld_opus\n%approve\n%model:opus\nReview this code"
    assert (
        result[1] == "%name:foo.cld_sonnet\n%approve\n%model:sonnet\nReview this code"
    )


def test_split_prompt_for_models_with_provider_syntax() -> None:
    """Multi-model with provider/model syntax splits correctly."""
    prompt = "%n:foo\n%{%model:codex/o3 | %model:claude/opus}\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cdx\n%model:codex/o3\nReview this code"
    assert result[1] == "%name:foo.cld\n%model:claude/opus\nReview this code"


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
        "codex": XPrompt(name="codex", content="gpt-5.5"),
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


def test_split_prompt_for_models_multi_model_with_user_alt_cartesian() -> None:
    """Model branches Cartesian-product with a user %alt(x,y)."""
    prompt = "%n:foo\n%{%model:opus | %model:sonnet} %alt(x,y)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 4
    assert "%name:foo.cld_opus" in result[0] and " x\nReview" in result[0]
    assert "%name:foo.cld_opus" in result[1] and " y\nReview" in result[1]
    assert "%name:foo.cld_sonnet" in result[2] and " x\nReview" in result[2]
    assert "%name:foo.cld_sonnet" in result[3] and " y\nReview" in result[3]


def test_split_prompt_for_models_multi_model_distinct_runtimes() -> None:
    """Two models on distinct runtimes get plain runtime suffixes (no model)."""
    prompt = "%n:foo\n%{%model:opus | %model:gpt-5.5}\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.cdx\n%model:gpt-5.5\nReview this code"


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_split_prompt_for_models_alias_uses_resolved_suffix(
    mock_config: MagicMock,
) -> None:
    """Fan-out names use the concrete configured model behind an alias."""
    mock_config.return_value = {"model_aliases": {"other": "claude/opus"}}

    prompt = "%n:foo\n%{%model:other | %model:gpt-5.5}\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld\n%model:other\nReview this code"
    assert result[1] == "%name:foo.cdx\n%model:gpt-5.5\nReview this code"


def test_split_prompt_for_models_other_uses_override_snapshot(
    monkeypatch,
) -> None:
    """While an override is active, "other" resolves to the displaced model.

    The configured alias points at claude/sonnet, but the override snapshot
    captures claude/opus (the default at the time the override was set).
    The fan-out disambiguator must use the snapshot's "opus" — pairing
    "other" against the actual displaced model — not the static alias.
    """
    from sase.llm_provider.temporary_override import set_temporary_override

    cfg = {
        "provider": "claude",
        "model_aliases": {"other": "claude/sonnet"},
    }
    # Patch both modules: registry imports the symbol at load time,
    # config defines it. Snapshot capture goes through registry.
    monkeypatch.setattr("sase.llm_provider.config.get_llm_provider_config", lambda: cfg)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: cfg
    )
    set_temporary_override("codex/o3", 3600.0, source="test")

    # other + sonnet are both claude → same-runtime collision uses model
    # names as the disambiguator. Without the override-aware "other",
    # other would also resolve to sonnet (per configured alias) and the
    # split would collapse to a single model.
    prompt = "%n:foo\n%{%model:other | %model:sonnet}\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld_opus\n%model:other\nReview"
    assert result[1] == "%name:foo.cld_sonnet\n%model:sonnet\nReview"


def test_split_prompt_for_models_resume_base(tmp_path: Path) -> None:
    """Multi-model fan-out without %name uses the resume-derived base."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models(
            "#fork:foo\n%{%model:opus | %model:sonnet}\nDo work"
        )
    assert result is not None
    assert result[0] == "%name:foo.f1.cld_opus\n#fork:foo\n%model:opus\nDo work"
    assert result[1] == "%name:foo.f1.cld_sonnet\n#fork:foo\n%model:sonnet\nDo work"


def test_split_prompt_for_models_wait_base(tmp_path: Path) -> None:
    """Multi-model fan-out without %name uses the wait-derived base."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models(
            "%wait:foo\n%{%model:opus | %model:sonnet}\nDo work"
        )
    assert result is not None
    assert result[0] == "%name:foo.w1.cld_opus\n%wait:foo\n%model:opus\nDo work"
    assert result[1] == "%name:foo.w1.cld_sonnet\n%wait:foo\n%model:sonnet\nDo work"


def test_split_prompt_for_models_resume_base_wins_over_wait(
    tmp_path: Path,
) -> None:
    """Multi-model fan-out uses the fork-derived base when both refs exist."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models(
            "%wait:foo\n#fork:foo\n%{%model:opus | %model:sonnet}\nDo work"
        )
    assert result is not None
    assert result[0] == (
        "%name:foo.f1.cld_opus\n%wait:foo\n#fork:foo\n%model:opus\nDo work"
    )
    assert result[1] == (
        "%name:foo.f1.cld_sonnet\n%wait:foo\n#fork:foo\n%model:sonnet\nDo work"
    )


def test_split_prompt_for_models_multi_model_auto_generated_base() -> None:
    """No %name with multi-model injects grouped auto-name templates."""
    result = split_prompt_for_models("%{%model:opus | %model:gpt-5.5}\nReview")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:@.cld\n%model:opus\nReview"
    assert result[1] == "%name:@.cdx\n%model:gpt-5.5\nReview"


def test_split_prompt_for_models_multi_model_bare_name_auto_generated() -> None:
    """Bare %name with multi-model behaves like an unnamed generated launch."""
    result = split_prompt_for_models("%name\n%{%model:opus | %model:gpt-5.5}\nReview")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:@.cld\n%model:opus\nReview"
    assert result[1] == "%name:@.cdx\n%model:gpt-5.5\nReview"


def test_split_prompt_for_models_unknown_model_uses_default_provider() -> None:
    """An unknown model maps to the default provider's runtime label."""
    from sase.llm_provider.registry import (
        get_default_provider_name,
        provider_short_name_map,
    )

    default = get_default_provider_name()
    default_short = provider_short_name_map().get(default, default)
    prompt = "%n:foo\n%{%model:unknown_model_xyz | %model:opus}\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    # When the unknown model resolves to the same runtime as opus (claude),
    # collision suffixing kicks in; otherwise plain runtime labels.
    if default == "claude":
        assert (
            result[0] == "%name:foo.cld_unknown_model_xyz\n"
            "%model:unknown_model_xyz\nReview"
        )
        assert result[1] == "%name:foo.cld_opus\n%model:opus\nReview"
    else:
        assert (
            result[0] == f"%name:foo.{default_short}\n%model:unknown_model_xyz\nReview"
        )
        assert result[1] == "%name:foo.cld\n%model:opus\nReview"


def test_split_prompt_for_models_codex_collision_uses_short_alias() -> None:
    """Same-runtime codex collision substitutes short aliases for model names."""
    prompt = "%n:o\n%{%model:gpt-5.5 | %model:gpt-5.3-codex}\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == ("%name:o.cdx_gpt55\n%model:gpt-5.5\nReview")
    assert result[1] == ("%name:o.cdx_gpt53\n%model:gpt-5.3-codex\nReview")


def test_split_prompt_for_models_opencode_nested_models_use_short_aliases() -> None:
    """Explicit OpenCode provider/model strings use provider-local model aliases."""
    prompt = (
        "%n:o\n"
        "%{%model:opencode/anthropic/claude-sonnet-4-5 | %model:opencode/openai/gpt-5-mini}\n"
        "Review"
    )
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == (
        "%name:o.opc_sonnet45\n%model:opencode/anthropic/claude-sonnet-4-5\nReview"
    )
    assert result[1] == ("%name:o.opc_gpt5m\n%model:opencode/openai/gpt-5-mini\nReview")


def test_split_prompt_for_models_unknown_nested_model_suffix_is_name_safe() -> None:
    """Unknown explicit nested model names are sanitized for generated names."""
    prompt = (
        "%n:o\n%{%model:opencode/acme/foo/bar | %model:opencode/acme/baz/qux}\nReview"
    )
    result = split_prompt_for_models(prompt)
    assert result is not None
    name_lines = [line for item in result for line in item.splitlines()[:1]]
    assert name_lines == ["%name:o.opc_acme_foo_bar", "%name:o.opc_acme_baz_qux"]


def test_split_prompt_for_models_claude_collision_unchanged() -> None:
    """Claude opus/sonnet keep their raw names (no aliases declared)."""
    prompt = "%n:o\n%{%model:opus | %model:sonnet}\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:o.cld_opus\n%model:opus\nReview"
    assert result[1] == "%name:o.cld_sonnet\n%model:sonnet\nReview"


def test_split_prompt_for_models_no_collision_unchanged() -> None:
    """Distinct-runtime case never embeds the model name (alias irrelevant)."""
    prompt = "%n:o\n%{%model:opus | %model:gpt-5.5}\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:o.cld\n%model:opus\nReview"
    assert result[1] == "%name:o.cdx\n%model:gpt-5.5\nReview"


def test_split_prompt_for_models_unknown_model_falls_through() -> None:
    """Unknown model in a same-runtime collision keeps its raw name."""
    from sase.llm_provider.registry import get_default_provider_name

    if get_default_provider_name() != "codex":
        # Test relies on unknown_xyz routing to codex (the fallback default).
        # If a different default is configured, skip the assertion path.
        return
    prompt = "%n:o\n%{%model:gpt-5.5 | %model:unknown_xyz}\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == ("%name:o.cdx_gpt55\n%model:gpt-5.5\nReview")
    assert result[1] == "%name:o.cdx_unknown_xyz\n%model:unknown_xyz\nReview"


def test_split_prompt_for_models_alias_collision_falls_back_to_raw() -> None:
    """Two models that alias to the same short form fall back to raw names."""
    fake_aliases = {
        "gpt-5.5": "gp",
        "gpt-5.3-codex": "gp",
    }
    with patch(
        "sase.llm_provider.registry.model_short_alias_map",
        return_value=fake_aliases,
    ):
        result = split_prompt_for_models(
            "%n:o\n%{%model:gpt-5.5 | %model:gpt-5.3-codex}\nReview"
        )
    assert result is not None
    assert len(result) == 2
    assert result[0] == ("%name:o.cdx_gpt_5.5\n%model:gpt-5.5\nReview")
    assert result[1] == ("%name:o.cdx_gpt_5.3_codex\n%model:gpt-5.3-codex\nReview")


def test_split_prompt_for_models_global_shorthand_name_uses_resolved_alias() -> None:
    """A model shorthand keeps its raw directive but names with the resolved alias."""
    xprompts = {
        "flash": XPrompt(name="flash", content="gpt-5.5"),
    }
    with patch("sase.xprompt.processor.get_all_xprompts", return_value=xprompts):
        result = split_prompt_for_models(
            "%n:o\n%{%model:#flash | %model:gpt-5.3-codex}\nReview"
        )

    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:o.cdx_gpt55\n%model:#flash\nReview"
    assert result[1] == "%name:o.cdx_gpt53\n%model:gpt-5.3-codex\nReview"


def test_split_prompt_for_models_same_runtime_shorthands_use_resolved_aliases() -> None:
    """Same-runtime shorthand variants disambiguate with resolved model aliases."""
    xprompts = {
        "flash": XPrompt(name="flash", content="gpt-5.5"),
        "pro": XPrompt(name="pro", content="gpt-4.1"),
    }
    with patch("sase.xprompt.processor.get_all_xprompts", return_value=xprompts):
        result = split_prompt_for_models(
            "%n:ag\n%{%model:#flash | %model:#pro}\nReview"
        )

    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:ag.cdx_gpt55\n%model:#flash\nReview"
    assert result[1] == "%name:ag.cdx_gpt41\n%model:#pro\nReview"


def test_split_prompt_for_models_keeps_raw_and_shorthand_alt_branches() -> None:
    """Raw and shorthand branches stay distinct even if they resolve alike."""
    xprompts = {
        "flash": XPrompt(name="flash", content="gemini-3-flash-preview"),
    }
    with patch("sase.xprompt.processor.get_all_xprompts", return_value=xprompts):
        result = split_prompt_for_models(
            "%{%model:#flash | %model:gemini-3-flash-preview}\nReview"
        )

    assert result == [
        "%name:@.1\n%model:#flash\nReview",
        "%name:@.2\n%model:gemini-3-flash-preview\nReview",
    ]


def test_split_prompt_for_models_unknown_shorthand_name_strips_hash_fallback() -> None:
    """Unknown shorthand remains raw in %model but drops # from the name suffix."""
    with patch(
        "sase.xprompt._directive_alt._runtime_label_for_model",
        return_value="cdx",
    ):
        result = split_prompt_for_models(
            "%n:o\n%{%model:#unknown_model_alias | %model:gpt-5.5}\nReview"
        )

    assert result is not None
    assert len(result) == 2
    assert result[0] == (
        "%name:o.cdx_unknown_model_alias\n%model:#unknown_model_alias\nReview"
    )
    assert result[1] == "%name:o.cdx_gpt55\n%model:gpt-5.5\nReview"


def test_split_prompt_for_models_pure_alt_gets_planned_names() -> None:
    """A %alt(...) with no %model branches gets shared-base child names."""
    prompt = "%n:foo\n%alt(x,y)\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.1\nx\nDo work"
    assert result[1] == "%name:foo.2\ny\nDo work"


def test_split_prompt_for_models_allows_template_name_base() -> None:
    """Template bases are preserved and extended for fan-out child names."""
    result = split_prompt_for_models("%n:foo-@\n%alt(x,y)\nDo work")

    assert result is not None
    assert result == [
        "%name:foo-@.1\nx\nDo work",
        "%name:foo-@.2\ny\nDo work",
    ]


def test_split_prompt_for_models_named_shorthand_alt_ids() -> None:
    """Named shorthand alt args use the branch name and unnamed args use numbers."""
    prompt = "%n:foo\n%(fast=[[fast pass]], [[slow pass]])\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.fast\nfast pass\nDo work"
    assert result[1] == "%name:foo.1\nslow pass\nDo work"


def test_split_prompt_for_models_shared_named_alt_ids_get_child_names() -> None:
    """Repeated named keys across alt directives use the shared key suffix."""
    prompt = "%n:foo\n%{a=Describe | b=Explain} how this repo works %{a=in detail}."
    result = split_prompt_for_models(prompt)

    assert result == [
        "%name:foo.a\nDescribe how this repo works in detail.",
        "%name:foo.b\nExplain how this repo works.",
    ]


def test_split_prompt_for_models_pure_alt_auto_generated_base() -> None:
    """Pure alt fan-out without %name injects grouped auto-name templates."""
    result = split_prompt_for_models("%alt(x,y)\nDo work")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:@.1\nx\nDo work"
    assert result[1] == "%name:@.2\ny\nDo work"


def test_split_prompt_for_models_pure_alt_auto_base_stays_template_before_launch(
    tmp_path: Path,
) -> None:
    """Pure splitting leaves generated-name collision checks to launch planning."""
    _make_agent(tmp_path, "proj", "run-0", "0", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models("%alt(x,y)\nDo work")

    assert result is not None
    assert result[0] == "%name:@.1\nx\nDo work"
    assert result[1] == "%name:@.2\ny\nDo work"


def test_split_prompt_for_models_pure_alt_resume_base(tmp_path: Path) -> None:
    """Pure %alt fan-out without %name uses one resume-derived base."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models("#fork:foo\n%alt(x,y)\nDo work")

    assert result is not None
    assert result[0] == "%name:foo.f1.1\n#fork:foo\nx\nDo work"
    assert result[1] == "%name:foo.f1.2\n#fork:foo\ny\nDo work"


def test_split_prompt_for_models_pure_alt_resume_base_skips_existing_slot(
    tmp_path: Path,
) -> None:
    """Pure %alt resume allocation skips existing descendant resume slots."""
    _make_agent(tmp_path, "proj", "run-old", "foo.r1.sec", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models("#fork:foo\n%alt(sec=x,perf=y)\nDo work")

    assert result is not None
    assert result[0] == "%name:foo.f2.sec\n#fork:foo\nx\nDo work"
    assert result[1] == "%name:foo.f2.perf\n#fork:foo\ny\nDo work"


def test_split_prompt_for_models_named_model_alt_overrides_model_suffix() -> None:
    """Named model branches use the branch ids instead of runtime suffixes."""
    prompt = "%n:foo\n%alt(sec=%model:opus,perf=%model:sonnet)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.sec\n%model:opus\nReview"
    assert result[1] == "%name:foo.perf\n%model:sonnet\nReview"


def test_split_prompt_for_models_numeric_named_alt_ids_do_not_collide() -> None:
    """Unnamed numeric ids skip user-provided numeric branch names."""
    prompt = "%n:foo\n%(2=[[named two]], [[first]], [[second]])\nDo work"
    result = split_prompt_for_models(prompt)

    assert result is not None
    assert result == [
        "%name:foo.2\nnamed two\nDo work",
        "%name:foo.1\nfirst\nDo work",
        "%name:foo.3\nsecond\nDo work",
    ]


def test_split_prompt_for_models_explicit_alt_base_becomes_explicit_child_names(
    tmp_path: Path,
) -> None:
    """Explicit %name fan-out emits explicit child %name directives."""
    _make_agent(tmp_path, "proj", "run-old", "foo.sec", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models("%n:foo\n%alt(sec=x,perf=y)\nDo work")

    assert result is not None
    assert result[0] == "%name:foo.sec\nx\nDo work"
    assert result[1] == "%name:foo.perf\ny\nDo work"


def test_split_prompt_for_models_alt_with_nested_model_not_double_collected() -> None:
    """%alt(%model:a,%model:b) is processed as a single alt, not re-collected."""
    prompt = "%n:foo\n%alt(%model:opus,%model:sonnet)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld_opus\n%model:opus\nReview"
    assert result[1] == "%name:foo.cld_sonnet\n%model:sonnet\nReview"


def test_split_prompt_for_models_with_alt_directive() -> None:
    """Model branches combined with %(x,y) produce 4 prompts."""
    prompt = "%n:foo\n%{%model:opus | %model:sonnet} %(x,y)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 4
    assert (
        "%name:foo.cld_opus" in result[0]
        and "%model:opus" in result[0]
        and "x" in result[0]
    )
    assert (
        "%name:foo.cld_opus" in result[1]
        and "%model:opus" in result[1]
        and "y" in result[1]
    )
    assert (
        "%name:foo.cld_sonnet" in result[2]
        and "%model:sonnet" in result[2]
        and "x" in result[2]
    )
    assert (
        "%name:foo.cld_sonnet" in result[3]
        and "%model:sonnet" in result[3]
        and "y" in result[3]
    )
