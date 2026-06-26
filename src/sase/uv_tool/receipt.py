"""Parse ``uv-receipt.toml`` and reconstruct the injected ``--with`` set.

The receipt is the **source of truth** for what lives in sase's uv tool
environment (epic decision *D2*): its ``[tool].requirements`` array records the
primary ``sase`` package plus every injected plugin, faithfully preserving
editable paths, git sources, version specifiers, and extras. ``uv tool install
--with X`` *replaces* the injected set rather than appending to it, so adding or
upgrading one plugin means re-running install with the **full** reconstructed
set; this module produces that set.

Reconstruction is deduped by PEP 503-normalized name. A real receipt can list the
same plugin twice (e.g. an editable dev entry plus a bare index entry); the first
occurrence wins and a conflicting duplicate raises a *warning* rather than being
silently dropped.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.uv_tool.detect import SASE_PACKAGE
from sase.uv_tool.errors import ReceiptError
from sase.version._utils import normalize_distribution_name

#: Matches ``name``, optional ``[extras]``, and a trailing version specifier.
_SPEC_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[(?P<extras>[^\]]*)\])?"
    r"(?P<rest>.*)$"
)

#: Characters that start a PEP 440 version specifier.
_SPECIFIER_START = frozenset("=<>!~")


@dataclass(frozen=True)
class Requirement:
    """One ``[tool].requirements`` entry, modeling every uv source variant.

    Exactly one *source* applies: an ``editable`` local path, a ``git`` URL
    (with optional ``git_ref``), a direct ``url`` / local-path passthrough, or —
    the default — an index requirement described by ``name``, ``extras``, and
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
    def from_spec(cls, spec: str) -> Requirement:
        """Parse an install spec string into a :class:`Requirement`.

        Handles plain names, ``name[extras]``, version specifiers, ``git+`` URLs,
        and direct URL / local-path references (passed through verbatim).
        """
        spec = spec.strip()
        if not spec:
            raise ValueError("empty requirement spec")
        if spec.startswith("git+") or "://" in spec or _looks_like_path(spec):
            return cls(name=_derive_name(spec), url=spec)

        match = _SPEC_RE.match(spec)
        rest = match.group("rest").strip() if match else ""
        if match is None or (rest and rest[0] not in _SPECIFIER_START):
            # Not a clean PEP 508 spec (markers, ``@`` refs, ...): pass through.
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
class ReconstructedRequirements:
    """The deduped, reconstructed install set plus any receipt warnings."""

    primary: Requirement
    plugins: tuple[Requirement, ...]
    warnings: tuple[str, ...] = ()
    added: Requirement | None = None
    upgrade_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolReceipt:
    """A parsed ``uv-receipt.toml``: the primary package and injected plugins."""

    primary: Requirement
    plugins: tuple[Requirement, ...] = ()
    requirements: tuple[Requirement, ...] = field(default_factory=tuple)

    def injected_plugins(self) -> tuple[Requirement, ...]:
        """Every requirement that is not the primary package (order preserved).

        This is the *raw* injected set: a dev/editable receipt can list the same
        plugin twice (an editable entry plus a bare index entry), and both are
        preserved here. User-facing inventory and bulk-target surfaces should use
        :meth:`deduped_injected_plugins` instead so duplicates collapse.
        """
        return self.plugins

    def deduped_injected_plugins(self) -> tuple[Requirement, ...]:
        """Injected plugins in receipt order, deduped by normalized name.

        Reuses :meth:`reconstruct`'s normalized-name dedupe (first occurrence
        wins), so display and target-selection surfaces report one row per
        installed distribution even when the receipt records duplicates.
        """
        return self.reconstruct().plugins

    def is_injected(self, name: str) -> bool:
        """Whether *name* (any case/normalization) is an injected plugin."""
        key = normalize_distribution_name(name)
        return any(plugin.normalized_name == key for plugin in self.plugins)

    def reconstruct(
        self, *, add: Requirement | str | None = None
    ) -> ReconstructedRequirements:
        """Rebuild the full injected set, deduped, optionally adding *add*."""
        reqs = list(self.plugins)
        added: Requirement | None = None
        if add is not None:
            added = add if isinstance(add, Requirement) else Requirement.from_spec(add)
            reqs.append(added)
        deduped, warnings = _dedupe(reqs)
        return ReconstructedRequirements(
            primary=self.primary,
            plugins=deduped,
            warnings=warnings,
            added=added,
        )

    def with_added(self, spec: Requirement | str) -> ReconstructedRequirements:
        """Reconstructed set that additionally includes *spec*."""
        return self.reconstruct(add=spec)

    def with_upgraded(self, name: str) -> ReconstructedRequirements:
        """Reconstructed set for upgrading *name*.

        Upgrading does not change set *membership* (it only re-pins a version),
        so the set equals the current deduped set; *name* is recorded in
        ``upgrade_targets`` and the ``--upgrade-package <name>`` flag is applied
        by :func:`sase.uv_tool.commands.build_upgrade_packages`.
        """
        recon = self.reconstruct()
        return ReconstructedRequirements(
            primary=recon.primary,
            plugins=recon.plugins,
            warnings=recon.warnings,
            upgrade_targets=(name,),
        )


def parse_receipt(text: str, *, primary_name: str = SASE_PACKAGE) -> ToolReceipt:
    """Parse receipt *text* into a :class:`ToolReceipt`.

    Raises :class:`~sase.uv_tool.errors.ReceiptError` when the TOML is malformed,
    the ``[tool].requirements`` array is missing/empty, or the primary package is
    absent.
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
    return parse_receipt(text, primary_name=primary_name)


def _requirement_from_table(table: dict[str, Any]) -> Requirement:
    name = table.get("name")
    if not isinstance(name, str) or not name:
        raise ReceiptError(f"uv receipt requirement is missing a name: {table!r}")

    extras = tuple(e for e in table.get("extras", ()) if isinstance(e, str))
    specifier = table.get("specifier")
    specifier = specifier if isinstance(specifier, str) and specifier else None

    editable = _editable_path(table)
    git = table.get("git") if isinstance(table.get("git"), str) else None
    git_ref = _first_str(table, "rev", "tag", "branch")

    url: str | None = None
    if isinstance(table.get("url"), str):
        url = table["url"]
    elif editable is None and git is None:
        url = _first_str(table, "path", "directory")

    return Requirement(
        name=name,
        extras=extras,
        specifier=specifier,
        editable=editable,
        git=git,
        git_ref=git_ref,
        url=url,
    )


def _editable_path(table: dict[str, Any]) -> str | None:
    value = table.get("editable")
    if isinstance(value, str):
        return value
    if value is True:
        return _first_str(table, "path", "directory")
    return None


def _first_str(table: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = table.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _dedupe(
    requirements: list[Requirement],
) -> tuple[tuple[Requirement, ...], tuple[str, ...]]:
    kept: dict[str, Requirement] = {}
    order: list[str] = []
    warnings: list[str] = []
    for req in requirements:
        key = req.normalized_name
        existing = kept.get(key)
        if existing is None:
            kept[key] = req
            order.append(key)
        elif existing != req:
            warnings.append(
                f"plugin '{req.name}' appears multiple times in the uv receipt "
                f"with conflicting sources; keeping {existing.describe()} and "
                f"ignoring {req.describe()}."
            )
    return tuple(kept[key] for key in order), tuple(warnings)


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


__all__ = [
    "ReconstructedRequirements",
    "Requirement",
    "ToolReceipt",
    "load_receipt",
    "parse_receipt",
]
