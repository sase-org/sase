"""Nested Jinja output stays data without corrupting prompts or trace evidence."""

from __future__ import annotations

from itertools import count
from pathlib import Path
from unittest.mock import patch

import pytest

from sase import file_references
from sase.agent._macro_swarm_rendering import render_macro_swarm
from sase.llm_provider.preprocessing import preprocess_prompt_early
from sase.macro._exceptions import MacroArgumentError
from sase.macro._jinja import _render_jinja2_template
from sase.macro._trace import ExpansionTrace
from sase.macro.cmdsub_source import (
    CmdsubProvenance,
    GeneratedTextGuard,
    GeneratedTextLeakError,
    PromptTextKind,
    assert_no_generated_text_residue,
    generated_provenance,
    _interpolation_markers,
)
from sase.macro.models import InputArg, InputType, Macro
from sase.macro.processor import process_macro_references_with_catalog
from sase.macro.source_render import render_source_template
from tests._macro_swarm_helpers import expand_macro_swarms, patch_catalog, xp


def _human() -> CmdsubProvenance:
    return CmdsubProvenance(PromptTextKind.HUMAN_SOURCE, "human")


def _catalog(*macros: Macro) -> dict[str, Macro]:
    return {macro.name: macro for macro in macros}


@pytest.fixture
def counting_executor(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = file_references.execute_cmd_cached

    def counting(cmd: str) -> tuple[str | None, bool]:
        calls.append(cmd)
        return real(cmd)

    monkeypatch.setattr(file_references, "execute_cmd_cached", counting)
    return calls


@pytest.mark.parametrize("renderer", ["macro", "source"])
@pytest.mark.parametrize(
    ("template", "expected"),
    [
        (
            '{% macro t() %}{{ "```text" }}\na.md\n{{ "```" }}{% endmacro %}{{ t() }}',
            "```text\na.md\n```",
        ),
        ('{% set y %}{{ "a" }}-{{ "b" }}{% endset %}[{{ y }}]', "[a-b]"),
        (
            "{% macro w() %}<{{ caller() }}>{% endmacro %}"
            '{% call w() %}{{ "in" }}{% endcall %}',
            "<in>",
        ),
        ('{% filter upper %}{{ "q" }}{% endfilter %}', "Q"),
        ('{% macro t() %}{{ "a" }}{% endmacro %}{{ t() | upper }}', "A"),
        ('{% filter lower %}{{ "Q" }}{% endfilter %}', "q"),
        ('{% filter title %}{{ " hello world" }}{% endfilter %}', " Hello World"),
    ],
)
def test_nested_markers_round_trip(renderer: str, template: str, expected: str) -> None:
    guard = GeneratedTextGuard()
    if renderer == "macro":
        rendered = _render_jinja2_template(template, [], {}, "nested", guard=guard)
    else:
        rendered = render_source_template(
            template, {}, provenance=generated_provenance(), guard=guard
        )
    result = guard.unwrap(rendered)
    assert result == expected
    assert "\x00" not in result


@pytest.mark.parametrize("image", [True, False])
def test_nested_tree_preserves_swarm_segments(image: bool) -> None:
    swarm = xp(
        "sw",
        '{%- macro tree(files) -%}{{ "```text" }}\n'
        '{% for file in files %}{{ file }}\n{% endfor %}{{ "```" }}'
        "{%- endmacro -%}\n"
        'lead\n{{ tree(["a.md", "b.md"]) }}\n'
        "---\n%if(should_run={{ img }})\nimage\n"
        "---\n%if(should_run={{ img }})\nlinker",
        inputs=[InputArg(name="img", type=InputType.BOOL, default=True)],
    )
    with patch_catalog(_catalog(swarm)):
        segments = expand_macro_swarms(["#!sw" if image else "#!sw(img=false)"])
    assert segments == [
        "lead\n```text\na.md\nb.md\n```",
        *(["image", "linker"] if image else []),
    ]
    assert all("\x00" not in segment for segment in segments)


def _word_catalog() -> dict[str, Macro]:
    return _catalog(
        Macro(
            name="gen",
            content='{% for s in ["cdx", "cld"] %}#typed(suffix={{ s }}) {% endfor %}',
        ),
        Macro(
            name="typed",
            inputs=[InputArg(name="suffix", type=InputType.WORD)],
            content="T[{{ suffix }}]",
        ),
    )


@pytest.mark.parametrize("early", [False, True])
def test_interpolated_word_arguments(early: bool) -> None:
    catalog = _word_catalog()
    if early:
        with patch("sase.macro.processor.get_all_macros", return_value=catalog):
            result = preprocess_prompt_early("#gen").prompt
    else:
        result = process_macro_references_with_catalog(
            "#gen", catalog, aliases_resolved=True, raise_on_error=True
        )
    assert result == "T[cdx] T[cld] "


@pytest.mark.parametrize(
    ("call", "input_type", "body", "expected"),
    [
        ("#typed({{ 3 }})", InputType.INT, "N={{ value + 1 }}", "N=4"),
        (
            "#typed(value={{ 'cdx' }})",
            InputType.WORD,
            "{% if value == 'cdx' %}YES{% else %}NO{% endif %}",
            "YES",
        ),
        *[
            (
                f'#typed(value={{{{ "{suffix}" }}}})',
                InputType.WORD,
                "{% if false %}UNUSED{% elif value and value != 'false' %}"
                "SUFFIX{% else %}NONE{% endif %}",
                expected,
            )
            for suffix, expected in [("cdx", "SUFFIX"), ("false", "NONE")]
        ],
    ],
)
def test_interpolated_arguments_reach_typed_jinja_logic(
    call: str, input_type: InputType, body: str, expected: str
) -> None:
    result = process_macro_references_with_catalog(
        "#outer",
        _catalog(
            Macro(name="outer", content=call),
            Macro(
                name="typed",
                inputs=[InputArg(name="value", type=input_type)],
                content=body,
            ),
        ),
        aliases_resolved=True,
        raise_on_error=True,
    )
    assert result == expected


def test_revealed_text_argument_never_executes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, counting_executor: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    result = process_macro_references_with_catalog(
        "#outer",
        _catalog(
            Macro(name="outer", content="#typed(v={{ data }})"),
            Macro(
                name="typed",
                inputs=[InputArg(name="v", type=InputType.TEXT)],
                content="{{ v }}",
            ),
        ),
        scope={"data": "$(touch marker)"},
        cmdsub_provenance=_human(),
        aliases_resolved=True,
        raise_on_error=True,
    )
    assert result == "$(touch marker)"
    assert counting_executor == []
    assert not (tmp_path / "marker").exists()


@pytest.mark.parametrize("kind", ["text", "repeatable", "code", "positional"])
def test_revealed_helper_scope_never_executes(
    kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    counting_executor: list[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    helper_body = {
        "text": "{{ v }}",
        "repeatable": "{{ v[0] }}",
        "code": "{{ v.source }}",
        "positional": "{{ _1 }}",
    }[kind]
    main = Macro(
        name="main",
        content="#_h",
        inputs=[]
        if kind == "positional"
        else [
            InputArg(
                name="v",
                type=InputType.CODE if kind == "code" else InputType.TEXT,
                repeatable=kind == "repeatable",
            )
        ],
        local_macros={"_h": Macro(name="_h", content=helper_body)},
    )
    result = process_macro_references_with_catalog(
        "#outer",
        _catalog(
            Macro(
                name="outer",
                content="#main({{ data }})"
                if kind in ("positional", "repeatable")
                else "#main(v={{ data }})",
            ),
            main,
            Macro(name="echo", content="{{ _1 }}"),
        ),
        scope={"data": "#echo($(touch helper-marker))"},
        cmdsub_provenance=_human(),
        aliases_resolved=True,
        raise_on_error=True,
    )
    assert result == "$(touch helper-marker)"
    assert counting_executor == []
    assert not (tmp_path / "helper-marker").exists()


@pytest.mark.parametrize("marker_index", [0, 1])
def test_orphan_marker_fails_loudly(marker_index: int) -> None:
    guard = GeneratedTextGuard()
    marker = _interpolation_markers(guard.nonce)[marker_index]
    with pytest.raises(GeneratedTextLeakError, match="unbalanced interpolation"):
        guard.hide_marked_spans(f"before {marker.upper()} after")


@pytest.mark.parametrize(
    "text",
    [
        "\x00SASEDATA_foreign_0\x00",
        "\x00SJSMARK_FOREIGN_S\x00",
        "\x00sjsmark_foreign_e\x00",
    ],
)
def test_residue_error_names_boundary_without_leaking_nonce(text: str) -> None:
    with pytest.raises(GeneratedTextLeakError) as exc:
        assert_no_generated_text_residue(text, boundary="test boundary")
    assert "test boundary" in str(exc.value)
    assert "invariant violation" in str(exc.value)
    assert "prompt was not launched" in str(exc.value)
    assert "foreign" not in str(exc.value).lower()


@pytest.mark.parametrize(
    "text", ["", "clean $(literal) text", "SJSMARK_not_a_marker", "ordinary\x00content"]
)
def test_clean_text_has_no_residue(text: str) -> None:
    assert_no_generated_text_residue(text, boundary="clean text")


def test_swarm_rejects_residue_before_splitting() -> None:
    with patch(
        "sase.agent._macro_swarm_rendering.expand_single_macro",
        return_value="lead\n---\n\x00SASEDATA_foreign_0\x00",
    ):
        with pytest.raises(GeneratedTextLeakError, match="macro swarm #sw"):
            render_macro_swarm(xp("sw", "unused"), [], {}, count())


def test_preprocessing_rejects_foreign_residue() -> None:
    with pytest.raises(GeneratedTextLeakError, match="prompt preprocessing"):
        preprocess_prompt_early("\x00SASEDATA_foreign_0\x00")


def test_template_marker_failure_retains_macro_context() -> None:
    guard = GeneratedTextGuard()
    with pytest.raises(
        MacroArgumentError, match="Macro '#broken' template error"
    ) as exc:
        _render_jinja2_template(
            _interpolation_markers(guard.nonce)[0], [], {}, "broken", guard=guard
        )
    assert isinstance(exc.value.__cause__, GeneratedTextLeakError)


@pytest.mark.parametrize("named", [False, True])
def test_trace_evidence_is_unwrapped(named: bool) -> None:
    trace = ExpansionTrace()
    result = process_macro_references_with_catalog(
        "#outer",
        _catalog(
            Macro(
                name="outer",
                content="#g(who={{ 'world' }})" if named else "#g({{ 'world' }})",
            ),
            Macro(
                name="g",
                inputs=[InputArg(name="who", type=InputType.WORD)],
                content="Hello {{ who }}",
            ),
        ),
        aliases_resolved=True,
        raise_on_error=True,
        trace=trace,
    )
    assert result == "Hello world"
    for record in trace.records:
        assert all(
            "\x00" not in text
            for text in [
                record.expanded_text,
                *record.positional_args,
                *record.named_args.values(),
            ]
        )
    record = next(record for record in trace.records if record.name == "g")
    assert record.named_args == ({"who": "world"} if named else {})
    assert record.positional_args == ([] if named else ["world"])
