"""Family detail-panel hint and link tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sase.ace.changespec.models import DeltaEntry, DeltaLineStats
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    cache_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
    HeaderHintState,
)
from sase.ace.tui.widgets.prompt_panel._artifact_files import ArtifactFilePath
from sase.ace.tui.widgets.prompt_panel._hint_caps import (
    HINT_TRUNCATION_MESSAGE,
    HintContentBudget,
)
from tests.ace.tui.widgets._agent_display_family_helpers import make_family
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of
from tests.ace.tui.widgets._agent_display_plan_helpers import plan_summary


def test_family_hint_render_returns_cached_plan_delta_artifact_and_commit_views(
    tmp_path: Path,
) -> None:
    root, _child = make_family(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan_path = tmp_path / "approved-plan.md"
    artifact_path = tmp_path / "report.txt"
    root.workspace_dir = str(workspace)
    root.step_output = {
        "meta_commits": [
            {
                "message": "feat: preserve family hints\n\nBody line",
                "sha": "abcdef1234567890",
                "cwd": str(workspace),
            }
        ]
    }
    panel = FakePromptPanel()
    cache_detail_header_summary(
        panel,
        root,
        DetailHeaderSummary(
            associated_plan=plan_summary(
                actual_path=str(plan_path),
                display_path="sase/repos/plans/approved-plan.md",
            ),
            delta_entries=[
                DeltaEntry(
                    path="src/family.py",
                    change_type="M",
                    line_stats=DeltaLineStats(modified=2),
                )
            ],
            artifact_file_paths=[
                ArtifactFilePath(
                    display_path="report.txt",
                    actual_path=str(artifact_path),
                )
            ],
        ),
    )

    result = panel.update_display_with_hints(root)
    plain = plain_of(panel.captured[-1])

    assert result.file_hints == {
        1: str(plan_path),
        3: str(workspace / "src/family.py"),
        4: str(artifact_path),
    }
    assert list(result.commit_views) == [2]
    assert result.commit_views[2].sha == "abcdef1234567890"
    assert result.commit_views[2].cwd == str(workspace)
    assert "Path: [1] sase/repos/plans/approved-plan.md" in plain
    assert "[2] abcdef123456 feat: preserve family hints" in plain
    assert "[3] src/family.py" in plain
    assert "[4] report.txt" in plain
    assert not result.header_enrichment_pending


def test_family_content_hints_are_full_at_both_levels_and_use_phase_workspace(
    tmp_path: Path,
) -> None:
    root, child = make_family(tmp_path)
    root_workspace = tmp_path / "root-workspace"
    child_workspace = tmp_path / "child-workspace"
    root_workspace.mkdir()
    child_workspace.mkdir()
    root.workspace_dir = str(root_workspace)
    child.workspace_dir = str(child_workspace)

    root_dir = Path(root.artifacts_dir or "")
    child_dir = Path(child.artifacts_dir or "")
    (root_dir / "raw_xprompt.md").write_text(
        "@docs/visible-xprompt.md\n"
        + "\n".join(f"xprompt filler {index}" for index in range(2, 15))
        + "\n@docs/hidden-xprompt.md\n",
        encoding="utf-8",
    )
    (root_dir / "01_prompt.md").write_text(
        "src/visible-prompt.py\n"
        + "\n".join(f"prompt filler {index}" for index in range(2, 15))
        + "\nsrc/hidden-prompt.py\n",
        encoding="utf-8",
    )
    (root_dir / "response.md").write_text(
        "root/hidden-reply.txt\nroot filler 2\nroot filler 3\n"
        "root filler 4\nroot filler 5\nroot/visible-reply.txt\n",
        encoding="utf-8",
    )
    (child_dir / "response.md").write_text(
        "child/hidden-reply.txt\nchild filler 2\nchild filler 3\n"
        "child filler 4\nchild filler 5\nchild/visible-reply.txt\n",
        encoding="utf-8",
    )

    expected_paths = {
        str(root_workspace / "docs/visible-xprompt.md"),
        str(root_workspace / "docs/hidden-xprompt.md"),
        str(root_workspace / "src/visible-prompt.py"),
        str(root_workspace / "src/hidden-prompt.py"),
        str(root_workspace / "root/hidden-reply.txt"),
        str(root_workspace / "root/visible-reply.txt"),
        str(child_workspace / "child/hidden-reply.txt"),
        str(child_workspace / "child/visible-reply.txt"),
    }
    rendered_paths: list[set[str]] = []
    for level in (FoldLevel.EXPANDED, FoldLevel.FULLY_EXPANDED):
        panel = FakePromptPanel()
        panel.app = SimpleNamespace(
            panel_fold_level=level,
            _panel_fold_overrides=SimpleNamespace(snapshot=lambda: {}),
        )
        cache_detail_header_summary(panel, root, DetailHeaderSummary())

        result = panel.update_display_with_hints(root)
        rendered_paths.append(set(result.file_hints.values()))

    assert rendered_paths == [expected_paths, expected_paths]


@pytest.mark.parametrize("level", [FoldLevel.EXPANDED, FoldLevel.FULLY_EXPANDED])
def test_family_hint_render_caps_total_member_content(
    tmp_path: Path,
    level: FoldLevel,
) -> None:
    root, child = make_family(tmp_path)
    root_workspace = tmp_path / "root-workspace"
    child_workspace = tmp_path / "child-workspace"
    root_workspace.mkdir()
    child_workspace.mkdir()
    root.workspace_dir = str(root_workspace)
    child.workspace_dir = str(child_workspace)
    root_reply = Path(root.response_path or "")
    child_reply = Path(child.response_path or "")
    root_reply.write_text(
        "root/head.py\n" + ("root filler\n" * 8_000) + "root/tail.py\n",
        encoding="utf-8",
    )
    child_reply.write_text(
        "child/head.py\n" + ("child filler\n" * 8_000) + "child/tail.py\n",
        encoding="utf-8",
    )
    panel = FakePromptPanel()
    panel.app = SimpleNamespace(
        panel_fold_level=level,
        _panel_fold_overrides=SimpleNamespace(snapshot=lambda: {}),
    )
    cache_detail_header_summary(panel, root, DetailHeaderSummary())

    result = panel.update_display_with_hints(root)
    plain = plain_of(panel.captured[-1])

    assert HINT_TRUNCATION_MESSAGE in plain
    assert list(result.file_hints) == list(range(1, len(result.file_hints) + 1))
    assert str(root_workspace / "root/head.py") in result.file_hints.values()
    assert str(child_workspace / "child/tail.py") not in result.file_hints.values()


def test_family_reply_resolves_workspace_once_for_all_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _child = make_family(tmp_path)
    chunks = [
        (
            datetime(2026, 7, 18, 12, minute).isoformat(),
            f"see src/chunk-{minute}.py",
        )
        for minute in range(3)
    ]
    monkeypatch.setattr(
        Agent,
        "get_timestamped_reply_chunks",
        lambda _agent: chunks,
    )
    resolve_workspace = Mock(return_value="/workspace")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_family_render."
        "resolve_agent_workspace_dir",
        resolve_workspace,
    )
    panel = FakePromptPanel()
    hint_state = HeaderHintState(1, {}, None, {})

    panel._family_reply_renderables_with_hints(
        root,
        hint_state,
        budget=HintContentBudget(),
    )

    resolve_workspace.assert_called_once()
    assert hint_state.hint_mappings == {
        1: "/workspace/src/chunk-0.py",
        2: "/workspace/src/chunk-1.py",
        3: "/workspace/src/chunk-2.py",
    }
