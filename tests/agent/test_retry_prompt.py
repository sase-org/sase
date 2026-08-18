"""Unit tests for shared retry-prompt identity helpers."""

from __future__ import annotations

import pytest

from sase.agent.retry_prompt import prompt_has_id_directive

_EPIC_ROOT_PROMPT = (
    "#gh:gh_sase-org__sase\n"
    "%id(sase-pw.1, bead=sase-pw.1)\n"
    "%clan(sase-pw, tribe=epic, summary_script=sase_clan_summary_epic)\n"
    "%model:@medium\n"
    "%auto\n"
    "#bd/work_phase_bead:sase-pw.1"
)


@pytest.mark.parametrize(
    "prompt",
    [
        "%id:foo",
        "%i:foo",
        "%id:!foo",
        "%id:@.cld",
        "%id:sase-8a.3\n%auto\nDo work",
        "%id:`quoted name`",
        "%id(2, clan=sase-8k, bead=sase-8k.2)",
        "%id(!code, family=sase-8u.4.2, bead=sase-8u.4.2)",
        _EPIC_ROOT_PROMPT,
        "%model:@no_such_alias\n%id:foo\nDo work",
    ],
)
def test_prompt_has_id_directive_true(prompt: str) -> None:
    assert prompt_has_id_directive(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    [
        "Do work",
        "#gh:gh_sase-org__sase Describe this repo.",
        "#gh:gh_sase-org__sase #plan",
        "Implement the plan",
        "part one\n---\npart two",
        "%id\nDo work",
        "```\n%id:fenced\n```\nDo work",
        ("%xprompts_enabled:false\n%id:disabled\n%xprompts_enabled:true\nDo work"),
        "%model:@no_such_alias\nDo work",
    ],
)
def test_prompt_has_id_directive_false(prompt: str) -> None:
    assert prompt_has_id_directive(prompt) is False
