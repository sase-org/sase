"""CLI coverage for ``sase bead pages``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.cli_pages import handle_bead_pages
from sase.bead_pages.refresh_models import (
    BeadPagesRefreshAction,
    BeadPagesRefreshReport,
)
from sase.main.parser import create_parser
from sase.sdd.store import SddStore


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
    url = "https://github.com/sase-org/sase--beads/blob/main/pages/sase-ai/sase-ai.7.md"

    class _Resolver:
        def bead_url(self, bead_id: str) -> str:
            assert bead_id == "sase-ai.7"
            return url

    monkeypatch.setattr(
        "sase.bead.cli_pages._page_context",
        lambda **_kwargs: (store, tmp_path, "sase"),
    )
    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: _Resolver(),
    )
    args = create_parser().parse_args(["bead", "pages", "url", "sase-ai.7"])

    with pytest.raises(SystemExit) as exc:
        handle_bead_pages(args)

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == url
