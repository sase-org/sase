"""Tests for archive-source extraction, dedup, and weighting inputs."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from sase.history.prompt_prediction_archive import (
    ARCHIVE_CORPUS_WEIGHT,
    ARCHIVE_SOURCE_ROLE,
    ARCHIVE_TOKEN_BUDGET,
    ArchivePredictionTarget,
    archive_prediction_source_token,
    build_archive_prediction_rows,
    _clean_archive_body,
    _normalize_archive_paragraph,
    _split_archive_paragraphs,
)


def _doc(
    tmp_path: Path,
    month: str,
    name: str,
    body: str,
    *,
    parse_error: str | None = None,
    mtime: float = 1759276800.0,
) -> SimpleNamespace:
    path = tmp_path / "prompts" / month / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return SimpleNamespace(
        path=path,
        relpath=f"prompts/{month}/{name}.md",
        month=month,
        name=name,
        body=body,
        parse_error=parse_error,
    )


def _target(tmp_path: Path, project_key: str = "sase") -> ArchivePredictionTarget:
    return ArchivePredictionTarget(project_key=project_key, sidecar_path=tmp_path)


def _inventory(docs: list[SimpleNamespace]):  # type: ignore[no-untyped-def]
    def run(_root: Path) -> list[SimpleNamespace]:
        return list(docs)

    return run


def test_clean_archive_body_strips_link_tables() -> None:
    body = "Can you help me implement it now\n\n[1]:\n  https://example.test/plan\n"
    assert _clean_archive_body(body) == "Can you help me implement it now"


def test_split_and_normalize_paragraphs() -> None:
    text = "First  paragraph\nwrapped\n\n\nSecond"
    paragraphs = _split_archive_paragraphs(text)
    assert paragraphs == ["First  paragraph\nwrapped", "Second"]
    assert _normalize_archive_paragraph(paragraphs[0]) == "first paragraph wrapped"


def test_rows_tag_project_epoch_and_unset_origin(tmp_path: Path) -> None:
    doc = _doc(tmp_path, "202609", "a", "Help me implement the plan")
    rows = build_archive_prediction_rows(
        history_texts=[],
        targets=(_target(tmp_path),),
        inventory_fn=_inventory([doc]),
    )
    assert len(rows) == 1
    assert rows[0].project == "sase"
    assert rows[0].epoch_seconds == 1759276800
    # Unset origin lets the core origin heuristic exclude generated prompts.
    assert rows[0].origin is None
    assert rows[0].cancelled is False


def test_rows_dedup_within_archive_and_against_history(tmp_path: Path) -> None:
    shared = "Shared swarm copy paragraph"
    first = _doc(tmp_path, "202609", "a", f"{shared}\n\nUnique first words here")
    second = _doc(tmp_path, "202609", "b", f"{shared}\n\nUnique second words here")
    rows = build_archive_prediction_rows(
        history_texts=[f"{shared}\n\nLocal history prose"],
        targets=(_target(tmp_path),),
        inventory_fn=_inventory([first, second]),
    )
    texts = [row.text for row in rows]
    # The swarm copy is seeded from history, so neither row keeps it.
    assert all(shared not in text for text in texts)
    assert any("Unique first words here" in text for text in texts)
    assert any("Unique second words here" in text for text in texts)


def test_rows_skip_parse_errors_and_fully_duplicate_docs(tmp_path: Path) -> None:
    broken = _doc(
        tmp_path, "202609", "broken", "Broken body", parse_error="invalid header"
    )
    dupe = _doc(tmp_path, "202609", "dupe", "Exact same prose")
    rows = build_archive_prediction_rows(
        history_texts=["Exact same prose"],
        targets=(_target(tmp_path),),
        inventory_fn=_inventory([broken, dupe]),
    )
    assert rows == []


def test_rows_bound_to_recent_months(tmp_path: Path) -> None:
    docs = [
        _doc(tmp_path, f"20260{month}", f"doc-{month}", f"Prose for month {month}")
        for month in range(1, 10)
    ]
    rows = build_archive_prediction_rows(
        history_texts=[],
        targets=(_target(tmp_path),),
        inventory_fn=_inventory(docs),
    )
    assert len(rows) == 6
    assert "Prose for month 1" not in [row.text for row in rows]


def test_rows_bound_to_token_budget(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "sase.history.prompt_prediction_archive.ARCHIVE_TOKEN_BUDGET", 4
    )
    assert ARCHIVE_TOKEN_BUDGET > 4
    docs = [
        _doc(tmp_path, "202609", "a", "one two three"),
        _doc(tmp_path, "202609", "b", "four five six"),
    ]
    rows = build_archive_prediction_rows(
        history_texts=[],
        targets=(_target(tmp_path),),
        inventory_fn=_inventory(docs),
    )
    # Newest first (relpath desc): b fits, then a would exceed the budget.
    assert [row.text for row in rows] == ["four five six"]


def test_archive_source_role_and_weight_match_model_contract() -> None:
    assert ARCHIVE_SOURCE_ROLE == "archive"
    assert ARCHIVE_CORPUS_WEIGHT == 0.25


def test_source_token_tracks_month_mtime_and_count(tmp_path: Path) -> None:
    _doc(tmp_path, "202609", "a", "Some prose")
    target = _target(tmp_path)
    (entry,) = archive_prediction_source_token(targets=(target,))
    assert entry[0] == "sase"
    assert entry[1] == "202609"
    assert entry[3] == 1
    _doc(tmp_path, "202609", "b", "More prose")
    (updated,) = archive_prediction_source_token(targets=(target,))
    assert updated[3] == 2
    assert updated != entry
