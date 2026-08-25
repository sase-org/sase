"""The host-owned sidecar-commit derivation step in ``_commit_store.py``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.feature_flags import override_flags
from sase.sdd._commit_store import _derive_artifact_links_for_commit
from sase.sdd.artifact_link_store import ArtifactLinkStore


def _capture_derivation(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    calls: list[tuple[object, ...]] = []

    def _fake(store: object, documents: object, **kwargs: object) -> object:
        calls.append((store, documents, kwargs))
        return None

    monkeypatch.setattr(
        "sase.sdd.artifact_link_derivation.derive_and_persist_artifact_links", _fake
    )
    return calls


def _fake_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.sdd.artifact_link_store.resolve_artifact_link_store",
        lambda cwd=None: ArtifactLinkStore(
            project_key="gh_sase-org__sase", sidecar_roots={"plan": tmp_path}
        ),
    )


def test_skips_a_non_derivable_sidecar_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _capture_derivation(monkeypatch)

    with override_flags(artifact_link_derivation=True):
        _derive_artifact_links_for_commit(
            tmp_path,
            sidecar_role="beads",
            cause="user",
            changed_files=["202608/a.md"],
        )

    assert calls == []


def test_skips_the_artifact_links_cause_to_avoid_retriggering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _capture_derivation(monkeypatch)
    _fake_store(tmp_path, monkeypatch)

    with override_flags(artifact_link_derivation=True):
        _derive_artifact_links_for_commit(
            tmp_path,
            sidecar_role="plans",
            cause="artifact_links",
            changed_files=["202608/a.md"],
        )

    assert calls == []


def test_skips_when_the_flag_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _capture_derivation(monkeypatch)
    _fake_store(tmp_path, monkeypatch)
    (tmp_path / "202608").mkdir()
    (tmp_path / "202608" / "a.md").write_text("body\n", encoding="utf-8")

    with override_flags():
        _derive_artifact_links_for_commit(
            tmp_path,
            sidecar_role="plans",
            cause="user",
            changed_files=["202608/a.md"],
        )

    assert calls == []


def test_derives_for_changed_markdown_files_and_skips_the_links_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _capture_derivation(monkeypatch)
    _fake_store(tmp_path, monkeypatch)
    (tmp_path / "202608").mkdir()
    (tmp_path / "202608" / "a.md").write_text("body\n", encoding="utf-8")
    (tmp_path / "links" / "202608").mkdir(parents=True)
    (tmp_path / "links" / "202608" / "a.md.json").write_text("{}", encoding="utf-8")

    with override_flags(artifact_link_derivation=True):
        _derive_artifact_links_for_commit(
            tmp_path,
            sidecar_role="plans",
            cause="user",
            changed_files=[
                "202608/a.md",
                "links/202608/a.md.json",
                "202608/deleted.md",
            ],
        )

    assert len(calls) == 1
    _store, documents, _kwargs = calls[0]
    assert [document.ref for document in documents] == ["plan:202608/a.md"]
