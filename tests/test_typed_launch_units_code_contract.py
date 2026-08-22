"""Gated `%if`/`%proc` contract, fence opacity, and flag-off rejection."""

from __future__ import annotations

import pytest

from sase.feature_flags import FeatureFlag, override_flags
from sase.xprompt.code_value import (
    TYPED_LAUNCH_UNITS_DISABLED_MESSAGE,
    make_code_value,
    scan_directive_owned_fences,
)
from sase.xprompt.directives import DirectiveError, extract_prompt_directives
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.processor import process_xprompt_references_with_catalog


def test_flag_off_rejects_if_and_does_not_leak_to_cleaned_prompt() -> None:
    prompt = "%if::\n\n```bash\ntest -f pyproject.toml\n```\nReview"
    with pytest.raises(DirectiveError, match="typed_launch_units"):
        extract_prompt_directives(prompt)


def test_flag_off_rejects_proc_paren_form() -> None:
    with pytest.raises(DirectiveError, match="typed_launch_units"):
        extract_prompt_directives('%proc("just check")\nReview')


def test_flag_on_captures_if_fence_and_strips_from_model_prompt() -> None:
    prompt = "%if::\n\n```bash\ntest -f pyproject.toml\n%wait and #refs\n```\nReview the tree"
    with override_flags(typed_launch_units=True):
        cleaned, directives = extract_prompt_directives(prompt)
    assert "Review the tree" in cleaned
    assert "%if" not in cleaned
    assert "test -f pyproject.toml" not in cleaned
    assert directives.if_code is not None
    assert directives.if_code.language == "bash"
    assert "%wait and #refs" in directives.if_code.source
    assert len(directives.if_code.digest) == 64


def test_flag_on_paren_proc_is_literal_and_stripped() -> None:
    with override_flags(typed_launch_units=True):
        cleaned, directives = extract_prompt_directives(
            '%proc("echo %wait and #foo")\nDone'
        )
    assert cleaned.strip() == "Done"
    assert directives.proc_code is not None
    assert directives.proc_code.source == "echo %wait and #foo"
    assert directives.proc_code.language == "bash"


def test_flag_on_fenced_proc_preserves_options() -> None:
    prompt = '%proc(timeout="20m", label="Scoped")::\n```bash\njust check\n```\n'
    with override_flags(typed_launch_units=True):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == ""
    assert directives.proc_code is not None
    assert directives.proc_code.source == "just check\n"
    assert directives.proc_options == {"timeout": "20m", "label": "Scoped"}


def test_fenced_proc_rejects_parenthesized_body() -> None:
    prompt = '%proc("just check")::\n```bash\njust test\n```\n'
    with override_flags(typed_launch_units=True):
        with pytest.raises(DirectiveError, match="parenthesized body"):
            extract_prompt_directives(prompt)


def test_literal_percent_hash_frontmatter_and_jinja_inside_owned_fence() -> None:
    body = "%model:opus\n#work\n---\n{{ name }}\n$(echo hi)\n``` inner"
    prompt = f"%if::\n```python\n{body}\n```\nLaunch"
    with override_flags(typed_launch_units=True):
        cleaned, directives = extract_prompt_directives(prompt)
    assert directives.if_code is not None
    assert directives.if_code.source.strip() == body
    assert "%model" not in cleaned
    assert directives.model is None


def test_unknown_language_and_missing_fence_are_hard_errors() -> None:
    with override_flags(typed_launch_units=True):
        with pytest.raises(DirectiveError, match="unsupported code language"):
            extract_prompt_directives("%proc::\n```ruby\nputs 1\n```\n")
        with pytest.raises(DirectiveError, match="exactly one closed"):
            extract_prompt_directives("%if::\n\nReview")


def test_crlf_and_blank_lines_before_owned_fence() -> None:
    prompt = "%if::\r\n\r\n```bash\r\ntrue\r\n```\r\nGo"
    scan = scan_directive_owned_fences(prompt)
    assert not scan.diagnostics
    assert scan.directives[0].code is not None
    assert scan.directives[0].code.language == "bash"


def test_nested_expansion_does_not_expand_inside_owned_fence() -> None:
    catalog = {}
    prompt = "%if::\n```bash\necho #secret\n```\n#secret"
    with override_flags(typed_launch_units=True):
        expanded = process_xprompt_references_with_catalog(prompt, catalog)
    assert "echo #secret" in expanded


def test_code_input_type_is_structured() -> None:
    arg = InputArg(name="script", type=InputType.CODE)
    value = arg.validate_and_convert("print('hi')")
    assert value.source == "print('hi')"
    assert value.language == "bash"
    assert value.digest == make_code_value("print('hi')", "bash").digest


def test_completion_hides_if_and_proc_while_flag_is_off() -> None:
    from sase.ace.tui.widgets.directive_completion import (
        build_directive_completion_candidates,
    )

    candidates, _ = build_directive_completion_candidates("%")
    insertions = {candidate.insertion for candidate in candidates}
    assert "%if" not in insertions
    assert "%proc" not in insertions
    with override_flags(typed_launch_units=True):
        enabled, _ = build_directive_completion_candidates("%")
    enabled_insertions = {candidate.insertion for candidate in enabled}
    assert "%if" in enabled_insertions
    assert "%proc" in enabled_insertions
