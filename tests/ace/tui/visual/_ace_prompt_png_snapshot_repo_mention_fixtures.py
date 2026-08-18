"""Deterministic repo-mention catalog fixtures for ACE prompt PNG snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui import AceApp
from sase.ace.tui.repo_mention_catalog import PromptRepoMentionContext
from sase.repo_inventory import RepoRecord
from sase.xprompt.glossary_catalog import EditorGlossaryProject
from sase.xprompt.repo_mention_catalog import EditorRepoMentionCatalog, RepoMention
from tests.ace.tui.visual._ace_prompt_png_snapshot_wire import (
    VisualCompiledSpans,
    visual_editor_range,
    visual_literal_ranges,
    visual_span_segment,
)


def patch_visual_repo_mention_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _visual_repo_mention_catalog()

    def _catalog(
        _app: AceApp,
        _context: PromptRepoMentionContext,
        *,
        schedule: bool = True,
    ) -> EditorRepoMentionCatalog:
        del schedule
        return catalog

    def _warm(
        _app: AceApp,
        _context: PromptRepoMentionContext,
    ) -> None:
        return None

    monkeypatch.setattr(AceApp, "get_prompt_repo_mention_catalog", _catalog)
    monkeypatch.setattr(
        AceApp,
        "is_prompt_repo_mention_catalog_warm",
        lambda _app, _context: True,
    )
    monkeypatch.setattr(AceApp, "warm_prompt_repo_mention_catalog", _warm)


class _VisualCompiledRepoMentions(VisualCompiledSpans):
    def __init__(self, mentions: tuple[RepoMention, ...]) -> None:
        self._mentions = mentions

    def scan(self, text: str) -> list[dict[str, Any]]:
        literal_ranges = visual_literal_ranges(text)
        spans: list[dict[str, Any]] = []
        for mention in self._mentions:
            identifier = mention.identifier
            start = 0
            literal_index = 0
            while True:
                found = text.find(identifier, start)
                if found == -1:
                    break
                end = found + len(identifier)
                while (
                    literal_index < len(literal_ranges)
                    and literal_ranges[literal_index][1] <= found
                ):
                    literal_index += 1
                if (
                    literal_index < len(literal_ranges)
                    and literal_ranges[literal_index][0] < end
                ):
                    start = end
                    continue
                spans.append(_visual_repo_mention_span_wire(text, mention, found, end))
                start = end
        return spans


def _visual_repo_mention_catalog() -> EditorRepoMentionCatalog:
    config_path = Path("/workspace/sase/sase.yml")
    record = RepoRecord(
        name="sase-core",
        kind="linked",
        project="sase",
        project_key="sase",
        path="/workspace/sase/repos/linked/sase-core",
        exists=True,
        auto_clone=True,
        description="Shared Rust core backend.",
        source="test",
        env_name="SASE_CORE",
        slug=None,
    )
    mention = RepoMention(
        identifier="sase-core",
        kind="linked",
        record=record,
        index=0,
        config_path=str(config_path),
        config_line=216,
        config_col=7,
    )
    return EditorRepoMentionCatalog(
        schema_version=1,
        project=EditorGlossaryProject(
            key="sase",
            name="sase",
            aliases=("sase-org",),
            workspace_dir=Path("/workspace/sase"),
        ),
        mentions=(mention,),
        compiled=_VisualCompiledRepoMentions((mention,)),
    )


def _visual_repo_mention_span_wire(
    text: str,
    mention: RepoMention,
    start: int,
    end: int,
) -> dict[str, Any]:
    return {
        "term": mention.identifier,
        "entry_index": mention.index,
        "alias_index": 0,
        "alias": mention.identifier,
        "matched_text": text[start:end],
        "byte_start": len(text[:start].encode("utf-8")),
        "byte_end": len(text[:end].encode("utf-8")),
        "range": visual_editor_range(text, start, end),
        "segments": [visual_span_segment(text, start, end)],
    }
