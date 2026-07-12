"""Tests for top-level prompt Jinja2 inspection helpers."""

from __future__ import annotations

from sase.xprompt import jinja_inspect
from sase.xprompt._jinja import get_global_template_vars


def test_builtin_runtime_names_contains_agent_run_context() -> None:
    names = jinja_inspect.builtin_runtime_names()

    assert names >= {
        "cl_name",
        "workspace_num",
        "n",
        "N",
        "wait_chats",
        "agents",
    }
    assert "__sase_workflow_inherited_vcs_tag" not in names


def test_inspect_template_accepts_builtin_runtime_names() -> None:
    known = (
        jinja_inspect.known_toplevel_context() | jinja_inspect.builtin_runtime_names()
    )

    diagnostics = jinja_inspect.inspect_template(
        "{{ wait_chats }} {{ agents }}",
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
    assert "root" in jinja_inspect.known_toplevel_context()
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


def test_completion_context_inside_unclosed_tag() -> None:
    text = "Hello {{ ro"
    ctx = jinja_inspect.completion_context(text, len(text))

    assert ctx is not None
    assert ctx.prefix == "ro"
    assert text[ctx.replacement_start : ctx.replacement_end] == "ro"
    assert ctx.tag_kind == "variable"


def test_matching_delimiters_returns_pair_around_cursor() -> None:
    text = "Hello {{ root }}"
    cursor = text.index("root") + 1

    spans = jinja_inspect.matching_delimiter_spans(text, cursor)

    assert tuple(text[start:end] for start, end in spans) == ("{{", "}}")
