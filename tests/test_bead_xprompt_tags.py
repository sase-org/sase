"""Tests for bead-automation xprompt tag wiring (sase-r.2)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.bead.xprompts import (
    BeadXPromptNotFoundError,
    _resolve_bead_xprompt,
    resolve_land_epic_xprompt,
    resolve_work_phase_xprompt,
)
from sase.xprompt.loader import get_all_prompts
from sase.xprompt.tags import XPromptTag, parse_tags
from sase.xprompt.workflow_models import Workflow, WorkflowStep


# ── Tag enum parsing ───────────────────────────────────────────────────


def test_new_tags_parse_from_string() -> None:
    assert parse_tags("create_epic_bead") == frozenset({XPromptTag.create_epic_bead})
    assert parse_tags("work_phase_bead") == frozenset({XPromptTag.work_phase_bead})
    assert parse_tags("land_epic") == frozenset({XPromptTag.land_epic})


def test_new_tags_parse_from_list() -> None:
    parsed = parse_tags(["create_epic_bead", "land_epic"])
    assert parsed == frozenset({XPromptTag.create_epic_bead, XPromptTag.land_epic})


# ── Built-ins resolvable by tag ────────────────────────────────────────


def test_builtin_work_phase_resolves() -> None:
    wf = resolve_work_phase_xprompt()
    assert wf.name == "bd/work_phase_bead"
    assert XPromptTag.work_phase_bead in wf.tags


def test_builtin_land_epic_resolves() -> None:
    wf = resolve_land_epic_xprompt()
    assert wf.name == "bd/land_epic"
    assert XPromptTag.land_epic in wf.tags


def test_builtin_xprompts_loaded_from_config() -> None:
    """Confirm the three built-ins are present in the loader registry."""
    prompts = get_all_prompts()
    assert "bd/new_epic" in prompts
    assert "bd/land_epic" in prompts
    assert "bd/work_phase_bead" in prompts
    assert XPromptTag.create_epic_bead in prompts["bd/new_epic"].tags
    assert XPromptTag.land_epic in prompts["bd/land_epic"].tags
    assert XPromptTag.work_phase_bead in prompts["bd/work_phase_bead"].tags


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
