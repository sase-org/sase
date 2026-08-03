"""Tests for best-effort bead-page commit footer links."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.bead_pages.links import (
    resolve_bead_commit_tag,
    resolve_bead_page_url_from_cwd,
)
from sase.core.commit_footer_facade import LinkedCommitTagValue
from sase.sdd.store import SddStore
from sase.workflows.commit.commit_hooks import apply_bead_commit_tag


def _in_tree_store(root: Path) -> SddStore:
    return SddStore("in_tree", root / "sdd", root)


def test_resolve_bead_commit_tag_returns_linked_value_when_hosted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = (
        "https://github.com/sase-org/sase--beads/blob/main/pages/sase-ai/sase-ai.2.md"
    )
    resolver = MagicMock()
    resolver.bead_url.return_value = destination
    factory = MagicMock(return_value=resolver)
    monkeypatch.setattr("sase.sdd.hosted_links.hosted_link_resolver", factory)
    store = _in_tree_store(tmp_path)

    assert resolve_bead_commit_tag(
        "sase-ai.2",
        store=store,
        cwd=tmp_path,
    ) == LinkedCommitTagValue("sase-ai.2", destination)
    factory.assert_called_once_with(store, primary_root=tmp_path)
    resolver.bead_url.assert_called_once_with("sase-ai.2")


def test_resolve_bead_commit_tag_degrades_to_bare_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = MagicMock()
    resolver.bead_url.return_value = None
    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        MagicMock(return_value=resolver),
    )

    assert (
        resolve_bead_commit_tag(
            "sase-ai.2",
            store=_in_tree_store(tmp_path),
            cwd=tmp_path,
        )
        == "sase-ai.2"
    )


def test_resolve_bead_commit_tag_never_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.bead_pages.links._resolve_store",
        MagicMock(side_effect=RuntimeError("not configured")),
    )

    assert resolve_bead_commit_tag("sase-ai.2", cwd=tmp_path) == "sase-ai.2"


def test_resolve_bead_page_url_from_cwd_checks_the_resolved_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = (
        "https://github.com/sase-org/sase--beads/blob/main/pages/sase-ai/sase-ai.2.md"
    )
    store = _in_tree_store(tmp_path)
    store_resolver = MagicMock(return_value=store)
    page_resolver = MagicMock(return_value=destination)
    monkeypatch.setattr("sase.bead_pages.links._resolve_store", store_resolver)
    monkeypatch.setattr(
        "sase.bead_pages.links.resolve_bead_page_target",
        page_resolver,
    )

    assert resolve_bead_page_url_from_cwd(" sase-ai.2 ", cwd=tmp_path) == destination
    store_resolver.assert_called_once_with(tmp_path)
    page_resolver.assert_called_once_with(
        "sase-ai.2",
        store=store,
        primary_root=tmp_path,
    )


def test_resolve_bead_page_url_from_cwd_never_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.bead_pages.links._resolve_store",
        MagicMock(side_effect=RuntimeError("not configured")),
    )

    assert resolve_bead_page_url_from_cwd("sase-ai.2", cwd=tmp_path) is None


def test_apply_bead_commit_tag_leaves_subject_byte_identical(tmp_path: Path) -> None:
    payload = {
        "message": "feat: publish pages\n\nKeep this body.",
        "bead_id": "sase-ai.2",
    }

    apply_bead_commit_tag(payload, store=_in_tree_store(tmp_path), cwd=tmp_path)

    assert payload["message"].splitlines()[0] == "feat: publish pages"
    assert payload["message"].startswith("feat: publish pages\n\nKeep this body.")
    assert payload["message"].endswith("SASE_BEAD=sase-ai.2")


def test_apply_bead_commit_tag_is_idempotent(tmp_path: Path) -> None:
    payload = {"message": "feat: publish pages", "bead_id": "sase-ai.2"}

    apply_bead_commit_tag(payload, store=_in_tree_store(tmp_path), cwd=tmp_path)
    first = payload["message"]
    apply_bead_commit_tag(payload, store=_in_tree_store(tmp_path), cwd=tmp_path)

    assert payload["message"] == first
    assert payload["message"].count("SASE_BEAD=") == 1


def test_apply_bead_commit_tag_precedes_existing_plan_and_agent(
    tmp_path: Path,
) -> None:
    payload = {
        "message": (
            "feat: publish pages\n\n"
            "SASE_PLAN=plans:202607/bead_pages.md\n"
            "SASE_AGENT=alice.athena.sase-ai.2"
        ),
        "bead_id": "sase-ai.2",
    }

    apply_bead_commit_tag(payload, store=_in_tree_store(tmp_path), cwd=tmp_path)

    assert payload["message"] == (
        "feat: publish pages\n\n"
        "SASE_BEAD=sase-ai.2\n"
        "SASE_PLAN=plans:202607/bead_pages.md\n"
        "SASE_AGENT=alice.athena.sase-ai.2"
    )


def test_apply_bead_commit_tag_omits_tag_without_bead_id() -> None:
    payload = {"message": "feat: publish pages"}

    apply_bead_commit_tag(payload)

    assert payload == {"message": "feat: publish pages"}
