"""Justfile setup and Rust-install wiring."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests._justfile_lint_helpers import (
    ROOT,
    clean_sase_core_env,
    copy_justfile,
    dry_run,
)

pytestmark = pytest.mark.contract


def _install_spy_python(root: Path) -> None:
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$JUST_SPY_FILE"\nexit 0\n',
        encoding="utf-8",
    )
    python.chmod(0o755)


def test_setup_is_fatal_on_the_core_version_behind_bit() -> None:
    output = dry_run("_setup")

    assert "if [ $((validation_status & 16)) -ne 0 ]" in output
    assert (
        "[setup] ERROR: the sase-core checkout is behind the sase-core-rs floor"
        in output
    )
    assert "sase repo open sase-core" in output
    assert 'if [ "${SASE_ALLOW_STALE_CORE:-}" = "1" ]' in output


def test_setup_notes_the_core_version_ahead_bit_as_normal() -> None:
    output = dry_run("_setup")

    assert "if [ $((validation_status & 1)) -ne 0 ]" in output
    assert (
        "[setup] Note: the sase-core checkout is ahead of the published "
        "sase-core-rs window in pyproject.toml" in output
    )
    assert "no action is needed here" in output


def test_setup_propagates_the_post_rebuild_bindings_check_exit_status() -> None:
    """Without this, `_setup` silently swallows a still-stale rebuilt extension.

    `just` runs recipes under `sh -cu` (no `-e`), so a failing command that
    isn't checked doesn't fail the recipe on its own.
    """
    output = dry_run("_setup")

    assert "tools/validate_sase_core_rs --sase-core-dir" in output
    assert "|| exit $?" in output


def test_refresh_sase_core_checkout_skips_fetch_when_stale_core_is_allowed(
    tmp_path: Path,
) -> None:
    copy_justfile(tmp_path)
    marker = tmp_path / "python-called"
    _install_spy_python(tmp_path)

    subprocess.run(
        [
            "just",
            "--justfile",
            str(tmp_path / "Justfile"),
            "--set",
            "venv_dir",
            ".venv",
            "--set",
            "sase_core_dir",
            str(tmp_path / "sase-core"),
            "_refresh-sase-core-checkout",
        ],
        cwd=tmp_path,
        env=clean_sase_core_env()
        | {
            "JUST_SPY_FILE": str(marker),
            "SASE_ALLOW_STALE_CORE": "1",
        },
        check=True,
        capture_output=True,
        text=True,
    )

    assert not marker.exists()


def test_refresh_sase_core_checkout_fetches_when_stale_core_is_not_allowed(
    tmp_path: Path,
) -> None:
    copy_justfile(tmp_path)
    marker = tmp_path / "python-called"
    _install_spy_python(tmp_path)

    subprocess.run(
        [
            "just",
            "--justfile",
            str(tmp_path / "Justfile"),
            "--set",
            "venv_dir",
            ".venv",
            "--set",
            "sase_core_dir",
            str(tmp_path / "sase-core"),
            "_refresh-sase-core-checkout",
        ],
        cwd=tmp_path,
        env=clean_sase_core_env() | {"JUST_SPY_FILE": str(marker)},
        check=True,
        capture_output=True,
        text=True,
    )

    assert "tools/refresh_linked_checkout" in marker.read_text(encoding="utf-8")


@pytest.mark.parametrize("recipe", ["rust-install", "rust-dev-install"])
def test_rust_install_recipes_skip_refresh_helper_when_stale_core_is_allowed(
    recipe: str,
) -> None:
    output = dry_run(recipe, "/tmp/fake-venv")

    assert 'if [ "${SASE_ALLOW_STALE_CORE:-}" != "1" ]; then' in output
    assert "_refresh-sase-core-checkout" in output
    assert "maturin" in output


def test_rust_dev_install_disables_cargo_incremental_cache() -> None:
    output = dry_run("rust-dev-install", "/tmp/fake-venv")

    assert output.count("CARGO_INCREMENTAL=0") >= 2
    assert (
        output.count(
            'rm -rf "$py_target_dir/build/$profile/incremental" '
            '"$py_target_dir/$profile/incremental"'
        )
        == 1
    )
    assert (
        output.count(
            'rm -rf "$lsp_target_dir/build/$profile/incremental" '
            '"$lsp_target_dir/$profile/incremental"'
        )
        == 1
    )
    assert output.count('"$py_target_dir/$profile/incremental"') == 1
    assert output.count('"$py_target_dir/build/$profile/incremental"') == 1
    assert output.count('"$lsp_target_dir/$profile/incremental"') == 1
    assert output.count('"$lsp_target_dir/build/$profile/incremental"') == 1


def test_rust_dev_install_isolates_cargo_build_dir_with_target() -> None:
    output = dry_run("rust-dev-install", "/tmp/fake-venv")

    assert 'CARGO_BUILD_BUILD_DIR="$py_target_dir/build"' in output
    assert 'CARGO_BUILD_BUILD_DIR="$lsp_target_dir/build"' in output


def test_rust_lsp_install_isolates_cargo_build_dir_with_target() -> None:
    output = dry_run("rust-lsp-install", "/tmp/fake-venv")

    assert 'CARGO_BUILD_BUILD_DIR="$lsp_target_dir/build"' in output


def test_rust_install_also_refreshes_the_macro_lsp_binary() -> None:
    """`just install-venv` must never leave a stale `sase-macro-lsp` behind.

    The extension and the LSP server both compile the same directive contract,
    and the ACE/LSP parity tests compare them, so rebuilding only the extension
    fails those tests with a confusing completion diff.
    """
    output = dry_run("rust-install", "/tmp/fake-venv")

    assert 'rust-lsp-install "/tmp/fake-venv"' in output


def test_rust_install_consults_sase_core_wheel_cache() -> None:
    output = dry_run("rust-install", "/tmp/fake-venv")

    assert 'cache_tool="' in output
    assert 'sase_core_wheel_cache"; cached_wheel=' in output
    assert '"$cache_tool" lookup' in output
    assert "--reinstall-package sase-core-rs" in output
    assert '"$cache_tool" store' in output
    assert 'maturin" develop --release' in output


def test_rust_lsp_install_consults_sase_core_artifact_cache() -> None:
    output = dry_run("rust-lsp-install", "/tmp/fake-venv")

    assert 'cache_tool="' in output
    assert '"$cache_tool" lookup --kind lsp --profile "$profile"' in output
    assert '"$cache_tool" store --kind lsp --profile "$profile"' in output
    assert '--cargo-target-dir "$lsp_target_dir"' in output
    assert "[rust-lsp-install] Installing cached LSP binary from " in output
    assert 'lsp_bin="$(basename "$src")"' in output
    assert '"$lsp_pkg"' in output
    assert '"$lsp_target_dir/$profile/sase-macro-lsp"' in output


def test_rust_install_is_fatal_on_a_behind_status() -> None:
    output = dry_run("rust-install", "/tmp/fake-venv")

    assert 'if [ "$status" -eq 3 ]' in output
    assert (
        "[rust-install] ERROR: the sase-core checkout is behind the sase-core-rs floor"
        in output
    )
    assert "sase repo open sase-core" in output
    assert 'if [ "${SASE_ALLOW_STALE_CORE:-}" = "1" ]' in output


def test_rust_install_notes_other_nonzero_status_as_normal() -> None:
    output = dry_run("rust-install", "/tmp/fake-venv")

    assert 'elif [ "$status" -ne 0 ]' in output
    assert (
        "[rust-install] Note: the sase-core checkout is ahead of the published "
        "sase-core-rs window in pyproject.toml" in output
    )
    assert "no action is needed here" in output


def test_rust_dev_install_writes_the_core_source_stamp() -> None:
    """`rust-dev-install` leaves the same freshness stamp as `rust-install`.

    The identity is captured after the checkout refresh and before the
    build, and the stamp lands only after both the extension and the LSP
    install succeed, so an edit made mid-build still reads as stale.
    """
    output = dry_run("rust-dev-install", "/tmp/fake-venv")

    assert "tools/_sase_core_source_identity.py" in output
    assert ".sase-core-rs-source.json.pending" in output
    assert 'mv -f "$pending"' in output
    assert output.index("_sase_core_source_identity.py") < output.index(
        "develop --profile"
    )
    assert output.index("[rust-dev-install] installed") < output.index(
        'mv -f "$pending"'
    )


@pytest.mark.parametrize(
    "recipe",
    ["rust-install-uv-tool", "rust-dev-install-uv-tool", "rust-lsp-install-uv-tool"],
)
def test_rust_uv_tool_recipes_fail_when_prerequisites_are_missing(
    recipe: str,
) -> None:
    """The uv-tool wrappers must fail, not silently succeed, without uv.

    A missing `uv` or tool venv previously exited 0, so callers (`sase
    update`, the mode switch, and later the installer) could believe the
    rebuild happened.
    """
    output = dry_run(recipe)

    assert output.count("exit 1") == 2
    assert "exit 0" not in output


def test_rust_recipes_are_grouped_and_documented() -> None:
    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "--list"],
        cwd=ROOT,
        env=clean_sase_core_env(),
        check=True,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert "[rust]" in output
    documented = {
        "rust-install ": "Build and install sase_core_rs into a venv",
        "rust-install-uv-tool": "Install sase_core_rs into the uv-tool venv",
        "rust-dev-install ": "Build dev-profile Rust artifacts",
        "rust-dev-install-uv-tool": "Install dev-profile Rust artifacts",
        "rust-lsp-install ": "Build and install the sase-macro-lsp server",
        "rust-lsp-install-uv-tool": "Install sase-macro-lsp into the uv-tool venv",
        "rust-test": "Run cargo test across the sase-core workspace",
        "rust-fmt ": "Format Rust sources in sase-core",
        "rust-fmt-check": "Check Rust formatting in sase-core",
        "rust-clippy": "Run clippy with warnings-as-errors",
        "rust-bench": "Run the Rust direct-parser benchmark",
        "rust-check": "Run Rust fmt-check, clippy, and tests",
    }
    for recipe, doc in documented.items():
        assert recipe in output
        assert doc in output
