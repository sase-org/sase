"""End-to-end CLI coverage for the ``json`` and ``full`` search renderers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from sase.prompt.cli_search import handle_prompt_search
from sase.prompt.cli_show import handle_prompt_show

from ._helpers import _entry, _prompt_id, _seed


def _ns(query: str, **overrides: object) -> argparse.Namespace:
    """Build a search Namespace with the parser defaults, overridable per test."""
    base: dict[str, object] = {
        "query": query,
        "after": None,
        "before": None,
        "color": "never",
        "format": "compact",
        "limit": 20,
        "source": "all",
        "tag": None,
        "cancelled": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _write_archive(base: Path, month: str, name: str, content: str) -> None:
    path = base / "prompts" / month / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run the search handler from an isolated repo root (for archive discovery)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.prompt.cli_search.resolve_prompt_archive_root", lambda: tmp_path
    )
    return tmp_path


# Documented, stable key orders (the JSON envelope is a downstream contract).
_ENVELOPE_KEYS = ["query", "count", "total", "counts", "results"]
_RESULT_KEYS = [
    "source",
    "id",
    "path",
    "title",
    "date",
    "matched_fields",
    "tags",
    "plan",
    "artifact_count",
    "cancelled",
    "text_sha256",
    "text_chars",
    "text",
]


# ---------------------------------------------------------------------------
# json renderer
# ---------------------------------------------------------------------------


def test_json_envelope_shape_and_keys(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_archive(
        repo,
        "202604",
        "auth_snapshot",
        "---\nprompt_tags: [review]\n---\n"
        "- **PLAN:** [202604/auth.md](https://example.test/plans/auth)\n"
        "- **ARTIFACTS:**\n"
        "  - [trace.txt](../../artifacts/202604/trace.txt)\n\n"
        "Rotate auth tokens nightly.\n",
    )
    _seed(_entry("retry the auth flow on failure", "260601_000000"))

    handle_prompt_search(_ns("auth", format="json"))
    payload = json.loads(capsys.readouterr().out)

    # Envelope keys are present, in the documented stable order.
    assert list(payload.keys()) == _ENVELOPE_KEYS
    assert payload["query"] == "auth"
    assert payload["count"] == 2
    assert payload["total"] == 2
    assert payload["counts"] == {"archive": 1, "local": 1}

    # archive ranks first; every documented result key is present, in order.
    archive, local = payload["results"]
    assert list(archive.keys()) == _RESULT_KEYS
    assert archive["source"] == "archive"
    assert archive["id"] == "auth_snapshot"
    assert archive["path"] == "prompts/202604/auth_snapshot.md"
    assert archive["date"] == "2026-04-01"  # frontmatter-less → YYYYMM path fallback
    assert archive["plan"] == "202604/auth.md"
    assert archive["artifact_count"] == 1
    assert archive["tags"] == ["review"]
    assert archive["cancelled"] is None
    assert "body" in archive["matched_fields"]
    # Full text is carried (parity with prompt show -f json).
    assert archive["text"] == "Rotate auth tokens nightly."
    assert archive["text_chars"] == len("Rotate auth tokens nightly.")

    assert local["source"] == "local"
    assert local["id"] == _prompt_id("retry the auth flow on failure")
    assert local["path"] is None
    assert local["date"] == "2026-06-01"
    assert local["cancelled"] is False
    assert local["text"] == "retry the auth flow on failure"


def test_json_is_never_colored(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("auth token rotation", "260601_000000"))
    # Even with --color always, json must stay machine-clean.
    handle_prompt_search(_ns("auth", source="local", format="json", color="always"))
    out = capsys.readouterr().out
    assert "\x1b[" not in out
    json.loads(out)  # still valid json


def test_json_no_match_is_empty_envelope(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("totally unrelated", "260601_000000"))
    handle_prompt_search(_ns("zzzznotpresent", format="json"))
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 0
    assert payload["total"] == 0
    assert payload["counts"] == {"archive": 0, "local": 0}
    assert payload["results"] == []


def test_json_truncation_reports_count_total_counts(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("auth one", "260601_000000"),
        _entry("auth two", "260602_000000"),
        _entry("auth three", "260603_000000"),
    )
    handle_prompt_search(_ns("auth", source="local", format="json", limit=2))
    payload = json.loads(capsys.readouterr().out)
    # count reflects the truncated, shown set; total/counts are pre-limit.
    assert payload["count"] == 2
    assert len(payload["results"]) == 2
    assert payload["total"] == 3
    assert payload["counts"] == {"archive": 0, "local": 3}


def test_json_date_is_null_when_undatable(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A snapshot under a non-month dir with no frontmatter date and a 0 mtime
    # would floor; simpler: an undated frontmatter still resolves via mtime, so
    # assert the null path through a local entry whose date is the floor.
    _seed(_entry("auth floor", "000000_000000"))
    handle_prompt_search(_ns("auth", source="local", format="json"))
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["date"] is None


# ---------------------------------------------------------------------------
# full renderer
# ---------------------------------------------------------------------------


def test_full_renders_archive_metadata_and_body(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_archive(
        repo,
        "202604",
        "auth_snapshot",
        "---\nprompt_tags: [review]\n---\n"
        "- **PLAN:** [202604/auth.md](https://example.test/plans/auth)\n"
        "- **ARTIFACTS:**\n"
        "  - [trace.txt](../../artifacts/202604/trace.txt)\n\n"
        "Rotate auth tokens nightly.\n",
    )
    handle_prompt_search(_ns("auth", source="archive", format="full"))
    out = capsys.readouterr().out
    # Per-hit header: badge + locator + date.
    assert "archive" in out
    assert "auth_snapshot" in out
    assert "2026-04-01" in out
    # Compact metadata header for the archive-specific fields.
    assert "path: prompts/202604/auth_snapshot.md" in out
    assert "plan: 202604/auth.md" in out
    assert "artifacts: 1" in out
    assert "tags: review" in out
    # The body is rendered in full.
    assert "Rotate auth tokens nightly." in out


def test_full_highlights_match_when_colored(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_archive(repo, "202604", "auth_snapshot", "Rotate auth tokens nightly.\n")
    handle_prompt_search(_ns("auth", source="archive", format="full", color="always"))
    out = capsys.readouterr().out
    assert "\x1b[" in out
    assert "33m" in out  # bold-yellow highlight on the matched term


def test_full_renders_local_markdown(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("deploy the auth service", "260601_000000"))
    handle_prompt_search(_ns("auth", source="local", format="full"))
    out = capsys.readouterr().out
    prompt_id = _prompt_id("deploy the auth service")
    # Per-hit header plus the reused prompt-show markdown body.
    assert f"# Prompt {prompt_id}" in out
    assert "- cancelled: false" in out
    assert "deploy the auth service" in out


def test_full_local_matches_prompt_show_markdown(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("rotate the auth credentials", "260601_000000"))
    prompt_id = _prompt_id("rotate the auth credentials")

    # The canonical prompt-show markdown rendering.
    handle_prompt_show(argparse.Namespace(id=prompt_id, format="markdown"))
    show_md = capsys.readouterr().out

    # The full search output must embed that exact rendering (no drift).
    handle_prompt_search(_ns("auth", source="local", format="full"))
    full_out = capsys.readouterr().out
    assert show_md in full_out


def test_full_divides_consecutive_hits(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_archive(repo, "202604", "auth_snapshot", "auth in the snapshot\n")
    _seed(_entry("auth in local history", "260601_000000"))
    handle_prompt_search(_ns("auth", format="full"))
    out = capsys.readouterr().out
    assert "─" * 72 in out  # the divider between the two hits


def test_full_no_match_message(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(_entry("totally unrelated", "260601_000000"))
    handle_prompt_search(_ns("zzzznotpresent", format="full"))
    out = capsys.readouterr().out
    assert 'No prompts match "zzzznotpresent".' in out


def test_full_footer_reports_truncation(
    repo: Path,
    history_file: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed(
        _entry("auth one", "260601_000000"),
        _entry("auth two", "260602_000000"),
        _entry("auth three", "260603_000000"),
    )
    handle_prompt_search(_ns("auth", source="local", format="full", limit=2))
    out = capsys.readouterr().out
    assert "3 matches (0 archive · 3 local)" in out
    assert "showing 2" in out
