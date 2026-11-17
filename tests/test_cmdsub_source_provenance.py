"""Source-aware command substitution: preprocessing provenance (sase-1tc.1.1.2).

Proves generated data never reaches either command execution pass (the
early source boundary and macro argument/definition boundaries) while
authorized source commands still execute in human launches.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sase import file_references
from sase.llm_provider.preprocessing import (
    preprocess_prompt_early,
    preprocess_prompt_late,
)
from sase.macro.cmdsub_source import (
    CmdsubProvenance,
    GeneratedTextGuard,
    PromptTextKind,
    execute_eligible_commands,
    generated_provenance,
    _plan_source_commands,
    _resolve_launch_authorship,
    resolve_provenance,
)
from sase.macro.models import InputArg, InputType, Macro
from sase.macro.processor import process_macro_references_with_catalog


def _human() -> CmdsubProvenance:
    return CmdsubProvenance(PromptTextKind.HUMAN_SOURCE, "human")


def _agent() -> CmdsubProvenance:
    return CmdsubProvenance(PromptTextKind.HUMAN_SOURCE, "agent")


def _catalog(*macros: Macro) -> dict[str, Macro]:
    return {macro.name: macro for macro in macros}


@pytest.fixture
def counting_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    """Count real command executions, wrapping the cached executor."""
    calls: list[str] = []
    real = file_references.execute_cmd_cached

    def counting(cmd: str) -> tuple[str | None, bool]:
        calls.append(cmd)
        return real(cmd)

    monkeypatch.setattr(file_references, "execute_cmd_cached", counting)
    return calls


def _early_late(
    template: str,
    context: dict | None = None,
) -> str:
    """Run the early source boundary plus the late phase (no file refs)."""
    early = preprocess_prompt_early(template, context=context)
    return preprocess_prompt_late(early.prompt, file_ref_mode="skip")


# --- Unsafe context channels stay data -------------------------------------


def test_interpolated_model_channels_never_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The four unsafe channels plus _raw/_response stay literal, twice over."""
    monkeypatch.chdir(tmp_path)
    context = {
        "review": {
            "summary": "$(touch field-marker)",
            "_data": "$(touch data-marker)",
            "_raw": "$(touch raw-marker)",
            "_response": "$(touch response-marker)",
        },
        "loop_step": "$(touch join-marker)",
        "setup": {"branch_name": "topic/$(touch branch-marker)"},
    }
    template = (
        "summary={{ review.summary }} data={{ review._data }} "
        "raw={{ review._raw }} response={{ review._response }} "
        "join={{ loop_step }} branch={{ setup.branch_name }} "
        "again={{ review.summary }}"
    )
    early = preprocess_prompt_early(template, context=context)
    result = preprocess_prompt_late(early.prompt, file_ref_mode="skip")

    for marker in (
        "field-marker",
        "data-marker",
        "raw-marker",
        "response-marker",
        "join-marker",
        "branch-marker",
    ):
        assert not (tmp_path / marker).exists()
        assert f"$(touch {marker})" in result
    # Repeated interpolation renders once per site, before formatting.
    assert early.prompt.count("$(touch field-marker)") == 2


def test_nested_containers_stay_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Commands nested in mappings, lists, and joins never execute."""
    monkeypatch.chdir(tmp_path)
    context = {
        "nested": {"deep": {"cmd": "$(touch nested-marker)"}},
        "items": ["a", "$(touch list-marker)"],
    }
    template = "deep={{ nested.deep.cmd }} joined={{ items | join(', ') }}"
    result = _early_late(template, context)

    assert not (tmp_path / "nested-marker").exists()
    assert not (tmp_path / "list-marker").exists()
    assert "$(touch nested-marker)" in result
    assert "$(touch list-marker)" in result


def test_human_literal_command_beside_malicious_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A human literal executes next to an interpolated malicious value."""
    monkeypatch.chdir(tmp_path)
    result = _early_late(
        "human $(touch human-marker) data={{ payload }}",
        {"payload": "$(touch data-marker)"},
    )

    assert (tmp_path / "human-marker").exists()
    assert not (tmp_path / "data-marker").exists()
    assert "$(touch data-marker)" in result


# --- Jinja sees typed values; only evaluated literals execute --------------


def test_jinja_conditionals_see_typed_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The _raw conditional takes the true branch; the false command is gone."""
    monkeypatch.chdir(tmp_path)
    template = (
        '{% if "LGTM" in review._raw %}ship $(touch taken-marker)'
        "{% else %}hold{% endif %}"
    )
    result = _early_late(template, {"review": {"_raw": "LGTM, ship it"}})

    assert (tmp_path / "taken-marker").exists()
    assert "ship" in result


def test_jinja_false_branch_command_never_renders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A command in a false Jinja branch never renders and never executes."""
    monkeypatch.chdir(tmp_path)
    template = (
        '{% if "LGTM" in review._raw %}ship'
        "{% else %}hold $(touch else-marker){% endif %}"
    )
    result = _early_late(template, {"review": {"_raw": "LGTM, ship it"}})

    assert not (tmp_path / "else-marker").exists()
    assert "$(touch else-marker)" not in result
    assert "ship" in result


def test_jinja_filters_transform_data_without_executing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transforming filters apply to data; the result stays literal."""
    monkeypatch.chdir(tmp_path)
    result = _early_late("label={{ label | upper }}", {"label": "x$(touch f)"})

    assert not (tmp_path / "f").exists()
    assert "X$(TOUCH F)" in result


def test_jinja_comparisons_and_loops_keep_working(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real comparisons and loops render; loop data stays literal."""
    monkeypatch.chdir(tmp_path)
    template = (
        "{% if count > 2 %}many{% else %}few{% endif %}"
        ":{% for item in items %}[{{ item }}]{% endfor %}"
    )
    context = {"count": 5, "items": ["a", "$(touch loop-marker)"]}
    result = _early_late(template, context)

    assert "many" in result
    assert "[a]" in result
    assert not (tmp_path / "loop-marker").exists()
    assert "$(touch loop-marker)" in result


# --- Literal zones, escapes, and stdout ------------------------------------


def test_escaped_command_stays_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An escaped command is restored to literal text, never executed."""
    monkeypatch.chdir(tmp_path)
    result = _early_late("literal \\$(touch escaped-marker) here")

    assert not (tmp_path / "escaped-marker").exists()
    assert "$(touch escaped-marker)" in result


def test_fenced_block_in_rendered_template_stays_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fences in the source template protect commands through rendering."""
    monkeypatch.chdir(tmp_path)
    template = "```\n$(touch fence-marker)\n```\nrun $(touch fence-go-marker) {{ val }}"
    result = _early_late(template, {"val": "V"})

    assert (tmp_path / "fence-go-marker").exists()
    assert not (tmp_path / "fence-marker").exists()
    assert "$(touch fence-marker)" in result


def test_disabled_region_in_source_stays_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disabled regions in source protect commands; the rest executes."""
    monkeypatch.chdir(tmp_path)
    template = (
        "%macros_enabled:false\n$(touch disabled-marker)\n%macros_enabled:true\n"
        "go $(touch disabled-go-marker)"
    )
    result = _early_late(template)

    assert (tmp_path / "disabled-go-marker").exists()
    assert not (tmp_path / "disabled-marker").exists()
    assert "$(touch disabled-marker)" in result


def test_command_stdout_containing_cmdsub_stays_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacement text is never rescanned for commands."""
    monkeypatch.chdir(tmp_path)
    result = _early_late("out: $(printf '%s' '$(touch nested-marker)')")

    assert not (tmp_path / "nested-marker").exists()
    assert "$(touch nested-marker)" in result


# --- Macro argument and definition boundaries -------------------------------


def test_macro_positional_and_named_args_execute_for_human(
    counting_executor: list[str],
) -> None:
    """Human source macro arguments resolve through the executor."""
    macro = Macro(
        name="cmd_sub",
        content="{{ _1 }} {{ id }}",
        inputs=[
            InputArg(name="value", type=InputType.TEXT),
            InputArg(name="id", type=InputType.TEXT),
        ],
    )
    catalog = _catalog(macro)
    result = process_macro_references_with_catalog(
        "#cmd_sub($(printf POSITIONAL), id=$(printf NAMED))",
        catalog,
        aliases_resolved=True,
        raise_on_error=True,
    )

    assert result == "POSITIONAL NAMED"
    assert sorted(counting_executor) == ["printf NAMED", "printf POSITIONAL"]


def test_macro_args_do_not_execute_for_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent launches expand macros but resolve no argument commands."""
    monkeypatch.chdir(tmp_path)
    macro = Macro(name="echo", content="{{ _1 }}")
    result = process_macro_references_with_catalog(
        "#echo($(touch agent-arg-marker))",
        _catalog(macro),
        aliases_resolved=True,
        raise_on_error=True,
        cmdsub_provenance=_agent(),
    )

    assert not (tmp_path / "agent-arg-marker").exists()
    assert "$(touch agent-arg-marker)" in result


def test_macro_shorthand_args_execute_for_human(
    counting_executor: list[str],
) -> None:
    """Colon and double-colon shorthand arguments resolve like paren args."""
    macro = Macro(name="echo", content="{{ _1 }}")
    catalog = _catalog(macro)

    assert (
        process_macro_references_with_catalog(
            "#echo:$(printf SHORTHAND)",
            catalog,
            aliases_resolved=True,
            raise_on_error=True,
        )
        == "SHORTHAND"
    )
    assert (
        process_macro_references_with_catalog(
            "#echo:: $(printf DBLCOLON)",
            catalog,
            aliases_resolved=True,
            raise_on_error=True,
        )
        == "DBLCOLON"
    )
    assert sorted(counting_executor) == ["printf DBLCOLON", "printf SHORTHAND"]


def test_macro_nested_args_execute_once(
    counting_executor: list[str],
) -> None:
    """A command in a nested macro reference executes exactly once."""
    catalog = _catalog(
        Macro(name="outer", content="{{ _1 }}"),
        Macro(name="inner", content="{{ _1 }}"),
    )
    result = process_macro_references_with_catalog(
        "#outer(#inner($(printf NESTED)))",
        catalog,
        aliases_resolved=True,
        raise_on_error=True,
    )

    assert result == "NESTED"
    assert counting_executor == ["printf NESTED"]


def test_macro_command_assembled_from_adjacent_data_stays_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A command assembled across an interpolation boundary stays literal."""
    from unittest.mock import patch

    monkeypatch.chdir(tmp_path)
    with patch(
        "sase.macro.processor.get_all_macros",
        return_value={"echo": Macro(name="echo", content="{{ _1 }}")},
    ):
        result = _early_late(
            "#echo({{ first }}{{ second }})",
            {"first": "$(touch", "second": " adj-marker)"},
        )

    assert not (tmp_path / "adj-marker").exists()
    assert "$(touch adj-marker)" in result


def test_rendered_combined_value_expands_macros_without_executing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rendered combined values still expand ordinary macros, literally."""
    monkeypatch.chdir(tmp_path)
    combined = "#echo($(touch combined-marker)) hello"
    result = process_macro_references_with_catalog(
        combined,
        _catalog(Macro(name="echo", content="{{ _1 }}")),
        aliases_resolved=True,
        raise_on_error=True,
        cmdsub_provenance=generated_provenance(),
    )

    assert not (tmp_path / "combined-marker").exists()
    assert result == "$(touch combined-marker) hello"


def test_admitted_definition_body_executes_for_human() -> None:
    """An admitted macro definition body executes at its own boundary."""
    macro = Macro(name="stamp", content="made $(printf STAMPED)")
    result = process_macro_references_with_catalog(
        "#stamp",
        _catalog(macro),
        aliases_resolved=True,
        raise_on_error=True,
    )

    assert result == "made STAMPED"


def test_admitted_definition_body_stays_literal_for_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent launches expand admitted definitions without executing."""
    monkeypatch.chdir(tmp_path)
    macro = Macro(name="stamp", content="made $(touch agent-body-marker)")
    result = process_macro_references_with_catalog(
        "#stamp",
        _catalog(macro),
        aliases_resolved=True,
        raise_on_error=True,
        cmdsub_provenance=_agent(),
    )

    assert not (tmp_path / "agent-body-marker").exists()
    assert result == "made $(touch agent-body-marker)"


def test_definition_command_assembled_from_data_arg_stays_literal() -> None:
    """A definition command spanning an argument boundary stays literal."""
    macro = Macro(name="wrap", content="run $(echo {{ _1 }})")
    result = process_macro_references_with_catalog(
        "#wrap($(printf DATAARG))",
        _catalog(macro),
        aliases_resolved=True,
        raise_on_error=True,
    )

    assert result == "run $(echo DATAARG)"


def test_if_segment_filter_runs_before_definition_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dropped %if segment never executes; a kept one does, once."""
    monkeypatch.chdir(tmp_path)
    macro = Macro(
        name="gated",
        content=(
            "kept $(touch kept-marker)\n"
            "---\n"
            "%if(should_run={{ flag }})\n"
            "conditional $(touch conditional-marker)\n"
        ),
    )
    catalog = _catalog(macro)

    taken = process_macro_references_with_catalog(
        "#gated",
        catalog,
        aliases_resolved=True,
        raise_on_error=True,
        scope={"flag": "true"},
        preserve_segment_separators=True,
    )
    assert (tmp_path / "kept-marker").exists()
    assert (tmp_path / "conditional-marker").exists()
    assert "conditional" in taken

    (tmp_path / "kept-marker").unlink()
    (tmp_path / "conditional-marker").unlink()
    # The cached executor would suppress re-execution of the same command
    # string; clear it so the dropped run genuinely re-plans its boundary.
    file_references._cmd_cache.clear()
    dropped = process_macro_references_with_catalog(
        "#gated",
        catalog,
        aliases_resolved=True,
        raise_on_error=True,
        scope={"flag": "false"},
        preserve_segment_separators=True,
    )
    assert (tmp_path / "kept-marker").exists()
    assert not (tmp_path / "conditional-marker").exists()
    assert "conditional" not in dropped


def test_local_helper_args_execute_for_human(
    counting_executor: list[str],
) -> None:
    """Local helper references resolve argument commands in human launches."""
    helper = Macro(name="_helper", content="H[{{ _1 }}]")
    main = Macro(
        name="greeter",
        content="#_helper($(printf LOCAL))",
        local_macros={"_helper": helper},
    )
    result = process_macro_references_with_catalog(
        "#greeter",
        _catalog(main),
        aliases_resolved=True,
        raise_on_error=True,
    )

    assert result == "H[LOCAL]"
    assert counting_executor == ["printf LOCAL"]


def test_local_helper_args_do_not_execute_for_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent launches expand local helpers without executing arguments."""
    monkeypatch.chdir(tmp_path)
    helper = Macro(name="_helper", content="H[{{ _1 }}]")
    main = Macro(
        name="greeter",
        content="#_helper($(touch agent-helper-marker))",
        local_macros={"_helper": helper},
    )
    result = process_macro_references_with_catalog(
        "#greeter",
        _catalog(main),
        aliases_resolved=True,
        raise_on_error=True,
        cmdsub_provenance=_agent(),
    )

    assert not (tmp_path / "agent-helper-marker").exists()
    assert "$(touch agent-helper-marker)" in result


# --- Repetition and concurrency --------------------------------------------


def test_repeated_preprocessing_with_carried_provenance_executes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, counting_executor: list[str]
) -> None:
    """Re-running the pipeline on its own output executes nothing new."""
    monkeypatch.chdir(tmp_path)
    source = "run $(touch once-marker) and {{ payload }}"

    early_first = preprocess_prompt_early(
        source, context={"payload": "$(touch derived-marker)"}
    )
    late_first = preprocess_prompt_late(early_first.prompt, file_ref_mode="skip")

    assert (tmp_path / "once-marker").exists()
    assert counting_executor.count("touch once-marker") == 1
    assert not (tmp_path / "derived-marker").exists()

    early_second = preprocess_prompt_early(
        late_first, provenance=early_first.provenance
    )
    late_second = preprocess_prompt_late(
        early_second.prompt,
        file_ref_mode="skip",
        provenance=early_second.provenance,
    )

    assert counting_executor.count("touch once-marker") == 1
    assert not (tmp_path / "derived-marker").exists()
    assert "$(touch derived-marker)" in late_second


def test_concurrent_boundaries_do_not_share_authorization(tmp_path: Path) -> None:
    """Explicit provenance keeps concurrent human/agent boundaries apart."""
    catalog = _catalog(Macro(name="echo", content="{{ _1 }}"))

    def human_task(index: int) -> bool:
        marker = tmp_path / f"conc-human-{index}.marker"
        out = process_macro_references_with_catalog(
            f"#echo($(touch {marker}))",
            catalog,
            aliases_resolved=True,
            raise_on_error=True,
            cmdsub_provenance=_human(),
        )
        return marker.exists() and "$(" not in out

    def agent_task(index: int) -> bool:
        marker = tmp_path / f"conc-agent-{index}.marker"
        out = process_macro_references_with_catalog(
            f"#echo($(touch {marker}))",
            catalog,
            aliases_resolved=True,
            raise_on_error=True,
            cmdsub_provenance=_agent(),
        )
        return (not marker.exists()) and f"$(touch {marker})" in out

    with ThreadPoolExecutor(max_workers=8) as executor:
        human_results = list(executor.map(human_task, range(4)))
        agent_results = list(executor.map(agent_task, range(4)))

    assert all(human_results)
    assert all(agent_results)


# --- Adapter and provenance units -------------------------------------------


def test_plan_refuses_generated_text_in_human_launch() -> None:
    """Generated text plans no replacements even in a human launch."""
    assert (
        _plan_source_commands(
            "run $(touch x)",
            provenance=CmdsubProvenance(PromptTextKind.GENERATED, "human"),
        )
        == []
    )


def test_plan_refuses_source_text_in_agent_launch() -> None:
    """Agent launches plan no replacements even for source text."""
    assert _plan_source_commands("run $(touch x)", provenance=_agent()) == []


def test_execute_eligible_commands_agent_returns_text_unchanged() -> None:
    """Ineligible text (escapes included) returns byte-identical."""
    text = "keep \\$(touch x) literal"
    assert execute_eligible_commands(text, provenance=_agent()) == text


def test_plan_reports_character_offsets_for_non_ascii_prefix() -> None:
    """Adapter offsets are str indexes even with multibyte prefixes."""
    text = "éé $(printf hi) end"
    (replacement,) = _plan_source_commands(text, provenance=_human())

    assert text[replacement.start : replacement.end] == "$(printf hi)"
    assert replacement.command == "printf hi"


def test_guard_unwrap_restores_only_known_tokens() -> None:
    """Unwrap restores minted tokens and leaves foreign text alone."""
    guard = GeneratedTextGuard()
    token = guard.wrap("hello")

    assert guard.unwrap(f"a {token} b") == "a hello b"
    assert guard.unwrap("no tokens here") == "no tokens here"
    assert guard.unwrap("\x00SASEDATA_other_0\x00") == "\x00SASEDATA_other_0\x00"


def test_resolve_launch_authorship_prefers_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit authorship wins; the stamp decides otherwise."""
    assert _resolve_launch_authorship("agent") == "agent"
    assert _resolve_launch_authorship("human") == "human"

    monkeypatch.setenv("SASE_PROMPT_AUTHORSHIP", "agent")
    assert _resolve_launch_authorship() == "agent"
    assert _resolve_launch_authorship(None) == "agent"

    monkeypatch.setenv("SASE_PROMPT_AUTHORSHIP", "bogus")
    assert _resolve_launch_authorship() == "agent"


def test_resolve_provenance_defaults_to_human_source() -> None:
    """Missing provenance presents the prompt as human source."""
    provenance = resolve_provenance(None)

    assert provenance.kind is PromptTextKind.HUMAN_SOURCE
    assert provenance.launch_authorship == "human"
    assert resolve_provenance(None, launch_authorship="agent").launch_authorship == (
        "agent"
    )
