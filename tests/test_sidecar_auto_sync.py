"""Generic primary-sidecar auto-sync (sase-mq.6) tests."""

from __future__ import annotations

from pathlib import Path

import pytest

import sase._sidecar_auto_sync as sidecar_auto_sync
from sase._linked_repo_config import _SIDECAR_REMOTE_URL_KEY, _SIDECAR_ROLE_KEY
from sase._sidecar_auto_sync import auto_sync_roles, sync_primary_sidecar_role
from tests._linked_repo_resolution_helpers import _set_github_origin
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo


def _adjacent_config() -> dict[str, object]:
    return {"workspace": {"root": "adjacent", "project_key": "demo"}}


def _write_project_file(path: Path, *, primary: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"WORKSPACE_DIR: {primary}\nNAME: demo\nDESCRIPTION:\n  fixture\nSTATUS: Ready\n",
        encoding="utf-8",
    )
    return path


def _entry(
    role: str,
    *,
    auto_sync: bool = True,
    disabled: bool = False,
    remote_url: str | None = None,
) -> dict[str, object]:
    return {
        _SIDECAR_ROLE_KEY: role,
        "auto_sync": auto_sync,
        "disabled": disabled,
        _SIDECAR_REMOTE_URL_KEY: remote_url,
    }


def _behind_sidecar_checkout(
    tmp_path: Path, role: str
) -> tuple[Path, Path, Path, str, str, str]:
    """Return ``(primary, project_file, sidecar, old_head, new_head, remote)``.

    The sidecar clone is on ``main``, clean, and strictly behind its remote.
    """

    remote = tmp_path / "sidecar.git"
    seed = tmp_path / "sidecar-seed"
    primary = tmp_path / "proj"
    primary.mkdir()
    project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
    sidecar = primary / "sase" / "repos" / role

    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("v1\n", encoding="utf-8")
    commit_all(seed, "v1")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, sidecar)
    old_head = git(["rev-parse", "HEAD"], sidecar).stdout.strip()
    (seed / "README.md").write_text("v2\n", encoding="utf-8")
    commit_all(seed, "v2")
    git(["push"], seed)
    new_head = git(["rev-parse", "HEAD"], seed).stdout.strip()
    return primary, project_file, sidecar, old_head, new_head, str(remote)


class TestSyncPrimarySidecarRole:
    def test_not_configured_role_is_reported_without_touching_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        monkeypatch.setattr(
            sidecar_auto_sync, "_resolved_sidecar_entries", lambda *_a, **_kw: []
        )

        result = sync_primary_sidecar_role(
            "demo", "plans", project_file=project_file, config=_adjacent_config()
        )

        assert result.status == "not_configured"

    def test_disabled_auto_sync_role_is_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [_entry("plans", auto_sync=False)],
        )

        result = sync_primary_sidecar_role(
            "demo", "plans", project_file=project_file, config=_adjacent_config()
        )

        assert result.status == "not_configured"

    def test_disabled_entry_is_still_reported_when_auto_sync_opt_in_is_bypassed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [_entry("beads", auto_sync=False, disabled=True)],
        )

        result = sync_primary_sidecar_role(
            "demo",
            "beads",
            project_file=project_file,
            config=_adjacent_config(),
            require_auto_sync_opt_in=False,
        )

        assert result.status == "not_configured"

    def test_auto_sync_opt_in_can_be_bypassed_to_unblock_a_bead_waiter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary, project_file, sidecar, _old, new_head, remote = (
            _behind_sidecar_checkout(tmp_path, "beads")
        )
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [_entry("beads", auto_sync=False, remote_url=remote)],
        )

        result = sync_primary_sidecar_role(
            "demo",
            "beads",
            project_file=project_file,
            config=_adjacent_config(),
            require_auto_sync_opt_in=False,
        )

        assert result.status == "refreshed"
        assert git(["rev-parse", "HEAD"], sidecar).stdout.strip() == new_head

    def test_missing_clone_is_reported_and_not_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [_entry("plans")],
        )

        result = sync_primary_sidecar_role(
            "demo", "plans", project_file=project_file, config=_adjacent_config()
        )

        assert result.status == "missing"
        assert not (primary / "sase" / "repos" / "plans").exists()

    def test_refreshes_clean_strictly_behind_clone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary, project_file, sidecar, _old, new_head, remote = (
            _behind_sidecar_checkout(tmp_path, "plans")
        )
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [_entry("plans", remote_url=remote)],
        )

        result = sync_primary_sidecar_role(
            "demo", "plans", project_file=project_file, config=_adjacent_config()
        )

        assert result.status == "refreshed"
        assert git(["rev-parse", "HEAD"], sidecar).stdout.strip() == new_head
        assert git(["status", "--porcelain"], sidecar).stdout == ""

    def test_up_to_date_clone_is_left_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        remote = tmp_path / "sidecar.git"
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        sidecar = primary / "sase" / "repos" / "beads"
        init_bare_repo(remote)
        clone(remote, sidecar)
        (sidecar / "README.md").write_text("v1\n", encoding="utf-8")
        commit_all(sidecar, "v1")
        git(["push", "-u", "origin", "main"], sidecar)
        head = git(["rev-parse", "HEAD"], sidecar).stdout.strip()
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [_entry("beads", remote_url=str(remote))],
        )

        result = sync_primary_sidecar_role(
            "demo", "beads", project_file=project_file, config=_adjacent_config()
        )

        assert result.status == "up_to_date"
        assert git(["rev-parse", "HEAD"], sidecar).stdout.strip() == head

    def test_dirty_clone_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary, project_file, sidecar, old_head, _new, remote = (
            _behind_sidecar_checkout(tmp_path, "plans")
        )
        (sidecar / "README.md").write_text("local edit\n", encoding="utf-8")
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [_entry("plans", remote_url=remote)],
        )

        result = sync_primary_sidecar_role(
            "demo", "plans", project_file=project_file, config=_adjacent_config()
        )

        assert result.status == "dirty"
        assert git(["rev-parse", "HEAD"], sidecar).stdout.strip() == old_head
        assert (sidecar / "README.md").read_text(encoding="utf-8") == "local edit\n"

    def test_detached_clone_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary, project_file, sidecar, old_head, _new, remote = (
            _behind_sidecar_checkout(tmp_path, "plans")
        )
        git(["checkout", "--detach", "HEAD"], sidecar)
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [_entry("plans", remote_url=remote)],
        )

        result = sync_primary_sidecar_role(
            "demo", "plans", project_file=project_file, config=_adjacent_config()
        )

        assert result.status == "detached"
        assert git(["rev-parse", "HEAD"], sidecar).stdout.strip() == old_head

    def test_no_upstream_clone_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary, project_file, sidecar, old_head, _new, remote = (
            _behind_sidecar_checkout(tmp_path, "plans")
        )
        git(["branch", "--unset-upstream"], sidecar)
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [_entry("plans", remote_url=remote)],
        )

        result = sync_primary_sidecar_role(
            "demo", "plans", project_file=project_file, config=_adjacent_config()
        )

        assert result.status == "no_upstream"
        assert git(["rev-parse", "HEAD"], sidecar).stdout.strip() == old_head

    def test_diverged_clone_is_never_reset_or_rebased(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary, project_file, sidecar, _old, _new, remote = _behind_sidecar_checkout(
            tmp_path, "plans"
        )
        (sidecar / "NOTES.md").write_text("local-only\n", encoding="utf-8")
        commit_all(sidecar, "local-only commit")
        local_head = git(["rev-parse", "HEAD"], sidecar).stdout.strip()
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [_entry("plans", remote_url=remote)],
        )

        result = sync_primary_sidecar_role(
            "demo", "plans", project_file=project_file, config=_adjacent_config()
        )

        assert result.status == "diverged"
        assert git(["rev-parse", "HEAD"], sidecar).stdout.strip() == local_head
        assert (sidecar / "NOTES.md").read_text(encoding="utf-8") == "local-only\n"

    def test_remote_mismatch_is_skipped_without_fetching(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary, project_file, sidecar, old_head, _new, _remote = (
            _behind_sidecar_checkout(tmp_path, "plans")
        )
        other_remote = tmp_path / "other.git"
        init_bare_repo(other_remote)
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [_entry("plans", remote_url=str(other_remote))],
        )

        result = sync_primary_sidecar_role(
            "demo", "plans", project_file=project_file, config=_adjacent_config()
        )

        assert result.status == "remote_mismatch"
        assert git(["rev-parse", "HEAD"], sidecar).stdout.strip() == old_head

    def test_hidden_agents_role_is_always_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        primary = tmp_path / "proj"
        primary.mkdir()
        project_file = _write_project_file(tmp_path / "demo.sase", primary=primary)
        monkeypatch.setattr(
            sidecar_auto_sync,
            "_resolved_sidecar_entries",
            lambda *_a, **_kw: [_entry("agents")],
        )

        result = sync_primary_sidecar_role(
            "demo", "agents", project_file=project_file, config=_adjacent_config()
        )

        assert result.status == "error"


class TestAutoSyncRoleResolution:
    def test_plans_beads_research_and_custom_roles_are_discovered(
        self, tmp_path: Path
    ) -> None:
        primary = tmp_path / "widget"
        primary.mkdir()
        _set_github_origin(primary, "git@github.com:acme/widget.git")
        config = {
            "repos": {
                "sidecar": {
                    "builtin": {
                        "plans": {"auto_sync": True},
                        "beads": {"auto_sync": True},
                        "agents": {},
                    },
                    "custom": {
                        "research": {"auto_sync": True},
                        "designs": {"auto_sync": False},
                    },
                }
            }
        }

        roles = auto_sync_roles(str(primary), config=config)

        assert roles == ("plans", "beads", "research")

    def test_disabled_role_is_excluded_even_with_auto_sync(
        self, tmp_path: Path
    ) -> None:
        primary = tmp_path / "widget"
        primary.mkdir()
        _set_github_origin(primary, "git@github.com:acme/widget.git")
        config = {
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {"auto_sync": True, "disabled": True},
                    }
                }
            }
        }

        assert auto_sync_roles(str(primary), config=config) == ()

    def test_hidden_agents_role_never_appears_even_if_configured(
        self, tmp_path: Path
    ) -> None:
        primary = tmp_path / "widget"
        primary.mkdir()
        _set_github_origin(primary, "git@github.com:acme/widget.git")
        config = {"repos": {"sidecar": {"builtin": {"agents": {"auto_sync": True}}}}}

        assert auto_sync_roles(str(primary), config=config) == ()
