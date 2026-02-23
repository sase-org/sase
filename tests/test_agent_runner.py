"""Tests for the headless agent runner module."""

import json
from typing import Any
from unittest.mock import patch

from sase.ace.changespec import ChangeSpec, CommentEntry, CommitEntry, HookEntry


def _make_changespec(
    name: str = "test_feature",
    description: str = "Test description",
    status: str = "Ready",
    cl: str | None = None,
    parent: str | None = None,
    file_path: str = "/tmp/myproject.gp",
    commits: list[CommitEntry] | None = None,
    hooks: list[HookEntry] | None = None,
    comments: list[CommentEntry] | None = None,
) -> ChangeSpec:
    """Create a mock ChangeSpec for testing."""
    return ChangeSpec(
        name=name,
        description=description,
        parent=parent,
        cl=cl,
        status=status,
        test_targets=None,
        kickstart=None,
        file_path=file_path,
        line_number=1,
        commits=commits,
        hooks=hooks,
        comments=comments,
    )


MOCK_CHANGESPECS = [
    _make_changespec(name="feature_a"),
    _make_changespec(name="feature_b"),
    _make_changespec(name="feature_c"),
]


def _patch_changespecs(specs: list[ChangeSpec] | None = None) -> Any:
    """Return a patch context manager for find_all_changespecs."""
    return patch(
        "sase.ace.changespec.find_all_changespecs",
        return_value=specs if specs is not None else MOCK_CHANGESPECS,
    )


async def test_no_keys_returns_initial_state() -> None:
    """No keys pressed returns default initial state."""
    from sase.ace.agent_runner import run_agent_mode

    with _patch_changespecs():
        result = json.loads(await run_agent_mode(query='"feature"'))

    assert result["error"] is None
    state = result["state"]
    assert state["idx"] == 0
    assert state["total"] == 3
    assert state["tab"] == "changespecs"
    assert state["modal"] is None
    assert state["selected"]["name"] == "feature_a"


async def test_slash_opens_query_modal() -> None:
    """Pressing slash opens the QueryEditModal."""
    from sase.ace.agent_runner import run_agent_mode

    with _patch_changespecs():
        result = json.loads(await run_agent_mode(query='"feature"', keys=["slash"]))

    assert result["error"] is None
    assert result["state"]["modal"] == "QueryEditModal"


async def test_tab_changes_tab() -> None:
    """Pressing tab switches to the agents tab."""
    from sase.ace.agent_runner import run_agent_mode

    with _patch_changespecs():
        result = json.loads(await run_agent_mode(query='"feature"', keys=["tab"]))

    assert result["error"] is None
    assert result["state"]["tab"] == "agents"


async def test_invalid_query_populates_error() -> None:
    """Invalid query string populates error field."""
    from sase.ace.agent_runner import run_agent_mode

    result = json.loads(await run_agent_mode(query='"unclosed'))

    assert result["error"] is not None
    assert result["screen"] == ""
    assert result["state"] == {}
