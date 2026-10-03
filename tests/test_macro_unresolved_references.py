"""Tests for unresolved macro-reference diagnostics."""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from sase.macro._exceptions import MacroError
from sase.macro.models import InputArg, InputType, Macro
from sase.macro.processor import process_macro_references
from sase.macro.unresolved import (
    find_unresolved_reference_names,
    scan_query_for_unresolved_references,
)
from sase.macro.workflow_models import Workflow, WorkflowStep


def _workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="main", prompt_part="body")])


@pytest.fixture(autouse=True)
def _stable_unresolved_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.project_aliases.canonicalize_project_aliases_in_prompt",
        lambda prompt, *args, **kwargs: prompt,
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"macro_aliases": {}},
    )
    monkeypatch.setattr(
        "sase.workspace_provider.get_workflow_names",
        lambda: {"git"},
    )
    monkeypatch.setattr(
        "sase.workspace_provider.get_ref_patterns",
        lambda: {
            "git": re.compile(r"(?:^|(?<=\s))#git(?:[_:]([^\s]+)|\(([^)]*)\))"),
        },
    )
    monkeypatch.setattr(
        "sase.macro.loader.get_known_project_workspaces",
        lambda *args, **kwargs: {},
    )


def test_unknown_names_are_deduped_in_first_seen_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.macro.loader.get_all_prompts", lambda: {})

    assert find_unresolved_reference_names("#missing #other #missing") == (
        "missing",
        "other",
    )


def test_known_global_workflow_and_local_macro_are_not_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.macro.loader.get_all_prompts",
        lambda: {"review": _workflow("review"), "ship": _workflow("ship")},
    )
    local = {"_helper": Macro(name="_helper", content="local")}

    assert find_unresolved_reference_names(
        "#review #!ship #_helper #typo",
        extra_macros=local,
    ) == ("typo",)


def test_alias_resolved_name_is_not_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"macro_aliases": {"rvw": "review"}},
    )
    monkeypatch.setattr(
        "sase.macro.loader.get_all_prompts",
        lambda: {"review": _workflow("review")},
    )

    assert find_unresolved_reference_names("#rvw") == ()


def test_vcs_and_resume_references_are_not_flagged_but_removed_cd_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.macro.loader.get_all_prompts", lambda: {})

    removed_ref = "#" + "cd:/tmp"
    assert find_unresolved_reference_names(
        f"#git:sase {removed_ref} #fork #resume:abc"
    ) == ("cd",)


def test_fenced_disabled_numeric_and_midword_hashes_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.macro.loader.get_all_prompts", lambda: {})

    prompt = (
        "```\n#inside\n```\n"
        "%xprompts_enabled:false\n#disabled\n%xprompts_enabled:true\n"
        "#123 https://example.test/page#anchor #real"
    )

    assert find_unresolved_reference_names(prompt) == ("real",)


def test_scan_query_expands_local_macros_before_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.macro.loader.get_all_prompts", lambda: {})
    monkeypatch.setattr("sase.macro.processor.get_all_macros", lambda: {})

    query = "---\nxprompts:\n  _local: local body\n---\n#_local #missing"

    assert scan_query_for_unresolved_references(query) == ("missing",)


def test_scan_query_is_exception_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_query: str) -> object:
        raise SystemExit(2)

    monkeypatch.setattr("sase.agent.multi_prompt.parse_multi_prompt", fail)

    assert scan_query_for_unresolved_references("#missing") == ()


def _typed_failing_macro() -> Macro:
    return Macro(
        name="typed",
        content="{{ prompt }}",
        inputs=[
            InputArg(name="prompt", type=InputType.TEXT),
            InputArg(name="wait", type=InputType.WORD, default=None),
            InputArg(name="priority", type=InputType.INT, default=None),
        ],
    )


def test_scan_query_emits_nothing_when_expansion_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = _typed_failing_macro()
    monkeypatch.setattr(
        "sase.macro.loader.get_all_prompts",
        lambda: {"typed": failing},
    )
    monkeypatch.setattr(
        "sase.macro.processor.get_all_macros",
        lambda *args, **kwargs: {"typed": failing},
    )
    query = "#typed(hello, has spaces, 1, extra)"

    with patch("sase.macro.processor.print_status") as print_status:
        assert scan_query_for_unresolved_references(query) == ()

    print_status.assert_not_called()


def test_process_macro_references_raise_on_error_skips_print_and_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = _typed_failing_macro()
    monkeypatch.setattr(
        "sase.macro.processor.get_all_macros",
        lambda *args, **kwargs: {"typed": failing},
    )

    with patch("sase.macro.processor.print_status") as print_status:
        with pytest.raises(MacroError) as exc_info:
            process_macro_references(
                "#typed(hello, has spaces, 1, extra)",
                raise_on_error=True,
            )

    print_status.assert_not_called()
    message = str(exc_info.value)
    assert "XPrompt '#typed' argument error:" in message
    assert "received 4 positional arguments but declares 3 inputs" in message
    assert "surplus positional 2 bound to 'wait'" in message


def test_process_macro_references_default_still_prints_and_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = _typed_failing_macro()
    monkeypatch.setattr(
        "sase.macro.processor.get_all_macros",
        lambda *args, **kwargs: {"typed": failing},
    )

    with patch("sase.macro.processor.print_status") as print_status:
        with pytest.raises(SystemExit):
            process_macro_references("#typed(hello, has spaces, 1, extra)")

    print_status.assert_called_once()
    printed = print_status.call_args.args[0]
    assert "XPrompt '#typed' argument error:" in printed
    assert "surplus positional 2 bound to 'wait'" in printed
