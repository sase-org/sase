"""Typed launch-unit plan construction from `%repeat`, `%{...}`, and documented forms."""

from __future__ import annotations

import pytest

from sase.core.agent_launch_facade import plan_typed_launch_units
from sase.core.agent_launch_wire import AgentUnitWire, ProcUnitWire
from sase.feature_flags import override_flags
from sase.xprompt.directives import DirectiveError, extract_prompt_directives


def test_repeat_and_alt_produce_stable_mixed_units() -> None:
    pytest.importorskip("sase_core_rs")
    with override_flags(typed_launch_units=True):
        repeated = plan_typed_launch_units(
            '%repeat:2\n%proc("echo ready")',
            selected_project="sase",
        )
        mixed_alt = plan_typed_launch_units(
            '%{%proc("echo left") | %id:reviewer\nReview}',
            selected_project="sase",
        )
        fanout = plan_typed_launch_units(
            '%proc("echo first")\n---\n%wait\n%id:reviewer\nReview',
            launch_kind="multi_prompt",
            selected_project="sase",
        )

    assert len(repeated.units) == 2
    assert all(isinstance(unit.payload, ProcUnitWire) for unit in repeated.units)
    assert [unit.logical_id for unit in repeated.units] == ["unit-1", "unit-2"]
    assert mixed_alt.units
    kinds = {type(unit.payload) for unit in mixed_alt.units}
    assert AgentUnitWire in kinds
    assert ProcUnitWire in kinds
    assert isinstance(fanout.units[0].payload, ProcUnitWire)
    assert isinstance(fanout.units[1].payload, AgentUnitWire)
    assert fanout.units[1].waits[0].kind == "logical"
    assert fanout.units[1].waits[0].logical_id == fanout.units[0].logical_id
    assert fanout.units[0].logical_id != fanout.units[1].logical_id


def test_documented_typed_launch_forms_plan_and_flag_off_rejects() -> None:
    pytest.importorskip("sase_core_rs")
    examples = [
        "%if::\n\n```bash\ntest -f pyproject.toml\n```\nReview",
        '%proc("just check")',
        '%proc(python="print(\'ready\')", timeout="20m", label="Preflight")',
        (
            '%proc(timeout="20m", idle_timeout="5m", cwd="docs", workspace="true")::\n\n'
            "```bash\njust docs-check\n```\n"
        ),
    ]
    for prompt in examples:
        with pytest.raises(DirectiveError, match="typed_launch_units"):
            extract_prompt_directives(prompt)
        with pytest.raises(DirectiveError, match="typed_launch_units"):
            plan_typed_launch_units(prompt, selected_project="sase")

    with override_flags(typed_launch_units=True):
        conditioned = plan_typed_launch_units(examples[0], selected_project="sase")
        positional = plan_typed_launch_units(examples[1], selected_project="sase")
        named = plan_typed_launch_units(examples[2], selected_project="sase")
        fenced = plan_typed_launch_units(examples[3], selected_project="sase")

    assert isinstance(conditioned.units[0].payload, AgentUnitWire)
    assert conditioned.units[0].condition is not None
    assert conditioned.units[0].condition.code.language == "bash"
    assert "test -f pyproject.toml" in conditioned.units[0].condition.code.source
    assert isinstance(positional.units[0].payload, ProcUnitWire)
    assert positional.units[0].payload.code.source == "just check"
    assert isinstance(named.units[0].payload, ProcUnitWire)
    assert named.units[0].payload.code.language == "python"
    assert named.units[0].payload.timeout == "20m"
    assert named.units[0].payload.label == "Preflight"
    assert isinstance(fenced.units[0].payload, ProcUnitWire)
    assert fenced.units[0].payload.workspace is True
    assert fenced.units[0].payload.cwd == "docs"
    assert fenced.units[0].payload.timeout == "20m"
    assert fenced.units[0].payload.idle_timeout == "5m"
    assert "just docs-check" in fenced.units[0].payload.code.source
