"""CLI coverage for ``sase bead pages``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.config import save_config
from sase.bead.cli_pages import handle_bead_pages
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.bead_pages.refresh_models import (
    BeadPagesRefreshAction,
    BeadPagesRefreshReport,
)
from sase.main.parser import create_parser
from sase.sdd.store import SddStore, write_sdd_store_record
from tests.test_bead.resolution_test_helpers import (
    bead_store_snapshot,
    isolate_bead_store_resolution,
)


def _store(tmp_path: Path) -> SddStore:
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    plans.mkdir()
    beads.mkdir()
    return SddStore(
        "sidecar_repos",
        plans,
        plans,
        beads_dir=beads,
        beads_remote_url="git@github.com:sase-org/sase--beads.git",
    )


def _write_split_store_record(primary: Path) -> None:
    write_sdd_store_record(
        primary,
        {
            "schema_version": 3,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "owner/repo--plans",
                    "remote_url": "git@github.com:owner/repo--plans.git",
                },
                "beads": {
                    "repo": "owner/repo--beads",
                    "remote_url": "git@github.com:owner/repo--beads.git",
                },
            },
        },
    )


def test_pages_parser_defaults_to_dry_run_and_bare_group_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = create_parser()
    refresh = parser.parse_args(["bead", "pages", "refresh"])

    assert refresh.bead is None
    assert not refresh.json
    assert not refresh.write

    bare = parser.parse_args(["bead", "pages"])
    with pytest.raises(SystemExit) as exc:
        handle_bead_pages(bare)

    assert exc.value.code == 0
    assert "sase bead pages refresh" in capsys.readouterr().out


def test_refresh_json_is_machine_readable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = _store(tmp_path)
    assert store.beads_dir is not None
    report = BeadPagesRefreshReport(
        root=store.beads_dir / "pages",
        write=False,
        bead=None,
        scanned=2,
        lineages=1,
        actions=(BeadPagesRefreshAction("sase-ai/README.md", "update", "sase-ai"),),
        issues=(),
        changed_files=(),
        removed_files=(),
        committed=False,
    )
    monkeypatch.setattr(
        "sase.bead.cli_pages._page_context",
        lambda **_kwargs: (store, tmp_path, "sase"),
    )
    monkeypatch.setattr(
        "sase.bead_pages.refresh.refresh_bead_pages",
        lambda *_args, **_kwargs: report,
    )
    args = create_parser().parse_args(["bead", "pages", "refresh", "--json"])

    with pytest.raises(SystemExit) as exc:
        handle_bead_pages(args)

    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["would_change"] == 1
    assert payload["actions"] == [
        {
            "path": "sase-ai/README.md",
            "change": "update",
            "bead_id": "sase-ai",
        }
    ]


def test_url_prints_resolved_hosted_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = _store(tmp_path)
    assert store.beads_dir is not None
    with BeadProject.init(store.beads_dir, beads_dirname=BEADS_DIRNAME_ROOT):
        pass
    save_config(
        store.beads_dir,
        {"issue_prefix": "sase-ai", "next_counter": 7, "owner": ""},
    )
    with BeadProject(store.beads_dir, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create("Hosted page", IssueType.PLAN)
    url = (
        f"https://github.com/sase-org/sase--beads/blob/main/pages/sase-ai/{issue.id}.md"
    )

    class _Resolver:
        def bead_url(self, bead_id: str) -> str:
            assert bead_id == issue.id
            return url

    monkeypatch.setattr(
        "sase.bead.cli_pages._page_context",
        lambda **_kwargs: (store, tmp_path, "sase"),
    )
    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: _Resolver(),
    )
    args = create_parser().parse_args(["bead", "pages", "url", issue.id])

    with pytest.raises(SystemExit) as exc:
        handle_bead_pages(args)

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == url


def test_url_foreign_full_id_uses_owner_sidecar_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "caller"
    plans = owner / "sase/repos/plans"
    beads = owner / "sase/repos/beads"
    caller.mkdir()
    plans.mkdir(parents=True)
    beads.mkdir(parents=True)
    _write_split_store_record(owner)
    with BeadProject.init(beads, beads_dirname=BEADS_DIRNAME_ROOT):
        pass
    save_config(
        beads,
        {"issue_prefix": "sase-page", "next_counter": 1, "owner": ""},
    )
    with BeadProject(beads, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create("Hosted foreign page", IssueType.PLAN)
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    monkeypatch.chdir(caller)
    monkeypatch.setattr(
        "sase.bead.operation_context.enabled_project_store_snapshots",
        lambda: (bead_store_snapshot("owner", owner, issue.id, beads_dir=beads),),
    )
    url = f"https://example.test/pages/sase-page/{issue.id}.md"
    captured: dict[str, object] = {}

    class _Resolver:
        def bead_url(self, bead_id: str) -> str:
            assert bead_id == issue.id
            return url

    def resolver(store: SddStore, **kwargs: object) -> _Resolver:
        captured["store"] = store
        captured.update(kwargs)
        return _Resolver()

    monkeypatch.setattr("sase.sdd.hosted_links.hosted_link_resolver", resolver)

    args = create_parser().parse_args(["bead", "pages", "url", issue.id])
    with pytest.raises(SystemExit) as exc:
        handle_bead_pages(args)

    assert exc.value.code == 0
    store = captured["store"]
    assert isinstance(store, SddStore)
    assert store.kind_root("beads") == beads
    assert captured["primary_root"] == owner
    assert captured["project"] == "owner"
    assert capsys.readouterr().out.strip() == url
