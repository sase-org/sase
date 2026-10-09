"""Dev-run output tests (JSON payloads, ephemeral refusal, render lines).

Split from ``tests.sase_install.test_run_dev``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.sase_install._run_dev_harness import (
    Harness,
    install_plan,
    install_ui,
    kit,
)


def test_dev_json_reports_success_with_reapply_command(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    exit_code, out, _ = harness.run(["dev", "-y", "-j"])
    assert exit_code == 0
    doc = json.loads(out)
    assert doc["mode"] == "dev"
    assert doc["outcome"] == "success"
    purposes = [command["purpose"] for command in doc["commands"]]
    assert "swap" in purposes
    assert "re-apply" in purposes
    assert "re-apply" in doc["steps"]


def test_dev_dry_run_json_lists_reapply_command(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    exit_code, out, _ = harness.run(["dev", "-n", "-j"])
    assert exit_code == 0
    doc = json.loads(out)
    assert doc["mode"] == "dev"
    purposes = [command["purpose"] for command in doc["commands"]]
    assert "re-apply" in purposes


def test_ephemeral_checkout_refuses_dev_run(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.env["SASE_WORKSPACE_ROOT"] = str(tmp_path)
    entry = kit.load_entry()
    exit_code, out, err = kit.run_entry(
        entry,
        ["dev", "-n"],
        env=harness.env,
        pypi_lookup=harness.lookup,
        checkout_root=harness.checkout,
    )
    assert exit_code == 2
    assert "install-dev" in out + err


def test_render_dev_success_names_shas_and_pin() -> None:
    plan = install_plan.InstallPlan(
        mode="dev",
        command="just install-dev",
        rows=(),
        python=install_plan.PythonPlan(current="3.14.7", target="3.14.7"),
        target_dir="/tmp/tool",
        current_mode="none",
        consequential=False,
        noop=False,
        warnings=(),
        swap_argv=(),
        overrides_lines=(),
        overrides_path=None,
        checkout_root="/tmp/checkout",
        core_dir="/tmp/core",
    )
    line = install_ui.render_dev_success(
        plan,
        checkout_short="3412a9f",
        core_short="e411a39",
        pin_short="e8606a5",
        commits_past_pin=1,
    )
    assert line == (
        "✓ sase now runs this checkout (3412a9f) "
        "with sase-core e411a39 (pin e8606a5 + 1)\n"
        "  Python edits are live · after Rust edits: just install-dev "
        "· back to the release: just install"
    )
    at_pin = install_ui.render_dev_success(
        plan,
        checkout_short="3412a9f",
        core_short="e411a39",
        pin_short="e8606a5",
        commits_past_pin=0,
    )
    assert "(pin e8606a5)" in at_pin
    assert "+ 0" not in at_pin


def test_render_dev_noop_names_shas() -> None:
    plan = install_plan.InstallPlan(
        mode="dev",
        command="just install-dev",
        rows=(),
        python=install_plan.PythonPlan(current="3.14.7", target="3.14.7"),
        target_dir="/tmp/tool",
        current_mode="none",
        consequential=False,
        noop=True,
        warnings=(),
        swap_argv=(),
        overrides_lines=(),
        overrides_path=None,
        checkout_root="/tmp/checkout",
        core_dir="/tmp/core",
    )
    assert install_ui.render_noop_line(
        plan, checkout_short="3412a9f", core_short="e411a39"
    ) == (
        "✓ sase already runs this checkout (3412a9f) "
        "with sase-core e411a39 — nothing to do (--force reinstalls)"
    )
    assert "already runs this checkout — nothing" in install_ui.render_noop_line(plan)
