"""The ``--sync`` fatal gate: fetch/report for dry runs, merge for real ones."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import tests._sase_install_testkit as kit
from tests._sase_install_testkit import install_core, install_ui


def _seed_remote(tmp_path: Path, name: str = "remote.git") -> Path:
    remote = tmp_path / name
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    return remote


def _clone(remote: Path, dest: Path) -> Path:
    subprocess.run(
        ["git", "clone", str(remote), str(dest)], check=True, capture_output=True
    )
    kit._git(["checkout", "-b", "master"], cwd=dest)
    return dest


def _tracked_clone(tmp_path: Path, name: str = "repo") -> tuple[Path, Path]:
    """Return ``(remote, clone)`` with one pushed commit and an upstream."""
    remote = _seed_remote(tmp_path, f"{name}.git")
    repo = _clone(remote, tmp_path / name)
    repo.joinpath("Cargo.toml").write_text(
        '[workspace]\n[workspace.package]\nversion = "0.35.0"\n',
        encoding="utf-8",
    )
    kit._git(["add", "-A"], cwd=repo)
    kit._git(["commit", "-m", "seed"], cwd=repo)
    kit._git(["push", "-u", "origin", "master"], cwd=repo)
    return remote, repo


def test_fetch_reports_without_merging(tmp_path: Path) -> None:
    remote, repo = _tracked_clone(tmp_path)
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(remote), str(other)], check=True, capture_output=True
    )
    kit.git_commit(other, "upstream.txt")
    kit._git(["push", "origin", "master"], cwd=other)

    before = kit.git_head(repo)
    env = kit.make_env(tmp_path)
    result = install_core.sync_repo(repo, merge=False, env=env)
    assert result.ok
    assert not result.skipped
    assert result.detail.startswith("would fast-forward ")
    assert "(+1)" in result.detail
    assert result.shortstat is not None
    # A dry-run fetch never moves HEAD.
    assert kit.git_head(repo) == before


def test_merge_fast_forwards_and_reports_diffstat(tmp_path: Path) -> None:
    remote, repo = _tracked_clone(tmp_path)
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(remote), str(other)], check=True, capture_output=True
    )
    kit.git_commit(other, "upstream.txt")
    kit._git(["push", "origin", "master"], cwd=other)

    env = kit.make_env(tmp_path)
    result = install_core.sync_repo(repo, merge=True, env=env)
    assert result.ok
    assert result.detail.startswith("fast-forwarded ")
    assert result.shortstat is not None and "1 file changed" in result.shortstat

    again = install_core.sync_repo(repo, merge=False, env=env)
    assert again.ok
    assert again.detail.startswith("already up to date")


def test_failure_states_aggregate(tmp_path: Path) -> None:
    _, clean = _tracked_clone(tmp_path, "clean")
    remote, diverged = _tracked_clone(tmp_path, "diverged")
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(remote), str(other)], check=True, capture_output=True
    )
    kit.git_commit(other, "upstream.txt")
    kit._git(["push", "origin", "master"], cwd=other)
    kit.git_commit(diverged, "local.txt")
    # Pull the upstream in so the checkout reads as diverged, not behind.
    subprocess.run(
        ["git", "fetch", "origin"], cwd=str(diverged), check=True, capture_output=True
    )

    dirty = tmp_path / "dirty"
    subprocess.run(
        ["git", "clone", str(remote), str(dirty)], check=True, capture_output=True
    )
    dirty.joinpath("Cargo.toml").write_text(
        dirty.joinpath("Cargo.toml").read_text(encoding="utf-8") + "# dirty\n",
        encoding="utf-8",
    )
    plain = tmp_path / "plain"
    plain.mkdir()

    env = kit.make_env(tmp_path)
    results = install_core.sync_repos(
        [clean, diverged, dirty, plain, clean], merge=False, env=env
    )
    assert len(results) == 4  # the repeated checkout is visited once
    by_path = {result.path: result for result in results}
    assert by_path[str(clean)].ok
    assert not by_path[str(diverged)].ok
    assert "diverged" in by_path[str(diverged)].detail
    assert not by_path[str(dirty)].ok
    assert "dirty" in by_path[str(dirty)].detail
    assert by_path[str(plain)].ok
    assert by_path[str(plain)].skipped


def test_detached_and_upstreamless_checkouts_fail(tmp_path: Path) -> None:
    _, repo = _tracked_clone(tmp_path)
    subprocess.run(
        ["git", "checkout", "--detach", "HEAD"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    env = kit.make_env(tmp_path)
    detached = install_core.sync_repo(repo, merge=False, env=env)
    assert not detached.ok
    assert "detached" in detached.detail

    lone = kit.init_git_repo(tmp_path / "lone")
    upstreamless = install_core.sync_repo(lone, merge=False, env=env)
    assert not upstreamless.ok
    assert "no upstream" in upstreamless.detail


def test_sync_report_renders_a_fixed_width_box(tmp_path: Path) -> None:
    text = install_ui.render_sync_report(
        [
            {"path": "/home/u/proj/sase", "ok": True, "detail": "already up to date"},
            {"path": "/home/u/proj/core", "ok": False, "detail": "dirty worktree"},
            {
                "path": "/tmp/plain",
                "ok": True,
                "skipped": True,
                "detail": "not a git checkout; skipping",
            },
        ],
        width=80,
        color=False,
        home="/home/u",
    )
    lines = text.splitlines()
    assert all(len(line) <= 80 for line in lines)
    assert lines[0].startswith("\u256d\u2500 just install-dev \u00b7 --sync")
    assert lines[-1].startswith("\u2570") and lines[-1].endswith("\u256f")
    assert "\u2713 ~/proj/sase" in text
    assert "\u2717 ~/proj/core" in text
    assert "\u2013 /tmp/plain" in text
    assert "\x1b[" not in text


def _entry_harness(
    tmp_path: Path, monkeypatch: object, core: Path | None
) -> tuple[object, dict[str, str], Path, Path, Path, object]:
    entry = kit.load_entry()
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    checkout = kit.make_checkout(tmp_path, core_dep="sase-core-rs>=0.35.0,<0.36.0")
    tool_dir, bin_dir = kit.make_tool_env(tmp_path, checkout=checkout)
    env = kit.make_env(tmp_path)
    if core is not None:
        # The pairing gate runs before the sync report: pin the checkout
        # at the fixture core so planning succeeds.
        kit.write_pin_file(checkout, kit.git_head(core))
        env["SASE_CORE_DIR"] = str(core)
    lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.37.0"})
    return entry, env, checkout, tool_dir, bin_dir, lookup


def test_dry_run_sync_reports_and_never_merges(
    tmp_path: Path, monkeypatch: object
) -> None:
    remote, core = _tracked_clone(tmp_path, "core")
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(remote), str(other)], check=True, capture_output=True
    )
    kit.git_commit(other, "upstream.txt")
    kit._git(["push", "origin", "master"], cwd=other)

    entry, env, checkout, tool_dir, bin_dir, lookup = _entry_harness(
        tmp_path, monkeypatch, core
    )
    before = kit.git_head(core)
    exit_code, out, _ = kit.run_entry(
        entry,
        ["dev", "-n", "--sync"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 0
    assert "--sync" in out
    assert "would fast-forward" in out
    assert kit.git_head(core) == before


def test_dry_run_sync_failure_exits_1_with_boxed_list(
    tmp_path: Path, monkeypatch: object
) -> None:
    _, core = _tracked_clone(tmp_path, "core")
    core.joinpath("seed.txt").write_text("dirty\n", encoding="utf-8")
    entry, env, checkout, tool_dir, bin_dir, lookup = _entry_harness(
        tmp_path, monkeypatch, core
    )
    exit_code, out, _ = kit.run_entry(
        entry,
        ["dev", "-n", "--sync"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 1
    assert "dirty worktree" in out


def test_dry_run_sync_json_carries_per_repo_results(
    tmp_path: Path, monkeypatch: object
) -> None:
    _, core = _tracked_clone(tmp_path, "core")
    entry, env, checkout, tool_dir, bin_dir, lookup = _entry_harness(
        tmp_path, monkeypatch, core
    )
    exit_code, out, _ = kit.run_entry(
        entry,
        ["dev", "-n", "-j", "--sync"],
        env=env,
        pypi_lookup=lookup,
        checkout_root=checkout,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    assert exit_code == 0
    doc = json.loads(out)
    assert isinstance(doc["sync"], list)
    assert {entry["path"] for entry in doc["sync"]} >= {str(core)}
    assert all(entry["ok"] for entry in doc["sync"])
