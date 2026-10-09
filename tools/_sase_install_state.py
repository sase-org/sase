#!/usr/bin/env python3
"""Installed-state snapshot for the ``sase_install`` engine (stdlib-only).

Reads the uv tool environment without running the installed ``sase``: the
receipt (via :mod:`tomllib`), the interpreter version (via ``pyvenv.cfg``),
installed distributions (via ``*.dist-info``), the core source stamp, and the
LSP binary. The receipt model twins ``sase.uv_tool.receipt`` field for field so
parity tests can compare them entry by entry.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit


#: The primary package / uv tool name.
SASE_PACKAGE = "sase"

#: The uv tool receipt filename living in each tool's venv directory.
RECEIPT_FILENAME = "uv-receipt.toml"

#: Stamp written after a successful editable core build (mirrors the Justfile).
CORE_STAMP_FILENAME = ".sase-core-rs-source.json"

#: The macro LSP server binary installed into the tool ``bin/`` directory.
LSP_BINARY_NAME = "sase-macro-lsp"

_SPEC_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[(?P<extras>[^\]]*)\])?"
    r"(?P<rest>.*)$"
)

_SPECIFIER_START = frozenset("=<>!~")

_NORMALIZE_RE = re.compile(r"[-_.]+")


def normalize_distribution_name(distribution_name: str) -> str:
    """PEP 503-normalize a distribution name (mirrors ``sase``'s helper)."""
    return _NORMALIZE_RE.sub("-", distribution_name).lower()


class ReceiptError(ValueError):
    """A ``uv-receipt.toml`` file is missing, malformed, or incomplete."""


@dataclass(frozen=True)
class InstallRequirement:
    """One ``[tool].requirements`` entry (twin of ``sase``'s ``Requirement``).

    Exactly one source applies: an ``editable`` local path, a ``git`` URL (with
    optional ``git_ref``), a direct ``url`` / local-path passthrough, or — the
    default — an index requirement described by ``name``, ``extras``, and
    ``specifier``.
    """

    name: str
    extras: tuple[str, ...] = ()
    specifier: str | None = None
    editable: str | None = None
    git: str | None = None
    git_ref: str | None = None
    url: str | None = None

    @property
    def normalized_name(self) -> str:
        """PEP 503-normalized distribution name, for dedup/lookup."""
        return normalize_distribution_name(self.name)

    def as_spec(self) -> str:
        """Render the ``name[extras]specifier`` form (index requirements)."""
        extras = f"[{','.join(self.extras)}]" if self.extras else ""
        return f"{self.name}{extras}{self.specifier or ''}"

    def requirement_argument(self) -> str:
        """The single token passed to ``--with`` (or as the install positional)."""
        if self.git is not None:
            ref = f"@{self.git_ref}" if self.git_ref else ""
            return f"git+{self.git}{ref}"
        if self.url is not None:
            return self.url
        return self.as_spec()

    def with_args(self) -> list[str]:
        """argv fragment that re-injects this requirement on ``uv tool install``."""
        if self.editable is not None:
            return ["--with-editable", self.editable]
        return ["--with", self.requirement_argument()]

    def primary_args(self) -> list[str]:
        """argv fragment for this requirement as the install *positional* target."""
        if self.editable is not None:
            return ["--editable", self.editable]
        return [self.requirement_argument()]

    def describe(self) -> str:
        """Human-readable source summary, used in conflict warnings."""
        if self.editable is not None:
            return f"editable {self.editable}"
        if self.git is not None:
            return f"git {self.git}"
        if self.url is not None:
            return f"url {self.url}"
        if self.specifier:
            return f"{self.name} {self.specifier}"
        return f"{self.name} (from the index)"

    @classmethod
    def from_spec(cls, spec: str) -> InstallRequirement:
        """Parse an install spec string into an :class:`InstallRequirement`."""
        spec = spec.strip()
        if not spec:
            raise ValueError("empty requirement spec")
        if spec.startswith("git+") or "://" in spec or _looks_like_path(spec):
            return cls(name=_derive_name(spec), url=spec)

        match = _SPEC_RE.match(spec)
        rest = match.group("rest").strip() if match else ""
        if match is None or (rest and rest[0] not in _SPECIFIER_START):
            return cls(name=_derive_name(spec), url=spec)

        extras_group = match.group("extras")
        extras = (
            tuple(e.strip() for e in extras_group.split(",") if e.strip())
            if extras_group
            else ()
        )
        return cls(
            name=match.group("name"),
            extras=extras,
            specifier=rest or None,
        )


@dataclass(frozen=True)
class ToolReceipt:
    """A parsed ``uv-receipt.toml``: the primary package and injected plugins."""

    primary: InstallRequirement
    plugins: tuple[InstallRequirement, ...] = ()
    requirements: tuple[InstallRequirement, ...] = field(default_factory=tuple)


def parse_receipt_text(text: str, *, primary_name: str = SASE_PACKAGE) -> ToolReceipt:
    """Parse receipt *text* into a :class:`ToolReceipt`.

    Mirrors ``sase.uv_tool.receipt.parse_receipt``: extra tables (``overrides``,
    ``entrypoints``, ``[tool.options]``) are tolerated and ignored.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ReceiptError(f"could not parse uv receipt: {exc}") from exc

    tool = data.get("tool")
    if not isinstance(tool, dict):
        raise ReceiptError("uv receipt is missing the [tool] table")

    raw = tool.get("requirements")
    if not isinstance(raw, list) or not raw:
        raise ReceiptError("uv receipt [tool].requirements is missing or empty")

    requirements = tuple(
        _requirement_from_table(item) for item in raw if isinstance(item, dict)
    )
    if not requirements:
        raise ReceiptError("uv receipt [tool].requirements has no valid entries")

    primary_key = normalize_distribution_name(primary_name)
    primary_index = next(
        (i for i, req in enumerate(requirements) if req.normalized_name == primary_key),
        None,
    )
    if primary_index is None:
        raise ReceiptError(
            f"uv receipt does not list the primary package '{primary_name}'"
        )

    primary = requirements[primary_index]
    plugins = tuple(req for i, req in enumerate(requirements) if i != primary_index)
    return ToolReceipt(primary=primary, plugins=plugins, requirements=requirements)


def load_receipt(path: str | Path, *, primary_name: str = SASE_PACKAGE) -> ToolReceipt:
    """Read and parse the receipt at *path*."""
    receipt_path = Path(path)
    try:
        text = receipt_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReceiptError(
            f"could not read uv receipt at {receipt_path}: {exc}"
        ) from exc
    return parse_receipt_text(text, primary_name=primary_name)


def _requirement_from_table(table: dict[str, object]) -> InstallRequirement:
    name = table.get("name")
    if not isinstance(name, str) or not name:
        raise ReceiptError(f"uv receipt requirement is missing a name: {table!r}")

    extras_raw = table.get("extras", ())
    extras = tuple(e for e in extras_raw if isinstance(e, str)) if isinstance(
        extras_raw, (list, tuple)
    ) else ()
    specifier = table.get("specifier")
    specifier = specifier if isinstance(specifier, str) and specifier else None

    editable = _editable_path(table)
    raw_git = table.get("git")
    git = raw_git if isinstance(raw_git, str) else None
    git_ref = _first_str(table, "rev", "tag", "branch")

    url: str | None = None
    raw_url = table.get("url")
    if isinstance(raw_url, str):
        url = raw_url
    elif editable is None and git is None:
        url = _first_str(table, "path", "directory")

    return InstallRequirement(
        name=name,
        extras=extras,
        specifier=specifier,
        editable=editable,
        git=git,
        git_ref=git_ref,
        url=url,
    )


def _editable_path(table: dict[str, object]) -> str | None:
    value = table.get("editable")
    if isinstance(value, str):
        return value
    if value is True:
        return _first_str(table, "path", "directory")
    return None


def _first_str(table: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = table.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _looks_like_path(spec: str) -> bool:
    return spec.startswith(("/", "./", "../", "~")) or spec == "."


def _derive_name(spec: str) -> str:
    """Best-effort distribution name for a URL / git / path spec (for dedup)."""
    egg = re.search(r"[#&]egg=([A-Za-z0-9._-]+)", spec)
    if egg:
        return egg.group(1)
    body = spec.split("#", 1)[0].split("?", 1)[0]
    body = body.split("@", 1)[0] if body.startswith("git+") else body
    tail = body.rstrip("/").rsplit("/", 1)[-1]
    if tail.endswith(".git"):
        tail = tail[: -len(".git")]
    return tail


@dataclass(frozen=True)
class InstalledDist:
    """One installed distribution found via ``*.dist-info``."""

    name: str
    version: str | None = None
    editable_path: str | None = None

    @property
    def normalized_name(self) -> str:
        """PEP 503-normalized distribution name."""
        return normalize_distribution_name(self.name)


def _dist_info_dirs(site_packages: Path) -> list[Path]:
    try:
        entries = sorted(site_packages.iterdir())
    except OSError:
        return []
    return [
        entry
        for entry in entries
        if entry.is_dir() and entry.name.endswith(".dist-info")
    ]


def _metadata_value(text: str, key: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            value = line[len(key) + 1 :].strip()
            if value:
                return value
    return None


def _editable_from_direct_url(dist_info: Path) -> str | None:
    try:
        payload = json.loads((dist_info / "direct_url.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    info = payload.get("dir_info")
    if not (isinstance(info, dict) and info.get("editable") is True):
        return None
    url = payload.get("url")
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    # Windows file URLs may carry a netloc drive; keep this POSIX-focused.
    if parsed.netloc and parsed.netloc != "localhost":
        path = f"//{parsed.netloc}{path}"
    return path or None


def read_installed_dists(site_packages: str | Path) -> tuple[InstalledDist, ...]:
    """Return installed distributions from ``*.dist-info`` metadata."""
    dists: list[InstalledDist] = []
    for dist_info in _dist_info_dirs(Path(site_packages)):
        try:
            metadata = (dist_info / "METADATA").read_text(encoding="utf-8")
        except OSError:
            continue
        name = _metadata_value(metadata, "Name")
        if not name:
            continue
        dists.append(
            InstalledDist(
                name=name,
                version=_metadata_value(metadata, "Version"),
                editable_path=_editable_from_direct_url(dist_info),
            )
        )
    return tuple(sorted(dists, key=lambda dist: dist.normalized_name))


def find_site_packages(tool_dir: str | Path) -> Path | None:
    """Locate the tool env's site-packages directory, if it exists."""
    root = Path(tool_dir)
    candidates = sorted(root.glob("lib/python*/site-packages"))
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    windows = root / "Lib" / "site-packages"
    if windows.is_dir():
        return windows
    return None


def read_python_version(tool_dir: str | Path) -> str | None:
    """Return the tool env's interpreter version from ``pyvenv.cfg``."""
    try:
        text = (Path(tool_dir) / "pyvenv.cfg").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "version_info":
            version = value.strip()
            return version or None
    return None


def read_core_stamp(tool_dir: str | Path) -> dict[str, object] | None:
    """Return the parsed core source stamp, if present and valid JSON."""
    try:
        payload = json.loads(
            (Path(tool_dir) / CORE_STAMP_FILENAME).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


@dataclass(frozen=True)
class InstallState:
    """A read-only snapshot of the uv tool environment, without running it."""

    tool_dir: Path
    bin_dir: Path
    env_exists: bool
    receipt: ToolReceipt | None = None
    receipt_error: str | None = None
    python_version: str | None = None
    dists: tuple[InstalledDist, ...] = ()
    core_stamp: dict[str, object] | None = None
    lsp_exists: bool = False
    mode: str = "none"

    def find_dist(self, name: str) -> InstalledDist | None:
        """Return the installed distribution for *name*, if any."""
        key = normalize_distribution_name(name)
        for dist in self.dists:
            if dist.normalized_name == key:
                return dist
        return None


def classify_mode(
    *, env_exists: bool, host_editable: bool, any_editable: bool
) -> str:
    """Return the install mode: ``pypi``, ``dev``, ``mixed``, or ``none``."""
    if not env_exists:
        return "none"
    if host_editable:
        return "dev"
    if any_editable:
        return "mixed"
    return "pypi"


def read_state(
    *,
    tool_dir: str | Path,
    bin_dir: str | Path | None = None,
    receipt_filename: str = RECEIPT_FILENAME,
) -> InstallState:
    """Snapshot the tool environment at *tool_dir* (pure filesystem reads)."""
    tool_path = Path(tool_dir)
    bin_path = Path(bin_dir) if bin_dir is not None else tool_path / "bin"
    python = tool_path / "bin" / "python"
    env_exists = python.is_file() or python.is_symlink()

    receipt: ToolReceipt | None = None
    receipt_error: str | None = None
    if env_exists:
        try:
            receipt = load_receipt(tool_path / receipt_filename)
        except ReceiptError as exc:
            receipt_error = str(exc)

    site_packages = find_site_packages(tool_path)
    dists = read_installed_dists(site_packages) if site_packages is not None else ()
    host = next(
        (
            dist
            for dist in dists
            if dist.normalized_name == normalize_distribution_name(SASE_PACKAGE)
        ),
        None,
    )
    mode = classify_mode(
        env_exists=env_exists,
        host_editable=bool(host is not None and host.editable_path),
        any_editable=any(dist.editable_path for dist in dists),
    )
    return InstallState(
        tool_dir=tool_path,
        bin_dir=bin_path,
        env_exists=env_exists,
        receipt=receipt,
        receipt_error=receipt_error,
        python_version=read_python_version(tool_path) if env_exists else None,
        dists=dists,
        core_stamp=read_core_stamp(tool_path) if env_exists else None,
        lsp_exists=(bin_path / LSP_BINARY_NAME).exists(),
        mode=mode,
    )


__all__ = [
    "CORE_STAMP_FILENAME",
    "LSP_BINARY_NAME",
    "RECEIPT_FILENAME",
    "SASE_PACKAGE",
    "InstallRequirement",
    "InstalledDist",
    "InstallState",
    "ReceiptError",
    "ToolReceipt",
    "classify_mode",
    "find_site_packages",
    "load_receipt",
    "normalize_distribution_name",
    "parse_receipt_text",
    "read_core_stamp",
    "read_installed_dists",
    "read_python_version",
    "read_state",
]
