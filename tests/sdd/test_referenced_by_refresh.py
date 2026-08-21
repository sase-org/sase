from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import subprocess

from sase.agents_sync.referenced_by_outbox import ReferencedByOutboxItem
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION
from sase.sdd.plan_header_block import PlanHeaderSection, PlanHeaderSectionKind
from sase.sdd.plan_header_block import render_plan_header_block
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
        description="prompt reference @plan:202608/example.md",
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
        "links/202608/example.md.json",
        "202608/example.md",
        ".gitignore",
    )
    assert committed[0]["cause"] == "artifact_links"
    assert committed[0]["already_locked"] is True
    content = document.read_text(encoding="utf-8")
    assert content.startswith("# Example\n\nBody\n\n<!-- sase:referenced-by:start -->")
    assert "## Referenced By" in content
    assert (
        "| cited-by | agent:alice.athena.worker | "
        "prompt reference @plan:202608/example.md | 2 |"
    ) in content
    index = json.loads(
        (root / "links/202608/example.md.json").read_text(encoding="utf-8")
    )
    assert index["schema_version"] == ARTIFACT_LINK_ROW_SCHEMA_VERSION
    assert index["artifact_ref"] == "plan:202608/example.md"
    assert index["rows"][0]["source_ref"] == "agent:alice.athena.worker"
    assert index["rows"][0]["relation"] == "cites"
    assert index["rows"][0]["origin"] == "prompt_ref"
    assert index["rows"][0]["uses"] == 2

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


def test_refresh_artifact_links_writes_v2_tables_after_plan_header(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    root = tmp_path / "plans"
    store = _store(root)
    document = root / "202608" / "example.md"
    document.parent.mkdir(parents=True)
    header = render_plan_header_block(
        (
            PlanHeaderSection(
                PlanHeaderSectionKind.PARENT,
                label="plan:202608/root.md",
                target="root.md",
            ),
        )
    )
    document.write_text(
        f"---\ntitle: Example\n---\n\n{header}\n\n# Example\n\nBody\n",
        encoding="utf-8",
    )
    index_path = root / "links" / "202608" / "example.md.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                "artifact_ref": "plan:202608/example.md",
                "rows": [
                    {
                        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                        "source_ref": "plan:202608/example.md",
                        "relation": "related",
                        "target_ref": "plan:202608/other.md",
                        "description": "shares context",
                        "origin": "manual",
                        "created_by": "alice.athena.worker",
                        "created_at": "2026-08-12T00:00:00Z",
                        "uses": 1,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
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

    report = refresh_referenced_by(
        store,
        role="plans",
        requests=(_request(),),
        write=True,
    )

    assert report.ok and report.committed
    assert committed[0]["cause"] == "artifact_links"
    assert report.changed_files == (
        "links/202608/example.md.json",
        "202608/example.md",
        ".gitignore",
    )
    content = document.read_text(encoding="utf-8")
    assert content.index("<!-- sase:links:start -->") > content.index("**PARENT:**")
    assert content.index("<!-- sase:links:start -->") < content.index("# Example")
    assert "| related | plan:202608/other.md | shares context |" in content
    assert "Plus 1 automatic references" in content
    assert "## Referenced By" in content
    assert (
        "| cited-by | agent:alice.athena.worker | "
        "prompt reference @plan:202608/example.md | 2 |"
    ) in content
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == ARTIFACT_LINK_ROW_SCHEMA_VERSION
    assert {row["origin"] for row in payload["rows"]} == {"manual", "prompt_ref"}


def test_refresh_artifact_links_creates_binary_companion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    root = tmp_path / "plans"
    store = _store(root)
    image = root / "202608" / "diagram.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"not really a png")
    request = ReferencedByOutboxItem(
        project_key="proj",
        project="Project",
        global_agent="alice.athena.worker",
        agent_url=None,
        primary_revision="a" * 40,
        sidecar_role="plans",
        provider="plan",
        artifact_id="plan:202608/diagram.png",
        repo_relpath="202608/diagram.png",
        identity_value=None,
        canonical_ref="plan:202608/diagram.png",
        destination=None,
        uses=1,
        published_date="2026-08-12",
        description="prompt reference @plan:202608/diagram.png",
    )
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
    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", lambda *_a, **_k: True)

    report = refresh_referenced_by(
        store,
        role="plans",
        requests=(request,),
        write=True,
    )

    companion = root / "202608" / "diagram.md"
    assert report.ok
    assert companion.is_file()
    content = companion.read_text(encoding="utf-8")
    assert content.startswith("# diagram.png\n\n![diagram.png](./diagram.png)")
    assert "This file is generated; do not hand-edit." in content
    assert "## Referenced By" in content


def test_projection_refresh_commits_index_and_ignore_without_lock_residue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )
    monkeypatch.setattr(
        "sase.sdd.referenced_by_refresh._pull_rebase_if_remote",
        lambda _repo_root: None,
    )
    monkeypatch.setattr(
        "sase.file_references.format_markdown_files_with_prettier",
        lambda _paths: True,
    )
    root = tmp_path / "plans"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=root,
        check=True,
    )
    document = root / "202608" / "example.md"
    document.parent.mkdir(parents=True)
    document.write_text("# Example\n\nBody\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)
    store = SddStore("sidecar_repos", root, root)

    report = refresh_referenced_by(
        store,
        role="plans",
        requests=(_request(),),
        write=True,
    )

    assert report.ok and report.committed
    names = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "links/202608/example.md.json" in names
    assert ".gitignore" in names
    assert not any(name.endswith(".lock") for name in names)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status == ""
    lock = root / "links" / "202608" / "example.md.lock"
    assert lock.is_file()
    assert "/links/**/*.lock" in (root / ".gitignore").read_text(encoding="utf-8")
