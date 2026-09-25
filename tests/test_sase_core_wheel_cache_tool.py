from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time
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
def fake_cargo(tmp_path: Path) -> Path:
    cargo = tmp_path / "cargo"
    cargo.write_text(
        "#!/bin/sh\n"
        'if [ -n "${FAKE_CARGO_COUNTER:-}" ]; then printf build >> "$FAKE_CARGO_COUNTER"; fi\n'
        'sleep "${FAKE_CARGO_DELAY:-0}"\n'
        "profile=\n"
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = "--profile" ]; then shift; profile="$1"; fi\n'
        "  shift\n"
        "done\n"
        'mkdir -p "$CARGO_TARGET_DIR/$profile"\n'
        'printf lsp > "$CARGO_TARGET_DIR/$profile/sase-xprompt-lsp"\n',
        encoding="utf-8",
    )
    cargo.chmod(0o755)
    return cargo


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
    kind: str = "wheel",
    profile: str = "release",
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
        "--kind",
        kind,
        "--profile",
        profile,
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


@pytest.mark.parametrize(
    ("kind", "profile"),
    [("wheel", "release"), ("lsp", "dev-update")],
)
def test_dirty_checkout_is_not_cacheable(
    core_checkout: Path,
    fake_rustc: Path,
    tmp_path: Path,
    kind: str,
    profile: str,
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
            kind=kind,
            profile=profile,
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


def test_lsp_store_lookup_and_eviction(
    core_checkout: Path,
    fake_cargo: Path,
    fake_rustc: Path,
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    target_dir = core_checkout / "target/lsp"
    first = _run(
        [
            *_tool_args(
                "store",
                core_checkout=core_checkout,
                cache_dir=cache_dir,
                fake_rustc=fake_rustc,
                kind="lsp",
                profile="dev-update",
            ),
            "--cargo",
            str(fake_cargo),
            "--cargo-target-dir",
            str(target_dir),
            "--max-entries",
            "1",
        ],
        cwd=ROOT,
    )
    stored_lsp = Path(first.stdout.strip())

    lookup = _run(
        _tool_args(
            "lookup",
            core_checkout=core_checkout,
            cache_dir=cache_dir,
            fake_rustc=fake_rustc,
            kind="lsp",
            profile="dev-update",
        ),
        cwd=ROOT,
    )

    second = _run(
        [
            *_tool_args(
                "store",
                core_checkout=core_checkout,
                cache_dir=cache_dir,
                fake_rustc=fake_rustc,
                kind="lsp",
                profile="release",
            ),
            "--cargo",
            str(fake_cargo),
            "--cargo-target-dir",
            str(target_dir),
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
    stored_release = Path(second.stdout.strip())
    assert Path(lookup.stdout.strip()) == stored_lsp
    assert not stored_lsp.exists()
    assert stored_release.is_file()
    assert len(entries) == 1


def test_lsp_key_separates_profile_and_toolchain(
    core_checkout: Path,
    fake_rustc: Path,
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    release = _run(
        _tool_args(
            "key",
            core_checkout=core_checkout,
            cache_dir=cache_dir,
            fake_rustc=fake_rustc,
            kind="lsp",
            profile="release",
        ),
        cwd=ROOT,
    ).stdout.strip()
    dev_update = _run(
        _tool_args(
            "key",
            core_checkout=core_checkout,
            cache_dir=cache_dir,
            fake_rustc=fake_rustc,
            kind="lsp",
            profile="dev-update",
        ),
        cwd=ROOT,
    ).stdout.strip()
    other_rustc = tmp_path / "other-rustc"
    other_rustc.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'rustc 1.89.0 (test)' "
        "'binary: rustc' 'host: x86_64-unknown-linux-gnu'\n",
        encoding="utf-8",
    )
    other_rustc.chmod(0o755)
    other_toolchain = _run(
        _tool_args(
            "key",
            core_checkout=core_checkout,
            cache_dir=cache_dir,
            fake_rustc=other_rustc,
            kind="lsp",
            profile="release",
        ),
        cwd=ROOT,
    ).stdout.strip()

    assert len({release, dev_update, other_toolchain}) == 3


def test_lsp_store_rechecks_after_waiting_for_identity_lock(
    core_checkout: Path,
    fake_cargo: Path,
    fake_rustc: Path,
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    counter = tmp_path / "cargo-count"
    args = [
        *_tool_args(
            "store",
            core_checkout=core_checkout,
            cache_dir=cache_dir,
            fake_rustc=fake_rustc,
            kind="lsp",
            profile="dev-update",
        ),
        "--cargo",
        str(fake_cargo),
        "--cargo-target-dir",
        str(core_checkout / "target/lsp"),
    ]
    env = os.environ.copy()
    env.update({"FAKE_CARGO_COUNTER": str(counter), "FAKE_CARGO_DELAY": "0.3"})
    first = subprocess.Popen(
        args,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not counter.exists() and time.monotonic() < deadline:
        time.sleep(0.01)  # sase-test-wait: polls for fake cargo start marker
    assert counter.exists()

    second = _run(args, cwd=ROOT, env=env)
    first_stdout, first_stderr = first.communicate(timeout=5)

    assert first.returncode == 0, first_stderr
    assert Path(first_stdout.strip()).is_file()
    assert Path(second.stdout.strip()).is_file()
    assert "Waiting for the shared build lock" in second.stderr
    assert counter.read_text(encoding="utf-8") == "build"


def test_lsp_store_builds_after_lock_timeout(
    core_checkout: Path,
    fake_cargo: Path,
    fake_rustc: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "cache"
    key = _run(
        _tool_args(
            "key",
            core_checkout=core_checkout,
            cache_dir=cache_dir,
            fake_rustc=fake_rustc,
            kind="lsp",
            profile="dev-update",
        ),
        cwd=ROOT,
    ).stdout.strip()
    lock_path = cache_dir / ".locks" / f"{key}.lock"
    lock_path.parent.mkdir(parents=True)
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        monkeypatch.setenv("SASE_CORE_ARTIFACT_CACHE_LOCK_TIMEOUT_SECONDS", "0.01")
        result = _run(
            [
                *_tool_args(
                    "store",
                    core_checkout=core_checkout,
                    cache_dir=cache_dir,
                    fake_rustc=fake_rustc,
                    kind="lsp",
                    profile="dev-update",
                ),
                "--cargo",
                str(fake_cargo),
                "--cargo-target-dir",
                str(core_checkout / "target/lsp"),
            ],
            cwd=ROOT,
            env=os.environ.copy(),
        )

    assert Path(result.stdout.strip()).is_file()
    assert "Shared build lock timed out; building without it." in result.stderr
