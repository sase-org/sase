"""Attachment-fetch basics: store-discovery skip, config, and badges.

Split from ``tests.test_bead.test_attachment_fetch``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_bead._attachment_fetch_helpers import (
    create_plan,
    fetch_remote,  # noqa: F401 (registers the remote fixture)
    fetch_work_dir,  # noqa: F401 (registers the work_dir fixture)
    plant_hidden_clone,
    read_full,
)

__all__ = [
    "test_auto_fetch_config_default_and_fail_open",
    "test_badge_table",
    "test_read_without_attachments_skips_store_discovery",
]


def test_read_without_attachments_skips_store_discovery(
    project_dir: Path,
    work_dir: Path,
    remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Show/read of a bead with no attachments does no store discovery."""
    import sase.bead.attachments.git_store as git_store_mod
    import sase.bead.attachments.upload as upload_mod

    home_a = tmp_path / "sase-home-a"
    plant_hidden_clone(home_a, remote)
    issue_id = create_plan(project_dir)

    calls = {"clone_has_remote": 0, "GitAttachmentStore": 0}
    orig_has_remote = upload_mod.clone_has_remote
    orig_store = git_store_mod.GitAttachmentStore

    def _spy_has_remote(clone: Path) -> bool:
        calls["clone_has_remote"] += 1
        return bool(orig_has_remote(clone))

    def _spy_store(*args: object, **kwargs: object) -> object:
        calls["GitAttachmentStore"] += 1
        return orig_store(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(upload_mod, "clone_has_remote", _spy_has_remote)
    monkeypatch.setattr(git_store_mod, "GitAttachmentStore", _spy_store)

    out, err, code = read_full(issue_id)
    assert code == 0, err
    assert calls == {"clone_has_remote": 0, "GitAttachmentStore": 0}, calls


# -- config ------------------------------------------------------------


def test_auto_fetch_config_default_and_fail_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.bead.config as bead_config

    monkeypatch.setattr(bead_config, "load_merged_config", lambda: {}, raising=False)
    assert (
        bead_config.get_attachment_auto_fetch_max_bytes()
        == bead_config.DEFAULT_ATTACHMENT_AUTO_FETCH_MAX_BYTES
        == 26214400
    )
    for bad in (
        {"bead": {"attachments": {"auto_fetch_max_bytes": "big"}}},
        {"bead": {"attachments": {"auto_fetch_max_bytes": True}}},
        {"bead": {"attachments": {"auto_fetch_max_bytes": 0}}},
        {"bead": {"attachments": {"auto_fetch_max_bytes": -3}}},
        {"bead": {"attachments": "nope"}},
        {"bead": "nope"},
    ):
        monkeypatch.setattr(
            bead_config, "load_merged_config", lambda bad=bad: bad, raising=False
        )
        assert (
            bead_config.get_attachment_auto_fetch_max_bytes()
            == bead_config.DEFAULT_ATTACHMENT_AUTO_FETCH_MAX_BYTES
        )
    monkeypatch.setattr(
        bead_config,
        "load_merged_config",
        lambda: {"bead": {"attachments": {"auto_fetch_max_bytes": 123}}},
        raising=False,
    )
    assert bead_config.get_attachment_auto_fetch_max_bytes() == 123


# -- badges ------------------------------------------------------------


def test_badge_table() -> None:
    from sase.bead.attachments.fetch import attachment_badge

    assert attachment_badge("cached") is None
    assert attachment_badge("remote") is None
    assert (
        attachment_badge(
            "not_downloaded", size_bytes=2048, bead_id="sase-1", name="a.bin"
        )
        == "⇣ not downloaded · 2 KiB — sase bead attachment path sase-1 a.bin"
    )
    assert (
        attachment_badge("pending_upload", origin="laptop")
        == "⇡ pending upload (laptop)"
    )
    assert attachment_badge("local_only", origin="laptop") == "⚠ only on laptop"
    assert attachment_badge("unavailable") == "✕ unavailable offline"
    assert attachment_badge("purged") == "(purged)"
    assert attachment_badge("corrupt") == "‼ digest mismatch"
