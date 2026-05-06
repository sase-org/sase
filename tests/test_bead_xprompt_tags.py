"""Tests for bead-automation xprompt tag wiring (sase-r.2)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.bead.xprompts import (
    BeadXPromptNotFoundError,
    _resolve_bead_xprompt,
    resolve_land_epic_xprompt,
    resolve_land_legend_xprompt,
    resolve_work_phase_xprompt,
)
from sase.xprompt.loader import get_all_prompts, get_all_xprompts
from sase.xprompt.models import InputType
from sase.xprompt.processor import process_xprompt_references
from sase.xprompt.tags import XPromptTag, parse_tags
from sase.xprompt.workflow_models import Workflow, WorkflowStep


# ── Tag enum parsing ───────────────────────────────────────────────────


def test_new_tags_parse_from_string() -> None:
    assert parse_tags("create_epic_bead") == frozenset({XPromptTag.create_epic_bead})
    assert parse_tags("create_legend_bead") == frozenset(
        {XPromptTag.create_legend_bead}
    )
    assert parse_tags("work_phase_bead") == frozenset({XPromptTag.work_phase_bead})
    assert parse_tags("land_epic") == frozenset({XPromptTag.land_epic})
    assert parse_tags("land_legend") == frozenset({XPromptTag.land_legend})


def test_new_tags_parse_from_list() -> None:
    parsed = parse_tags(["create_epic_bead", "land_epic", "land_legend"])
    assert parsed == frozenset(
        {
            XPromptTag.create_epic_bead,
            XPromptTag.land_epic,
            XPromptTag.land_legend,
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


def test_builtin_land_legend_resolves() -> None:
    wf = resolve_land_legend_xprompt()
    assert wf.name == "bd/land_legend"
    assert XPromptTag.land_legend in wf.tags


def test_builtin_xprompts_loaded_from_config() -> None:
    """Confirm the bead automation built-ins are present in the loader registry."""
    prompts = get_all_prompts()
    assert "bd/new_epic" in prompts
    assert "bd/new_legend" in prompts
    assert "bd/land_epic" in prompts
    assert "bd/land_legend" in prompts
    assert "bd/work_phase_bead" in prompts
    assert XPromptTag.create_epic_bead in prompts["bd/new_epic"].tags
    assert XPromptTag.create_legend_bead in prompts["bd/new_legend"].tags
    assert XPromptTag.land_epic in prompts["bd/land_epic"].tags
    assert XPromptTag.land_legend in prompts["bd/land_legend"].tags
    assert XPromptTag.work_phase_bead in prompts["bd/work_phase_bead"].tags
    assert (
        "sase bead work <epic_id> --yes" in prompts["bd/new_epic"].steps[0].prompt_part
    )
    legend_body = prompts["bd/new_legend"].steps[0].prompt_part
    assert "--tier legend" in legend_body
    assert "--epic-count <epic_count>" in legend_body
    assert "epic_count: <epic_count>" in legend_body
    assert "sase bead work <legend_bead_id> --yes" in legend_body
    assert "Do not run `sase bead work`" not in legend_body


def test_new_epic_accepts_changespec_inputs() -> None:
    prompt = get_all_prompts()["bd/new_epic"]
    legend_bead_id = prompt.get_input_by_name("legend_bead_id")
    changespec = prompt.get_input_by_name("changespec")
    bug_id = prompt.get_input_by_name("bug_id")

    assert legend_bead_id is not None
    assert legend_bead_id.type is InputType.WORD
    assert legend_bead_id.default is None
    assert changespec is not None
    assert changespec.type is InputType.WORD
    assert changespec.default is None
    assert bug_id is not None
    assert bug_id.type is InputType.INT
    assert bug_id.default is None


def test_new_epic_changespec_guidance() -> None:
    body = get_all_prompts()["bd/new_epic"].steps[0].prompt_part

    assert "-c/--changespec" in body
    assert "-b/--bug-id" in body
    assert "bug_id` requires `changespec" in body
    assert "No ChangeSpec metadata was provided" in body
    assert "--tier epic" in body
    assert "--type plan(<plan_file>,<legend_bead_id>)" in body


def test_new_epic_requires_serial_phase_creation() -> None:
    body = get_all_prompts()["bd/new_epic"].steps[0].prompt_part

    assert "Create the epic plan bead first." in body
    assert "create the phase beads one at a time" in body
    assert "in the exact order they appear in the" in body
    assert "Do not run phase bead creation commands in parallel" in body
    assert "child bead suffixes are allocated by creation order" in body


def test_new_epic_colon_args_render_linked_legend_guidance() -> None:
    xprompt = get_all_xprompts()["bd/new_epic"]

    with patch(
        "sase.xprompt.processor.get_all_xprompts",
        return_value={"bd/new_epic": xprompt},
    ):
        body = process_xprompt_references(
            "#bd/new_epic:sdd/epics/202605/my_feature.md,zorg-1"
        )

    assert "sdd/epics/202605/my_feature.md" in body
    assert "Use `zorg-1` as the linked legend bead ID." in body
    assert "--type plan(<plan_file>,<legend_bead_id>)" in body


def test_new_legend_colon_args_render_plan_path_and_work_guidance() -> None:
    xprompt = get_all_xprompts()["bd/new_legend"]

    with patch(
        "sase.xprompt.processor.get_all_xprompts",
        return_value={"bd/new_legend": xprompt},
    ):
        body = process_xprompt_references(
            "#bd/new_legend:sdd/legends/202605/roadmap.md"
        )

    assert "sdd/legends/202605/roadmap.md" in body
    assert "--epic-count <epic_count>" in body
    assert "epic_count: <epic_count>" in body
    assert "sase bead work <legend_bead_id> --yes" in body


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


def test_land_legend_user_override_wins() -> None:
    """A custom land_legend prompt is returned by the strict resolver."""
    override = _user_xprompt("user/land_legend_override", XPromptTag.land_legend)
    with patch(
        "sase.xprompt.loader.get_all_prompts",
        return_value={override.name: override},
    ):
        wf = resolve_land_legend_xprompt()
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
