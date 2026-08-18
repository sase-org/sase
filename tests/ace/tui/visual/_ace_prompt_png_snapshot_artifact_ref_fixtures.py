"""Stable artifact-reference kinds for ACE prompt PNG snapshots."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

_VISUAL_ARTIFACT_REF_KINDS = frozenset(
    {
        "commit",
        "chat",
        "bug",
        "file",
        "bead",
        "agent",
        "plans",
        "designs",
    }
)


def patch_visual_artifact_ref_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.ace.tui.widgets import _artifact_ref_highlight

    def _known(
        project: str | None,
        _workspace_dir: str | None,
        _workspace_num: int,
    ) -> _artifact_ref_highlight._KnownKindsResult:
        return _artifact_ref_highlight._KnownKindsResult(
            project,
            _VISUAL_ARTIFACT_REF_KINDS,
        )

    monkeypatch.setattr(
        _artifact_ref_highlight,
        "_load_known_artifact_ref_kinds",
        _known,
    )


def seed_visual_artifact_ref_kinds(text_area: PromptTextArea) -> None:
    """Install stable known artifact kinds after a visual prompt is mounted."""
    project = text_area._xprompt_arg_assist_project_from_text()
    text_area._artifact_ref_known_kinds_by_project[project] = _VISUAL_ARTIFACT_REF_KINDS
    text_area._artifact_ref_kinds_warming.discard(project)
    text_area._build_highlight_map()
    text_area.refresh()
