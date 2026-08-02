"""Tests for the unified prompt-search corpus: archive + local history."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sase.history.prompt_store import PromptEntry, save_prompt_history
from sase.prompt.search.model import PromptHit, PromptSource
from sase.prompt.search.sources import (
    collect_prompt_hits,
    load_archive_prompt_hits,
    load_local_prompt_hits,
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _archive_prompt(
    body: str,
    *,
    plan: str | None = None,
    artifacts: tuple[str, ...] = (),
    frontmatter: str = "",
) -> str:
    lines: list[str] = []
    if frontmatter:
        lines.extend(["---", frontmatter.rstrip(), "---"])
    if plan is not None:
        lines.append(f"- **PLAN:** [{plan}](https://example.test/plans/{plan})")
    lines.extend(
        [
            "- **AGENTS:**",
            "  - [alice.athena.worker](https://example.test/agents/worker)",
        ]
    )
    if artifacts:
        lines.append("- **ARTIFACTS:**")
        lines.extend(
            f"  - [{name}](../../artifacts/202604/{name})" for name in artifacts
        )
    lines.extend(["", body])
    return "\n".join(lines).rstrip() + "\n"


def _by_id(hits: list[PromptHit]) -> dict[str, PromptHit]:
    return {hit.id: hit for hit in hits}


def test_archive_discovers_only_canonical_agents_layout(tmp_path: Path) -> None:
    _write(
        tmp_path / "prompts/202604/canonical.md",
        _archive_prompt("canonical body"),
    )
    _write(
        tmp_path / "plans/202604/prompts/legacy.md",
        "legacy plans snapshot\n",
    )
    _write(tmp_path / "prompts/README.md", "# Prompt index\n")

    hits = load_archive_prompt_hits(tmp_path)

    assert [hit.id for hit in hits] == ["canonical"]
    assert hits[0].source is PromptSource.ARCHIVE
    assert hits[0].path == "prompts/202604/canonical.md"


def test_archive_loader_empty_when_no_prompts_dir(tmp_path: Path) -> None:
    assert load_archive_prompt_hits(tmp_path) == []


def test_archive_strips_header_and_reads_metadata(tmp_path: Path) -> None:
    _write(
        tmp_path / "prompts/202604/widget.md",
        _archive_prompt(
            "#widget Fix the rendering bug.\nSecond line.",
            plan="202604/widget_plan.md",
            artifacts=("diagram.png", "trace.txt"),
        ),
    )

    hit = load_archive_prompt_hits(tmp_path)[0]

    assert hit.text == "#widget Fix the rendering bug.\nSecond line."
    assert "AGENTS" not in hit.text
    assert hit.title == "Fix the rendering bug."
    assert hit.plan == "202604/widget_plan.md"
    assert hit.artifact_count == 2
    assert hit.tags == ("widget",)
    assert hit.cancelled is None


def test_archive_date_prefers_frontmatter_then_month(tmp_path: Path) -> None:
    _write(
        tmp_path / "prompts/202604/dated.md",
        _archive_prompt(
            "dated body",
            frontmatter="last_used: '260512_143000'",
        ),
    )
    _write(
        tmp_path / "prompts/202604/undated.md",
        _archive_prompt("undated body"),
    )

    hits = _by_id(load_archive_prompt_hits(tmp_path))

    assert hits["dated"].date == "260512_143000"
    assert hits["undated"].date == "260401_000000"


def test_archive_tags_combine_frontmatter_and_body(tmp_path: Path) -> None:
    _write(
        tmp_path / "prompts/202604/tagged.md",
        _archive_prompt(
            "Look at #review and #widget.",
            frontmatter="prompt_tags: [review, auth]",
        ),
    )

    hit = load_archive_prompt_hits(tmp_path)[0]

    assert set(hit.tags) == {"review", "auth", "widget"}
    assert sum(tag.casefold() == "review" for tag in hit.tags) == 1


@pytest.mark.usefixtures("history_file")
def test_local_adapter_shape_includes_cancelled() -> None:
    save_prompt_history(
        [
            PromptEntry(
                text="launched prompt about tui",
                timestamp="260601_090000",
                last_used="260601_090000",
            ),
            PromptEntry(
                text="cancelled draft prompt",
                timestamp="260602_090000",
                last_used="260602_090000",
                cancelled=True,
            ),
        ]
    )

    hits = load_local_prompt_hits()
    by_text = {hit.text: hit for hit in hits}

    assert len(hits) == 2
    assert by_text["launched prompt about tui"].source is PromptSource.LOCAL
    assert by_text["launched prompt about tui"].artifact_count is None
    assert by_text["cancelled draft prompt"].cancelled is True


@pytest.mark.usefixtures("history_file")
def test_collect_dedup_prefers_archive_and_annotates(tmp_path: Path) -> None:
    shared = "Shared prompt about authentication token rotation."
    sha = _sha256(shared)
    _write(
        tmp_path / "prompts/202605/rotate.md",
        _archive_prompt(
            shared,
            frontmatter=f"sha256: {sha}\nlast_used: '260512_143000'",
        ),
    )
    _write(
        tmp_path / "prompts/202605/archive_only.md",
        _archive_prompt("only in archive"),
    )
    save_prompt_history(
        [
            PromptEntry(
                text=shared,
                timestamp="260512_143000",
                last_used="260512_143000",
            ),
            PromptEntry(
                text="local only prompt",
                timestamp="260601_090000",
                last_used="260601_090000",
            ),
        ]
    )

    hits = collect_prompt_hits([PromptSource.ARCHIVE, PromptSource.LOCAL], tmp_path)

    shared_hits = [hit for hit in hits if hit.text_sha256 == sha]
    assert len(shared_hits) == 1
    assert shared_hits[0].source is PromptSource.ARCHIVE
    assert shared_hits[0].also_in_local is True
    assert "archive_only" in {hit.id for hit in hits}
    assert any(hit.text == "local only prompt" for hit in hits)


@pytest.mark.usefixtures("history_file")
def test_collect_single_source_skips_the_other(tmp_path: Path) -> None:
    _write(
        tmp_path / "prompts/202605/only.md",
        _archive_prompt("archive body"),
    )
    save_prompt_history(
        [
            PromptEntry(
                text="local body",
                timestamp="260601_090000",
                last_used="260601_090000",
            )
        ]
    )

    archive_only = collect_prompt_hits([PromptSource.ARCHIVE], tmp_path)
    local_only = collect_prompt_hits([PromptSource.LOCAL], None)

    assert {hit.source for hit in archive_only} == {PromptSource.ARCHIVE}
    assert {hit.source for hit in local_only} == {PromptSource.LOCAL}
