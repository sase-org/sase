"""Tests for split_prompt_for_models."""

from pathlib import Path
from unittest.mock import patch

from sase.xprompt.directives import split_prompt_for_models
from sase.xprompt.models import XPrompt
from tests._agent_names_fixtures import make_agent as _make_agent


def test_split_prompt_for_models_two_models() -> None:
    """Two models produce two prompts, each with a single %model directive."""
    prompt = "%n:foo\n%m(opus,sonnet)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld-opus\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.cld-sonnet\n%model:sonnet\nReview this code"


def test_split_prompt_for_models_three_models() -> None:
    """Three models produce three prompts."""
    prompt = "%n:foo\n%model(opus,sonnet,haiku)\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 3
    assert result[0] == "%name:foo.cld-opus\n%model:opus\nDo work"
    assert result[1] == "%name:foo.cld-sonnet\n%model:sonnet\nDo work"
    assert result[2] == "%name:foo.cld-haiku\n%model:haiku\nDo work"


def test_split_prompt_for_models_single_model_returns_none() -> None:
    """Single model in parens returns None (not multi-model)."""
    assert split_prompt_for_models("%m(opus)\nDo work") is None


def test_split_prompt_for_models_no_directive_returns_none() -> None:
    """No model directive returns None."""
    assert split_prompt_for_models("Just a prompt") is None


def test_split_prompt_for_models_colon_syntax_returns_none() -> None:
    """Colon syntax is single model, returns None."""
    assert split_prompt_for_models("%m:opus\nDo work") is None


def test_split_prompt_for_models_preserves_other_directives() -> None:
    """Other directives in the prompt are preserved."""
    prompt = "%n:foo\n%approve\n%m(opus,sonnet)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld-opus\n%approve\n%model:opus\nReview this code"
    assert (
        result[1] == "%name:foo.cld-sonnet\n%approve\n%model:sonnet\nReview this code"
    )


def test_split_prompt_for_models_with_provider_syntax() -> None:
    """Multi-model with provider/model syntax splits correctly."""
    prompt = "%n:foo\n%m(codex/o3,claude/opus)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cdx\n%model:codex/o3\nReview this code"
    assert result[1] == "%name:foo.cld\n%model:claude/opus\nReview this code"


def test_split_prompt_for_models_spaces_in_args() -> None:
    """Spaces around model names in args are handled."""
    prompt = "%n:foo\n%m(opus, sonnet)\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld-opus\n%model:opus\nDo work"
    assert result[1] == "%name:foo.cld-sonnet\n%model:sonnet\nDo work"


def test_split_prompt_for_models_after_xprompt_expansion() -> None:
    """Xprompt-expanded %m(...) is correctly split by split_prompt_for_models."""
    from sase.xprompt.processor import process_xprompt_references

    # Simulate what happens when #swarm expands to %m(opus,sonnet)
    with patch(
        "sase.xprompt.processor.process_xprompt_references",
        wraps=process_xprompt_references,
    ):
        expanded = "%n:foo\n%m(opus,sonnet)\nReview this code"
        result = split_prompt_for_models(expanded)
        assert result is not None
        assert len(result) == 2
        assert result[0] == "%name:foo.cld-opus\n%model:opus\nReview this code"
        assert result[1] == "%name:foo.cld-sonnet\n%model:sonnet\nReview this code"


def test_split_prompt_for_models_direct_alt_same_as_multi_model() -> None:
    """Direct %alt(%model:...) produces the same output as %m(...)."""
    via_m = split_prompt_for_models("%n:foo\n%m(opus,sonnet)\nReview this code")
    via_alt = split_prompt_for_models(
        "%n:foo\n%alt(%model:opus,%model:sonnet)\nReview this code"
    )
    assert via_m == via_alt


# --- repeated scalar %model tests ---


def test_split_prompt_for_models_two_scalar_directives() -> None:
    """Two %model:X scalars produce two variants, directive lines collapsed."""
    prompt = "%n:foo\n%model:opus\n%model:sonnet\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld-opus\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.cld-sonnet\n%model:sonnet\nReview this code"


def test_split_prompt_for_models_alias_mix() -> None:
    """%m:opus + %model:sonnet (alias mix) produces two variants."""
    prompt = "%n:foo\n%m:opus\n%model:sonnet\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld-opus\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.cld-sonnet\n%model:sonnet\nReview this code"


def test_split_prompt_for_models_scalar_plus_paren() -> None:
    """%model:opus + %model(sonnet,haiku) → three variants in order."""
    prompt = "%n:foo\n%model:opus\n%model(sonnet,haiku)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 3
    assert result[0] == "%name:foo.cld-opus\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.cld-sonnet\n%model:sonnet\nReview this code"
    assert result[2] == "%name:foo.cld-haiku\n%model:haiku\nReview this code"


def test_split_prompt_for_models_identical_dupes_return_none() -> None:
    """Two identical %model:opus dupes yield no split (single unique model)."""
    prompt = "%model:opus\n%model:opus\nReview this code"
    assert split_prompt_for_models(prompt) is None


def test_split_prompt_for_models_interleaved_duplicates() -> None:
    """Duplicates spread across non-adjacent lines split correctly."""
    prompt = "%n:foo\n%model:opus\nHeader line\n%model:sonnet\nBody"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld-opus\n%model:opus\nHeader line\nBody"
    assert result[1] == "%name:foo.cld-sonnet\n%model:sonnet\nHeader line\nBody"


def test_split_prompt_for_models_scalar_inside_fenced_block_ignored() -> None:
    """%model:X inside a fenced code block is neither collected nor stripped."""
    prompt = "%model:opus\n```\n%model:sonnet\n```\nReview"
    result = split_prompt_for_models(prompt)
    # Only the outer %model:opus counts — single unique model, no split.
    assert result is None


def test_split_prompt_for_models_multi_model_with_user_alt_cartesian() -> None:
    """Two scalar %model directives Cartesian-product with a user %alt(x,y)."""
    prompt = "%n:foo\n%model:opus\n%model:sonnet %alt(x,y)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 4
    assert "%name:foo.cld-opus" in result[0] and " x\nReview" in result[0]
    assert "%name:foo.cld-opus" in result[1] and " y\nReview" in result[1]
    assert "%name:foo.cld-sonnet" in result[2] and " x\nReview" in result[2]
    assert "%name:foo.cld-sonnet" in result[3] and " y\nReview" in result[3]


def test_split_prompt_for_models_multi_model_distinct_runtimes() -> None:
    """Two models on distinct runtimes get plain runtime suffixes (no model)."""
    prompt = "%n:foo\n%m(opus,gpt-5.5)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.cld\n%model:opus\nReview this code"
    assert result[1] == "%name:foo.cdx\n%model:gpt-5.5\nReview this code"


def test_split_prompt_for_models_resume_base(tmp_path: Path) -> None:
    """Multi-model fan-out without %name uses the resume-derived base."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models("#resume:foo\n%m(opus,sonnet)\nDo work")
    assert result is not None
    assert result[0] == "%name:foo.r1.cld-opus\n#resume:foo\n%model:opus\nDo work"
    assert result[1] == "%name:foo.r1.cld-sonnet\n#resume:foo\n%model:sonnet\nDo work"


def test_split_prompt_for_models_multi_model_auto_generated_base() -> None:
    """No %name with multi-model → auto-name is generated once and shared."""
    with patch("sase.agent.names.get_next_auto_name", return_value="z"):
        result = split_prompt_for_models("%m(opus,gpt-5.5)\nReview")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:z.cld\n%model:opus\nReview"
    assert result[1] == "%name:z.cdx\n%model:gpt-5.5\nReview"


def test_split_prompt_for_models_multi_model_bare_name_auto_generated() -> None:
    """Bare %name with multi-model also auto-generates base once."""
    with patch("sase.agent.names.get_next_auto_name", return_value="z"):
        result = split_prompt_for_models("%name\n%m(opus,gpt-5.5)\nReview")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:z.cld\n%model:opus\nReview"
    assert result[1] == "%name:z.cdx\n%model:gpt-5.5\nReview"


def test_split_prompt_for_models_unknown_model_uses_default_provider() -> None:
    """An unknown model maps to the default provider's runtime label."""
    from sase.llm_provider.registry import (
        get_default_provider_name,
        provider_short_name_map,
    )

    default = get_default_provider_name()
    default_short = provider_short_name_map().get(default, default)
    prompt = "%n:foo\n%m(unknown_model_xyz,opus)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    # When the unknown model resolves to the same runtime as opus (claude),
    # collision suffixing kicks in; otherwise plain runtime labels.
    if default == "claude":
        assert (
            result[0] == "%name:foo.cld-unknown_model_xyz\n"
            "%model:unknown_model_xyz\nReview"
        )
        assert result[1] == "%name:foo.cld-opus\n%model:opus\nReview"
    else:
        assert (
            result[0] == f"%name:foo.{default_short}\n%model:unknown_model_xyz\nReview"
        )
        assert result[1] == "%name:foo.cld\n%model:opus\nReview"


def test_split_prompt_for_models_gemini_collision_uses_short_alias() -> None:
    """Same-runtime gemini collision substitutes short aliases for model names."""
    prompt = "%n:o\n%m(gemini-3-flash-preview,gemini-2.5-flash)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == ("%name:o.gem-flash3\n%model:gemini-3-flash-preview\nReview")
    assert result[1] == ("%name:o.gem-flash25\n%model:gemini-2.5-flash\nReview")


def test_split_prompt_for_models_claude_collision_unchanged() -> None:
    """Claude opus/sonnet keep their raw names (no aliases declared)."""
    prompt = "%n:o\n%m(opus,sonnet)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:o.cld-opus\n%model:opus\nReview"
    assert result[1] == "%name:o.cld-sonnet\n%model:sonnet\nReview"


def test_split_prompt_for_models_no_collision_unchanged() -> None:
    """Distinct-runtime case never embeds the model name (alias irrelevant)."""
    prompt = "%n:o\n%m(opus,gpt-5.5)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:o.cld\n%model:opus\nReview"
    assert result[1] == "%name:o.cdx\n%model:gpt-5.5\nReview"


def test_split_prompt_for_models_unknown_model_falls_through() -> None:
    """Unknown model in a same-runtime collision keeps its raw name."""
    from sase.llm_provider.registry import get_default_provider_name

    if get_default_provider_name() != "gemini":
        # Test relies on unknown_xyz routing to gemini (the fallback default).
        # If a different default is configured, skip the assertion path.
        return
    prompt = "%n:o\n%m(gemini-3-flash-preview,unknown_xyz)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == ("%name:o.gem-flash3\n%model:gemini-3-flash-preview\nReview")
    assert result[1] == "%name:o.gem-unknown_xyz\n%model:unknown_xyz\nReview"


def test_split_prompt_for_models_alias_collision_falls_back_to_raw() -> None:
    """Two models that alias to the same short form fall back to raw names."""
    fake_aliases = {
        "gemini-3-flash-preview": "fl",
        "gemini-2.5-flash": "fl",
    }
    with patch(
        "sase.llm_provider.registry.model_short_alias_map",
        return_value=fake_aliases,
    ):
        result = split_prompt_for_models(
            "%n:o\n%m(gemini-3-flash-preview,gemini-2.5-flash)\nReview"
        )
    assert result is not None
    assert len(result) == 2
    assert result[0] == (
        "%name:o.gem-gemini-3-flash-preview\n%model:gemini-3-flash-preview\nReview"
    )
    assert result[1] == (
        "%name:o.gem-gemini-2.5-flash\n%model:gemini-2.5-flash\nReview"
    )


def test_split_prompt_for_models_global_shorthand_name_uses_resolved_alias() -> None:
    """A model shorthand keeps its raw directive but names with the resolved alias."""
    xprompts = {
        "flash": XPrompt(name="flash", content="gemini-3-flash-preview"),
    }
    with patch("sase.xprompt.processor.get_all_xprompts", return_value=xprompts):
        result = split_prompt_for_models("%n:o\n%m(#flash,gemini-2.5-flash)\nReview")

    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:o.gem-flash3\n%model:#flash\nReview"
    assert result[1] == "%name:o.gem-flash25\n%model:gemini-2.5-flash\nReview"


def test_split_prompt_for_models_same_runtime_shorthands_use_resolved_aliases() -> None:
    """Same-runtime shorthand variants disambiguate with resolved model aliases."""
    xprompts = {
        "flash": XPrompt(name="flash", content="gemini-3-flash-preview"),
        "pro": XPrompt(name="pro", content="gemini-3.1-pro-preview"),
    }
    with patch("sase.xprompt.processor.get_all_xprompts", return_value=xprompts):
        result = split_prompt_for_models("%n:ag\n%m(#flash,#pro)\nReview")

    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:ag.gem-flash3\n%model:#flash\nReview"
    assert result[1] == "%name:ag.gem-pro31p\n%model:#pro\nReview"


def test_split_prompt_for_models_dedupes_raw_and_shorthand_same_model() -> None:
    """Raw and shorthand forms of the same model do not fan out."""
    xprompts = {
        "flash": XPrompt(name="flash", content="gemini-3-flash-preview"),
    }
    with patch("sase.xprompt.processor.get_all_xprompts", return_value=xprompts):
        result = split_prompt_for_models("%m(#flash,gemini-3-flash-preview)\nReview")

    assert result is None


def test_split_prompt_for_models_unknown_shorthand_name_strips_hash_fallback() -> None:
    """Unknown shorthand remains raw in %model but drops # from the name suffix."""
    with patch(
        "sase.xprompt._directive_alt._runtime_label_for_model",
        return_value="gem",
    ):
        result = split_prompt_for_models(
            "%n:o\n%m(#unknown_model_alias,gemini-3-flash-preview)\nReview"
        )

    assert result is not None
    assert len(result) == 2
    assert result[0] == (
        "%name:o.gem-unknown_model_alias\n%model:#unknown_model_alias\nReview"
    )
    assert result[1] == "%name:o.gem-flash3\n%model:gemini-3-flash-preview\nReview"


def test_split_prompt_for_models_pure_alt_gets_planned_names() -> None:
    """A %alt(...) with no %model branches gets shared-base child names."""
    prompt = "%n:foo\n%alt(x,y)\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.1\nx\nDo work"
    assert result[1] == "%name:foo.2\ny\nDo work"


def test_split_prompt_for_models_named_shorthand_alt_ids() -> None:
    """Named shorthand alt args use the branch name and unnamed args use numbers."""
    prompt = "%n:foo\n%(fast=[[fast pass]], [[slow pass]])\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:foo.fast\nfast pass\nDo work"
    assert result[1] == "%name:foo.1\nslow pass\nDo work"


def test_split_prompt_for_models_pure_alt_auto_generated_base() -> None:
    """Pure alt fan-out without %name auto-generates one shared base."""
    with patch("sase.agent.names.get_next_auto_name", return_value="z"):
        result = split_prompt_for_models("%alt(x,y)\nDo work")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%name:z.1\nx\nDo work"
    assert result[1] == "%name:z.2\ny\nDo work"


def test_split_prompt_for_models_pure_alt_auto_base_skips_active_names(
    tmp_path: Path,
) -> None:
    """Auto base allocation skips occupied visible agents for pure %alt."""
    _make_agent(tmp_path, "proj", "run-a", "a", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models("%alt(x,y)\nDo work")

    assert result is not None
    assert result[0] == "%name:b.1\nx\nDo work"
    assert result[1] == "%name:b.2\ny\nDo work"


def test_split_prompt_for_models_pure_alt_resume_base(tmp_path: Path) -> None:
    """Pure %alt fan-out without %name uses one resume-derived base."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models("#resume:foo\n%alt(x,y)\nDo work")

    assert result is not None
    assert result[0] == "%name:foo.r1.1\n#resume:foo\nx\nDo work"
    assert result[1] == "%name:foo.r1.2\n#resume:foo\ny\nDo work"


def test_split_prompt_for_models_pure_alt_resume_base_skips_existing_slot(
    tmp_path: Path,
) -> None:
    """Pure %alt resume allocation skips existing descendant resume slots."""
    _make_agent(tmp_path, "proj", "run-old", "foo.r1.sec", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models("#resume:foo\n%alt(sec=x,perf=y)\nDo work")

    assert result is not None
    assert result[0] == "%name:foo.r2.sec\n#resume:foo\nx\nDo work"
    assert result[1] == "%name:foo.r2.perf\n#resume:foo\ny\nDo work"


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
    """Explicit %name fan-out emits explicit child %name directives for claim-time dedup."""
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
    assert result[0] == "%name:foo.cld-opus\n%model:opus\nReview"
    assert result[1] == "%name:foo.cld-sonnet\n%model:sonnet\nReview"


def test_split_prompt_for_models_with_alt_directive() -> None:
    """%model(opus,sonnet) combined with %(x,y) produces 4 prompts."""
    prompt = "%n:foo\n%m(opus,sonnet) %(x,y)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 4
    assert (
        "%name:foo.cld-opus" in result[0]
        and "%model:opus" in result[0]
        and "x" in result[0]
    )
    assert (
        "%name:foo.cld-opus" in result[1]
        and "%model:opus" in result[1]
        and "y" in result[1]
    )
    assert (
        "%name:foo.cld-sonnet" in result[2]
        and "%model:sonnet" in result[2]
        and "x" in result[2]
    )
    assert (
        "%name:foo.cld-sonnet" in result[3]
        and "%model:sonnet" in result[3]
        and "y" in result[3]
    )
