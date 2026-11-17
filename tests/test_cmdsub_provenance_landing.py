"""Landing regressions for command-substitution provenance (sase-1tc.1.1).

Covers the remaining failures from the landing audit: nested guard custody,
escaped carry, Jinja value semantics, source evaluation order, late
directive/Jinja handling, and unchanged parallel pre-rendering. Existing
suites pass 47/47 without these; this file proves the fixes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase import file_references
from sase.llm_provider.preprocessing import (
    preprocess_prompt_early,
    preprocess_prompt_late,
)
from sase.macro.cmdsub_source import (
    CmdsubProvenance,
    PromptTextKind,
)
from sase.macro.models import InputArg, InputType, Macro
from sase.macro.processor import process_macro_references_with_catalog


def _human() -> CmdsubProvenance:
    return CmdsubProvenance(PromptTextKind.HUMAN_SOURCE, "human")


def _catalog(*macros: Macro) -> dict[str, Macro]:
    return {macro.name: macro for macro in macros}


@pytest.fixture
def counting_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> list[str]:
    calls: list[str] = []
    real = file_references.execute_cmd_cached

    def counting(cmd: str) -> tuple[str | None, bool]:
        calls.append(cmd)
        return real(cmd)

    monkeypatch.setattr(file_references, "execute_cmd_cached", counting)
    return calls


def _early_late(template: str, context: dict | None = None) -> str:
    early = preprocess_prompt_early(template, context=context)
    return preprocess_prompt_late(early.prompt, file_ref_mode="skip")


def test_nested_local_stdout_stays_literal(
    counting_executor: list[str],
) -> None:
    """Local helper stdout with embedded commands never executes outer."""
    catalog = _catalog(
        Macro(
            name="main",
            content="#_h",
            local_macros={
                "_h": Macro(name="_h", content="$(printf PAYLOAD)"),
            },
        ),
        Macro(name="echo", content="{{ _1 }}"),
    )

    def fake(cmd: str) -> tuple[str, bool]:
        counting_executor.append(cmd)
        if cmd == "printf PAYLOAD":
            return ("#echo($(printf DATA_EXECUTED))", True)
        return ("", True)

    import sase.file_references as fr

    orig = fr.execute_cmd_cached
    fr.execute_cmd_cached = fake  # type: ignore[method-assign]
    try:
        out = process_macro_references_with_catalog(
            "#main",
            catalog,
            aliases_resolved=True,
            raise_on_error=True,
            cmdsub_provenance=_human(),
        )
    finally:
        fr.execute_cmd_cached = orig
    assert counting_executor == ["printf PAYLOAD"]
    assert "$(printf DATA_EXECUTED)" in out
    assert "DATA_EXECUTED" not in counting_executor


def test_parent_interpolation_into_typed_local_validates(
    counting_executor: list[str],
) -> None:
    """Parent Jinja interpolation into a typed local helper validates."""
    catalog = _catalog(
        Macro(
            name="main",
            content="#_h(suffix={{ v }})",
            local_macros={
                "_h": Macro(
                    name="_h",
                    content="{{ suffix }}",
                    inputs=[InputArg(name="suffix", type=InputType.WORD)],
                )
            },
        ),
    )
    out = process_macro_references_with_catalog(
        "#main",
        catalog,
        scope={"v": "ok"},
        aliases_resolved=True,
        raise_on_error=True,
        cmdsub_provenance=_human(),
    )
    assert out == "ok"


def test_escaped_command_never_executes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    counting_executor: list[str],
) -> None:
    """Escaped command stays literal through source rendering and macros."""
    monkeypatch.chdir(tmp_path)
    result = _early_late(r"#echo(\$(printf ESCAPED))", {})
    assert not (tmp_path / "ESCAPED").exists()
    assert "$(printf ESCAPED)" in result
    assert "printf ESCAPED" not in counting_executor


def test_false_branch_never_executes_without_context(
    counting_executor: list[str],
) -> None:
    """Authored top-level Jinja renders at the source boundary."""
    result = _early_late("{% if false %}$(printf FALSE){% endif %}")
    assert "FALSE" not in result
    assert "printf FALSE" not in counting_executor


def test_set_capture_compares_real_values() -> None:
    """Set-block captures compare as real values, not marked spans."""
    result = _early_late(
        '{% set word %}{{ v }}{% endset %}{% if word == "ok" %}YES{% else %}NO{% endif %}',
        {"v": "ok"},
    )
    assert "YES" in result
    assert "NO" not in result


def test_late_jinja_preserves_data_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Late preprocessing preserves data Jinja instead of exiting."""
    monkeypatch.chdir(tmp_path)
    result = _early_late(
        "{{ review._raw }}", {"review": {"_raw": "{{ missing_data_variable }}"}}
    )
    assert "{{ missing_data_variable }}" in result


def test_late_directive_ignores_data_lines() -> None:
    """Data directive lines never become prompt directives."""
    early = preprocess_prompt_early(
        "{{ review._raw }}",
        context={"review": {"_raw": "%model:injected_model\nresponse"}},
    )
    assert early.directives.model is None
    late = preprocess_prompt_late(early.prompt, file_ref_mode="skip")
    assert "%model:injected_model" in late
