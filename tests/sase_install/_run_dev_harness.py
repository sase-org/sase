"""Shared harness for the ``test_run_dev_*`` dev-pipeline test modules.

Split from ``tests.sase_install.test_run_dev``. Public helpers used by more
than one split module live here under public names so no new module imports
a ``_``-prefixed name from another new module.
"""

from __future__ import annotations

import json
import os
import stat
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

__all__ = [
    "FAKE_JUST",
    "FAKE_SASE",
    "FAKE_TOOL_PYTHON",
    "FAKE_UV",
    "Harness",
    "agree_update_json",
    "core_identity",
    "install_core",
    "install_plan",
    "install_run",
    "install_state",
    "install_ui",
    "kit",
    "write_exe",
]

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


def write_exe(path: Path, body: str) -> Path:
    """Write an executable fake script to ``path``."""
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def agree_update_json() -> str:
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
        write_exe(self.fakes / "uv", FAKE_UV)
        write_exe(self.fakes / "just", FAKE_JUST)
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
        write_exe(bin_dir / "python", FAKE_TOOL_PYTHON)
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
        write_exe(self.bin_root / "sase", FAKE_SASE)

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
        self.env["FAKE_UPDATE_JSON"] = agree_update_json()
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
