"""Dev-run preparation tests (verify gates, sync, core clone, odd paths).

Split from ``tests.sase_install.test_run_dev``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tests.sase_install._run_dev_harness import (
    FAKE_JUST,
    FAKE_SASE,
    FAKE_TOOL_PYTHON,
    FAKE_UV,
    Harness,
    agree_update_json,
    core_identity,
    install_core,
    kit,
    write_exe,
)


def test_verify_failure_blocks_the_install(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.env["FAKE_HEALTH_JSON"] = '{"status": "error", "error": "no rust"}'
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 1
    assert out == ""
    assert "Verify failed" in err
    assert "health" in err
    assert "to restore the previous install, run:" in err


def test_bindings_failure_blocks_the_install(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.env["FAKE_BINDINGS_EXIT"] = "1"
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 1
    assert out == ""
    assert "Verify failed" in err
    assert "bindings" in err


def test_stale_cargo_lsp_warns_only(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    cargo_bin = tmp_path / "home" / ".cargo" / "bin"
    cargo_bin.mkdir(parents=True)
    write_exe(cargo_bin / "sase-macro-lsp", "#!/bin/sh\nexit 0\n")
    harness.env["HOME"] = str(tmp_path / "home")
    harness.env["PATH"] = f"{cargo_bin}{os.pathsep}{harness.env['PATH']}"
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 0
    assert "sase now runs this checkout" in out
    assert "cargo uninstall sase_macro_lsp" in err


def test_sync_failure_aborts_before_swap(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    (harness.checkout / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    exit_code, out, err = harness.run(["dev", "-y", "--sync"])
    assert exit_code == 1
    assert out == ""
    assert "Sync failed" in err
    assert "dirty worktree" in err
    assert harness.swap_argvs() == []
    assert harness.just_calls() == []


def test_prepare_clones_a_missing_core(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    bare = tmp_path / "sase-core-bare"
    subprocess.run(
        ["git", "clone", "--bare", str(harness.core), str(bare)],
        check=True,
        capture_output=True,
    )
    shutil.rmtree(harness.core)
    harness.env["SASE_INSTALL_CORE_REMOTE"] = str(bare)
    harness.env["JUST_WRITE_STAMP"] = "0"
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 0
    assert "sase now runs this checkout" in out
    assert (harness.core / "Cargo.toml").is_file()
    assert len(harness.swap_argvs()) == 1
    assert "cloned sase-core" in err


def test_dev_run_with_spaces_in_paths(tmp_path: Path, monkeypatch: Any) -> None:
    kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
    spaced = tmp_path / "dir with spaces"
    spaced.mkdir()
    core = kit.make_core_checkout(spaced, name="sase core")
    checkout = kit.make_dev_checkout(spaced, core, name="my checkout")
    kit.init_git_repo(checkout)
    env = kit.make_env(tmp_path)
    env["SASE_CORE_DIR"] = str(core)
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    write_exe(fakes / "uv", FAKE_UV)
    write_exe(fakes / "just", FAKE_JUST)
    bin_root = tmp_path / "bin"
    bin_root.mkdir()
    write_exe(bin_root / "sase", FAKE_SASE)
    env["PATH"] = str(fakes) + os.pathsep + env["PATH"]
    env["UV_TOOL_DIR"] = str(tmp_path / "tools")
    env["UV_TOOL_BIN_DIR"] = str(bin_root)
    env["UV_CAPTURE"] = str(tmp_path / "uv-capture.jsonl")
    env["JUST_CAPTURE"] = str(tmp_path / "just-capture.jsonl")
    env["JUST_WRITE_STAMP"] = "1"
    tool_dir = Path(env["UV_TOOL_DIR"]) / "sase"
    tool_bin = tool_dir / "bin"
    tool_bin.mkdir(parents=True)
    write_exe(tool_bin / "python", FAKE_TOOL_PYTHON)
    site = tool_dir / "lib" / "python3.14" / "site-packages"
    site.mkdir(parents=True)
    tool_dir.joinpath("pyvenv.cfg").write_text(
        "home = /fake/bin\nversion_info = 3.14.7\n"
        "include-system-site-packages = false\n",
        encoding="utf-8",
    )
    kit.write_receipt(tool_dir, [{"name": "sase", "specifier": "==0.17.1"}])
    kit.write_dist(site, "sase", "0.17.1")
    kit.write_dist(site, "sase-core-rs", "0.35.4")
    tool_bin.joinpath("sase-macro-lsp").write_bytes(b"fake-lsp")
    env["FAKE_IMPORTS"] = json.dumps(
        {
            "sase": str(checkout / "src" / "sase" / "__init__.py"),
            "sase_core_rs": str(
                core / "crates" / "sase_core_py" / "python" / "sase_core_rs"
            ),
        }
    )
    env["FAKE_VERSION_JSON"] = json.dumps(
        {
            "schema_version": 1,
            "packages": [
                {
                    "name": "sase",
                    "role": "host",
                    "install_type": "editable",
                    "source_root": str(checkout),
                }
            ],
        }
    )
    env["FAKE_UPDATE_JSON"] = agree_update_json()
    identity = core_identity.compute_identity(core)
    assert identity is not None
    env["JUST_TOOL_DIR"] = str(tool_dir)
    env["JUST_STAMP"] = core_identity.format_stamp(identity)
    monkeypatch.setattr(
        install_core,
        "pre_swap_build_check",
        lambda *args, **kwargs: install_core.BuildCheck(
            ok=True, method="test", detail="test build ok", elapsed=0.1
        ),
    )
    entry = kit.load_entry()
    exit_code, out, _ = kit.run_entry(
        entry,
        ["dev", "-y"],
        env=env,
        pypi_lookup=kit.FakePyPI({}),
        checkout_root=checkout,
    )
    assert exit_code == 0
    assert "sase now runs this checkout" in out
    capture = Path(env["UV_CAPTURE"])
    assert str(checkout) in capture.read_text(encoding="utf-8")
