"""Tests for split_prompt_for_models fan-out naming and model resolution."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.xprompt.directives import split_prompt_for_models
from sase.xprompt.models import XPrompt


def test_split_prompt_for_models_multi_model_distinct_runtimes() -> None:
    """Two models on distinct runtimes get plain runtime suffixes (no model)."""
    prompt = "%i:foo\n%{%model:opus | %model:gpt-5.6-sol}\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:foo.cld\n%model:opus\nReview this code"
    assert result[1] == "%id:foo.cdx\n%model:gpt-5.6-sol\nReview this code"


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_split_prompt_for_models_alias_uses_resolved_suffix(
    mock_config: MagicMock,
) -> None:
    """Fan-out names use the concrete configured model behind an alias."""
    mock_config.return_value = {
        "model_aliases": {
            "custom": {
                "other": {
                    "model": "claude/opus",
                    "description": "Other model.",
                }
            }
        }
    }

    prompt = "%i:foo\n%{%model:@other | %model:gpt-5.6-sol}\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:foo.cld\n%model:@other\nReview this code"
    assert result[1] == "%id:foo.cdx\n%model:gpt-5.6-sol\nReview this code"


def test_split_prompt_for_models_other_resolves_to_configured_alias(
    monkeypatch,
) -> None:
    """The "other" alias is ordinary config with no displaced-model behavior.

    The worker lane was retired in epic sase-5d phase 4, so "other" is no
    longer override-aware: it resolves purely to its configured target
    (claude/opus here). An active temporary default override must not give
    "other" any displaced-model behavior - the fan-out disambiguator follows
    the configured alias target, not the override.
    """
    from sase.llm_provider.temporary_override import set_temporary_override

    cfg = {
        "provider": "claude",
        "model_aliases": {
            "custom": {
                "other": {
                    "model": "claude/opus",
                    "description": "Other model.",
                }
            }
        },
    }
    # Patch both modules: registry imports the symbol at load time,
    # config defines it. Alias resolution goes through registry.
    monkeypatch.setattr("sase.llm_provider.config.get_llm_provider_config", lambda: cfg)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: cfg
    )
    # An active override (to a different runtime/model) must NOT change how
    # "other" resolves for fan-out naming.
    set_temporary_override("codex/o3", 3600.0, source="test")

    # other + sonnet are both claude; the same-runtime collision uses model
    # names as the disambiguator. "other" follows its configured alias target
    # (opus), so the two branches stay distinct.
    prompt = "%i:foo\n%{%model:@other | %model:sonnet}\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:foo.cld_opus\n%model:@other\nReview"
    assert result[1] == "%id:foo.cld_sonnet\n%model:sonnet\nReview"


def test_split_prompt_for_models_resume_base(tmp_path: Path) -> None:
    """Multi-model fan-out without %id uses the resume-derived base."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models(
            "#fork:foo\n%{%model:opus | %model:sonnet}\nDo work"
        )
    assert result is not None
    assert result[0] == "%id:foo.f0.cld_opus\n#fork:foo\n%model:opus\nDo work"
    assert result[1] == "%id:foo.f0.cld_sonnet\n#fork:foo\n%model:sonnet\nDo work"


def test_split_prompt_for_models_wait_base(tmp_path: Path) -> None:
    """Multi-model fan-out without %id uses the wait-derived base."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models(
            "%wait:foo\n%{%model:opus | %model:sonnet}\nDo work"
        )
    assert result is not None
    assert result[0] == "%id:foo.w0.cld_opus\n%wait:foo\n%model:opus\nDo work"
    assert result[1] == "%id:foo.w0.cld_sonnet\n%wait:foo\n%model:sonnet\nDo work"


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
        "%id:foo.f0.cld_opus\n%wait:foo\n#fork:foo\n%model:opus\nDo work"
    )
    assert result[1] == (
        "%id:foo.f0.cld_sonnet\n%wait:foo\n#fork:foo\n%model:sonnet\nDo work"
    )


def test_split_prompt_for_models_multi_model_auto_generated_base() -> None:
    """No %id with multi-model injects grouped auto-name templates."""
    result = split_prompt_for_models("%{%model:opus | %model:gpt-5.6-sol}\nReview")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:@.cld\n%model:opus\nReview"
    assert result[1] == "%id:@.cdx\n%model:gpt-5.6-sol\nReview"


def test_split_prompt_for_models_multi_model_bare_name_auto_generated() -> None:
    """Bare %id with multi-model behaves like an unnamed generated launch."""
    result = split_prompt_for_models("%id\n%{%model:opus | %model:gpt-5.6-sol}\nReview")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:@.cld\n%model:opus\nReview"
    assert result[1] == "%id:@.cdx\n%model:gpt-5.6-sol\nReview"


def test_split_prompt_for_models_unknown_model_uses_default_provider() -> None:
    """An unknown model maps to the default provider's runtime label."""
    from sase.llm_provider.registry import (
        get_default_provider_name,
        provider_short_name_map,
    )

    default = get_default_provider_name()
    default_short = provider_short_name_map().get(default, default)
    prompt = "%i:foo\n%{%model:unknown_model_xyz | %model:opus}\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    # When the unknown model resolves to the same runtime as opus (claude),
    # collision suffixing kicks in; otherwise plain runtime labels.
    if default == "claude":
        assert (
            result[0] == "%id:foo.cld_unknown_model_xyz\n"
            "%model:unknown_model_xyz\nReview"
        )
        assert result[1] == "%id:foo.cld_opus\n%model:opus\nReview"
    else:
        assert result[0] == f"%id:foo.{default_short}\n%model:unknown_model_xyz\nReview"
        assert result[1] == "%id:foo.cld\n%model:opus\nReview"


def test_split_prompt_for_models_codex_collision_uses_short_alias() -> None:
    """Same-runtime codex collision substitutes short aliases for model names."""
    prompt = "%i:o\n%{%model:gpt-5.6-sol | %model:gpt-5.3-codex}\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == ("%id:o.cdx_gpt56sol\n%model:gpt-5.6-sol\nReview")
    assert result[1] == ("%id:o.cdx_gpt53\n%model:gpt-5.3-codex\nReview")


def test_split_prompt_for_models_opencode_nested_models_use_short_aliases() -> None:
    """Explicit OpenCode provider/model strings use provider-local model aliases."""
    prompt = (
        "%i:o\n"
        "%{%model:opencode/anthropic/claude-sonnet-4-5 | %model:opencode/openai/gpt-5-mini}\n"
        "Review"
    )
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == (
        "%id:o.opc_sonnet45\n%model:opencode/anthropic/claude-sonnet-4-5\nReview"
    )
    assert result[1] == ("%id:o.opc_gpt5m\n%model:opencode/openai/gpt-5-mini\nReview")


def test_split_prompt_for_models_unknown_nested_model_suffix_is_name_safe() -> None:
    """Unknown explicit nested model names are sanitized for generated names."""
    prompt = (
        "%i:o\n%{%model:opencode/acme/foo/bar | %model:opencode/acme/baz/qux}\nReview"
    )
    result = split_prompt_for_models(prompt)
    assert result is not None
    name_lines = [line for item in result for line in item.splitlines()[:1]]
    assert name_lines == ["%id:o.opc_acme_foo_bar", "%id:o.opc_acme_baz_qux"]


def test_split_prompt_for_models_claude_collision_unchanged() -> None:
    """Claude opus/sonnet keep their raw names (no aliases declared)."""
    prompt = "%i:o\n%{%model:opus | %model:sonnet}\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:o.cld_opus\n%model:opus\nReview"
    assert result[1] == "%id:o.cld_sonnet\n%model:sonnet\nReview"


def test_split_prompt_for_models_no_collision_unchanged() -> None:
    """Distinct-runtime case never embeds the model name (alias irrelevant)."""
    prompt = "%i:o\n%{%model:opus | %model:gpt-5.6-sol}\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:o.cld\n%model:opus\nReview"
    assert result[1] == "%id:o.cdx\n%model:gpt-5.6-sol\nReview"


def test_split_prompt_for_models_unknown_model_falls_through() -> None:
    """Unknown model in a same-runtime collision keeps its raw name."""
    from sase.llm_provider.registry import get_default_provider_name

    if get_default_provider_name() != "codex":
        # Test relies on unknown_xyz routing to codex (the fallback default).
        # If a different default is configured, skip the assertion path.
        return
    prompt = "%i:o\n%{%model:gpt-5.6-sol | %model:unknown_xyz}\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == ("%id:o.cdx_gpt56sol\n%model:gpt-5.6-sol\nReview")
    assert result[1] == "%id:o.cdx_unknown_xyz\n%model:unknown_xyz\nReview"


def test_split_prompt_for_models_alias_collision_falls_back_to_raw() -> None:
    """Two models that alias to the same short form fall back to raw names."""
    fake_aliases = {
        "gpt-5.6-sol": "gp",
        "gpt-5.3-codex": "gp",
    }
    with patch(
        "sase.llm_provider.registry.model_short_alias_map",
        return_value=fake_aliases,
    ):
        result = split_prompt_for_models(
            "%i:o\n%{%model:gpt-5.6-sol | %model:gpt-5.3-codex}\nReview"
        )
    assert result is not None
    assert len(result) == 2
    assert result[0] == ("%id:o.cdx_gpt_5.6_sol\n%model:gpt-5.6-sol\nReview")
    assert result[1] == ("%id:o.cdx_gpt_5.3_codex\n%model:gpt-5.3-codex\nReview")


def test_split_prompt_for_models_global_shorthand_name_uses_resolved_alias() -> None:
    """A model shorthand keeps its raw directive but names with the resolved alias."""
    xprompts = {
        "flash": XPrompt(name="flash", content="gpt-5.6-sol"),
    }
    with patch("sase.xprompt.processor.get_all_xprompts", return_value=xprompts):
        result = split_prompt_for_models(
            "%i:o\n%{%model:#flash | %model:gpt-5.3-codex}\nReview"
        )

    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:o.cdx_gpt56sol\n%model:#flash\nReview"
    assert result[1] == "%id:o.cdx_gpt53\n%model:gpt-5.3-codex\nReview"


def test_split_prompt_for_models_same_runtime_shorthands_use_resolved_aliases() -> None:
    """Same-runtime shorthand variants disambiguate with resolved model aliases."""
    xprompts = {
        "flash": XPrompt(name="flash", content="gpt-5.6-sol"),
        "pro": XPrompt(name="pro", content="gpt-4.1"),
    }
    with patch("sase.xprompt.processor.get_all_xprompts", return_value=xprompts):
        result = split_prompt_for_models(
            "%i:ag\n%{%model:#flash | %model:#pro}\nReview"
        )

    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:ag.cdx_gpt56sol\n%model:#flash\nReview"
    assert result[1] == "%id:ag.cdx_gpt41\n%model:#pro\nReview"


def test_split_prompt_for_models_alias_shorthand_strips_at_before_expansion(
    monkeypatch,
) -> None:
    """Alias-marked shorthand branches expand and name with resolved aliases."""
    cfg = {
        "model_aliases": {
            "custom": {
                "agy_flash": {
                    "model": "agy/Gemini 3.5 Flash (High)",
                    "description": "Antigravity flash preset.",
                },
                "agy_pro": {
                    "model": "agy/Gemini 3.1 Pro (High)",
                    "description": "Antigravity pro preset.",
                },
            }
        }
    }
    xprompts = {
        "agy_flash": XPrompt(name="agy_flash", content="agy_flash"),
        "agy_pro": XPrompt(name="agy_pro", content="agy_pro"),
    }
    monkeypatch.setattr("sase.llm_provider.config.get_llm_provider_config", lambda: cfg)
    monkeypatch.setattr(
        "sase.llm_provider.registry.get_llm_provider_config", lambda: cfg
    )
    monkeypatch.setattr("sase.xprompt.processor.get_all_xprompts", lambda *_: xprompts)

    result = split_prompt_for_models("%i:ag\n%{%m:@#agy_pro | %m:@#agy_flash}\nReview")

    assert result is not None
    assert result == [
        "%id:ag.agy_pro31h\n%m:@#agy_pro\nReview",
        "%id:ag.agy_flash35h\n%m:@#agy_flash\nReview",
    ]


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
        "%id:@.1\n%model:#flash\nReview",
        "%id:@.2\n%model:gemini-3-flash-preview\nReview",
    ]


def test_split_prompt_for_models_unknown_shorthand_name_strips_hash_fallback() -> None:
    """Unknown shorthand remains raw in %model but drops # from the name suffix."""
    with patch(
        "sase.xprompt._directive_alt._runtime_label_for_model",
        return_value="cdx",
    ):
        result = split_prompt_for_models(
            "%i:o\n%{%model:#unknown_model_alias | %model:gpt-5.6-sol}\nReview"
        )

    assert result is not None
    assert len(result) == 2
    assert result[0] == (
        "%id:o.cdx_unknown_model_alias\n%model:#unknown_model_alias\nReview"
    )
    assert result[1] == "%id:o.cdx_gpt56sol\n%model:gpt-5.6-sol\nReview"
