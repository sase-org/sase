"""End-to-end tests for remapped keybindings via the headless agent runner."""

import json
from unittest.mock import patch

from sase.ace.changespec import ChangeSpec, CommitEntry, HookEntry, CommentEntry


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


def _patch_changespecs():
    return patch(
        "sase.ace.changespec.find_all_changespecs",
        return_value=MOCK_CHANGESPECS,
    )


def _patch_config(overrides: dict | None = None):
    """Patch load_merged_config to return custom ace keymaps config."""
    cfg: dict = {"ace": {}}
    if overrides:
        cfg["ace"]["keymaps"] = overrides
    return patch("sase.config.load_merged_config", return_value=cfg)


async def test_default_keys_still_work() -> None:
    """With no config override, default 'j' key navigates down."""
    from sase.ace.agent_runner import run_agent_mode

    with _patch_changespecs(), _patch_config():
        result = json.loads(await run_agent_mode(query='"feature"', keys=["j"]))

    assert result["error"] is None
    assert result["state"]["idx"] == 1


async def test_remapped_navigation_key() -> None:
    """Remapping next_changespec to 'f' makes 'f' navigate and 'j' not."""
    from sase.ace.agent_runner import run_agent_mode

    keymap_cfg = {"app": {"next_changespec": "f"}}

    # 'f' should navigate
    with _patch_changespecs(), _patch_config(keymap_cfg):
        result = json.loads(await run_agent_mode(query='"feature"', keys=["f"]))

    assert result["error"] is None
    assert result["state"]["idx"] == 1

    # 'j' should no longer navigate
    with _patch_changespecs(), _patch_config(keymap_cfg):
        result = json.loads(await run_agent_mode(query='"feature"', keys=["j"]))

    assert result["error"] is None
    assert result["state"]["idx"] == 0
