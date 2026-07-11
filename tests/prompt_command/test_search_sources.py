"""Tests for the unified prompt-search corpus: SDD + local loaders and dedup."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sase.history.prompt_store import PromptEntry, save_prompt_history
from sase.prompt.search.model import PromptHit, PromptSource
from sase.prompt.search.sources import (
    collect_prompt_hits,
    load_local_prompt_hits,
    load_sdd_prompt_hits,
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _by_id(hits: list[PromptHit]) -> dict[str, PromptHit]:
    return {hit.id: hit for hit in hits}


# ---------------------------------------------------------------------------
# SDD discovery across layouts
# ---------------------------------------------------------------------------


def test_sdd_discovers_canonical_legacy_and_local_layouts(tmp_path: Path) -> None:
    _write(tmp_path / "sdd" / "prompts" / "202604" / "canonical.md", "canonical body\n")
    _write(tmp_path / "prompts" / "legacy.md", "legacy body\n")
    # The local layout is reached by pointing base_dir at a ``.sase/sdd`` root.
    _write(
        tmp_path / "local_sdd" / "prompts" / "202605" / "localmode.md", "local body\n"
    )

    hits = _by_id(load_sdd_prompt_hits(tmp_path))
    assert set(hits) == {"canonical", "legacy"}
    assert all(hit.source is PromptSource.SDD for hit in hits.values())

    local_hits = _by_id(load_sdd_prompt_hits(tmp_path / "local_sdd"))
    assert "localmode" in local_hits


def test_sdd_project_root_includes_local_sase_sdd(tmp_path: Path) -> None:
    # A normal project-root scan must also surface the project-local
    # ``.sase/sdd/prompts`` store, not only the committed canonical/legacy roots.
    _write(tmp_path / "sdd" / "prompts" / "202604" / "canonical.md", "canonical body\n")
    _write(
        tmp_path / ".sase" / "sdd" / "prompts" / "202605" / "localsnap.md",
        "local snapshot body\n",
    )

    hits = _by_id(load_sdd_prompt_hits(tmp_path))
    assert set(hits) == {"canonical", "localsnap"}
    assert all(hit.source is PromptSource.SDD for hit in hits.values())
    # The local hit's path is reported relative to the project root.
    assert hits["localsnap"].path == ".sase/sdd/prompts/202605/localsnap.md"


def test_sdd_no_duplicate_when_local_root_overlaps(tmp_path: Path) -> None:
    # When *base_dir* is itself a ``.sase/sdd`` root, the canonical ``prompts/``
    # arm and the appended local ``.sase/sdd/prompts`` arm both reach the same
    # file; resolved-path de-dup must keep it to a single hit.
    sdd_root = tmp_path / ".sase" / "sdd"
    _write(sdd_root / "prompts" / "202605" / "localmode.md", "local body\n")
    hits = load_sdd_prompt_hits(sdd_root)
    assert [hit.id for hit in hits] == ["localmode"]


def test_sdd_loader_empty_when_no_prompts_dir(tmp_path: Path) -> None:
    assert load_sdd_prompt_hits(tmp_path) == []


def test_sdd_hit_relative_path_and_locator(tmp_path: Path) -> None:
    _write(tmp_path / "sdd" / "prompts" / "202604" / "kitty_panel.md", "body\n")
    hit = load_sdd_prompt_hits(tmp_path)[0]
    assert hit.id == "kitty_panel"
    assert hit.path == "sdd/prompts/202604/kitty_panel.md"


# ---------------------------------------------------------------------------
# Frontmatter parse, body strip, title, plan, date
# ---------------------------------------------------------------------------


def test_sdd_strips_frontmatter_from_text_and_reads_plan(tmp_path: Path) -> None:
    _write(
        tmp_path / "sdd" / "prompts" / "202604" / "foo.md",
        "---\nplan: sdd/plans/202604/foo.md\n---\n\nFix the widget thoroughly.\n",
    )
    hit = load_sdd_prompt_hits(tmp_path)[0]
    assert hit.text == "Fix the widget thoroughly."
    assert "plan:" not in hit.text
    assert hit.plan == "sdd/plans/202604/foo.md"
    assert hit.cancelled is None


def test_sdd_title_is_cleaned_first_line(tmp_path: Path) -> None:
    _write(
        tmp_path / "sdd" / "prompts" / "202604" / "foo.md",
        "#widget Fix the rendering bug.\nSecond line ignored.\n",
    )
    hit = load_sdd_prompt_hits(tmp_path)[0]
    # The ``#widget`` chip is stripped from the preview title.
    assert hit.title == "Fix the rendering bug."


def test_sdd_title_falls_back_to_locator_for_empty_body(tmp_path: Path) -> None:
    _write(
        tmp_path / "sdd" / "prompts" / "202604" / "empty_body.md", "---\nplan: x\n---\n"
    )
    hit = load_sdd_prompt_hits(tmp_path)[0]
    assert hit.title == "empty_body"


def test_sdd_date_precedence_frontmatter_then_path(tmp_path: Path) -> None:
    # ``prompt export`` quotes SASE timestamps so YAML round-trips them as
    # strings (unquoted, ``260512_143000`` would parse as an integer).
    _write(
        tmp_path / "sdd" / "prompts" / "202604" / "dated.md",
        "---\nlast_used: '260512_143000'\n---\nbody\n",
    )
    _write(tmp_path / "sdd" / "prompts" / "202604" / "undated.md", "body\n")
    hits = _by_id(load_sdd_prompt_hits(tmp_path))
    assert hits["dated"].date == "260512_143000"  # frontmatter wins
    assert hits["undated"].date == "260401_000000"  # path YYYYMM fallback


def test_sdd_tolerates_malformed_frontmatter(tmp_path: Path) -> None:
    _write(
        tmp_path / "sdd" / "prompts" / "202604" / "broken.md",
        "---\nplan: [unclosed\n: : :\n---\nstill scanned\n",
    )
    _write(tmp_path / "sdd" / "prompts" / "202604" / "ok.md", "fine\n")
    hits = _by_id(load_sdd_prompt_hits(tmp_path))
    # The broken file is still included rather than aborting the scan.
    assert set(hits) == {"broken", "ok"}


# ---------------------------------------------------------------------------
# Tag extraction
# ---------------------------------------------------------------------------


def test_sdd_tags_combine_frontmatter_and_body(tmp_path: Path) -> None:
    _write(
        tmp_path / "sdd" / "prompts" / "202604" / "tagged.md",
        "---\nprompt_tags: [review, auth]\n---\nLook at #review and #widget.\n",
    )
    hit = load_sdd_prompt_hits(tmp_path)[0]
    assert "review" in hit.tags
    assert "auth" in hit.tags
    assert "widget" in hit.tags  # chip name, sigil stripped
    # Tags are de-duplicated case-insensitively (``review`` from frontmatter
    # and the ``#review`` chip collapse to one).
    assert sum(1 for t in hit.tags if t.lower() == "review") == 1


def test_sdd_tags_accept_comma_delimited_string(tmp_path: Path) -> None:
    _write(
        tmp_path / "sdd" / "prompts" / "202604" / "csv.md",
        "---\nprompt_tags: review, auth\n---\nbody\n",
    )
    hit = load_sdd_prompt_hits(tmp_path)[0]
    assert set(hit.tags) == {"review", "auth"}


def test_sdd_no_tags_when_absent(tmp_path: Path) -> None:
    _write(tmp_path / "sdd" / "prompts" / "202604" / "plain.md", "just prose here\n")
    hit = load_sdd_prompt_hits(tmp_path)[0]
    assert hit.tags == ()


# ---------------------------------------------------------------------------
# Local adapter
# ---------------------------------------------------------------------------


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
    assert len(hits) == 2  # both launched and cancelled are loaded
    by_text = {hit.text: hit for hit in hits}
    launched = by_text["launched prompt about tui"]
    assert launched.source is PromptSource.LOCAL
    assert launched.id.startswith("ph_")
    assert launched.path is None
    assert launched.plan is None
    assert launched.date == "260601_090000"
    assert launched.cancelled is False
    assert by_text["cancelled draft prompt"].cancelled is True


@pytest.mark.usefixtures("history_file")
def test_local_adapter_extracts_body_tags() -> None:
    save_prompt_history(
        [
            PromptEntry(
                text="please run #widget and #review now",
                timestamp="260601_090000",
                last_used="260601_090000",
            ),
        ]
    )
    hit = load_local_prompt_hits()[0]
    assert "widget" in hit.tags
    assert "review" in hit.tags


@pytest.mark.usefixtures("history_file")
def test_local_adapter_text_sha256_matches_content() -> None:
    text = "a unique local prompt for hashing"
    save_prompt_history(
        [PromptEntry(text=text, timestamp="260601_090000", last_used="260601_090000")]
    )
    hit = load_local_prompt_hits()[0]
    assert hit.text_sha256 == _sha256(text)


# ---------------------------------------------------------------------------
# collect_prompt_hits: unification + dedup
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("history_file")
def test_collect_dedup_prefers_sdd_and_annotates(tmp_path: Path) -> None:
    shared = "Shared prompt about authentication token rotation."
    sha = _sha256(shared)
    _write(
        tmp_path / "sdd" / "prompts" / "202605" / "rotate.md",
        f"---\nsha256: {sha}\nlast_used: 260512_143000\n---\n\n{shared}\n",
    )
    _write(tmp_path / "sdd" / "prompts" / "202605" / "sdd_only.md", "only in sdd\n")
    save_prompt_history(
        [
            PromptEntry(
                text=shared, timestamp="260512_143000", last_used="260512_143000"
            ),
            PromptEntry(
                text="local only prompt",
                timestamp="260601_090000",
                last_used="260601_090000",
            ),
        ]
    )

    hits = collect_prompt_hits([PromptSource.SDD, PromptSource.LOCAL], tmp_path)

    shared_hits = [hit for hit in hits if hit.text_sha256 == sha]
    assert len(shared_hits) == 1  # collapsed to a single hit
    assert shared_hits[0].source is PromptSource.SDD  # SDD prioritized
    assert shared_hits[0].also_in_local is True  # annotated
    # The non-duplicate hits from both stores survive.
    ids = {hit.id for hit in hits}
    assert "sdd_only" in ids
    assert any(hit.text == "local only prompt" for hit in hits)


@pytest.mark.usefixtures("history_file")
def test_collect_single_source_skips_the_other(tmp_path: Path) -> None:
    _write(tmp_path / "sdd" / "prompts" / "202605" / "only.md", "sdd body\n")
    save_prompt_history(
        [
            PromptEntry(
                text="local body", timestamp="260601_090000", last_used="260601_090000"
            )
        ]
    )

    sdd_only = collect_prompt_hits([PromptSource.SDD], tmp_path)
    assert {hit.source for hit in sdd_only} == {PromptSource.SDD}

    local_only = collect_prompt_hits([PromptSource.LOCAL], tmp_path)
    assert {hit.source for hit in local_only} == {PromptSource.LOCAL}


@pytest.mark.usefixtures("history_file")
def test_collect_no_dedup_without_recorded_sha(tmp_path: Path) -> None:
    # An SDD snapshot whose body sha differs from the local entry is never
    # collapsed: dedup is strictly digest-based and conservative.
    _write(tmp_path / "sdd" / "prompts" / "202605" / "p.md", "body text one\n")
    save_prompt_history(
        [
            PromptEntry(
                text="different body text",
                timestamp="260601_090000",
                last_used="260601_090000",
            )
        ]
    )
    hits = collect_prompt_hits([PromptSource.SDD, PromptSource.LOCAL], tmp_path)
    assert len(hits) == 2
    assert not any(hit.also_in_local for hit in hits)
