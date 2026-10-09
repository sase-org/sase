"""Dev-update agreement tests (pass, repair, inconclusive, mixed mode).

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
    install_run,
    install_state,
    kit,
)


def _update_doc(
    mode: str,
    packages: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    roots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Parse a ``sase update -n -j`` fixture the way the probe output parses."""
    return json.loads(
        json.dumps(
            {
                "schema_version": 1,
                "dry_run": True,
                "mode": mode,
                "dev": {
                    "packages": packages,
                    "roots": roots or [],
                    "reconcile_steps": steps,
                },
            }
        )
    )


def test_agreement_pass_with_behind_upstream_pull_work() -> None:
    doc = _update_doc(
        "dev",
        [
            {
                "name": "sase",
                "role": "host",
                "status": "actionable",
                "reason": "behind upstream by 2 commit(s)",
            },
            {
                "name": "sase-core-rs",
                "role": "core",
                "status": "skipped",
                "reason": "already current",
            },
        ],
        [
            {
                "kind": "rust_dev_install",
                "label": "Rebuild Rust dev artifacts into the uv-tool venv",
                "command": ["just", "rust-dev-install-uv-tool"],
                "reason": None,
            }
        ],
    )
    verdict = install_run.classify_update_agreement(doc)
    assert verdict.agrees is True
    assert verdict.warning_only is False
    assert 'mode "dev"' in verdict.detail


def test_agreement_fails_on_published_wheel_core() -> None:
    doc = _update_doc(
        "dev",
        [
            {
                "name": "sase-core-rs",
                "role": "core",
                "status": "actionable",
                "reason": (
                    "installed sase-core-rs is a published wheel; dev installs "
                    "use the editable build from the local checkout"
                ),
            }
        ],
        [],
    )
    verdict = install_run.classify_update_agreement(doc)
    assert verdict.agrees is False
    assert verdict.warning_only is False
    assert "published wheel" in verdict.detail


def test_agreement_fails_on_unhealthy_reconcile_step() -> None:
    doc = _update_doc(
        "dev",
        [],
        [
            {
                "kind": "uv_tool_install",
                "label": "Reinstall uv-tool editable Python packages",
                "command": [],
                "reason": "uv tool receipt unavailable",
            }
        ],
    )
    verdict = install_run.classify_update_agreement(doc)
    assert verdict.agrees is False
    assert verdict.warning_only is False
    assert "repair" in verdict.detail


def test_agreement_warns_on_fetch_error() -> None:
    doc = _update_doc(
        "dev",
        [
            {
                "name": "sase",
                "role": "host",
                "status": "skipped",
                "reason": "fetch failed; using cached upstream ref",
                "fetch_error": "git fetch timed out",
            }
        ],
        [],
    )
    verdict = install_run.classify_update_agreement(doc)
    assert verdict.agrees is False
    assert verdict.warning_only is True
    assert "inconclusive" in verdict.detail


def test_agreement_fails_on_managed_mode() -> None:
    verdict = install_run.classify_update_agreement({"mode": "managed", "dev": None})
    assert verdict.agrees is False
    assert verdict.warning_only is False
    assert '"managed"' in verdict.detail


def _clean_mixed_doc() -> dict[str, Any]:
    return _update_doc(
        "mixed",
        [
            {
                "name": "sase",
                "role": "host",
                "status": "skipped",
                "reason": "already current",
            }
        ],
        [
            {
                "kind": "rust_dev_install",
                "label": "Rebuild Rust dev artifacts into the uv-tool venv",
                "command": ["just", "rust-dev-install-uv-tool"],
                "reason": None,
            }
        ],
    )


def test_agreement_accepts_mixed_when_allowed() -> None:
    verdict = install_run.classify_update_agreement(
        _clean_mixed_doc(), allow_mixed=True
    )
    assert verdict.agrees is True
    assert verdict.warning_only is False
    assert '"mixed"' in verdict.detail


def test_agreement_mixed_allowed_still_fails_on_published_wheel() -> None:
    doc = _update_doc(
        "mixed",
        [
            {
                "name": "sase-core-rs",
                "role": "core",
                "status": "actionable",
                "reason": (
                    "installed sase-core-rs is a published wheel; dev installs "
                    "use the editable build from the local checkout"
                ),
            }
        ],
        [],
    )
    verdict = install_run.classify_update_agreement(doc, allow_mixed=True)
    assert verdict.agrees is False
    assert verdict.warning_only is False
    assert "published wheel" in verdict.detail


def test_agreement_mixed_without_allow_mixed_still_fails() -> None:
    verdict = install_run.classify_update_agreement(_clean_mixed_doc())
    assert verdict.agrees is False
    assert verdict.warning_only is False
    assert '"mixed"' in verdict.detail


def test_mixed_mode_with_pypi_plugin_passes_dev_verify(
    tmp_path: Path, monkeypatch: Any
) -> None:
    harness = Harness(tmp_path, monkeypatch)
    # A receipt plugin installed from PyPI: no durable checkout exists, so
    # the dev plan targets PyPI and the install receipt is mixed.
    kit.write_receipt(
        harness.tool_dir,
        [
            {"name": "sase", "specifier": "==0.17.1"},
            {"name": "sase-github", "specifier": ">=0.1"},
        ],
    )
    kit.write_dist(Path(harness.env["FAKE_SITE_PACKAGES"]), "sase-github", "0.4.2")
    harness.lookup = kit.FakePyPI({"sase-github": "0.4.2"})
    harness.env["FAKE_UPDATE_JSON"] = json.dumps(_clean_mixed_doc())
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 0
    assert "sase now runs this checkout" in out
    assert "Verify failed" not in err


def test_agreement_warns_without_a_document() -> None:
    verdict = install_run.classify_update_agreement(None)
    assert verdict.agrees is False
    assert verdict.warning_only is True
    assert "inconclusive" in verdict.detail


def test_update_disagreement_fails_dev_verify(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.env["FAKE_UPDATE_JSON"] = json.dumps({"mode": "managed"})
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 1
    assert out == ""
    assert "Verify failed" in err
    assert 'not "dev"' in err


def test_update_repair_fails_dev_verify(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.env["FAKE_UPDATE_JSON"] = json.dumps(
        {
            "mode": "dev",
            "dev": {
                "packages": [
                    {
                        "name": "sase-core-rs",
                        "role": "core",
                        "status": "actionable",
                        "reason": (
                            "installed sase-core-rs is a published wheel; dev "
                            "installs use the editable build"
                        ),
                    }
                ],
                "roots": [],
                "reconcile_steps": [],
            },
        }
    )
    exit_code, out, err = harness.run(["dev", "-y"])
    assert exit_code == 1
    assert out == ""
    assert "Verify failed" in err
    assert "published wheel" in err


def test_update_timeout_warns_only(tmp_path: Path, monkeypatch: Any) -> None:
    harness = Harness(tmp_path, monkeypatch)
    plan = install_plan.build_plan(
        options=install_plan.PlanOptions(mode="dev"),
        state=install_state.read_state(
            tool_dir=harness.tool_dir, bin_dir=harness.tool_dir / "bin"
        ),
        checkout_root=harness.checkout,
        core_dir=harness.core,
        env=harness.env,
        pypi_lookup=harness.lookup,
    )

    def _hang(argv: object, **kwargs: object) -> install_run.RunnerResult:
        argv_list = list(argv) if isinstance(argv, (list, tuple)) else []
        if len(argv_list) >= 3 and argv_list[1:3] == ["update", "-n"]:
            return install_run.RunnerResult(
                returncode=124, stdout="", stderr="", timed_out=True
            )
        return install_run.default_runner(argv_list, **kwargs)  # type: ignore[arg-type]

    checks = install_run.verify_dev_install(
        plan=plan,
        state=install_state.read_state(
            tool_dir=harness.tool_dir, bin_dir=harness.tool_dir / "bin"
        ),
        tool_dir=harness.tool_dir,
        sase_exe=harness.bin_root / "sase",
        tool_python=harness.tool_dir / "bin" / "python",
        env=harness.env,
        run=_hang,
    )
    by_name = {check.name: check for check in checks}
    assert by_name["update-agreement"].warning_only is True
    assert "inconclusive" in by_name["update-agreement"].detail
    assert by_name["imports"].ok is True
    assert by_name["version"].ok is True
