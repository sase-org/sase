"""Coverage for the orthogonal ``%id(bead=...)`` launch association."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.agent.launch_validation import rewrite_force_reuse_name_directives
from sase.agent.multi_prompt_reference_directives import extract_static_name_directive
from sase.agent.repeat_launcher import spawn_repeat_batch
from sase.agent.retry_prompt import rewrite_retry_prompt_name
from sase.xprompt._directive_extract import extract_prompt_directives as extract_with
from sase.xprompt.directive_edit import (
    demote_prompt_clan_declaration,
    rewrite_prompt_clan_member_name,
)
from sase.xprompt.directives import (
    DirectiveError,
    extract_prompt_directives,
    split_prompt_for_models,
)


@pytest.mark.parametrize(
    ("prompt", "name", "clan", "family", "tribe"),
    [
        ("%id(worker, bead=sase-1)\nWork", "worker", None, None, None),
        (
            "%id(worker, clan=research, bead=sase-1)\nWork",
            "research.worker",
            "research",
            None,
            None,
        ),
        (
            "%id(reviewer, family=parent, bead=sase-1)\nWork",
            None,
            None,
            "parent",
            None,
        ),
        (
            "%id(worker, tribe=review, bead=sase-1)\nWork",
            "worker",
            None,
            None,
            "review",
        ),
    ],
)
def test_id_bead_combines_with_every_identity_form(
    prompt: str,
    name: str | None,
    clan: str | None,
    family: str | None,
    tribe: str | None,
) -> None:
    cleaned, directives = extract_prompt_directives(prompt)

    assert cleaned == "Work"
    assert directives.name == name
    assert directives.bead_id == "sase-1"
    assert directives.clan == clan
    assert directives.family_attach_parent == family
    assert directives.tribe == tribe


def test_id_bead_without_name_allocates_automatic_name() -> None:
    with patch("sase.agent.names.get_next_auto_name", return_value="auto-name"):
        _, directives = extract_prompt_directives("%id(bead=sase-1)\nWork")

    assert directives.name == "auto-name"
    assert directives.name_explicit is False
    assert directives.bead_id == "sase-1"


def test_id_bead_expands_xprompt_reference() -> None:
    _, directives = extract_with(
        "%id(worker, bead=#phase)\nWork",
        process_references=lambda value: value.replace("#phase", "sase-1.2"),
    )

    assert directives.bead_id == "sase-1.2"


@pytest.mark.parametrize(
    ("prompt", "message"),
    [
        ("%id(worker, bead=)", "non-empty, whitespace-free"),
        ("%id(worker, bead=`sase 1`)", "non-empty, whitespace-free"),
        ("%id(worker, bead=a, bead=b)", "Duplicate keyword argument 'bead'"),
        ("%id(worker, unknown=value)", "Only bead=, clan=, family=, and tribe="),
    ],
)
def test_id_bead_reports_targeted_argument_errors(prompt: str, message: str) -> None:
    with pytest.raises(DirectiveError, match=message):
        extract_prompt_directives(prompt)


def test_id_bead_rejects_whitespace_after_xprompt_expansion() -> None:
    with pytest.raises(DirectiveError, match="non-empty, whitespace-free"):
        extract_with(
            "%id(worker, bead=#phase)",
            process_references=lambda _value: "sase 1",
        )


def test_prompt_without_id_bead_remains_unassociated() -> None:
    _, directives = extract_prompt_directives("%id:worker\nWork")
    assert directives.bead_id is None


def test_id_bead_survives_fanout_repeat_retry_and_forced_reuse() -> None:
    assert extract_static_name_directive("%id(worker, bead=sase-1)\nWork") == "worker"
    assert split_prompt_for_models("%id(worker, bead=sase-1)\n%alt(a,b)\nWork") == [
        "%id(worker.1, bead=sase-1)\na\nWork",
        "%id(worker.2, bead=sase-1)\nb\nWork",
    ]

    specs = spawn_repeat_batch(
        "%r:2 %id(worker, bead=sase-1)\nWork",
        base_spawn_fn=lambda _spec: None,
    )
    assert specs[0].prompt.startswith("%i(worker.1, bead=sase-1)\n")
    assert specs[1].prompt.startswith("%i(worker.2, bead=sase-1)\n%wait:worker.1\n")

    assert (
        rewrite_retry_prompt_name("%id(worker, bead=sase-1)\nWork", "worker.r0")
        == "%id(worker.r0, bead=sase-1)\nWork"
    )
    assert (
        rewrite_retry_prompt_name(
            "%id(reviewer, family=worker, bead=sase-1)\nWork", "worker--reviewer.r0"
        )
        == "%id(worker--reviewer.r0, bead=sase-1)\nWork"
    )
    assert (
        rewrite_force_reuse_name_directives("%id(!worker, bead=sase-1)\nWork")
        == "%id(worker, bead=sase-1)\nWork"
    )


def test_id_bead_survives_clan_demotion_and_member_rewrite() -> None:
    declaring = "%clan:research\n%id(research.lead, bead=sase-1)\nWork"
    assert demote_prompt_clan_declaration(declaring) == (
        "%id(lead, clan=research, bead=sase-1)\nWork"
    )

    joining = "%id(worker, clan=research, bead=sase-1)\nWork"
    assert rewrite_prompt_clan_member_name(joining, "research.worker.r0") == (
        "%id(worker.r0, clan=research, bead=sase-1)\nWork"
    )
