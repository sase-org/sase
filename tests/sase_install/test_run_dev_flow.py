"""Dev-run flow tests (end-to-end run, no-op, rebuild, re-apply, stamp).

Split from ``tests.sase_install.test_run_dev``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.sase_install._run_dev_harness import (
    Harness,
    core_identity,
    install_core,
    install_run,
)


def test_dev_run_success_end_to_end(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 0
    assert "sase now runs this checkout" in out
    assert "Python edits are live" in out
    assert "back to the release: just install" in out

    swaps = harness.swap_argvs()
    assert len(swaps) == 1
    argv = swaps[0]
    assert argv[:6] == ["tool", "install", "--color", "never", "--force", "--reinstall"]
    assert "--editable" in argv and str(harness.checkout) in argv
    assert "--overrides" in argv
    assert "--python" in argv  # the existing env keeps its interpreter

    just_calls = harness.just_calls()
    assert len(just_calls) == 1
    call = just_calls[0]
    assert call["argv"][0] == "-f"
    assert call["argv"][1] == str(harness.checkout / "Justfile")
    assert call["argv"][-1] == "rust-dev-install-uv-tool"
    assert call["profile"] == "dev-update"

    overrides = (
        Path(harness.env["SASE_HOME"]) / "uv" / "editable-overrides.txt"
    ).read_text(encoding="utf-8")
    assert f"-e {harness.checkout}" in overrides
    assert "sase-core-rs" in overrides
    assert harness.log_files() != []


def test_dev_run_reports_shas_in_summary(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    exit_code, out, _ = harness.run(["dev", "-y"])
    assert exit_code == 0
    checkout_short = install_run.dev_summary_shas(
        checkout_root=harness.checkout, core_dir=harness.core
    )[0]
    assert f"({checkout_short})" in out
    assert "(pin " in out


def test_dev_noop_when_current_and_healthy(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.make_noop_env()
    exit_code, out, _ = harness.run(["dev", "-y"])
    assert exit_code == 0
    assert "already runs this checkout" in out
    assert "with sase-core" in out
    assert "--force reinstalls" in out
    assert harness.swap_argvs() == []
    assert harness.just_calls() == []
    assert harness.log_files() != []


def test_dev_noop_skipped_when_stamp_stale(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.make_noop_env()
    harness.tool_dir.joinpath(".sase-core-rs-source.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "head": "0" * 40,
                "dirty": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 0
    assert "sase now runs this checkout" in out
    assert "core stamp is stale" in err
    assert len(harness.swap_argvs()) == 1


def test_dev_noop_skipped_when_lsp_missing(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.make_noop_env()
    harness.env["JUST_WRITE_STAMP"] = "0"
    (harness.tool_dir / "bin" / "sase-macro-lsp").unlink()
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 0
    assert "sase now runs this checkout" in out
    assert "LSP binary is missing" in err
    assert len(harness.swap_argvs()) == 1


def test_dev_noop_skipped_when_core_retargeted(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    other = tmp_path / "other-core"
    other.mkdir()
    harness.make_noop_env()
    harness._write_tool_env(
        host=("editable", str(harness.checkout)),
        core_editable=str(other),
    )
    harness.write_current_stamp()
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 0
    assert "sase now runs this checkout" in out
    assert "installed core is not the paired checkout" in err
    assert len(harness.swap_argvs()) == 1


def test_dev_dirty_core_rebuilds(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.make_noop_env()
    (harness.core / "dirty-note.txt").write_text("uncommitted\n", encoding="utf-8")
    harness.write_current_stamp()
    harness.env["JUST_STAMP"] = core_identity.format_stamp(
        core_identity.compute_identity(Path(harness.core)) or {}
    )
    exit_code, out, _ = harness.run(["dev", "-y"])
    assert exit_code == 0
    assert "sase now runs this checkout" in out
    assert len(harness.swap_argvs()) == 1


def test_reapply_failure_prints_restore_and_pypi_core_note(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.env["JUST_EXIT"] = "1"
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 1
    assert out == ""
    assert "Re-apply failed" in err
    assert "now holds a PyPI sase-core build" in err
    assert "to restore the previous install, run:" in err


def test_stamp_mismatch_warns_only(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.env["JUST_STAMP"] = json.dumps(
        {"schema_version": 1, "head": "0" * 40, "dirty": "0" * 64}
    )
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 0
    assert "sase now runs this checkout" in out
    assert "sase-core changed during the build; rerun just install-dev" in err


def test_build_check_failure_blocks_before_swap(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    monkeypatch.setattr(
        install_core,
        "pre_swap_build_check",
        lambda *args, **kwargs: install_core.BuildCheck(
            ok=False,
            method="maturin-build",
            detail="maturin build failed: boom",
            elapsed=0.1,
        ),
    )
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 1
    assert out == ""
    assert "Prepare sase-core failed" in err
    assert "boom" in err
    assert harness.swap_argvs() == []
    assert harness.just_calls() == []
