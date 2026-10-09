"""sase-core pairing rule tests: real temporary git repos for rules 1-5."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import tests._sase_install_testkit as kit
from tests._sase_install_testkit import install_core, install_plan, install_state


def _pair(
    tmp_path: Path, checkout: Path, core: Path, **env_extra: str
) -> install_core.CorePairing:
    env = kit.make_env(tmp_path, **env_extra)
    return install_core.pair_core(checkout, core, env=env)


def _dev_plan(tmp_path: Path, checkout: Path, core: Path) -> install_plan.InstallPlan:
    tool_dir, _ = kit.make_tool_env(tmp_path, checkout=checkout)
    state = install_state.read_state(tool_dir=tool_dir, bin_dir=tool_dir / "bin")
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    return install_plan.build_plan(
        options=install_plan.PlanOptions(mode="dev"),
        state=state,
        checkout_root=checkout,
        core_dir=core,
        env=kit.make_env(tmp_path),
        pypi_lookup=lookup,
    )


def test_missing_core_plans_a_clone(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    core = tmp_path / "sase-core"
    pairing = _pair(tmp_path, checkout, core)
    assert pairing.action == "clone"
    assert pairing.kind == "add"
    assert not pairing.consequential
    assert pairing.note.startswith("clone sase-org/sase-core -> ")
    assert pairing.remote_url == install_core.DEFAULT_CORE_REMOTE

    plan = _dev_plan(tmp_path, checkout, core)
    row = next(row for row in plan.rows if row.role == "core")
    assert row.kind == "add"
    assert not row.consequential
    assert not plan.noop


def test_clone_remote_is_overridable(tmp_path: Path) -> None:
    checkout = kit.make_checkout(tmp_path)
    pairing = _pair(
        tmp_path,
        checkout,
        tmp_path / "sase-core",
        SASE_INSTALL_CORE_REMOTE="https://example.test/sase-core.git",
    )
    assert pairing.remote_url == "https://example.test/sase-core.git"
    assert "example.test" in pairing.note


def test_ready_pair_reports_containment(tmp_path: Path) -> None:
    core = kit.make_core_checkout(tmp_path)
    checkout = kit.make_dev_checkout(tmp_path, core)
    pairing = _pair(tmp_path, checkout, core)
    assert pairing.action == "ready"
    assert pairing.kind == "keep"
    assert not pairing.consequential
    assert "contains pin" in pairing.note
    assert "sase-core-revision.txt" in pairing.note


def test_ready_pair_counts_commits_past_pin(tmp_path: Path) -> None:
    core = kit.make_core_checkout(tmp_path)
    checkout = kit.make_dev_checkout(tmp_path, core)
    kit.git_commit(core, "later.txt")
    pairing = _pair(tmp_path, checkout, core)
    assert pairing.action == "ready"
    assert pairing.commits_past_pin == 1
    assert "+1" in pairing.note


def test_dirty_core_is_consequential_but_allowed(tmp_path: Path) -> None:
    core = kit.make_core_checkout(tmp_path)
    checkout = kit.make_dev_checkout(tmp_path, core)
    core.joinpath("Cargo.toml").write_text(
        core.joinpath("Cargo.toml").read_text(encoding="utf-8") + "# dirty\n",
        encoding="utf-8",
    )
    pairing = _pair(tmp_path, checkout, core)
    assert pairing.action == "ready"
    assert pairing.kind == "keep"
    assert pairing.consequential
    assert "dirty" in pairing.note

    plan = _dev_plan(tmp_path, checkout, core)
    assert plan.consequential
    assert not plan.noop


def test_behind_core_plans_a_fast_forward(tmp_path: Path) -> None:
    remote = tmp_path / "core-remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    core = tmp_path / "sase-core"
    subprocess.run(
        ["git", "clone", str(remote), str(core)], check=True, capture_output=True
    )
    kit._git(["checkout", "-b", "master"], cwd=core)
    core.joinpath("Cargo.toml").write_text(
        '[workspace]\n[workspace.package]\nversion = "0.35.0"\n',
        encoding="utf-8",
    )
    kit._git(["add", "-A"], cwd=core)
    kit._git(["commit", "-m", "core manifest"], cwd=core)
    kit._git(["push", "-u", "origin", "master"], cwd=core)

    checkout = kit.make_checkout(tmp_path, core_dep="sase-core-rs>=0.35.0,<0.36.0")
    # Advance the remote; the local clone is now clean and strictly behind.
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(remote), str(other)], check=True, capture_output=True
    )
    kit.git_commit(other, "upstream.txt")
    kit._git(["push", "origin", "master"], cwd=other)
    kit.write_pin_file(checkout, kit.git_head(other))

    pairing = _pair(tmp_path, checkout, core)
    assert pairing.action == "fast-forward"
    assert pairing.kind == "upgrade"
    assert not pairing.consequential
    assert pairing.note.startswith("fast-forward sase-core ")

    plan = _dev_plan(tmp_path, checkout, core)
    row = next(row for row in plan.rows if row.role == "core")
    assert row.kind == "upgrade"
    assert "fast-forward sase-core" in row.note


def _pushed_core(tmp_path: Path, name: str = "sase-core") -> tuple[Path, Path]:
    """Return ``(remote, clone)``: a core checkout with an upstream remote."""
    remote = tmp_path / f"{name}.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    core = tmp_path / name
    subprocess.run(
        ["git", "clone", str(remote), str(core)], check=True, capture_output=True
    )
    kit._git(["checkout", "-b", "master"], cwd=core)
    core.joinpath("Cargo.toml").write_text(
        '[workspace]\n[workspace.package]\nversion = "0.35.0"\n',
        encoding="utf-8",
    )
    kit._git(["add", "-A"], cwd=core)
    kit._git(["commit", "-m", "core manifest"], cwd=core)
    kit._git(["push", "-u", "origin", "master"], cwd=core)
    return remote, core


def test_unknown_pin_is_fatal_with_remote_remedy(tmp_path: Path) -> None:
    _, core = _pushed_core(tmp_path)
    checkout = kit.make_checkout(tmp_path, core_dep="sase-core-rs>=0.35.0,<0.36.0")
    kit.write_pin_file(checkout, "a" * 40)
    with pytest.raises(install_core.CorePairingError, match="not on the core's remote"):
        _pair(tmp_path, checkout, core)


def test_pin_fetch_failure_names_the_fetch_error(tmp_path: Path) -> None:
    # A core checkout with no remote cannot be fetched: the error names the
    # fetch failure instead of claiming the pin is missing upstream.
    core = kit.make_core_checkout(tmp_path)
    checkout = kit.make_checkout(tmp_path, core_dep="sase-core-rs>=0.35.0,<0.36.0")
    kit.write_pin_file(checkout, "a" * 40)
    with pytest.raises(install_core.CorePairingError, match="could not fetch"):
        _pair(tmp_path, checkout, core)


def test_diverged_core_is_fatal_with_diverged_state(tmp_path: Path) -> None:
    remote = tmp_path / "core-remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    core = tmp_path / "sase-core"
    subprocess.run(
        ["git", "clone", str(remote), str(core)], check=True, capture_output=True
    )
    kit._git(["checkout", "-b", "master"], cwd=core)
    core.joinpath("Cargo.toml").write_text(
        '[workspace]\n[workspace.package]\nversion = "0.35.0"\n',
        encoding="utf-8",
    )
    kit._git(["add", "-A"], cwd=core)
    kit._git(["commit", "-m", "core manifest"], cwd=core)
    kit._git(["push", "-u", "origin", "master"], cwd=core)

    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(remote), str(other)], check=True, capture_output=True
    )
    kit.git_commit(other, "upstream.txt")
    kit._git(["push", "origin", "master"], cwd=other)
    # Local commit after the fetch below makes the checkout diverged.
    kit.git_commit(core, "local.txt")

    checkout = kit.make_checkout(tmp_path, core_dep="sase-core-rs>=0.35.0,<0.36.0")
    kit.write_pin_file(checkout, kit.git_head(other))
    with pytest.raises(install_core.CorePairingError, match="diverged"):
        _pair(tmp_path, checkout, core)


def test_stale_hatch_downgrades_remote_miss_to_warning_row(
    tmp_path: Path,
) -> None:
    core = kit.make_core_checkout(tmp_path)
    checkout = kit.make_checkout(tmp_path, core_dep="sase-core-rs>=0.35.0,<0.36.0")
    kit.write_pin_file(checkout, "b" * 40)
    pairing = _pair(tmp_path, checkout, core, SASE_ALLOW_STALE_CORE="1")
    assert pairing.action == "stale"
    assert pairing.kind == "keep"
    assert pairing.consequential
    assert "SASE_ALLOW_STALE_CORE=1" in pairing.note

    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="dev"),
        state=install_state.read_state(
            tool_dir=kit.make_tool_env(tmp_path, checkout=checkout)[0],
            bin_dir=tmp_path / "tool" / "sase" / "bin",
        ),
        checkout_root=checkout,
        core_dir=core,
        env=kit.make_env(tmp_path, SASE_ALLOW_STALE_CORE="1"),
        pypi_lookup=kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"}),
    )
    assert plan.consequential
    assert not plan.noop


def test_missing_pin_file_is_fatal(tmp_path: Path) -> None:
    core = kit.make_core_checkout(tmp_path)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    with pytest.raises(
        install_core.CorePairingError, match="sase-core-revision.txt is missing"
    ):
        _pair(tmp_path, checkout, core)


def test_malformed_pin_is_fatal(tmp_path: Path) -> None:
    core = kit.make_core_checkout(tmp_path)
    checkout = kit.make_checkout(tmp_path)
    kit.write_pin_file(checkout, "not-a-sha")
    with pytest.raises(install_core.CorePairingError, match="does not hold a 40-hex"):
        _pair(tmp_path, checkout, core)


def test_floor_failure_is_fatal_and_stale_allows_it(tmp_path: Path) -> None:
    core = kit.make_core_checkout(tmp_path, version="0.34.0")
    checkout = kit.make_dev_checkout(tmp_path, core)
    with pytest.raises(
        install_core.CorePairingError, match="behind the sase-core-rs floor"
    ):
        _pair(tmp_path, checkout, core)
    pairing = _pair(tmp_path, checkout, core, SASE_ALLOW_STALE_CORE="1")
    assert pairing.action == "ready"
    assert pairing.consequential
    assert "floor" in pairing.note


def test_ahead_of_window_is_a_dim_note(tmp_path: Path) -> None:
    core = kit.make_core_checkout(tmp_path, version="0.37.0")
    checkout = kit.make_dev_checkout(tmp_path, core)
    pairing = _pair(tmp_path, checkout, core)
    assert pairing.action == "ready"
    assert not pairing.consequential
    assert "ahead of the published" in pairing.note


def test_containment_matches_sase_core_pin(tmp_path: Path) -> None:
    from sase.dev_update.core_pin import core_contains_revision

    core = kit.make_core_checkout(tmp_path)
    head = kit.git_head(core)
    env = kit.make_env(tmp_path)
    assert install_core.contains_revision(core, head, env=env) is True
    assert core_contains_revision(core, head, "HEAD") is True
    assert install_core.contains_revision(core, "c" * 40, env=env) is False
    assert core_contains_revision(core, "c" * 40, "HEAD") is False
    kit.git_commit(core, "later.txt")
    assert install_core.contains_revision(core, head, env=env) is True
    assert core_contains_revision(core, head, "HEAD") is True


def test_fast_forward_mirrors_refresh_clean_linked_checkout(
    tmp_path: Path,
) -> None:
    from sase._linked_repo_workspaces import refresh_clean_linked_checkout

    remote = tmp_path / "core-remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    core = tmp_path / "sase-core"
    subprocess.run(
        ["git", "clone", str(remote), str(core)], check=True, capture_output=True
    )
    kit._git(["checkout", "-b", "master"], cwd=core)
    core.joinpath("Cargo.toml").write_text(
        '[workspace]\n[workspace.package]\nversion = "0.35.0"\n',
        encoding="utf-8",
    )
    kit._git(["add", "-A"], cwd=core)
    kit._git(["commit", "-m", "core manifest"], cwd=core)
    kit._git(["push", "-u", "origin", "master"], cwd=core)

    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(remote), str(other)], check=True, capture_output=True
    )
    kit.git_commit(other, "upstream.txt")
    kit._git(["push", "origin", "master"], cwd=other)

    checkout = kit.make_checkout(tmp_path, core_dep="sase-core-rs>=0.35.0,<0.36.0")
    kit.write_pin_file(checkout, kit.git_head(other))
    # The pairing rule fetches the pin, then offers the same fast-forward
    # the workspace refresher performs.
    assert _pair(tmp_path, checkout, core).action == "fast-forward"
    assert refresh_clean_linked_checkout(str(core)) is not None
    # After the refresh the pin is contained: the pair is ready.
    assert _pair(tmp_path, checkout, core).action == "ready"


def test_entry_reports_pairing_failure_as_exit_1(
    tmp_path: Path, monkeypatch: object
) -> None:
    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    _, core = _pushed_core(tmp_path)
    checkout = kit.make_checkout(tmp_path, core_dep="sase-core-rs>=0.35.0,<0.36.0")
    kit.write_pin_file(checkout, "d" * 40)
    tool_dir, bin_dir = kit.make_tool_env(tmp_path, checkout=checkout)
    env = kit.make_env(tmp_path, SASE_CORE_DIR=str(core))
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    exit_code, _, err = kit.run_entry(
        entry,
        ["dev", "-n"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 1
    assert "not on the core's remote" in err
