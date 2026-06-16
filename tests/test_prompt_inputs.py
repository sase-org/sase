"""Tests for launch-time prompt input collection & substitution (sase-4r.5).

Covers the pure-logic surface in :mod:`sase.agent.prompt_inputs`: parsing the
declared inputs off a prompt's frontmatter, splitting required vs optional,
resolving + coercing collected values (with defaults), and rendering the values
into every segment while stripping the consumed ``input:`` block.
"""

from __future__ import annotations

import pytest

from sase.agent.prompt_inputs import (
    PromptInputError,
    _resolve_input_values,
    missing_required_input_names,
    parse_prompt_input_request,
    render_prompt_with_inputs,
)
from sase.xprompt.models import InputType

# A representative prompt: two required inputs, one optional (defaulted), local
# xprompts in frontmatter, and two ``---``-separated segments referencing them.
_PROMPT = """\
---
xprompts:
  _rules: Follow the checklist
input:
  service: word
  retries:
    type: int
    description: how many times
  dry_run:
    type: bool
    default: false
---
Refactor {{ service }} with {{ retries }} retries (dry_run={{ dry_run }}). #_rules
---
Second segment for {{ service }}.\
"""


def test_parse_returns_none_without_frontmatter() -> None:
    assert parse_prompt_input_request("just a plain prompt") is None


def test_parse_returns_none_when_no_input_key() -> None:
    prompt = "---\ndescription: hi\n---\nbody"
    assert parse_prompt_input_request(prompt) is None


def test_parse_splits_required_and_optional() -> None:
    request = parse_prompt_input_request(_PROMPT)
    assert request is not None
    assert [arg.name for arg in request.inputs] == ["service", "retries", "dry_run"]
    assert [arg.name for arg in request.required] == ["service", "retries"]
    assert [arg.name for arg in request.optional] == ["dry_run"]
    assert request.has_required is True


def test_parse_accepts_inputs_alias() -> None:
    prompt = "---\ninputs:\n  service: word\n---\nUse {{ service }}"
    request = parse_prompt_input_request(prompt)
    assert request is not None
    assert [arg.name for arg in request.inputs] == ["service"]


def test_all_optional_has_no_required() -> None:
    prompt = "---\ninput:\n  dry_run:\n    type: bool\n    default: false\n---\nx"
    request = parse_prompt_input_request(prompt)
    assert request is not None
    assert request.has_required is False
    assert request.required == []


def test_missing_required_input_names() -> None:
    assert missing_required_input_names(_PROMPT) == ["service", "retries"]
    assert missing_required_input_names("plain prompt") == []


def test_resolve_converts_values_and_fills_defaults() -> None:
    request = parse_prompt_input_request(_PROMPT)
    assert request is not None
    resolved = _resolve_input_values(
        request.inputs, {"service": "billing", "retries": "3"}
    )
    assert resolved == {"service": "billing", "retries": 3, "dry_run": False}


def test_resolve_supplied_optional_overrides_default() -> None:
    request = parse_prompt_input_request(_PROMPT)
    assert request is not None
    resolved = _resolve_input_values(
        request.inputs, {"service": "billing", "retries": "3", "dry_run": "true"}
    )
    assert resolved["dry_run"] is True


def test_resolve_raises_on_missing_required() -> None:
    request = parse_prompt_input_request(_PROMPT)
    assert request is not None
    with pytest.raises(PromptInputError, match="Missing required input 'retries'"):
        _resolve_input_values(request.inputs, {"service": "billing"})


def test_resolve_raises_on_invalid_value() -> None:
    request = parse_prompt_input_request(_PROMPT)
    assert request is not None
    with pytest.raises(PromptInputError, match="expects int"):
        _resolve_input_values(
            request.inputs, {"service": "billing", "retries": "three"}
        )


@pytest.mark.parametrize(
    ("type_name", "raw", "expected"),
    [
        ("word", "hello", "hello"),
        ("line", "a line", "a line"),
        ("text", "multi\nline", "multi\nline"),
        ("path", "src/x.py", "src/x.py"),
        ("int", "42", 42),
        ("float", "1.5", 1.5),
        ("bool", "yes", True),
        ("bool", "off", False),
    ],
)
def test_resolve_coerces_each_type(type_name: str, raw: str, expected: object) -> None:
    prompt = f"---\ninput:\n  v: {type_name}\n---\n{{{{ v }}}}"
    request = parse_prompt_input_request(prompt)
    assert request is not None
    assert request.inputs[0].type is InputType(type_name)
    resolved = _resolve_input_values(request.inputs, {"v": raw})
    assert resolved == {"v": expected}


def test_render_substitutes_all_segments_and_strips_input() -> None:
    out = render_prompt_with_inputs(_PROMPT, {"service": "billing", "retries": "3"})
    # `input:` is consumed; `xprompts:` is preserved.
    assert "input:" not in out
    assert "xprompts:" in out
    assert "_rules: Follow the checklist" in out
    # Both segments substituted; the optional default flowed in.
    assert "Refactor billing with 3 retries (dry_run=False). #_rules" in out
    assert "Second segment for billing." in out
    # The segment separator survives the substitution.
    assert out.count("\n---\n") >= 1


def test_render_drops_frontmatter_when_only_input_declared() -> None:
    prompt = "---\ninput:\n  service: word\n---\nHello {{ service }}"
    out = render_prompt_with_inputs(prompt, {"service": "auth"})
    assert out == "Hello auth"


def test_render_substitutes_optional_default_without_values() -> None:
    prompt = (
        "---\ninput:\n  dry_run:\n    type: bool\n    default: false\n---\n"
        "run={{ dry_run }}"
    )
    assert render_prompt_with_inputs(prompt, {}) == "run=False"


def test_render_is_noop_without_declared_inputs() -> None:
    prompt = "---\ndescription: hi\n---\nplain body {{ not_an_input }}"
    # No inputs declared -> returned untouched (Jinja left for the runner).
    assert render_prompt_with_inputs(prompt, {}) == prompt


def test_render_raises_on_missing_required() -> None:
    with pytest.raises(PromptInputError, match="Missing required input"):
        render_prompt_with_inputs(_PROMPT, {"service": "billing"})


def test_render_raises_on_invalid_value() -> None:
    with pytest.raises(PromptInputError, match="expects int"):
        render_prompt_with_inputs(_PROMPT, {"service": "billing", "retries": "three"})


def test_render_leaves_non_jinja_body_untouched() -> None:
    # Declared-but-unused input, body has no Jinja: body is returned verbatim
    # (no legacy `{1}` positional substitution is attempted).
    prompt = "---\ninput:\n  service: word\n---\nNo placeholders here."
    out = render_prompt_with_inputs(prompt, {"service": "auth"})
    assert out == "No placeholders here."


def test_run_query_errors_clearly_on_missing_required_inputs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The non-interactive CLI cannot prompt; a required (default-less) input must
    # surface a clear error up front instead of a cryptic later Jinja failure.
    from sase.main.query_handler._query import run_query

    prompt = "---\ninput:\n  service: word\n  retries: int\n---\nRefactor {{ service }}"
    with pytest.raises(SystemExit) as exc_info:
        run_query(prompt)

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "service" in out
    assert "retries" in out
    assert "sase ace" in out
