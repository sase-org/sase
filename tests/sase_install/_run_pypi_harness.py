"""Shared harness for the ``test_run_pypi_*`` PyPI-pipeline test modules.

Split from ``tests.sase_install.test_run_pypi``. Public helpers used by more
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
from tests._sase_install_testkit import (
    install_plan,
    install_run,
    install_state,
    install_ui,
)

__all__ = [
    "FAKE_SASE",
    "FAKE_TOOL_PYTHON",
    "FAKE_UV",
    "Harness",
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
    _rc = int(_o.environ.get("UV_EXIT", "0"))
    _m = _o.environ.get("HEALTH_MARKER")
    if _rc == 0 and _m:
        import pathlib as _p
        _p.Path(_m).touch()
    _s.exit(_rc)
else:
    print("unexpected uv args: %r" % (_a,), file=_s.stderr)
    _s.exit(2)
"""

FAKE_SASE = """\
#!/usr/bin/env python3
import json as _j, os as _o, sys as _s, time as _t
_a = _s.argv[1:]
if _a == ["core", "health", "-j"]:
    import pathlib as _p
    _m = _o.environ.get("HEALTH_MARKER")
    if _m and _p.Path(_m).exists():
        print('{"status": "ok"}')
        _s.exit(0)
    print(_o.environ.get("FAKE_HEALTH_JSON", '{"status": "ok"}'))
    _s.exit(int(_o.environ.get("FAKE_HEALTH_EXIT", "0")))
if _a == ["version", "-j"]:
    print(_o.environ["FAKE_VERSION_JSON"])
    _s.exit(int(_o.environ.get("FAKE_VERSION_EXIT", "0")))
if _a == ["update", "-n", "-j"]:
    print(_o.environ.get("FAKE_UPDATE_JSON", '{"mode": "managed"}'))
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
if _o.environ.get("FAKE_PYTHON_FAIL"):
    print("fake tool python is broken", file=_s.stderr)
    _s.exit(1)
_site = _o.environ["FAKE_SITE_PACKAGES"]
_missing = set(_o.environ.get("FAKE_MISSING_PLUGINS", "").split())
_script = _s.argv[_s.argv.index("-c") + 1]
_rest = _s.argv[_s.argv.index("-c") + 2:]
if "importlib" in _script:
    print(_j.dumps({n: (None if n in _missing else "9.9.9") for n in _rest}))
else:
    print(_j.dumps(_site + "/" + _rest[0].replace("_", "-") + "/__init__.py"))
"""


def write_exe(path: Path, body: str) -> Path:
    """Write an executable fake script to ``path``."""
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class Harness:
    """One hermetic install world: fakes, tool env, and env mapping."""

    def __init__(self, tmp_path: Path, monkeypatch: Any) -> None:
        kit.fake_probes(monkeypatch)  # type: ignore[arg-type]
        self.root = tmp_path
        self.fakes = tmp_path / "fakes"
        self.fakes.mkdir()
        write_exe(self.fakes / "uv", FAKE_UV)
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
        self.checkout = kit.make_checkout(tmp_path)
        self.lookup = kit.FakePyPI({"sase": "0.17.1", "sase-core-rs": "0.35.4"})
        self.tool_dir = self.tool_root / "sase"
        self._write_tool_env()
        self._write_version_json("0.17.1")

    def _write_tool_env(
        self,
        *,
        host: tuple[str, str | None] | None = ("pypi", "0.17.0"),
        core: tuple[str, str | None] | None = ("pypi", "0.35.4"),
        plugins: tuple[tuple[str, str, str | None], ...] = (),
        with_receipt: bool = True,
        python_version: str = "3.14.7",
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
            "home = /fake/bin\nversion_info = "
            f"{python_version}\ninclude-system-site-packages = false\n",
            encoding="utf-8",
        )
        entries: list[dict[str, str]] = []
        if host is not None:
            kind, value = host
            if kind == "editable":
                entries.append({"name": "sase", "editable": str(value)})
                kit.write_dist(site, "sase", "0.17.1", editable=str(value))
            else:
                entries.append({"name": "sase", "specifier": f"=={value}"})
                kit.write_dist(site, "sase", value or "0.17.1")
        for plugin_name, source, target in plugins:
            if source == "editable":
                assert target is not None
                entries.append({"name": plugin_name, "editable": target})
                kit.write_dist(site, plugin_name, "0.4.2", editable=target)
            else:
                entries.append({"name": plugin_name, "specifier": ">=0.1"})
                kit.write_dist(site, plugin_name, target or "0.4.2")
        if core is not None:
            kind, value = core
            if kind == "editable":
                assert value is not None
                kit.write_dist(site, "sase-core-rs", "0.37.0", editable=value)
            else:
                kit.write_dist(site, "sase-core-rs", value or "0.37.0")
        if with_receipt:
            kit.write_receipt(self.tool_dir, entries)
        write_exe(self.bin_root / "sase", FAKE_SASE)

    def _write_version_json(self, host_version: str) -> None:
        self.env["FAKE_VERSION_JSON"] = json.dumps(
            {
                "schema_version": 1,
                "packages": [
                    {
                        "name": "sase",
                        "role": "host",
                        "install_type": "wheel",
                        "distribution_version": host_version,
                    },
                    {"name": "sase-core-rs", "role": "core"},
                ],
            }
        )

    def run(self, args: list[str], **kwargs: Any) -> tuple[int, str, str]:
        """Run the real entry point against this harness (no path overrides).

        ``tool_dir``/``bin_dir`` are deliberately *not* passed: the entry
        point resolves them through the fake ``uv`` on ``PATH``, exactly like
        production.
        """
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
        capture = Path(self.env["UV_CAPTURE"])
        if not capture.exists():
            return []
        return [json.loads(line) for line in capture.read_text().splitlines()]

    def log_files(self) -> list[Path]:
        log_dir = self.sase_home / "logs" / "install"
        if not log_dir.is_dir():
            return []
        return sorted(log_dir.glob("install-*.log"))
