from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path

from sase.agents_sync.referenced_by_outbox import ReferencedByOutboxItem
from sase.sdd.referenced_by_refresh import refresh_referenced_by
from sase.sdd.store import SddStore


@contextmanager
def _acquired_lock(*_args: object, **_kwargs: object):
    yield True


def _store(root: Path) -> SddStore:
    root.mkdir()
    return SddStore("sidecar_repos", root, root)


def _request() -> ReferencedByOutboxItem:
    return ReferencedByOutboxItem(
        project_key="proj",
        project="Project",
        global_agent="alice.athena.worker",
        agent_url="https://example.test/agents/worker",
        primary_revision="a" * 40,
        sidecar_role="plans",
        provider="plan",
        artifact_id="plan:202608/example.md",
        repo_relpath="202608/example.md",
        identity_value=None,
        canonical_ref="plan:202608/example.md",
        destination="https://example.test/prompts/example.md",
        uses=2,
        published_date="2026-08-12",
    )


def test_refresh_referenced_by_dry_write_and_second_write_are_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "plans"
    store = _store(root)
    document = root / "202608" / "example.md"
    document.parent.mkdir(parents=True)
    document.write_text("# Example\n\nBody\n", encoding="utf-8")
    request = _request()
    committed: list[dict[str, object]] = []
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        _acquired_lock,
    )
    monkeypatch.setattr(
        "sase.sdd.referenced_by_refresh._pull_rebase_if_remote",
        lambda _repo_root: None,
    )
    monkeypatch.setattr(
        "sase.file_references.format_markdown_files_with_prettier",
        lambda _paths: True,
    )

    def commit(*_args: object, **kwargs: object) -> bool:
        committed.append(kwargs)
        return True

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit)
    before = document.read_text(encoding="utf-8")

    dry = refresh_referenced_by(store, role="plans", requests=(request,))

    assert dry.ok
    assert dry.scanned == 1
    assert [action.path for action in dry.actions] == ["202608/example.md"]
    assert dry.changed_files == ()
    assert document.read_text(encoding="utf-8") == before

    written = refresh_referenced_by(
        store,
        role="plans",
        requests=(request,),
        write=True,
    )

    assert written.ok and written.committed
    assert written.changed_files == (
        "202608/example.md",
        "links/202608/example.md.json",
    )
    assert committed[0]["cause"] == "referenced_by"
    assert committed[0]["already_locked"] is True
    content = document.read_text(encoding="utf-8")
    assert content.startswith("# Example\n\nBody\n\n<!-- sase:referenced-by:start -->")
    assert "## Referenced By" in content
    assert "| [alice.athena.worker][1] | Project | plan:202608/example.md |" in content
    index = json.loads(
        (root / "links/202608/example.md.json").read_text(encoding="utf-8")
    )
    assert index["rows"][0]["agent"] == "alice.athena.worker"
    assert index["rows"][0]["uses"] == 2
    assert index["rows"][0]["use_ids"] == [request.id]

    second = refresh_referenced_by(
        store,
        role="plans",
        requests=(request,),
        write=True,
    )

    assert second.ok
    assert second.actions == ()
    assert second.changed_files == ()
    assert not second.committed
    assert len(committed) == 1


def test_refresh_referenced_by_skips_v2_link_indexes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "plans"
    store = _store(root)
    document = root / "202608" / "example.md"
    document.parent.mkdir(parents=True)
    document.write_text("# Example\n\nBody\n", encoding="utf-8")
    index_path = root / "links" / "202608" / "example.md.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artifact_ref": "plan:202608/example.md",
                "rows": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_index = index_path.read_text(encoding="utf-8")
    before_doc = document.read_text(encoding="utf-8")
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        _acquired_lock,
    )
    monkeypatch.setattr(
        "sase.sdd.referenced_by_refresh._pull_rebase_if_remote",
        lambda _repo_root: None,
    )

    report = refresh_referenced_by(
        store,
        role="plans",
        requests=(_request(),),
        write=True,
    )

    assert report.ok
    assert report.actions == ()
    assert index_path.read_text(encoding="utf-8") == before_index
    assert document.read_text(encoding="utf-8") == before_doc
