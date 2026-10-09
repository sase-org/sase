"""Dev execution pipeline: hermetic end-to-end runs plus agreement coverage.

Every test here runs the real entry point with fake ``uv``/``just``/``sase``
executables on ``PATH`` and real temporary git repos for the sase checkout
and its paired sase-core — no network, no real tool environment, and no
prompt is ever answered by a human. Covered: the full dev sequence (prepare,
swap, re-apply, verify, restart, summary), re-apply failure messaging, stamp
mismatch, ``sase update`` agreement parsing (pass, repair, and inconclusive),
repeat-run no-op, a dirty-core rebuild, a workspace-path refusal, and paths
with spaces.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import tests._sase_install_testkit as kit

# NOTE: imported after the testkit, which puts tools/ on sys.path.
import _sase_core_source_identity as core_identity  # noqa: E402
from tests._sase_install_testkit import (
    install_core,
    install_plan,
    install_run,
    install_state,
    install_ui,
)


FAKE_UV = """\
#!/usr/bin/env python3
import json as _j, os as _o, sys as _s
_a = _s.argv[1:]
if _a == ["--version"]:
    print("uv 0.12.10")
elif _a == ["tool", "dir"]:
    print(_o.environ["UV_TOOL_DIR"])
elif _a == ["tool", "dir", "--bin"]:
    print(_o.environ["UV_TOOL_BIN_DIR"])
elif _a[:2] == ["tool", "install"]:
    _c = _o.environ.get("UV_CAPTURE")
    if _c:
        with open(_c, "a", encoding="utf-8") as _f:
            _f.write(_j.dumps(_a) + "\\n")
    _s.exit(int(_o.environ.get("UV_EXIT", "0")))
else:
    print("unexpected uv args: %r" % (_a,), file=_s.stderr)
    _s.exit(2)
"""

FAKE_JUST = """\
#!/usr/bin/env python3
import json as _j, os as _o, sys as _s
import pathlib as _p
_a = _s.argv[1:]
if "rust-dev-install-uv-tool" in _a:
    _c = _o.environ.get("JUST_CAPTURE")
    if _c:
        with open(_c, "a", encoding="utf-8") as _f:
            _f.write(
                _j.dumps(
                    {
                        "argv": _a,
                        "profile": _o.environ.get("SASE_RUST_DEV_PROFILE"),
                    }
                )
                + "\\n"
            )
    _rc = int(_o.environ.get("JUST_EXIT", "0"))
    if _rc == 0 and _o.environ.get("JUST_WRITE_STAMP") == "1":
        _tool = _p.Path(_o.environ["JUST_TOOL_DIR"])
        (_tool / "bin").mkdir(parents=True, exist_ok=True)
        (_tool / "bin" / "sase-macro-lsp").write_bytes(b"fake-lsp")
        _stamp = _o.environ.get("JUST_STAMP")
        if _stamp:
            (_tool / ".sase-core-rs-source.json").write_text(_stamp)
    _s.exit(_rc)
print("unexpected just args: %r" % (_a,), file=_s.stderr)
_s.exit(2)
"""

FAKE_SASE = """\
#!/usr/bin/env python3
import json as _j, os as _o, sys as _s
_a = _s.argv[1:]
if _a == ["core", "health", "-j"]:
    print(_o.environ.get("FAKE_HEALTH_JSON", '{"status": "ok"}'))
    _s.exit(int(_o.environ.get("FAKE_HEALTH_EXIT", "0")))
if _a == ["version", "-j"]:
    print(_o.environ["FAKE_VERSION_JSON"])
    _s.exit(int(_o.environ.get("FAKE_VERSION_EXIT", "0")))
if _a == ["lsp", "--version"]:
    print(_o.environ.get("FAKE_LSP_OUTPUT", "sase-macro-lsp 0.37.0"))
    _s.exit(int(_o.environ.get("FAKE_LSP_EXIT", "0")))
if _a == ["update", "-n", "-j"]:
    print(_o.environ["FAKE_UPDATE_JSON"])
    _s.exit(int(_o.environ.get("FAKE_UPDATE_EXIT", "0")))
if _a == ["scheduler", "restart"]:
    _c = _o.environ.get("SASE_CAPTURE")
    if _c:
        with open(_c, "a", encoding="utf-8") as _f:
            _f.write("scheduler-restart\\n")
    _s.exit(int(_o.environ.get("FAKE_RESTART_EXIT", "0")))
print("unexpected sase args: %r" % (_a,), file=_s.stderr)
_s.exit(2)
"""

FAKE_TOOL_PYTHON = """\
#!/usr/bin/env python3
import json as _j, os as _o, sys as _s
_a = _s.argv[1:]
if "--src" in _a:
    _s.exit(int(_o.environ.get("FAKE_BINDINGS_EXIT", "0")))
if "-c" in _a:
    _script = _a[_a.index("-c") + 1]
    if "importlib" in _script:
        _rest = _a[_a.index("-c") + 2 :]
        print(_j.dumps({n: "9.9.9" for n in _rest}))
    else:
        print(_o.environ.get("FAKE_IMPORTS", "{}"))
    _s.exit(0)
print("unexpected tool python args: %r" % (_a,), file=_s.stderr)
_s.exit(2)
"""


def _write_exe(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _agree_update_json() -> str:
    """Return an update dry-run document that agrees with a dev install."""
    return json.dumps(
        {
            "schema_version": 1,
            "dry_run": True,
            "mode": "dev",
            "dev": {
                "packages": [
                    {
                        "name": "sase",
                        "role": "host",
                        "status": "skipped",
                        "reason": "already current",
                    }
                ],
                "roots": [],
                "reconcile_steps": [],
            },
        }
    )


class Harness:
    """One hermetic dev-install world: fakes, git repos, tool env, env."""

    def __init__(self, tmp_path: Path, monkeypatch: Any) -> None:
        kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
        self.root = tmp_path
        self.fakes = tmp_path / "fakes"
        self.fakes.mkdir()
        _write_exe(self.fakes / "uv", FAKE_UV)
        _write_exe(self.fakes / "just", FAKE_JUST)
        self.tool_root = tmp_path / "tools"
        self.bin_root = tmp_path / "bin"
        self.bin_root.mkdir(parents=True)
        self.sase_home = tmp_path / "sase-home"
        self.env = kit.make_env(tmp_path)
        self.env["PATH"] = str(self.fakes) + os.pathsep + self.env["PATH"]
        self.env["UV_TOOL_DIR"] = str(self.tool_root)
        self.env["UV_TOOL_BIN_DIR"] = str(self.bin_root)
        self.env["UV_CAPTURE"] = str(tmp_path / "uv-capture.jsonl")
        self.env["SASE_CAPTURE"] = str(tmp_path / "sase-capture.txt")
        self.env["JUST_CAPTURE"] = str(tmp_path / "just-capture.jsonl")
        self.env["JUST_WRITE_STAMP"] = "1"
        repos = tmp_path / "repos"
        repos.mkdir()
        self.core = kit.make_core_checkout(repos, name="sase-core")
        self.checkout = kit.make_dev_checkout(repos, self.core, name="checkout")
        kit.init_git_repo(self.checkout)
        self.env["SASE_CORE_DIR"] = str(self.core)
        self.tool_dir = self.tool_root / "sase"
        self.lookup = kit.FakePyPI({})
        self._write_tool_env()
        self._write_probes()
        self._build_ok(monkeypatch)

    def _write_tool_env(
        self,
        *,
        host: tuple[str, str | None] | None = ("pypi", "0.17.1"),
        core_editable: str | None = None,
        with_receipt: bool = True,
        lsp: bool = True,
    ) -> None:
        if self.tool_dir.exists():
            import shutil

            shutil.rmtree(self.tool_dir)
        bin_dir = self.tool_dir / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        _write_exe(bin_dir / "python", FAKE_TOOL_PYTHON)
        site = self.tool_dir / "lib" / "python3.14" / "site-packages"
        site.mkdir(parents=True, exist_ok=True)
        self.env["FAKE_SITE_PACKAGES"] = str(site)
        self.tool_dir.joinpath("pyvenv.cfg").write_text(
            "home = /fake/bin\nversion_info = 3.14.7\n"
            "include-system-site-packages = false\n",
            encoding="utf-8",
        )
        entries: list[dict[str, str]] = []
        if host is not None:
            kind, value = host
            if kind == "editable":
                assert value is not None
                entries.append({"name": "sase", "editable": str(value)})
                kit.write_dist(site, "sase", "0.17.1", editable=str(value))
            else:
                entries.append({"name": "sase", "specifier": f"=={value}"})
                kit.write_dist(site, "sase", value or "0.17.1")
        if core_editable is not None:
            kit.write_dist(site, "sase-core-rs", "0.37.0", editable=core_editable)
        else:
            kit.write_dist(site, "sase-core-rs", "0.35.4")
        if with_receipt:
            kit.write_receipt(self.tool_dir, entries)
        if lsp:
            bin_dir.joinpath("sase-macro-lsp").write_bytes(b"fake-lsp")
        _write_exe(self.bin_root / "sase", FAKE_SASE)

    def _write_probes(self) -> None:
        self.env["FAKE_IMPORTS"] = json.dumps(
            {
                "sase": str(Path(self.checkout) / "src" / "sase" / "__init__.py"),
                "sase_core_rs": str(
                    Path(self.core)
                    / "crates"
                    / "sase_core_py"
                    / "python"
                    / "sase_core_rs"
                    / "__init__.py"
                ),
            }
        )
        self.env["FAKE_VERSION_JSON"] = json.dumps(
            {
                "schema_version": 1,
                "packages": [
                    {
                        "name": "sase",
                        "role": "host",
                        "install_type": "editable",
                        "source_root": str(self.checkout),
                    },
                    {"name": "sase-core-rs", "role": "core"},
                ],
            }
        )
        self.env["FAKE_UPDATE_JSON"] = _agree_update_json()
        identity = core_identity.compute_identity(Path(self.core))
        assert identity is not None
        self.env["JUST_TOOL_DIR"] = str(self.tool_dir)
        self.env["JUST_STAMP"] = core_identity.format_stamp(identity)

    def _build_ok(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            install_core,
            "pre_swap_build_check",
            lambda *args, **kwargs: install_core.BuildCheck(
                ok=True, method="test", detail="test build ok", elapsed=0.1
            ),
        )

    def write_current_stamp(self) -> None:
        """Stamp the tool env with the core's current identity (a no-op run)."""
        identity = core_identity.compute_identity(Path(self.core))
        assert identity is not None
        stamp = core_identity.format_stamp(identity)
        self.tool_dir.joinpath(".sase-core-rs-source.json").write_text(
            stamp, encoding="utf-8"
        )
        self.env["JUST_STAMP"] = stamp

    def make_noop_env(self) -> None:
        """Shape the tool env so a run is a repeat-run no-op."""
        self._write_tool_env(
            host=("editable", str(self.checkout)),
            core_editable=str(self.core),
        )
        self.write_current_stamp()

    def run(self, args: list[str], **kwargs: Any) -> tuple[int, str, str]:
        """Run the real entry point against this harness (no path overrides)."""
        entry = kit.load_entry()
        return kit.run_entry(
            entry,
            args,
            env=self.env,
            pypi_lookup=self.lookup,
            checkout_root=self.checkout,
            **kwargs,
        )

    def swap_argvs(self) -> list[list[str]]:
        """Return the captured ``uv tool install`` argvs (empty when no swap)."""
        capture = Path(self.env["UV_CAPTURE"])
        if not capture.exists():
            return []
        return [json.loads(line) for line in capture.read_text().splitlines()]

    def just_calls(self) -> list[dict[str, Any]]:
        """Return the captured ``just`` re-apply calls (argv plus profile)."""
        capture = Path(self.env["JUST_CAPTURE"])
        if not capture.exists():
            return []
        return [json.loads(line) for line in capture.read_text().splitlines()]

    def log_files(self) -> list[Path]:
        """Return the per-run install logs under this harness's SASE_HOME."""
        log_dir = self.sase_home / "logs" / "install"
        if not log_dir.is_dir():
            return []
        return sorted(log_dir.glob("install-*.log"))


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
    _write_exe(cargo_bin / "sase-macro-lsp", "#!/bin/sh\nexit 0\n")
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
    _write_exe(fakes / "uv", FAKE_UV)
    _write_exe(fakes / "just", FAKE_JUST)
    bin_root = tmp_path / "bin"
    bin_root.mkdir()
    _write_exe(bin_root / "sase", FAKE_SASE)
    env["PATH"] = str(fakes) + os.pathsep + env["PATH"]
    env["UV_TOOL_DIR"] = str(tmp_path / "tools")
    env["UV_TOOL_BIN_DIR"] = str(bin_root)
    env["UV_CAPTURE"] = str(tmp_path / "uv-capture.jsonl")
    env["JUST_CAPTURE"] = str(tmp_path / "just-capture.jsonl")
    env["JUST_WRITE_STAMP"] = "1"
    tool_dir = Path(env["UV_TOOL_DIR"]) / "sase"
    tool_bin = tool_dir / "bin"
    tool_bin.mkdir(parents=True)
    _write_exe(tool_bin / "python", FAKE_TOOL_PYTHON)
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
    env["FAKE_UPDATE_JSON"] = _agree_update_json()
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
