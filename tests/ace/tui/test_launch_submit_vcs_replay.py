"""Submit-time Ctrl+Space replay refresh (sase-p7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.history.vcs_xprompt_mru import _load_vcs_xprompt_mru
from tests._vcs_xprompt_mru_helpers import patched_mru_file, write_project
from tests.ace.tui._agent_launch_helpers import _FakeApp
from tests.conftest import redirect_sase_home


def test_submit_refreshes_replay_from_cycled_vcs_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[str] = []
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage",
        recorded.append,
    )
    app = _FakeApp()

    app._launch_resolved_prompt("#gh:cycled do the work")

    assert recorded == ["#gh:cycled"]
    assert len(app.launch_tasks) == 1
    assert app.launch_tasks[0]["prompt"] == "#gh:cycled do the work"


def test_submit_does_not_save_implicit_home_as_replay_target(tmp_path: Path) -> None:
    fake = tmp_path / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:sase"]}), encoding="utf-8")
    with patched_mru_file(fake):
        app = _FakeApp()
        app._launch_resolved_prompt("#git:home do the work")
        assert _load_vcs_xprompt_mru() == ["#gh:sase"]


def test_submit_does_not_save_non_launchable_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    write_project(sase_home / "projects", "deadproj", None)
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.is_launchable_project",
        lambda *_args, **_kwargs: False,
    )
    fake = sase_home / "vcs_xprompt_mru.json"
    fake.write_text(json.dumps({"entries": ["#gh:sase"]}), encoding="utf-8")
    with patched_mru_file(fake):
        app = _FakeApp()
        app._launch_resolved_prompt("#gh:deadproj do the work")
        assert _load_vcs_xprompt_mru() == ["#gh:sase"]
