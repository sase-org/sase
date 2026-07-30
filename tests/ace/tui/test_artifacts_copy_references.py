"""Artifact-reference coverage for Artifacts copy mode."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.clipboard import _artifacts
from sase.ace.tui.actions.clipboard import (
    _artifact_reference_resolution as _resolution,
)
from tests.ace.tui._artifacts_copy_helpers import CopyHarness


async def test_marked_reference_handoff_seeds_one_project_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = CopyHarness()
    app._show_prompt_input_bar_for_home = MagicMock()  # type: ignore[attr-defined]
    selection = _artifacts._ArtifactReferenceSelection(
        subtab="bugs",
        items=(
            _artifacts._ArtifactReferenceItem(
                "#41",
                ("bug", "alpha", "41"),
                None,
                "alpha",
                "/tmp",
            ),
            _artifacts._ArtifactReferenceItem(
                "#42",
                ("bug", "alpha", "42"),
                None,
                "alpha",
                "/tmp",
            ),
        ),
        marked=True,
        prompt_project="alpha",
        prompt_display_name="Alpha",
        prompt_project_file="/tmp/alpha.sase",
    )
    app._capture_artifact_reference_selection = lambda: selection  # type: ignore[method-assign]
    monkeypatch.setattr(
        _artifacts,
        "_resolve_artifact_selection",
        lambda _selection, **_kwargs: _artifacts._ResolvedArtifactSelection(
            tuple(
                _artifacts._ResolvedArtifactItem(item, reference, None)
                for item, reference in zip(
                    selection.items,
                    ("bug:Alpha#41", "bug:Alpha#42"),
                    strict=True,
                )
            ),
            (),
        ),
    )
    monkeypatch.setattr(
        "sase.workspace_provider.detect_workflow_type",
        lambda _project_file: "gh",
    )
    pending: list[Any] = []
    monkeypatch.setattr(
        _artifacts,
        "spawn_pump_free_task",
        lambda _owner, coroutine, **_kwargs: pending.append(coroutine),
    )

    app._run_artifact_reference_action(handoff=True)
    await pending.pop()

    app._show_prompt_input_bar_for_home.assert_called_once_with(
        initial_text="#gh:Alpha @bug:Alpha#41 @bug:Alpha#42 ",
        display_name="Alpha artifact reference",
        history_sort_key="alpha",
    )


async def test_marked_reference_copy_uses_paste_ready_lines_and_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = CopyHarness()
    selection = _artifacts._ArtifactReferenceSelection(
        subtab="commits",
        items=(
            _artifacts._ArtifactReferenceItem(
                "sase@aaaaaaa",
                ("commit", "sase", "a" * 40),
                None,
                "alpha",
                "/tmp",
            ),
            _artifacts._ArtifactReferenceItem(
                "sase@bbbbbbb",
                ("commit", "sase", "b" * 40),
                None,
                "alpha",
                "/tmp",
            ),
        ),
        marked=True,
        prompt_project="alpha",
        prompt_display_name="Alpha",
        prompt_project_file="/tmp/alpha.sase",
    )
    app._capture_artifact_reference_selection = lambda: selection  # type: ignore[method-assign]
    monkeypatch.setattr(
        _artifacts,
        "_resolve_artifact_selection",
        lambda _selection, **_kwargs: _artifacts._ResolvedArtifactSelection(
            tuple(
                _artifacts._ResolvedArtifactItem(item, reference, None)
                for item, reference in zip(
                    selection.items,
                    (
                        f"commit:sase@{'a' * 40}",
                        f"commit:sase@{'b' * 40}",
                    ),
                    strict=True,
                )
            ),
            (),
        ),
    )
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )
    pending: list[Any] = []
    monkeypatch.setattr(
        _artifacts,
        "spawn_pump_free_task",
        lambda _owner, coroutine, **_kwargs: pending.append(coroutine),
    )

    app._run_artifact_reference_action(handoff=False)
    await pending.pop()

    assert copied[0] == "\n".join(
        (
            f"@commit:sase@{'a' * 40}",
            f"@commit:sase@{'b' * 40}",
        )
    )
    assert app.notifications[-1] == (
        "Copied 2 references",
        "information",
    )


async def test_unreferenceable_chat_warns_with_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = CopyHarness()
    selection = _artifacts._ArtifactReferenceSelection(
        subtab="chats",
        items=(
            _artifacts._ArtifactReferenceItem(
                "imported-chat",
                ("chat", "/imports/chat.md"),
                None,
                "alpha",
                "/tmp",
            ),
        ),
        marked=False,
        prompt_project="alpha",
        prompt_display_name="Alpha",
        prompt_project_file="/tmp/alpha.sase",
    )
    app._capture_artifact_reference_selection = lambda: selection  # type: ignore[method-assign]
    monkeypatch.setattr(
        _artifacts,
        "_resolve_artifact_selection",
        lambda _selection, **_kwargs: _artifacts._ResolvedArtifactSelection(
            (),
            (
                "imported-chat cannot be referenced because it is an imported "
                "transcript outside the chats root",
            ),
        ),
    )
    pending: list[Any] = []
    monkeypatch.setattr(
        _artifacts,
        "spawn_pump_free_task",
        lambda _owner, coroutine, **_kwargs: pending.append(coroutine),
    )

    app._run_artifact_reference_action(handoff=False)
    await pending.pop()

    assert app.notifications[-1] == (
        "imported-chat cannot be referenced because it is an imported "
        "transcript outside the chats root",
        "warning",
    )


def test_reference_resolver_renders_every_artifacts_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.artifact_refs import (
        ArtifactRefContext,
        ArtifactRefDocumentRoot,
        ArtifactRefProject,
    )

    plans_root = tmp_path / "plans"
    chats_root = tmp_path / "chats"
    plan_path = plans_root / "202607" / "artifact.md"
    chat_path = chats_root / "202607" / "agent.md"
    plan_path.parent.mkdir(parents=True)
    chat_path.parent.mkdir(parents=True)
    plan_path.write_text("# Artifact")
    chat_path.write_text("# Chat")
    context = ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("plans", plans_root),),
        chats_root=chats_root,
        artifact_index_path=tmp_path / "index.jsonl",
        repositories=(),
        projects=(ArtifactRefProject("Alpha", "alpha"),),
    )
    monkeypatch.setattr(
        _resolution,
        "artifact_ref_context",
        lambda *_args, **_kwargs: context,
    )
    sha = "a" * 40
    proposal = SimpleNamespace(plan_path=str(plan_path))
    row = SimpleNamespace(
        row_id="proposal",
        project="alpha",
        kind="proposal",
        proposal=proposal,
        archive=None,
        issue=None,
    )
    cases = (
        (
            "commits",
            _artifacts._ArtifactReferenceItem(
                "commit",
                ("commit", "sase", sha),
                None,
                "alpha",
                str(tmp_path),
            ),
            f"@commit:sase@{sha}",
        ),
        (
            "plans",
            _artifacts._ArtifactReferenceItem(
                "plan",
                ("plan", "alpha", "proposal", "proposal"),
                row,
                "alpha",
                str(tmp_path),
            ),
            "@plans:202607/artifact.md",
        ),
        (
            "chats",
            _artifacts._ArtifactReferenceItem(
                "chat",
                ("chat", str(chat_path)),
                None,
                "alpha",
                str(tmp_path),
            ),
            "@chat:202607/agent.md",
        ),
        (
            "bugs",
            _artifacts._ArtifactReferenceItem(
                "bug",
                ("bug", "alpha", "42"),
                None,
                "alpha",
                str(tmp_path),
            ),
            "@bug:Alpha#42",
        ),
    )
    for subtab, item, expected in cases:
        selection = _artifacts._ArtifactReferenceSelection(
            subtab=subtab,
            items=(item,),
            marked=False,
            prompt_project="alpha",
            prompt_display_name="Alpha",
            prompt_project_file="/tmp/alpha.sase",
        )
        resolved = _artifacts._resolve_artifact_selection(
            selection,
            include_metadata=False,
        )
        assert tuple(f"@{item.reference}" for item in resolved.items) == (expected,)
        assert resolved.failures == ()
