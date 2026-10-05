"""Runtime, LSP, and TUI agree on named macro input types."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from sase.ace.tui.widgets._file_completion_macro_args import (
    build_macro_arg_completion_candidates,
    build_macro_arg_model_completion_candidates,
)
from sase.ace.tui.widgets._macro_arg_assist_inputs import input_hint_from_input_arg
from sase.ace.tui.widgets.macro_arg_assist import (
    MacroAssistEntry,
    detect_macro_arg_completion_at_cursor,
)
from sase.macro._exceptions import MacroArgumentError, MacroError
from sase.macro._model_completion_entry import ModelCompletionEntry
from sase.macro import highlight
from sase.macro.input_binding import bind_input_args
from sase.macro.loader import load_macro_from_file
from sase.macro.models import Macro
from sase.macro.plugin_input_types import _clear_plugin_input_type_registry_cache
from sase.macro.processor import (
    expand_single_macro,
    process_macro_references_with_catalog,
)
from tests._macro_directive_completion_parity_lsp import LspSession

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "macro_named_input_types.md"
)
_PLUGIN_MANIFEST = """\
    schema_version: 1
    types:
      audio_edition:
        description: Narration length for guide-backed audio editions.
        choices:
          - { value: brief, description: About 4 minutes }
          - { value: full, label: Full edition, description: About 16 minutes }
    """
_MODEL_SNAPSHOT = {
    "schema_version": 1,
    "providers": ["claude", "codex", "fakey"],
    "models": {"opus": "claude", "fakey-large": "fakey"},
    "aliases": ["large"],
    "effort_levels": [
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ],
}
_ACCEPTED = {
    "env": "staging",
    "model": "opus",
    "effort": "high",
    "edition": "brief",
}
_REJECTED = {
    "env": "staing",
    "model": "opsu",
    "effort": "hig",
    "edition": "breif",
}
_SUGGESTIONS = {
    "env": "staging",
    "model": "opus",
    "effort": "high",
    "edition": "brief",
}


@pytest.fixture(autouse=True)
def _clear_plugin_cache() -> None:
    _clear_plugin_input_type_registry_cache()
    yield
    _clear_plugin_input_type_registry_cache()


@pytest.fixture
def plugin_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[dict[str, str]]:
    manifest = tmp_path / "input_types.yml"
    manifest.write_text(textwrap.dedent(_PLUGIN_MANIFEST), encoding="utf-8")
    files = [
        {
            "distribution": "sase-research-artifacts",
            "module": "fake_plugin",
            "path": str(manifest),
        }
    ]
    monkeypatch.setattr(
        "sase.main.plugin_discovery.discover_macro_plugin_input_type_files",
        lambda *, accept_legacy=None: list(files),
    )
    monkeypatch.setattr(
        "sase.main.plugin_discovery.discover_macro_plugin_distributions",
        lambda *, accept_legacy=None: ["sase-research-artifacts"],
    )
    _clear_plugin_input_type_registry_cache()
    return files


@pytest.fixture
def model_snapshot(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setattr(
        "sase.llm_provider.model_validity.model_validity_snapshot",
        lambda *, use_cache=True: dict(_MODEL_SNAPSHOT),
    )
    return _MODEL_SNAPSHOT


@pytest.fixture
def parity_macro(
    plugin_files: list[dict[str, str]], model_snapshot: dict[str, object]
) -> Macro:
    del plugin_files, model_snapshot
    loaded = load_macro_from_file(_FIXTURE)
    assert loaded is not None
    return loaded


def _assist_entry(macro: Macro) -> MacroAssistEntry:
    hints = []
    for inp in macro.inputs:
        hint = input_hint_from_input_arg(inp, len(hints))
        if hint is not None:
            hints.append(hint)
    return MacroAssistEntry(
        name=macro.name,
        insertion=f"#{macro.name}",
        reference_prefix="#",
        kind="macro",
        input_signature=None,
        inputs=tuple(hints),
        content_preview=None,
    )


def _model_entries() -> tuple[ModelCompletionEntry, ...]:
    return (
        ModelCompletionEntry(
            value="opus",
            display="opus",
            description="Claude (opus)",
            provider="claude",
            provider_display="Claude",
            aliases=("opus",),
        ),
        ModelCompletionEntry(
            value="@large",
            display="@large",
            description="Large model alias",
            kind="implicit_alias",
            alias_kind="role",
            target_provider="claude",
            target_model="opus",
            target_effort="high",
        ),
    )


def _lsp_model_catalog() -> dict[str, object]:
    return {
        "schema_version": 1,
        "entries": [
            {
                "value": "opus",
                "display": "opus",
                "description": "Claude (opus)",
                "kind": "model",
                "provider": "claude",
                "aliases": ["opus"],
            },
            {
                "value": "@large",
                "display": "@large",
                "description": "Large model alias",
                "kind": "implicit_alias",
                "aliases": ["large"],
                "alias_kind": "role",
                "target_provider": "claude",
                "target_model": "opus",
                "target_effort": "high",
            },
        ],
        "routing": _MODEL_SNAPSHOT,
    }


def _diagnostic_codes(diagnostics: list[dict[str, object]]) -> set[str]:
    codes: set[str] = set()
    for item in diagnostics:
        code = item.get("code")
        if isinstance(code, dict):
            value = code.get("value")
            if value is not None:
                codes.add(str(value))
        elif code is not None:
            codes.add(str(code))
    return codes


def test_fixture_declares_enum_effort_model_and_plugin_type(
    parity_macro: Macro,
) -> None:
    by_name = {inp.name: inp for inp in parity_macro.inputs}
    assert set(by_name) == {"env", "model", "effort", "edition"}

    assert by_name["env"].type.value == "enum"
    assert [choice.value for choice in by_name["env"].choices] == ["staging", "prod"]

    assert by_name["model"].named_type == "model"
    assert by_name["model"].value_role == "model"

    assert by_name["effort"].named_type == "effort"
    assert by_name["effort"].type.value == "enum"
    assert [choice.value for choice in by_name["effort"].choices] == list(
        _MODEL_SNAPSHOT["effort_levels"]
    )

    assert by_name["edition"].named_type == "sase-research-artifacts@audio_edition"
    assert by_name["edition"].type.value == "enum"
    assert [choice.value for choice in by_name["edition"].choices] == ["brief", "full"]


def test_runtime_binder_accepts_and_rejects_the_same_values(
    parity_macro: Macro,
) -> None:
    bound = bind_input_args(parity_macro.inputs, [], dict(_ACCEPTED))
    for name, value in _ACCEPTED.items():
        assert bound.values[name] == value

    rendered = expand_single_macro(parity_macro, [], dict(_ACCEPTED))
    assert "env=staging" in rendered
    assert "model=opus" in rendered
    assert "effort=high" in rendered
    assert "edition=brief" in rendered

    catalog = {parity_macro.name: parity_macro}
    process_macro_references_with_catalog(
        "#parity(env=prod, model=@large, effort=max, edition=full)",
        catalog,
        raise_on_error=True,
    )

    for name, value in _REJECTED.items():
        suggestion = _SUGGESTIONS[name]
        with pytest.raises(MacroArgumentError, match=rf"did you mean `{suggestion}`"):
            expand_single_macro(parity_macro, [], {name: value})
        with pytest.raises(MacroError, match=rf"did you mean `{suggestion}`"):
            process_macro_references_with_catalog(
                f"#parity({name}={value})",
                catalog,
                raise_on_error=True,
            )


def test_tui_candidates_accept_and_reject_the_same_values(parity_macro: Macro) -> None:
    entry = _assist_entry(parity_macro)
    entries = [entry]
    model_entries = _model_entries()

    for name, accepted in _ACCEPTED.items():
        prompt = f"#parity({name}="
        ctx = detect_macro_arg_completion_at_cursor(prompt, len(prompt), entries)
        assert ctx is not None, name
        assert ctx.active_input is not None
        assert ctx.active_input.name == name
        if name == "model":
            assert ctx.completion_kind == "macro_arg_model"
            candidates, _shared = build_macro_arg_model_completion_candidates(
                ctx, entries=model_entries
            )
        else:
            assert ctx.completion_kind == "macro_arg_value"
            candidates, _shared = build_macro_arg_completion_candidates(ctx)
        names = {candidate.name for candidate in candidates}
        assert accepted in names, (name, names)
        assert _REJECTED[name] not in names, (name, names)


def test_lsp_diagnostics_accept_and_reject_the_same_values(
    tmp_path: Path, parity_macro: Macro
) -> None:
    entry = _assist_entry(parity_macro)
    catalog = [highlight._macro_arg_assist_entry_to_wire(entry)]
    valid = "#parity(env=staging, model=opus, effort=high, edition=brief)"
    with LspSession(
        tmp_path,
        macro_catalog=catalog,
        model_catalog=_lsp_model_catalog(),
    ) as session:
        session.complete("#par")
        valid_diagnostics = session.published_diagnostics(valid)
        valid_codes = _diagnostic_codes(valid_diagnostics)
        assert "invalid_macro_arg_choice" not in valid_codes
        assert "invalid_macro_arg_model" not in valid_codes

        for name, value in _REJECTED.items():
            text = f"#parity({name}={value})"
            expected = (
                "invalid_macro_arg_model"
                if name == "model"
                else "invalid_macro_arg_choice"
            )
            diagnostics = session.published_diagnostics(
                text, expected_codes=frozenset({expected})
            )
            assert expected in _diagnostic_codes(diagnostics), (name, diagnostics)
            suggestion = _SUGGESTIONS[name]
            messages = " ".join(str(item.get("message", "")) for item in diagnostics)
            assert f"did you mean `{suggestion}`" in messages, (name, messages)
