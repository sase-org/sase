from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "sase_core_wheel_cache"


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _git(core_dir: Path, *args: str) -> None:
    _run(["git", "-C", str(core_dir), *args], cwd=core_dir)


@pytest.fixture
def fake_rustc(tmp_path: Path) -> Path:
    rustc = tmp_path / "rustc"
    rustc.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' 'rustc 1.88.0 (test)' "
        "'binary: rustc' 'host: x86_64-unknown-linux-gnu'\n",
        encoding="utf-8",
    )
    rustc.chmod(0o755)
    return rustc


@pytest.fixture
def fake_maturin(tmp_path: Path) -> Path:
    maturin = tmp_path / "maturin"
    maturin.write_text(
        "#!/bin/sh\n"
        "out=''\n"
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = \'--out\' ]; then shift; out="$1"; fi\n'
        "  shift\n"
        "done\n"
        'mkdir -p "$out"\n'
        'printf test > "$out/sase_core_rs-0.0.0-cp311-cp311-linux_x86_64.whl"\n',
        encoding="utf-8",
    )
    maturin.chmod(0o755)
    return maturin


@pytest.fixture
def core_checkout(tmp_path: Path) -> Path:
    core_dir = tmp_path / "sase-core"
    (core_dir / "crates/sase_core_py/src").mkdir(parents=True)
    (core_dir / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    (core_dir / "Cargo.lock").write_text("# lock\n", encoding="utf-8")
    (core_dir / "crates/sase_core_py/Cargo.toml").write_text(
        "[package]\nname = 'sase_core_py'\nversion = '0.0.0'\n",
        encoding="utf-8",
    )
    (core_dir / "crates/sase_core_py/src/lib.rs").write_text(
        "pub fn test() {}\n",
        encoding="utf-8",
    )
    _run(["git", "init"], cwd=core_dir)
    _run(["git", "config", "user.name", "Test"], cwd=core_dir)
    _run(["git", "config", "user.email", "test@example.com"], cwd=core_dir)
    _run(["git", "add", "."], cwd=core_dir)
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    _run(["git", "commit", "-m", "init"], cwd=core_dir, env=env)
    return core_dir


def _tool_args(
    command: str,
    *,
    core_checkout: Path,
    cache_dir: Path,
    fake_rustc: Path,
) -> list[str]:
    return [
        sys.executable,
        str(TOOL),
        command,
        "--sase-core-dir",
        str(core_checkout),
        "--python",
        sys.executable,
        "--cache-dir",
        str(cache_dir),
        "--rustc",
        str(fake_rustc),
    ]


def test_key_changes_when_committed_crate_inputs_change(
    core_checkout: Path,
    fake_rustc: Path,
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    first = _run(
        _tool_args(
            "key",
            core_checkout=core_checkout,
            cache_dir=cache_dir,
            fake_rustc=fake_rustc,
        ),
        cwd=ROOT,
    ).stdout.strip()

    (core_checkout / "crates/sase_core_py/src/lib.rs").write_text(
        "pub fn changed() {}\n",
        encoding="utf-8",
    )
    _git(core_checkout, "add", ".")
    _git(core_checkout, "commit", "-m", "change")

    second = _run(
        _tool_args(
            "key",
            core_checkout=core_checkout,
            cache_dir=cache_dir,
            fake_rustc=fake_rustc,
        ),
        cwd=ROOT,
    ).stdout.strip()

    assert first
    assert second
    assert first != second


def test_dirty_checkout_is_not_cacheable(
    core_checkout: Path,
    fake_rustc: Path,
    tmp_path: Path,
) -> None:
    (core_checkout / "crates/sase_core_py/src/lib.rs").write_text(
        "pub fn dirty() {}\n",
        encoding="utf-8",
    )

    result = _run(
        _tool_args(
            "key",
            core_checkout=core_checkout,
            cache_dir=tmp_path / "cache",
            fake_rustc=fake_rustc,
        ),
        cwd=ROOT,
        check=False,
    )

    assert result.returncode == 1
    assert "checkout is dirty" in result.stderr


def test_untracked_target_directory_is_ignored(
    core_checkout: Path,
    fake_rustc: Path,
    tmp_path: Path,
) -> None:
    target_file = core_checkout / "target/release/build-output"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("generated\n", encoding="utf-8")

    result = _run(
        _tool_args(
            "key",
            core_checkout=core_checkout,
            cache_dir=tmp_path / "cache",
            fake_rustc=fake_rustc,
        ),
        cwd=ROOT,
    )

    assert result.stdout.strip()


def test_store_and_lookup_round_trip_cached_wheel(
    core_checkout: Path,
    fake_rustc: Path,
    fake_maturin: Path,
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"

    store = _run(
        [
            *_tool_args(
                "store",
                core_checkout=core_checkout,
                cache_dir=cache_dir,
                fake_rustc=fake_rustc,
            ),
            "--maturin",
            str(fake_maturin),
        ],
        cwd=ROOT,
    )
    stored_wheel = Path(store.stdout.strip())

    lookup = _run(
        _tool_args(
            "lookup",
            core_checkout=core_checkout,
            cache_dir=cache_dir,
            fake_rustc=fake_rustc,
        ),
        cwd=ROOT,
    )

    assert stored_wheel.is_file()
    assert Path(lookup.stdout.strip()) == stored_wheel


def test_prune_keeps_cache_bounded(
    core_checkout: Path,
    fake_rustc: Path,
    fake_maturin: Path,
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"

    _run(
        [
            *_tool_args(
                "store",
                core_checkout=core_checkout,
                cache_dir=cache_dir,
                fake_rustc=fake_rustc,
            ),
            "--maturin",
            str(fake_maturin),
            "--max-entries",
            "1",
        ],
        cwd=ROOT,
    )
    (core_checkout / "crates/sase_core_py/src/lib.rs").write_text(
        "pub fn newer() {}\n",
        encoding="utf-8",
    )
    _git(core_checkout, "add", ".")
    _git(core_checkout, "commit", "-m", "newer")
    _run(
        [
            *_tool_args(
                "store",
                core_checkout=core_checkout,
                cache_dir=cache_dir,
                fake_rustc=fake_rustc,
            ),
            "--maturin",
            str(fake_maturin),
            "--max-entries",
            "1",
        ],
        cwd=ROOT,
    )

    entries = [
        path
        for path in cache_dir.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(entries) == 1
