"""Tests for the structured :class:`PromptFrontmatter` model (Phase 2, sase-4r.2).

Pure-logic coverage of parse -> model -> serialize -> parse round-trips, the
``inputs`` -> ``input`` alias normalization, scalar/list/structured handling,
accessors/mutators, and the core-backed diagnostics hook.  No Textual.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.xprompt.loader_parsing import LocalXPromptNameError
from sase.xprompt.models import UNSET, InputArg, InputChoice, InputType, XPrompt
from sase.xprompt.prompt_frontmatter import (
    LOCAL_XPROMPT_SOURCE,
    PromptFrontmatter,
)


def _round_trip(raw: str) -> tuple[PromptFrontmatter, PromptFrontmatter]:
    """Parse *raw*, serialize, and re-parse; return both models."""
    model = PromptFrontmatter.parse(raw)
    reparsed = PromptFrontmatter.parse(model.serialize())
    return model, reparsed


# --- round-trip: the core invariant ---------------------------------------


def test_round_trip_full_frontmatter_is_lossless() -> None:
    raw = (
        "---\n"
        "name: my_prompt\n"
        "description: Refactor the auth module\n"
        "tags: refactor, backend\n"
        "input:\n"
        "  service: word\n"
        "  dry_run: {type: bool, default: false}\n"
        "  retries: {type: int, default: 3, description: how many}\n"
        "xprompts:\n"
        '  _rules: "Follow the checklist"\n'
        "  _greet:\n"
        "    input: {who: word}\n"
        '    content: "Hello {{ who }}"\n'
        "    description: greet someone\n"
        "skill: false\n"
        "snippet: trig\n"
        "---"
    )
    model, reparsed = _round_trip(raw)
    assert model == reparsed


def test_round_trip_serialize_is_idempotent() -> None:
    model = PromptFrontmatter.parse("---\nname: x\ntags: a, b\n---")
    once = model.serialize()
    twice = PromptFrontmatter.parse(once).serialize()
    assert once == twice


def test_serialize_has_delimiters_and_no_trailing_newline() -> None:
    model = PromptFrontmatter(name="x")
    serialized = model.serialize()
    assert serialized.startswith("---\n")
    assert serialized.endswith("\n---")
    assert not serialized.endswith("\n")


def test_serialize_orders_fields_canonically() -> None:
    model = PromptFrontmatter(
        snippet="trig",
        skill=False,
        name="n",
        description="d",
        tags=["a"],
    )
    lines = model.serialize().splitlines()
    keys = [
        line.split(":", 1)[0]
        for line in lines
        if not line.startswith(("---", " ", "-"))
    ]
    assert keys == ["name", "description", "tags", "skill", "snippet"]


# --- empty handling --------------------------------------------------------


def test_empty_model_serializes_to_empty_string() -> None:
    assert PromptFrontmatter().serialize() == ""


def test_empty_string_parses_to_empty_model() -> None:
    model = PromptFrontmatter.parse("")
    assert model == PromptFrontmatter()
    assert model.is_empty


def test_is_empty_reflects_set_fields() -> None:
    assert PromptFrontmatter().is_empty
    assert not PromptFrontmatter(name="x").is_empty


def test_unknown_fields_are_preserved_after_parity_fields() -> None:
    model = PromptFrontmatter.parse("---\ntitle: x\nbogus: 1\n---")
    assert model.extras == {"title": "x", "bogus": 1}
    assert model.present_fields() == ["title", "bogus"]
    assert PromptFrontmatter.parse(model.serialize()).extras == model.extras


def test_comments_are_detected_and_original_text_retained() -> None:
    raw = "---\n# keep this in mind\nname: review  # visible warning\n---"
    model = PromptFrontmatter.parse(raw)
    assert model.has_comments
    assert model.original_text == raw


def test_extra_order_is_stable_and_appended_after_parity_fields() -> None:
    model = PromptFrontmatter.parse(
        "---\noutput: {type: json_schema}\nname: review\nlog_skill_use: false\n---"
    )
    assert list(model.to_mapping()) == ["name", "output", "log_skill_use"]


def test_builtin_markdown_frontmatter_corpus_is_idempotent() -> None:
    roots = [Path("src/sase/xprompts"), Path("src/sase/default_xprompts")]
    for source in (path for root in roots for path in root.rglob("*.md")):
        text = source.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        model = PromptFrontmatter.parse(text)
        reparsed = PromptFrontmatter.parse(model.serialize())
        assert reparsed.to_mapping() == model.to_mapping(), source


# --- input vs inputs alias normalization -----------------------------------


def test_inputs_alias_normalizes_to_input() -> None:
    model = PromptFrontmatter.parse("---\ninputs:\n  svc: word\n---")
    assert [arg.name for arg in model.inputs] == ["svc"]
    # Canonical serialization uses `input`, never the `inputs` alias.
    serialized = model.serialize()
    assert "input:" in serialized
    assert "inputs:" not in serialized


def test_input_preferred_over_inputs_when_both_present() -> None:
    model = PromptFrontmatter.parse(
        "---\ninput:\n  canonical: word\ninputs:\n  alias: word\n---"
    )
    assert [arg.name for arg in model.inputs] == ["canonical"]


# --- scalars ---------------------------------------------------------------


def test_scalar_round_trip() -> None:
    _, reparsed = _round_trip("---\nname: foo\ndescription: a desc\n---")
    assert reparsed.name == "foo"
    assert reparsed.description == "a desc"


def test_skill_bool_and_list_round_trip() -> None:
    _, bool_model = _round_trip("---\nskill: false\n---")
    assert bool_model.skill is False
    _, list_model = _round_trip("---\nskill:\n  - claude\n  - codex\n---")
    assert list_model.skill == ["claude", "codex"]


def test_snippet_string_and_bool_round_trip() -> None:
    _, str_model = _round_trip("---\nsnippet: trig\n---")
    assert str_model.snippet == "trig"
    _, bool_model = _round_trip("---\nsnippet: true\n---")
    assert bool_model.snippet is True


# --- tags ------------------------------------------------------------------


def test_tags_comma_string_parses_to_list() -> None:
    model = PromptFrontmatter.parse("---\ntags: refactor, backend\n---")
    assert model.tags == ["refactor", "backend"]


def test_tags_yaml_list_parses_to_list() -> None:
    model = PromptFrontmatter.parse("---\ntags:\n  - refactor\n  - backend\n---")
    assert model.tags == ["refactor", "backend"]


def test_tags_round_trip() -> None:
    _, reparsed = _round_trip("---\ntags: refactor, backend\n---")
    assert reparsed.tags == ["refactor", "backend"]


def test_tags_are_free_form() -> None:
    # Ad-hoc prompt tags are not constrained to the xprompt tag enum.
    model = PromptFrontmatter.parse("---\ntags: not_a_real_tag\n---")
    assert model.tags == ["not_a_real_tag"]


# --- input arguments -------------------------------------------------------


def test_required_input_serializes_as_bare_type() -> None:
    model = PromptFrontmatter(inputs=[InputArg(name="svc", type=InputType.WORD)])
    assert "  svc: word" in model.serialize()


def test_input_with_default_round_trips() -> None:
    model = PromptFrontmatter(
        inputs=[InputArg(name="dry", type=InputType.BOOL, default=False)]
    )
    reparsed = PromptFrontmatter.parse(model.serialize())
    arg = reparsed.get_input("dry")
    assert arg is not None
    assert arg.type is InputType.BOOL
    assert arg.default is False


def test_required_input_keeps_unset_default() -> None:
    _, reparsed = _round_trip("---\ninput:\n  svc: word\n---")
    arg = reparsed.get_input("svc")
    assert arg is not None
    assert arg.default is UNSET


def test_input_explicit_null_default_round_trips() -> None:
    model = PromptFrontmatter(
        inputs=[InputArg(name="opt", type=InputType.LINE, default=None)]
    )
    reparsed = PromptFrontmatter.parse(model.serialize())
    arg = reparsed.get_input("opt")
    assert arg is not None
    assert arg.default is None


def test_int_and_float_defaults_round_trip() -> None:
    model = PromptFrontmatter(
        inputs=[
            InputArg(name="n", type=InputType.INT, default=3),
            InputArg(name="r", type=InputType.FLOAT, default=1.5),
        ]
    )
    reparsed = PromptFrontmatter.parse(model.serialize())
    assert reparsed.get_input("n").default == 3  # type: ignore[union-attr]
    assert reparsed.get_input("r").default == 1.5  # type: ignore[union-attr]


def test_input_description_round_trips() -> None:
    model = PromptFrontmatter(
        inputs=[InputArg(name="svc", type=InputType.WORD, description="the service")]
    )
    reparsed = PromptFrontmatter.parse(model.serialize())
    arg = reparsed.get_input("svc")
    assert arg is not None
    assert arg.description == "the service"


def test_enum_input_unlabeled_choices_round_trip_as_scalars() -> None:
    model = PromptFrontmatter(
        inputs=[
            InputArg(
                name="mode",
                type=InputType.ENUM,
                choices=(InputChoice(value="fast"), InputChoice(value="slow")),
            )
        ]
    )
    serialized = model.serialize()
    assert "choices" in serialized

    reparsed = PromptFrontmatter.parse(serialized)
    arg = reparsed.get_input("mode")
    assert arg is not None
    assert arg.type is InputType.ENUM
    assert arg.choices == (
        InputChoice(value="fast"),
        InputChoice(value="slow"),
    )


def test_enum_input_labeled_choices_round_trip() -> None:
    model = PromptFrontmatter(
        inputs=[
            InputArg(
                name="mode",
                type=InputType.ENUM,
                choices=(
                    InputChoice(value="fast", label="Fast mode"),
                    InputChoice(value="slow"),
                ),
            )
        ]
    )
    reparsed = PromptFrontmatter.parse(model.serialize())
    arg = reparsed.get_input("mode")
    assert arg is not None
    assert arg.choices == (
        InputChoice(value="fast", label="Fast mode"),
        InputChoice(value="slow"),
    )


# --- xprompts --------------------------------------------------------------


def test_simple_xprompt_serializes_as_bare_string() -> None:
    model = PromptFrontmatter.parse('---\nxprompts:\n  _rules: "be concise"\n---')
    serialized = model.serialize()
    assert "_rules: be concise" in serialized
    _, reparsed = _round_trip('---\nxprompts:\n  _rules: "be concise"\n---')
    assert reparsed.xprompts["_rules"].content == "be concise"
    assert reparsed.xprompts["_rules"].source_path == LOCAL_XPROMPT_SOURCE


def test_structured_xprompt_round_trips() -> None:
    raw = (
        "---\n"
        "xprompts:\n"
        "  _greet:\n"
        "    input: {who: word}\n"
        '    content: "Hello {{ who }}"\n'
        "    description: greet someone\n"
        "---"
    )
    model, reparsed = _round_trip(raw)
    assert model == reparsed
    greet = reparsed.xprompts["_greet"]
    assert greet.content == "Hello {{ who }}"
    assert greet.description == "greet someone"
    assert [arg.name for arg in greet.inputs] == ["who"]


def test_xprompt_multiline_content_round_trips() -> None:
    xprompt = XPrompt(
        name="_multi",
        content="line one\nline two\nline three",
        source_path=LOCAL_XPROMPT_SOURCE,
    )
    model = PromptFrontmatter(xprompts={"_multi": xprompt})
    reparsed = PromptFrontmatter.parse(model.serialize())
    assert reparsed.xprompts["_multi"].content == "line one\nline two\nline three"


def test_xprompt_name_must_be_underscore_prefixed() -> None:
    with pytest.raises(LocalXPromptNameError):
        PromptFrontmatter.parse('---\nxprompts:\n  rules: "no underscore"\n---')


# --- accessors / mutators --------------------------------------------------


def test_set_input_appends_and_replaces() -> None:
    model = PromptFrontmatter()
    model.set_input(InputArg(name="svc", type=InputType.WORD))
    assert len(model.inputs) == 1
    # Same name replaces in place rather than appending.
    model.set_input(InputArg(name="svc", type=InputType.LINE))
    assert len(model.inputs) == 1
    assert model.get_input("svc").type is InputType.LINE  # type: ignore[union-attr]


def test_remove_input_reports_presence() -> None:
    model = PromptFrontmatter(inputs=[InputArg(name="svc")])
    assert model.remove_input("svc") is True
    assert model.remove_input("svc") is False
    assert model.get_input("svc") is None


def test_set_and_remove_xprompt() -> None:
    model = PromptFrontmatter()
    model.set_xprompt(XPrompt(name="_a", content="x"))
    assert model.get_xprompt("_a") is not None
    assert model.remove_xprompt("_a") is True
    assert model.remove_xprompt("_a") is False
    assert model.get_xprompt("_a") is None


def test_present_fields_in_canonical_order() -> None:
    model = PromptFrontmatter(
        snippet="t", name="n", inputs=[InputArg(name="svc")], tags=["a"]
    )
    assert model.present_fields() == ["name", "tags", "input", "snippet"]


# --- bare / partial input --------------------------------------------------


def test_parse_bare_yaml_body_without_delimiters() -> None:
    model = PromptFrontmatter.parse("name: bare\ndescription: no delims")
    assert model.name == "bare"
    assert model.description == "no delims"


def test_parse_unterminated_frontmatter_block() -> None:
    model = PromptFrontmatter.parse("---\nname: typing")
    assert model.name == "typing"


def test_parse_non_mapping_yields_empty_model() -> None:
    assert PromptFrontmatter.parse("- just\n- a\n- list").is_empty


# --- diagnostics (delegated to sase-core) ----------------------------------


def test_diagnostics_clean_for_valid_frontmatter() -> None:
    model = PromptFrontmatter.parse(
        "---\nname: x\ntags: a, b\ninput:\n  svc: word\nskill: false\n---"
    )
    assert model.diagnostics() == []


def test_diagnostics_empty_model_has_none() -> None:
    assert PromptFrontmatter().diagnostics() == []


def test_diagnostics_alias_normalized_form_is_clean() -> None:
    # `inputs` alone would draw an "unknown field" diagnostic from core, but the
    # model serializes the canonical `input`, so the diagnostics are clean.
    model = PromptFrontmatter.parse("---\ninputs:\n  svc: word\n---")
    assert model.diagnostics() == []


def test_diagnostics_surface_core_errors() -> None:
    # An `int` input with a non-int default is a model the panel/raw-mode can
    # produce; core flags it, proving diagnostics() delegates to the real
    # validator rather than always returning clean.
    model = PromptFrontmatter(
        inputs=[InputArg(name="n", type=InputType.INT, default="notanint")]
    )
    diags = model.diagnostics()
    assert any(d.is_error for d in diags)


def test_diagnostics_matches_direct_core_validation() -> None:
    from sase.xprompt.frontmatter_schema import validate_frontmatter

    model = PromptFrontmatter.parse("---\nname: x\ninput:\n  svc: word\n---")
    assert model.diagnostics() == validate_frontmatter(model.serialize())
