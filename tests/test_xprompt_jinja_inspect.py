"""Tests for top-level prompt Jinja2 inspection helpers."""

from __future__ import annotations

from sase.xprompt import jinja_assist, jinja_inspect
from sase.xprompt._jinja import get_global_template_vars


def test_engine_catalog_contains_agent_run_context() -> None:
    names = {variable.name for variable in jinja_assist.jinja_catalog().variables}

    assert names >= {
        "cl_name",
        "patch_name",
        "workspace_num",
        "n",
        "N",
        "wait",
        "wait_chats",
        "agents",
    }


def test_inspect_template_accepts_engine_known_names() -> None:
    from sase.xprompt.jinja_inspect import _default_known_context

    known = _default_known_context()

    diagnostics = jinja_inspect.inspect_template(
        "{{ wait.chats }} {{ wait.artifacts }} {{ wait_chats }} {{ agents }}",
        known=known,
    )
    typo = jinja_inspect.inspect_template("{{ wait_chat }}", known=known)

    assert diagnostics.unknown_variables == ()
    assert typo.unknown_variables == ("wait_chat",)


def test_tokenize_skips_fenced_blocks() -> None:
    text = (
        "before {{ root | tojson }}\n"
        "```\n"
        "{{ missing_inside_fence }}\n"
        "```\n"
        "{% if root %}ok{% endif %}"
    )

    spans = jinja_inspect.tokenize(text)
    values = [span.value for span in spans]

    assert "root" in values
    assert "tojson" in values
    assert "if" in values
    assert "missing_inside_fence" not in values
    assert any(span.kind == "filter" and span.value == "tojson" for span in spans)
    assert any(span.kind == "keyword" and span.value == "if" for span in spans)


def test_tokenize_skips_punctuation_adjacent_inline_code() -> None:
    text = "prefix`{{ hidden }}`/`{% if hidden %}no{% endif %}` {{ visible }}"

    spans = jinja_inspect.tokenize(text)

    assert [span.value for span in spans if span.kind == "variable"] == ["visible"]
    assert not any(span.value == "hidden" for span in spans)


def test_alt_with_adjacent_directive_is_not_a_jinja_statement() -> None:
    text = "%{%m:opus | %m:sonnet} and {{ root }}"

    spans = jinja_inspect.tokenize(text)
    diagnostics = jinja_inspect.inspect_template(text, known={"root"})

    assert [(span.kind, span.value) for span in spans] == [
        ("delimiter", "{{"),
        ("variable", "root"),
        ("delimiter", "}}"),
    ]
    assert diagnostics.has_jinja is True
    assert diagnostics.ok is True
    assert diagnostics.unknown_variables == ()
    assert jinja_inspect.has_jinja("%{%m:opus | %m:sonnet}") is False


def test_diagnose_is_clean_for_glued_alt_directive() -> None:
    text = "foo%{%m:opus | %m:sonnet} go"

    diagnostics = jinja_inspect.diagnose(text)

    assert diagnostics.has_jinja is False
    assert diagnostics.ok is True


def test_diagnose_is_clean_for_opener_after_literal_brace() -> None:
    for text in ("{%{a | b}", "{%(a,b)", "x {%{a | b} y"):
        diagnostics = jinja_inspect.diagnose(text)

        assert diagnostics.has_jinja is False, text
        assert diagnostics.ok is True, text
    assert jinja_inspect.has_jinja("{%{a | b}") is False


def test_diagnose_still_reports_unclosed_jinja_tag() -> None:
    diagnostics = jinja_inspect.diagnose("{% if x %}")

    assert diagnostics.has_jinja is True
    assert diagnostics.ok is False


def test_diagnose_reports_line_and_span_for_invalid_template() -> None:
    text = "first line\nHello {{ name }"

    diagnostics = jinja_inspect.diagnose(text)

    assert diagnostics.has_jinja is True
    assert diagnostics.ok is False
    assert diagnostics.lineno == 2
    assert diagnostics.span is not None
    start, end = diagnostics.span
    assert text[start:end] in {"}", "{{"}
    assert diagnostics.message


def test_unknown_variables_respects_set_and_loop_targets() -> None:
    text = (
        "{{ root }} {{ missing }} "
        "{% set local = 1 %}{{ local }} "
        "{% for item in items %}{{ item }}{% endfor %}"
    )

    unknown = jinja_inspect.unknown_variables(text, {"root", "items"})

    assert unknown == ["missing"]


def test_reserved_globals_are_known_when_runtime_value_is_unresolved(
    monkeypatch,
) -> None:
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)

    assert get_global_template_vars() == {}
    from sase.xprompt.jinja_inspect import _default_known_context

    assert "root" in _default_known_context()
    assert jinja_inspect.inspect_template("Path is {{ root }}").unknown_variables == ()


def test_inspect_template_ignores_disabled_regions_for_validation() -> None:
    text = (
        "%xprompts_enabled:false\n"
        "{{ missing }}\n"
        "{% bad %}\n"
        "{{}}\n"
        "%xprompts_enabled:true\n"
    )

    diagnostics = jinja_inspect.inspect_template(text, known=set())

    assert diagnostics.has_jinja is False
    assert diagnostics.ok is True
    assert diagnostics.unknown_variables == ()
    assert jinja_inspect.unknown_variables(text, set()) == []


def test_inspect_template_still_validates_live_jinja() -> None:
    text = (
        "{{ known }}\n"
        "%xprompts_enabled:false\n"
        "{{ missing }}\n"
        "{% bad %}\n"
        "%xprompts_enabled:true\n"
    )

    diagnostics = jinja_inspect.inspect_template(text, known={"known"})

    assert diagnostics.has_jinja is True
    assert diagnostics.ok is True
    assert diagnostics.unknown_variables == ()


def test_engine_completion_inside_unclosed_tag() -> None:
    text = "Hello {{ ro"
    completion = jinja_assist.jinja_completion(
        text, len(text), jinja_assist.JinjaScope(kind="prompt", frontmatter=None)
    )

    assert completion is not None
    assert completion.prefix == "ro"
    assert any(item.name == "root" for item in completion.items)


def test_engine_completion_inside_wait_namespace() -> None:
    text = "Hello {{ wait.art }}"
    completion = jinja_assist.jinja_completion(
        text,
        len("Hello {{ wait.art"),
        jinja_assist.JinjaScope(kind="prompt", frontmatter=None),
    )

    assert completion is not None
    assert completion.prefix == "art"
    assert any(item.name == "artifacts" for item in completion.items)


def test_matching_delimiters_returns_pair_around_cursor() -> None:
    text = "Hello {{ root }}"
    cursor = text.index("root") + 1

    spans = jinja_inspect.matching_delimiter_spans(text, cursor)

    assert tuple(text[start:end] for start, end in spans) == ("{{", "}}")
