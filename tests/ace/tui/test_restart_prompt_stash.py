"""Restart-time prompt-stash coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow._prompt_bar_stash import PromptBarStashMixin
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.widgets.prompt_input_bar import StashedPromptPane
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


def _skip_without_prompt_stash_bindings() -> None:
    rust_module = pytest.importorskip(RUST_EXTENSION_MODULE_NAME)
    if not hasattr(rust_module, "append_prompt_stash"):
        pytest.skip("sase_core_rs is too old (no append_prompt_stash binding).")


def _point_store_at(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr("sase.core.paths.prompt_stash_path", lambda: path, raising=True)


def _entries(path: Path) -> list[Any]:
    from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

    return list(read_prompt_stash_snapshot(path).entries)


def _prompt_context() -> PromptContext:
    return PromptContext(
        project_name="sase",
        cl_name=None,
        project_file="/tmp/sase.gp",
        workspace_dir="/tmp",
        workspace_num=11,
        workflow_name="default",
        timestamp="260629-000000",
        history_sort_key="260629-000000",
        display_name="sase",
        update_target="",
    )


class _FakeBar:
    def __init__(
        self,
        panes: list[StashedPromptPane],
        *,
        mode: str = "prompt",
    ) -> None:
        self._mode = mode
        self._panes = panes
        self.capture_calls = 0

    def capture_stashable_panes(self) -> list[StashedPromptPane]:
        self.capture_calls += 1
        return list(self._panes)


class _RestartStashApp(PromptBarStashMixin):
    def __init__(self, bar: _FakeBar | None) -> None:
        self._bar = bar
        self._prompt_context = _prompt_context()

    def _mounted_prompt_bar(self) -> Any:
        return self._bar


def test_stash_prompt_bar_before_restart_writes_one_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _skip_without_prompt_stash_bindings()
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)
    frontmatter = "---\ndescription: draft\n---"
    bar = _FakeBar(
        [
            StashedPromptPane("alpha", frontmatter=frontmatter, pane_index=0),
            StashedPromptPane("beta", frontmatter=frontmatter, pane_index=1),
        ]
    )
    app = _RestartStashApp(bar)

    assert app._stash_prompt_bar_before_restart() is True

    entries = _entries(stash_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.text == "alpha\n---\nbeta"
    assert entry.frontmatter == frontmatter
    assert entry.project == "sase"
    assert entry.source == "restart"
    assert entry.pane_index == 0


@pytest.mark.parametrize(
    "bar",
    [
        None,
        _FakeBar([]),
        _FakeBar([StashedPromptPane("feedback")], mode="feedback"),
    ],
)
def test_stash_prompt_bar_before_restart_noops_without_prompt_draft(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bar: _FakeBar | None
) -> None:
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)
    app = _RestartStashApp(bar)

    assert app._stash_prompt_bar_before_restart() is False
    assert not stash_path.exists()


def test_stash_prompt_bar_before_restart_swallows_write_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stash_path = tmp_path / "prompt_stash.jsonl"
    _point_store_at(monkeypatch, stash_path)
    bar = _FakeBar([StashedPromptPane("alpha")])
    app = _RestartStashApp(bar)

    def _boom(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("write failed")

    monkeypatch.setattr("sase.core.prompt_stash_facade.append_prompt_stash", _boom)

    assert app._stash_prompt_bar_before_restart() is False
    assert not stash_path.exists()
