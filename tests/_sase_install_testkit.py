"""Shared fixtures for the ``sase_install`` engine tests (not collected).

Every ``tools/`` engine file is referenced here by basename so
``tools/pyscripts-260801`` rule 1 (each file needs a reference outside
``tools/``) holds once these tests land: ``sase_install``,
``_sase_install_core.py``, ``_sase_install_env.py``, ``_sase_install_state.py``,
``_sase_install_pypi.py``, ``_sase_install_plan.py``, ``_sase_install_ui.py``.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import Any


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import _sase_install_core as install_core  # noqa: E402
import _sase_install_env as install_env  # noqa: E402
import _sase_install_plan as install_plan  # noqa: E402
import _sase_install_pypi as install_pypi  # noqa: E402
import _sase_install_state as install_state  # noqa: E402
import _sase_install_ui as install_ui  # noqa: E402


ENTRY_BASENAME = "sase_install"
HELPER_BASENAMES = (
    "_sase_install_core.py",
    "_sase_install_env.py",
    "_sase_install_state.py",
    "_sase_install_pypi.py",
    "_sase_install_plan.py",
    "_sase_install_ui.py",
)


def all_engine_basenames() -> tuple[str, ...]:
    """Return every engine file basename (keeps the pyscripts refs live)."""
    return (ENTRY_BASENAME, *HELPER_BASENAMES)


def load_entry() -> Any:
    """Load the extensionless ``tools/sase_install`` entry point as a module."""
    assert ENTRY_BASENAME == Path("tools/sase_install").name
    path = TOOLS_DIR / ENTRY_BASENAME
    loader = SourceFileLoader("sase_install_main", str(path))
    spec = importlib.util.spec_from_file_location(
        "sase_install_main", str(path), loader=loader
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeStdin(io.StringIO):
    """A StringIO with a controllable ``isatty`` answer."""

    def __init__(self, text: str = "", *, tty: bool = False) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        """Return the configured TTY answer."""
        return self._tty


class FakePyPI:
    """An injectable ``pypi_lookup`` mapping names to canned answers."""

    def __init__(
        self,
        versions: dict[str, str] | None = None,
        *,
        unpublished: tuple[str, ...] = (),
        unreachable: tuple[str, ...] = (),
    ) -> None:
        self.versions = dict(versions or {})
        self.unpublished = set(unpublished)
        self.unreachable = set(unreachable)

    def __call__(self, name: str) -> install_pypi.PypiInfo:
        if name in self.unreachable:
            return install_pypi.PypiInfo(
                name=name,
                published=None,
                warning=f"could not reach PyPI for {name}: offline",
            )
        if name in self.unpublished:
            return install_pypi.PypiInfo(name=name, published=False)
        if name in self.versions:
            return install_pypi.PypiInfo(
                name=name, published=True, version=self.versions[name]
            )
        return install_pypi.PypiInfo(name=name, published=True, version="2.0.0")


def make_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    """Return a hermetic env mapping (never the agent's real environment)."""
    env = {
        "HOME": str(tmp_path / "home"),
        "SASE_HOME": str(tmp_path / "sase-home"),
        "SASE_WORKSPACE_ROOT": str(tmp_path / "ws-root"),
        "NO_COLOR": "1",
        "COLUMNS": "80",
        "PATH": os.environ.get("PATH", ""),
    }
    env.update(overrides)
    return env


def make_checkout(
    parent: Path,
    name: str = "checkout",
    version: str = "0.17.1",
    core_dep: str | None = None,
) -> Path:
    """Create a fake sase checkout with a static ``[project]`` version.

    Pass *core_dep* (for example ``"sase-core-rs>=0.35.0,<0.36.0"``) to
    declare the ``sase-core-rs`` floor the version-window check validates.
    """
    root = parent / name
    root.mkdir(parents=True, exist_ok=True)
    dep_line = f'\ndependencies = ["{core_dep}"]' if core_dep else ""
    root.joinpath("pyproject.toml").write_text(
        f'[project]\nname = "sase"\nversion = "{version}"{dep_line}\n',
        encoding="utf-8",
    )
    root.joinpath("sase-core-revision.txt").write_text(
        "e8606a564e4ddccbc4eb2369f4f32dd02ce8c3af\n", encoding="utf-8"
    )
    return root


def write_pin_file(checkout: Path, sha: str) -> Path:
    """Point a fixture checkout's pin file at *sha*."""
    pin = checkout / "sase-core-revision.txt"
    pin.write_text(f"{sha}\n", encoding="utf-8")
    return pin


def _git(args: list[str], cwd: Path) -> Any:
    """Run git with throwaway identity (no global config required)."""
    import subprocess

    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=sase-test",
            "-c",
            "user.email=sase-test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


def init_git_repo(path: Path, *, branch: str = "master") -> Path:
    """Turn *path* into a git repo with one commit on *branch*."""
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", branch], cwd=path)
    path.joinpath("seed.txt").write_text("seed\n", encoding="utf-8")
    _git(["add", "-A"], cwd=path)
    _git(["commit", "-m", "seed"], cwd=path)
    return path


def git_commit(repo: Path, filename: str = "work.txt", content: str = "work\n") -> None:
    """Append one commit touching *filename* in *repo*."""
    repo.joinpath(filename).write_text(content, encoding="utf-8")
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-m", f"touch {filename}"], cwd=repo)


def git_head(repo: Path) -> str:
    """Return the full HEAD sha of *repo*."""
    import subprocess

    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def make_core_checkout(
    parent: Path, name: str = "sase-core", version: str = "0.35.0"
) -> Path:
    """Create a fixture sase-core git checkout at *version*."""
    root = init_git_repo(parent / name)
    root.joinpath("Cargo.toml").write_text(
        f'[workspace]\n[workspace.package]\nversion = "{version}"\n',
        encoding="utf-8",
    )
    _git(["add", "-A"], cwd=root)
    _git(["commit", "-m", "core manifest"], cwd=root)
    return root


def make_dev_checkout(
    parent: Path,
    core: Path,
    *,
    name: str = "checkout",
    dep: str = "sase-core-rs>=0.35.0,<0.36.0",
) -> Path:
    """Create a fixture sase checkout pinned at *core*'s HEAD."""
    checkout = make_checkout(parent, name=name, core_dep=dep)
    write_pin_file(checkout, git_head(core))
    return checkout


def make_sibling(parent: Path, dist_name: str, version: str = "0.4.2") -> Path:
    """Create a fake durable sibling plugin checkout next to a checkout."""
    root = parent / dist_name
    root.mkdir(parents=True, exist_ok=True)
    root.joinpath("pyproject.toml").write_text(
        f'[project]\nname = "{dist_name}"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    return root


def _toml_entry(entry: dict[str, str]) -> str:
    parts = []
    for key, value in entry.items():
        parts.append(f'{key} = "{value}"')
    return "{ " + ", ".join(parts) + " }"


def write_receipt(
    tool_dir: Path,
    entries: list[dict[str, str]],
    *,
    extra: str = "",
) -> Path:
    """Write a ``uv-receipt.toml`` with the given requirement entries."""
    body = "".join(f"    {_toml_entry(entry)},\n" for entry in entries)
    text = f"[tool]\nrequirements = [\n{body}]\n{extra}"
    path = tool_dir / "uv-receipt.toml"
    path.write_text(text, encoding="utf-8")
    return path


def write_dist(
    site_packages: Path,
    name: str,
    version: str,
    *,
    editable: str | None = None,
) -> Path:
    """Create a fake ``*.dist-info`` directory for one installed distribution."""
    norm = name.replace("-", "_")
    dist_info = site_packages / f"{norm}-{version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    dist_info.joinpath("METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )
    if editable is not None:
        dist_info.joinpath("direct_url.json").write_text(
            json.dumps({"url": f"file://{editable}", "dir_info": {"editable": True}}),
            encoding="utf-8",
        )
    return dist_info


def make_tool_env(
    tmp_path: Path,
    *,
    host: tuple[str, str | None] | None = ("editable", None),
    plugins: tuple[tuple[str, str, str | None], ...] = (),
    core: tuple[str, str | None] | None = ("pypi", "0.37.0"),
    python_version: str = "3.14.7",
    with_receipt: bool = True,
    lsp: bool = True,
    checkout: Path | None = None,
) -> tuple[Path, Path]:
    """Create a fake uv tool environment; return ``(tool_dir, bin_dir)``.

    *host* is ``("editable", path)`` or ``("pypi", version)`` (the receipt
    entry); *plugins* holds ``(name, source, version-or-path)`` triples with
    source ``"editable"`` or ``"pypi"``; *core* describes the installed
    ``sase-core-rs`` dist (a ``"local"`` source means a non-editable local
    build). Pass ``host=None`` for an env without the host installed.
    """
    tool_dir = tmp_path / "tool" / "sase"
    if tool_dir.exists():
        shutil.rmtree(tool_dir)
    bin_dir = tool_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.joinpath("python").write_bytes(b"fake")
    tool_dir.joinpath("pyvenv.cfg").write_text(
        "home = /fake/bin\nversion_info = "
        f"{python_version}\ninclude-system-site-packages = false\n",
        encoding="utf-8",
    )
    site_packages = tool_dir / "lib" / "python3.14" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)

    host_path = checkout or (tmp_path / "checkout")
    entries: list[dict[str, str]] = []
    if host is not None:
        kind, value = host
        if kind == "editable":
            entries.append({"name": "sase", "editable": str(value or host_path)})
            write_dist(
                site_packages, "sase", "0.17.1", editable=str(value or host_path)
            )
        else:
            entries.append({"name": "sase", "specifier": f"=={value}"})
            write_dist(site_packages, "sase", value or "0.17.1")
    for plugin_name, source, target in plugins:
        if source == "editable":
            assert target is not None
            entries.append({"name": plugin_name, "editable": target})
            write_dist(site_packages, plugin_name, "0.4.2", editable=target)
        else:
            entries.append({"name": plugin_name, "specifier": ">=0.1"})
            write_dist(site_packages, plugin_name, target or "0.4.2")
    if core is not None:
        kind, value = core
        if kind == "editable":
            assert value is not None
            write_dist(site_packages, "sase-core-rs", "0.37.0", editable=value)
        else:
            write_dist(site_packages, "sase-core-rs", value or "0.37.0")
    if with_receipt:
        write_receipt(tool_dir, entries)
    if lsp:
        bin_dir.joinpath("sase-macro-lsp").write_bytes(b"fake-lsp")
    return tool_dir, bin_dir


def run_entry(
    entry: Any,
    args: list[str],
    *,
    env: dict[str, str],
    stdin: FakeStdin | None = None,
    pypi_lookup: Any = None,
    checkout_root: Path | None = None,
    tool_dir: Path | None = None,
    bin_dir: Path | None = None,
) -> tuple[int, str, str]:
    """Run the entry point with captured streams; return ``(exit, out, err)``."""
    out = io.StringIO()
    err = io.StringIO()
    exit_code = entry.run(
        args,
        env=env,
        stdin=stdin or FakeStdin(),
        stdout=out,
        stderr=err,
        pypi_lookup=pypi_lookup,
        checkout_root=checkout_root,
        tool_dir=tool_dir,
        bin_dir=bin_dir,
    )
    return exit_code, out.getvalue(), err.getvalue()


def fake_probes(monkeypatch: Any) -> None:
    """Patch prerequisite probes to healthy canned answers (no subprocesses)."""
    monkeypatch.setattr(
        install_env,
        "probe_uv",
        lambda: install_env.ProbeResult(
            name="uv", ok=True, version="uv 0.12.10", detail="/fake/uv"
        ),
    )
    monkeypatch.setattr(
        install_env,
        "probe_git",
        lambda: install_env.ProbeResult(
            name="git", ok=True, version="git version 2.50.0", detail="/fake/git"
        ),
    )
    monkeypatch.setattr(
        install_env,
        "probe_cargo",
        lambda: install_env.ProbeResult(
            name="cargo", ok=True, version="cargo 1.89.0", detail="/fake/cargo"
        ),
    )
