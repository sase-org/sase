"""Python/Rust parity for the closed %auto grammar.

Runs one spelling matrix through both ``extract_prompt_directives`` and
the typed launch planner binding (``plan_typed_launch_units``) and asserts
the same accept/reject outcome and the same launch fields on both sides.
"""

from __future__ import annotations

import pytest

from sase.core.agent_launch_facade import plan_typed_launch_units
from sase.core.rust import require_rust_binding
from sase.macro._directive_types import AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS
from sase.macro._exceptions import DirectiveError
from sase.macro.directives import extract_prompt_directives

ACCEPTED: list[tuple[str, bool, str | None]] = [
    ("%auto", True, "plan"),
    ("%a", True, "plan"),
    ("%auto+", True, "plan"),
    ("%auto:true", True, "plan"),
    ("%auto:plan", True, "plan"),
    ("%auto:tale", True, "tale"),
    ("%auto:epic", True, "epic"),
    ("%auto:manual", False, None),
    ("%auto:off", False, None),
]

REJECTED: list[str] = [
    "%auto(plan=ask)",
    "%a(epic=ask)",
    "%auto(plan, epic)",
    "%auto()",
    "%auto(",
    "%auto:foo",
    "%auto:epic_plan",
    "%auto:x(plan=ask)",
]


@pytest.mark.parametrize(("token", "enabled", "mode"), ACCEPTED)
def test_auto_accepted_spellings_match_rust(
    token: str, enabled: bool, mode: str | None
) -> None:
    """Accepted spellings extract the same fields in Python and Rust."""
    _, directives = extract_prompt_directives(f"{token}\nDo the work")
    assert directives.auto_enabled is enabled
    assert directives.auto_mode == mode

    plan = plan_typed_launch_units(f"{token}\nDo the work", selected_project="sase")
    payload = plan.units[0].payload
    assert payload.auto_enabled is enabled
    assert payload.auto_mode == mode


@pytest.mark.parametrize("token", REJECTED)
def test_auto_rejected_spellings_match_rust(token: str) -> None:
    """Rejected spellings fail in Python and in the Rust planner alike."""
    with pytest.raises(DirectiveError, match="Invalid %auto spelling"):
        extract_prompt_directives(f"{token}\nDo the work")
    with pytest.raises(ValueError, match="Invalid %auto spelling"):
        plan_typed_launch_units(f"{token}\nDo the work", selected_project="sase")


def test_auto_error_messages_match_on_every_surface() -> None:
    """Every surface shows the exact same message for one bad spelling."""
    from sase.macro._directive_scan import scan_auto_directive

    cases = {
        "%a:foo": "%auto:foo",
        "%auto:`foo`": "%auto:foo",
        "%auto:foo": "%auto:foo",
    }
    for token, canonical in cases.items():
        prompt = f"{token}\nDo the work"
        with pytest.raises(DirectiveError) as py_exc:
            extract_prompt_directives(prompt)
        scan = scan_auto_directive(prompt)
        assert scan is not None and scan.error is not None
        with pytest.raises(ValueError) as rust_exc:
            plan_typed_launch_units(prompt, selected_project="sase")
        assert str(py_exc.value) == scan.error == str(rust_exc.value)
        assert f"'{canonical}'" in str(py_exc.value)


def test_auto_paren_error_keeps_literal_source_on_every_surface() -> None:
    """Paren spellings keep their literal source slice everywhere."""
    from sase.macro._directive_scan import scan_auto_directive

    token = "%a(epic=ask)"
    prompt = f"{token}\nDo the work"
    with pytest.raises(DirectiveError) as py_exc:
        extract_prompt_directives(prompt)
    scan = scan_auto_directive(prompt)
    assert scan is not None and scan.error is not None
    with pytest.raises(ValueError) as rust_exc:
        plan_typed_launch_units(prompt, selected_project="sase")
    assert str(py_exc.value) == scan.error == str(rust_exc.value)
    assert f"'{token}'" in str(py_exc.value)


def test_auto_duplicate_rejected_on_both_sides() -> None:
    """A duplicate %auto (including %auto with %auto:off) fails everywhere."""
    with pytest.raises(DirectiveError, match="Duplicate directive '%auto'"):
        extract_prompt_directives("%auto\n%auto:off\nDo the work")
    with pytest.raises(ValueError, match="Only one %auto directive"):
        plan_typed_launch_units(
            "%auto\n%auto:off\nDo the work", selected_project="sase"
        )


def test_auto_suggestion_vocabulary_matches_core() -> None:
    """The Python suggestion tuple stays parity-tested against the core."""
    vocabulary = require_rust_binding("auto_directive_vocabulary")()
    assert tuple(vocabulary["modes"]) == ("plan", "tale", "epic")
    assert tuple(vocabulary["manual_values"]) == ("manual", "off")
    assert AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS == tuple(
        vocabulary["modes"]
    ) + tuple(vocabulary["manual_values"])
