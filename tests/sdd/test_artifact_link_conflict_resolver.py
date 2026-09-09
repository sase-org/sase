"""Artifact-link semantic conflict resolver coverage."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

import sase.sdd._artifact_link_conflict_resolver as resolver_mod
import sase.sdd._artifact_link_markdown_conflict_resolver as markdown_resolver_mod
from sase.sdd._artifact_link_conflict_resolver import resolve_artifact_link_conflicts
from sase.sdd._semantic_conflict_resolver import resolve_semantic_conflicts

LINK_PATH = "links/202609/a.md.json"
ARTIFACT_REF = "plan:202609/a.md"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "--initial-branch=master")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def _row(source: str, description: str, created_at: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "source_ref": source,
        "relation": "cites",
        "target_ref": ARTIFACT_REF,
        "description": description,
        "origin": "manual",
        "created_by": source,
        "created_at": created_at,
        "uses": 1,
    }


def _index(
    rows: list[dict[str, Any]],
    *,
    artifact_ref: str = ARTIFACT_REF,
) -> dict[str, Any]:
    return {"schema_version": 2, "artifact_ref": artifact_ref, "rows": rows}


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _write_content(repo: Path, relative_path: str, content: object | None) -> None:
    path = repo / relative_path
    if content is None:
        _git(repo, "rm", relative_path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(_json_bytes(content))
    _git(repo, "add", relative_path)


def _build_rebase_conflict(
    repo: Path,
    *,
    base: object | None,
    local: object | None,
    upstream: object | None,
    path: str = LINK_PATH,
) -> None:
    _init_repo(repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    if base is not None:
        _write_content(repo, path, base)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    _git(repo, "checkout", "-b", "upstream")
    _write_content(repo, path, upstream)
    _git(repo, "commit", "-m", "upstream")

    _git(repo, "checkout", "master")
    _write_content(repo, path, local)
    _git(repo, "commit", "-m", "local")

    rebase = _git(repo, "rebase", "upstream", check=False)
    assert rebase.returncode != 0


def _resolved_json(repo: Path, path: str = LINK_PATH) -> dict[str, Any]:
    return json.loads((repo / path).read_text(encoding="utf-8"))


def test_both_added_indexes_merge_and_stage_canonical_json(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    local = _index([_row("agent:local", "local citation", "2026-09-03T00:00:00Z")])
    upstream = _index(
        [_row("agent:upstream", "upstream citation", "2026-09-02T00:00:00Z")]
    )
    _build_rebase_conflict(repo, base=None, local=local, upstream=upstream)

    result = resolve_semantic_conflicts(repo)

    assert result.ok is True, result.message
    assert result.resolved_files == (LINK_PATH,)
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout == ""
    merged = _resolved_json(repo)
    assert [row["source_ref"] for row in merged["rows"]] == [
        "agent:upstream",
        "agent:local",
    ]
    assert (repo / LINK_PATH).read_bytes() == _json_bytes(merged)
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == LINK_PATH


def test_both_modified_indexes_preserve_base_and_distinct_rows(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    base_row = _row("agent:base", "base citation", "2026-09-01T00:00:00Z")
    local_row = _row("agent:local", "local citation", "2026-09-03T00:00:00Z")
    upstream_row = _row("agent:upstream", "upstream citation", "2026-09-02T00:00:00Z")
    _build_rebase_conflict(
        repo,
        base=_index([base_row]),
        local=_index([base_row, local_row]),
        upstream=_index([base_row, upstream_row]),
    )

    result = resolve_artifact_link_conflicts(repo, (LINK_PATH,))

    assert result.ok is True, result.message
    assert [row["source_ref"] for row in _resolved_json(repo)["rows"]] == [
        "agent:base",
        "agent:upstream",
        "agent:local",
    ]


def test_rebase_stage_orientation_passes_local_stage_as_ours(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    local = _index([_row("agent:local", "local side", "2026-09-03T00:00:00Z")])
    upstream = _index([_row("agent:upstream", "upstream side", "2026-09-02T00:00:00Z")])
    _build_rebase_conflict(repo, base=None, local=local, upstream=upstream)
    captured: dict[str, dict[str, Any]] = {}

    def fake_merge(
        base: dict[str, Any],
        ours: dict[str, Any],
        theirs: dict[str, Any],
    ) -> dict[str, Any]:
        captured["base"] = base
        captured["ours"] = ours
        captured["theirs"] = theirs
        return _index([])

    monkeypatch.setattr(resolver_mod, "merge_artifact_link_indexes", fake_merge)

    result = resolve_artifact_link_conflicts(repo, (LINK_PATH,))

    assert result.ok is True, result.message
    assert captured["base"]["rows"] == []
    assert captured["ours"]["rows"][0]["description"] == "local side"
    assert captured["theirs"]["rows"][0]["description"] == "upstream side"


def test_malformed_stage_fails_without_staging(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    upstream = _index(
        [_row("agent:upstream", "upstream citation", "2026-09-02T00:00:00Z")]
    )
    _build_rebase_conflict(repo, base=None, local="{not json", upstream=upstream)

    result = resolve_artifact_link_conflicts(repo, (LINK_PATH,))

    assert result.ok is False
    assert "malformed artifact-link conflict stage" in result.message
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == (
        LINK_PATH
    )


def test_mismatched_artifact_refs_fail_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    other_ref = "plan:202609/other.md"
    local = _index([_row("agent:local", "local citation", "2026-09-03T00:00:00Z")])
    upstream = _index(
        [
            dict(
                _row("agent:upstream", "upstream citation", "2026-09-02T00:00:00Z"),
                target_ref=other_ref,
            )
        ],
        artifact_ref=other_ref,
    )
    _build_rebase_conflict(repo, base=None, local=local, upstream=upstream)

    result = resolve_artifact_link_conflicts(repo, (LINK_PATH,))

    assert result.ok is False
    assert "same artifact_ref" in result.message
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == (
        LINK_PATH
    )


def test_ambiguous_same_key_edit_fails_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    base_row = _row("agent:base", "base citation", "2026-09-01T00:00:00Z")
    local_row = dict(base_row, description="local edit")
    upstream_row = dict(base_row, description="upstream edit")
    _build_rebase_conflict(
        repo,
        base=_index([base_row]),
        local=_index([local_row]),
        upstream=_index([upstream_row]),
    )

    result = resolve_artifact_link_conflicts(repo, (LINK_PATH,))

    assert result.ok is False
    assert "ambiguous artifact-link index merge keys" in result.message
    assert "agent:base cites plan:202609/a.md" in result.message


def test_modify_delete_conflict_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    base_row = _row("agent:base", "base citation", "2026-09-01T00:00:00Z")
    local_row = dict(base_row, description="local edit")
    _build_rebase_conflict(
        repo,
        base=_index([base_row]),
        local=_index([local_row]),
        upstream=None,
    )

    result = resolve_artifact_link_conflicts(repo, (LINK_PATH,))

    assert result.ok is False
    assert "modify/delete stages" in result.message


def test_unrelated_path_is_not_claimed_by_semantic_chain(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    notes = repo / "notes.txt"
    notes.write_text("base\n", encoding="utf-8")
    _git(repo, "add", "notes.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "upstream")
    notes.write_text("upstream\n", encoding="utf-8")
    _git(repo, "commit", "-am", "upstream")
    _git(repo, "checkout", "master")
    notes.write_text("local\n", encoding="utf-8")
    _git(repo, "commit", "-am", "local")
    assert _git(repo, "rebase", "upstream", check=False).returncode != 0

    result = resolve_semantic_conflicts(repo)

    assert result.ok is False
    assert result.message == "non-bead conflicts remain: notes.txt"


def test_managed_markdown_conflict_rebuilds_link_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _install_markdown_store(repo, monkeypatch)
    _build_rebase_conflict(
        repo,
        base=_managed_markdown("base managed row"),
        local=_managed_markdown("local managed row"),
        upstream=_managed_markdown("upstream managed row"),
        path="202609/a.md",
    )

    result = resolve_semantic_conflicts(repo)

    assert result.ok is True, result.message
    assert result.resolved_files == ("202609/a.md",)
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout == ""
    text = (repo / "202609/a.md").read_text(encoding="utf-8")
    assert "merged citation" in text
    assert "local managed row" not in text
    assert "upstream managed row" not in text
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == (
        "202609/a.md"
    )


def test_both_added_managed_markdown_conflict_rebuilds_link_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _install_markdown_store(repo, monkeypatch)
    _build_rebase_conflict(
        repo,
        base=None,
        local=_managed_markdown("local managed row"),
        upstream=_managed_markdown("upstream managed row"),
        path="202609/a.md",
    )

    result = resolve_semantic_conflicts(repo)

    assert result.ok is True, result.message
    assert result.resolved_files == ("202609/a.md",)
    assert "merged citation" in (repo / "202609/a.md").read_text(encoding="utf-8")


def test_managed_markdown_authored_body_conflict_is_left_unmerged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _install_markdown_store(repo, monkeypatch)
    _build_rebase_conflict(
        repo,
        base=_managed_markdown("base managed row"),
        local="# Local title\n\n" + _managed_markdown("local managed row"),
        upstream="# Upstream title\n\n" + _managed_markdown("upstream managed row"),
        path="202609/a.md",
    )

    result = resolve_semantic_conflicts(repo)

    assert result.ok is False
    assert "authored Markdown conflict remains" in result.message
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == (
        "202609/a.md"
    )


def _managed_markdown(cell: str) -> str:
    return (
        "# A\n\n"
        "<!-- sase:links:start -->\n\n"
        "| Relation | Artifact | Why |\n"
        "| --- | --- | --- |\n"
        f"| cites | agent:x | {cell} |\n\n"
        "<!-- sase:links:end -->\n"
    )


def _install_markdown_store(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Store:
        project_key = "gh_sase-org__sase"
        sidecar_roots = {"plan": repo}
        sdd_store = None

        def load_artifact_rows(self, artifact_ref: str) -> tuple[dict[str, Any], ...]:
            assert artifact_ref == ARTIFACT_REF
            return (_row("agent:merged", "merged citation", "2026-09-04T00:00:00Z"),)

    monkeypatch.setattr(
        markdown_resolver_mod,
        "resolve_artifact_link_store",
        lambda *, cwd=None: Store(),
    )
