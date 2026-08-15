"""Tests for bead-automation xprompt tag wiring (sase-r.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.bead.xprompts import (
    BeadXPromptNotFoundError,
    _resolve_bead_xprompt,
    resolve_land_epic_xprompt,
    resolve_work_phase_xprompt,
    resolve_work_task_xprompt,
)
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.loader import get_all_prompts
from sase.xprompt.tags import XPromptTag, parse_tags
from sase.xprompt.workflow_models import Workflow, WorkflowStep

# ── Tag enum parsing ───────────────────────────────────────────────────


def test_new_tags_parse_from_string() -> None:
    assert parse_tags("create_epic_bead") == frozenset({XPromptTag.create_epic_bead})
    assert parse_tags("work_phase_bead") == frozenset({XPromptTag.work_phase_bead})
    assert parse_tags("work_task_bead") == frozenset({XPromptTag.work_task_bead})
    assert parse_tags("land_epic") == frozenset({XPromptTag.land_epic})


def test_new_tags_parse_from_list() -> None:
    parsed = parse_tags(["create_epic_bead", "land_epic"])
    assert parsed == frozenset(
        {
            XPromptTag.create_epic_bead,
            XPromptTag.land_epic,
        }
    )


# ── Built-ins resolvable by tag ────────────────────────────────────────


def test_builtin_work_phase_resolves() -> None:
    wf = resolve_work_phase_xprompt()
    assert wf.name == "bd/work_phase_bead"
    assert XPromptTag.work_phase_bead in wf.tags


def test_builtin_land_epic_resolves() -> None:
    wf = resolve_land_epic_xprompt()
    assert wf.name == "bd/land_epic"
    assert XPromptTag.land_epic in wf.tags


def test_builtin_work_task_resolves() -> None:
    wf = resolve_work_task_xprompt()
    assert wf.name == "bd/work_task"
    assert XPromptTag.work_task_bead in wf.tags


def test_builtin_xprompts_loaded_from_config() -> None:
    """Confirm the bead automation built-ins are present in the loader registry."""
    prompts = get_all_prompts()
    assert "bd/new_epic" not in prompts
    assert "bd/next" not in prompts
    assert "bd/land_epic" in prompts
    assert "bd/work_phase_bead" in prompts
    assert "bd/work_task" in prompts
    assert XPromptTag.land_epic in prompts["bd/land_epic"].tags
    assert XPromptTag.work_phase_bead in prompts["bd/work_phase_bead"].tags
    assert XPromptTag.work_task_bead in prompts["bd/work_task"].tags


def _builtin_prompt_body(name: str) -> str:
    body = get_all_prompts()[name].steps[0].prompt_part
    assert body is not None
    return body


def _single_spaced(text: str) -> str:
    return " ".join(text.split())


def _assert_no_wait_directives(name: str, task_instruction: str) -> None:
    cleaned, directives = extract_prompt_directives(_builtin_prompt_body(name))

    assert directives.wait_priority is None
    assert directives.wait == []
    assert directives.wait_beads == []
    assert directives.wait_duration is None
    assert directives.wait_until is None
    assert directives.wait_runners is None
    assert task_instruction in cleaned


@pytest.mark.parametrize(
    ("name", "task_instruction"),
    [
        (
            "bd/work_phase_bead",
            "Can you complete the work for bead {{ bead_id }}",
        ),
        (
            "bd/land_epic",
            "You are the land agent for epic bead {{ bead_id }}",
        ),
        (
            "bd/work_task",
            "Can you complete the work for task bead {{ bead_id }}",
        ),
    ],
)
def test_bead_worker_builtin_xprompts_do_not_author_wait_directives(
    name: str,
    task_instruction: str,
) -> None:
    _assert_no_wait_directives(name, task_instruction)


def test_builtin_phase_and_land_prompts_capture_follow_ups() -> None:
    prompts = get_all_prompts()
    phase_body = prompts["bd/work_phase_bead"].steps[0].prompt_part
    land_body = prompts["bd/land_epic"].steps[0].prompt_part
    assert phase_body is not None
    assert land_body is not None

    assert "sase bead note {{ bead_id }} 'PROPOSED FOLLOW-UP:" in phase_body
    assert "collect every `PROPOSED FOLLOW-UP:` note entry" in land_body
    assert "review the epic bead's own notes" in land_body
    assert "review every child note" in land_body
    assert "Unresolved issues caused by this epic remain epic work" in land_body
    assert "use `/sase_new_task`" in land_body
    assert "sase bead create -T task" not in land_body


def test_builtin_phase_prompt_keeps_single_bead_ownership() -> None:
    body = _builtin_prompt_body("bd/work_phase_bead")
    prose = _single_spaced(body)

    assert "close only this bead with" in body
    assert "Do NOT close the parent epic or any ancestor plan bead" in body
    assert (
        "Any instruction in a phase description or child plan to close an ancestor "
        "is preparation and evidence for that ancestor's land agent"
    ) in prose
    assert "not authorization for a phase worker" in prose


def test_builtin_land_prompt_plans_remaining_work_only() -> None:
    body = _builtin_prompt_body("bd/land_epic")

    assert "Plan only the remaining work" in body
    assert "Do not include this epic's close, symvision pass" in body
    assert "as a child phase" in body
    assert "child epic's `parent_bead` link is the handoff" in body
    assert "Make step 3 the plan's final phase" not in body


def test_builtin_land_prompt_resumes_nested_parent_handoffs() -> None:
    body = _builtin_prompt_body("bd/land_epic")
    prose = _single_spaced(body)

    assert "inspect the linked `parent_bead`" in body
    assert "If the parent is a phase bead" in body
    assert "close only that parent phase normally" in body
    assert "leave the containing epic to its already-waiting land agent" in body
    assert "If the parent is a plan bead" in body
    assert "review the parent's previous landing note" in prose
    assert "rerun descendant and linked-plan readiness checks" in prose
    assert "close it normally with `sase bead close <parent-bead>" in prose
    assert "repeat through directly parented plan ancestors" in body
    assert "Stop at the first incomplete or ambiguous parent" in body
    assert "never use `--force` to advance a successful nested landing" in body


def test_builtin_task_prompt_omits_commit_deferral_line() -> None:
    body = get_all_prompts()["bd/work_task"].steps[0].prompt_part
    assert body is not None

    assert (
        "Do not commit your changes unless/until the finalizer asks you to." not in body
    )


def test_builtin_plan_review_uses_prompt_archive_and_plan_glob(
    tmp_path: Path,
) -> None:
    month = tmp_path / "sdd" / "plans" / "202607"
    plan = month / "example.md"
    month.mkdir(parents=True)
    plan.write_text("plan\n", encoding="utf-8")

    body = get_all_prompts()["bd/review/plan"].steps[0].prompt_part
    assert "sase agent prompts show {{ file_base }}" in body
    assert "@sdd/plans/*/prompts/{{ file_base }}.md" not in body
    assert "@sdd/plans/*/{{ file_base }}.md" in body
    assert list(tmp_path.glob("sdd/plans/*/example.md")) == [plan]


# ── User overrides win via precedence chain ────────────────────────────


def _user_xprompt(name: str, tag: XPromptTag) -> Workflow:
    return Workflow(
        name=name,
        steps=[WorkflowStep(name="main", prompt_part=f"override for {tag.value}")],
        tags=frozenset({tag}),
        source_path="local_config",
    )


def test_user_override_wins() -> None:
    """A user xprompt tagged with the same tag replaces the built-in."""
    override = _user_xprompt("user/work_phase_override", XPromptTag.work_phase_bead)
    # Single-entry registry simulates "only the override has this tag"
    # (the loader's precedence chain yields exactly one workflow per tag
    # when a user has overridden it, so get_by_tag_strict picks it).
    with patch(
        "sase.xprompt.loader.get_all_prompts",
        return_value={override.name: override},
    ):
        wf = resolve_work_phase_xprompt()
    assert wf is override


def test_duplicate_tag_raises() -> None:
    """Two xprompts with the same tag → strict resolver raises ValueError."""
    a = _user_xprompt("user/a", XPromptTag.land_epic)
    b = _user_xprompt("user/b", XPromptTag.land_epic)
    with patch(
        "sase.xprompt.loader.get_all_prompts",
        return_value={a.name: a, b.name: b},
    ):
        with pytest.raises(ValueError, match="Multiple xprompts"):
            resolve_land_epic_xprompt()


def test_missing_tag_raises_clear_error() -> None:
    """No xprompt with the tag → BeadXPromptNotFoundError."""
    with patch("sase.xprompt.loader.get_all_prompts", return_value={}):
        with pytest.raises(BeadXPromptNotFoundError, match="create_epic_bead"):
            _resolve_bead_xprompt(XPromptTag.create_epic_bead)
