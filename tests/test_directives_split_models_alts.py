"""Tests for split_prompt_for_models alternative-axis fan-out."""

from pathlib import Path
from unittest.mock import patch

from sase.xprompt.directives import split_prompt_for_models
from sase.xprompt.models import XPrompt
from tests._agent_names_fixtures import make_agent as _make_agent


def test_split_prompt_for_models_multi_model_with_user_alt_cartesian() -> None:
    """Model branches Cartesian-product with a user %alt(x,y)."""
    prompt = "%i:foo\n%{%model:opus | %model:sonnet} %alt(x,y)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 4
    name_lines = [variant.splitlines()[0] for variant in result]
    assert name_lines == [
        "%id:foo.cld_opus.1",
        "%id:foo.cld_opus.2",
        "%id:foo.cld_sonnet.1",
        "%id:foo.cld_sonnet.2",
    ]
    assert len(set(name_lines)) == len(name_lines)
    assert " x\nReview" in result[0]
    assert " y\nReview" in result[1]
    assert " x\nReview" in result[2]
    assert " y\nReview" in result[3]


def test_split_prompt_for_models_text_alt_then_model_alt_gets_unique_names() -> None:
    """Text-first and model-last axes keep both dimensions in generated names."""
    xprompts = {
        "codex": XPrompt(name="codex", content="gpt-5.6-sol"),
    }

    result = split_prompt_for_models(
        "%i:foo %{Describe | Explain} repo. %{%m:opus | %m:#codex}",
        extra_xprompts=xprompts,
    )

    assert result is not None
    assert len(result) == 4
    name_lines = [variant.splitlines()[0] for variant in result]
    assert name_lines == [
        "%id:foo.1.cld",
        "%id:foo.1.cdx",
        "%id:foo.2.cld",
        "%id:foo.2.cdx",
    ]
    assert len(set(name_lines)) == len(name_lines)
    assert "Describe repo." in result[0]
    assert "Describe repo." in result[1]
    assert "Explain repo." in result[2]
    assert "Explain repo." in result[3]


def test_split_prompt_for_models_pure_alt_gets_planned_names() -> None:
    """A %alt(...) with no %model branches gets shared-base child names."""
    prompt = "%i:foo\n%alt(x,y)\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:foo.1\nx\nDo work"
    assert result[1] == "%id:foo.2\ny\nDo work"


def test_split_prompt_for_models_preserves_tribe_keyword() -> None:
    result = split_prompt_for_models("%id(foo, tribe=review)\n%alt(x,y)\nDo work")

    assert result == [
        "%id(foo.1, tribe=review)\nx\nDo work",
        "%id(foo.2, tribe=review)\ny\nDo work",
    ]


def test_split_prompt_for_models_allows_template_name_base() -> None:
    """Template bases are preserved and extended for fan-out child names."""
    result = split_prompt_for_models("%i:foo-@\n%alt(x,y)\nDo work")

    assert result is not None
    assert result == [
        "%id:foo-@.1\nx\nDo work",
        "%id:foo-@.2\ny\nDo work",
    ]


def test_split_prompt_for_models_named_shorthand_alt_ids() -> None:
    """Named shorthand alt args use the branch name and unnamed args use numbers."""
    prompt = "%i:foo\n%(fast=[[fast pass]], [[slow pass]])\nDo work"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:foo.fast\nfast pass\nDo work"
    assert result[1] == "%id:foo.1\nslow pass\nDo work"


def test_split_prompt_for_models_shared_named_alt_ids_get_child_names() -> None:
    """Repeated named keys across alt directives use the shared key suffix."""
    prompt = "%i:foo\n%{a=Describe | b=Explain} how this repo works %{a=in detail}."
    result = split_prompt_for_models(prompt)

    assert result == [
        "%id:foo.a\nDescribe how this repo works in detail.",
        "%id:foo.b\nExplain how this repo works.",
    ]


def test_split_prompt_for_models_pure_alt_auto_generated_base() -> None:
    """Pure alt fan-out without %id injects grouped auto-name templates."""
    result = split_prompt_for_models("%alt(x,y)\nDo work")
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:@.1\nx\nDo work"
    assert result[1] == "%id:@.2\ny\nDo work"


def test_split_prompt_for_models_pure_alt_auto_base_stays_template_before_launch(
    tmp_path: Path,
) -> None:
    """Pure splitting leaves generated-name collision checks to launch planning."""
    _make_agent(tmp_path, "proj", "run-0", "0", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models("%alt(x,y)\nDo work")

    assert result is not None
    assert result[0] == "%id:@.1\nx\nDo work"
    assert result[1] == "%id:@.2\ny\nDo work"


def test_split_prompt_for_models_pure_alt_resume_base(tmp_path: Path) -> None:
    """Pure %alt fan-out without %id uses one resume-derived base."""
    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models("#fork:foo\n%alt(x,y)\nDo work")

    assert result is not None
    assert result[0] == "%id:foo.f0.1\n#fork:foo\nx\nDo work"
    assert result[1] == "%id:foo.f0.2\n#fork:foo\ny\nDo work"


def test_split_prompt_for_models_multi_parent_uses_neutral_base() -> None:
    result = split_prompt_for_models("#fork:planner,coder\n%alt(x,y)\nDo work")

    assert result == [
        "%id:@.1\n#fork:planner,coder\nx\nDo work",
        "%id:@.2\n#fork:planner,coder\ny\nDo work",
    ]


def test_split_prompt_for_models_pure_alt_resume_base_ignores_legacy_slot(
    tmp_path: Path,
) -> None:
    """Pure %alt resume allocation ignores legacy descendant retry slots."""
    _make_agent(tmp_path, "proj", "run-old", "foo.r1.sec", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models("#fork:foo\n%alt(sec=x,perf=y)\nDo work")

    assert result is not None
    assert result[0] == "%id:foo.f0.sec\n#fork:foo\nx\nDo work"
    assert result[1] == "%id:foo.f0.perf\n#fork:foo\ny\nDo work"


def test_split_prompt_for_models_named_model_alt_overrides_model_suffix() -> None:
    """Named model branches use the branch ids instead of runtime suffixes."""
    prompt = "%i:foo\n%alt(sec=%model:opus,perf=%model:sonnet)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:foo.sec\n%model:opus\nReview"
    assert result[1] == "%id:foo.perf\n%model:sonnet\nReview"


def test_split_prompt_for_models_numeric_named_alt_ids_do_not_collide() -> None:
    """Unnamed numeric ids skip user-provided numeric branch names."""
    prompt = "%i:foo\n%(2=[[named two]], [[first]], [[second]])\nDo work"
    result = split_prompt_for_models(prompt)

    assert result is not None
    assert result == [
        "%id:foo.2\nnamed two\nDo work",
        "%id:foo.1\nfirst\nDo work",
        "%id:foo.3\nsecond\nDo work",
    ]


def test_split_prompt_for_models_explicit_alt_base_becomes_explicit_child_names(
    tmp_path: Path,
) -> None:
    """Explicit %id fan-out emits explicit child %id directives."""
    _make_agent(tmp_path, "proj", "run-old", "foo.sec", done=True)

    with patch.object(Path, "home", return_value=tmp_path):
        result = split_prompt_for_models("%i:foo\n%alt(sec=x,perf=y)\nDo work")

    assert result is not None
    assert result[0] == "%id:foo.sec\nx\nDo work"
    assert result[1] == "%id:foo.perf\ny\nDo work"


def test_split_prompt_for_models_alt_with_nested_model_not_double_collected() -> None:
    """%alt(%model:a,%model:b) is processed as a single alt, not re-collected."""
    prompt = "%i:foo\n%alt(%model:opus,%model:sonnet)\nReview"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 2
    assert result[0] == "%id:foo.cld_opus\n%model:opus\nReview"
    assert result[1] == "%id:foo.cld_sonnet\n%model:sonnet\nReview"


def test_split_prompt_for_models_model_value_fanout() -> None:
    """%m:%{...} is equivalent to per-branch model directives."""
    prompt = "%i:foo\n%m:%{opus | sonnet}\nReview"
    result = split_prompt_for_models(prompt)

    assert result == [
        "%id:foo.cld_opus\n%m:opus\nReview",
        "%id:foo.cld_sonnet\n%m:sonnet\nReview",
    ]


def test_split_prompt_for_models_with_alt_directive() -> None:
    """Model branches combined with %(x,y) produce 4 prompts."""
    prompt = "%i:foo\n%{%model:opus | %model:sonnet} %(x,y)\nReview this code"
    result = split_prompt_for_models(prompt)
    assert result is not None
    assert len(result) == 4
    name_lines = [variant.splitlines()[0] for variant in result]
    assert name_lines == [
        "%id:foo.cld_opus.1",
        "%id:foo.cld_opus.2",
        "%id:foo.cld_sonnet.1",
        "%id:foo.cld_sonnet.2",
    ]
    assert len(set(name_lines)) == len(name_lines)
    assert "%model:opus" in result[0] and "x" in result[0]
    assert "%model:opus" in result[1] and "y" in result[1]
    assert "%model:sonnet" in result[2] and "x" in result[2]
    assert "%model:sonnet" in result[3] and "y" in result[3]
