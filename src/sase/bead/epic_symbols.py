"""Discover Justfile ``--epic-symbol`` whitelist entries.

Symvision accepts ``--epic-symbol <bead_id>(<symbol>)`` only while that bead
is still open. The exemption goes stale the instant the bead closes, and the
next unrelated ``just check`` is what used to discover the leftover. Parse the
working tree's Justfile so close can surface those entries instead of leaving
them for the next agent.

The local Justfile is not the whole story: a sibling phase can land a row on
the default branch after this checkout synced, and that row escapes a
local-only guard. The scan therefore also reads the Justfile at the default
branch (``origin/<branch>`` after a bounded fetch, or the freshest
remote-tracking ref when offline) and unions those rows with the local ones.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
import re
import subprocess
import sys

from sase.bead.flag_fields import is_flag_bead
from sase.bead.model import Issue, Status

_JUSTFILE_NAMES = ("Justfile", "justfile")
_EPIC_SYMBOL_TOKEN = re.compile(
    r"""--epic-symbol(?:\s+|=)(?:"([^"]+)"|'([^']+)'|(\S+))"""
)
_EPIC_SYMBOL_BODY = re.compile(r"^(?P<bead>[^\s(]+)\((?P<symbol>[^)]+)\)$")

_LOCAL_ORIGIN = "local"
_UPSTREAM_FETCH_TIMEOUT_S = 30
_UPSTREAM_READ_TIMEOUT_S = 15


@dataclass(frozen=True, slots=True)
class _EpicSymbolEntry:
    """One ``--epic-symbol <bead_id>(<symbol>)`` flag from a Justfile."""

    bead_id: str
    symbol: str
    source: Path | None = None
    origins: tuple[str, ...] = ()
    """Where the row was seen: ``"local"`` and/or a ref like ``"origin/master"``."""

    @property
    def raw(self) -> str:
        return f"{self.bead_id}({self.symbol})"

    @property
    def flag(self) -> str:
        return f'--epic-symbol "{self.raw}"'


@dataclass(frozen=True, slots=True)
class _EpicSymbolScan:
    """Union of local and default-branch ``--epic-symbol`` rows."""

    entries: tuple[_EpicSymbolEntry, ...]
    local_justfile: Path | None
    upstream_justfile: str | None
    """Such as ``"origin/master:Justfile"``; None when no upstream read ran."""
    upstream_stale: bool = False
    """True when the fetch failed and the upstream rows come from a cached ref."""
    upstream_warning: str | None = None
    """Non-None when the upstream read fell back; print it loudly, never wedge."""


_FLAG_REGISTRY_RELPATH = Path("src/sase/feature_flags/registry.py")


class _LeftoverEpicSymbolsError(ValueError):
    """Raised when closing would stale remaining ``--epic-symbol`` entries."""


def _discover_justfile(start: Path | None = None) -> Path | None:
    """Return the nearest Justfile at or above *start*, stopping at a git root."""
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        for name in _JUSTFILE_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        if (directory / ".git").exists():
            return None
    return None


def _parse_epic_symbol_entries(
    text: str,
    source: Path | None = None,
    *,
    origins: tuple[str, ...] = (_LOCAL_ORIGIN,),
) -> list[_EpicSymbolEntry]:
    """Parse ``--epic-symbol`` flags from Justfile (or equivalent) text."""
    entries: list[_EpicSymbolEntry] = []
    for match in _EPIC_SYMBOL_TOKEN.finditer(text):
        body = next(group for group in match.groups() if group)
        parsed = _EPIC_SYMBOL_BODY.fullmatch(body)
        if parsed is None:
            continue
        entries.append(
            _EpicSymbolEntry(
                bead_id=parsed.group("bead"),
                symbol=parsed.group("symbol"),
                source=source,
                origins=origins,
            )
        )
    return entries


def _git_env() -> dict[str, str]:
    """Return an env that keeps git reads from prompting for credentials."""
    try:
        from sase.workspace_provider.utils import non_interactive_git_env

        return non_interactive_git_env()
    except Exception:
        import os

        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env


def _run_git(
    repo_root: Path, *args: str, timeout: float
) -> subprocess.CompletedProcess[str] | None:
    """Run a read-only git command, returning None when git cannot run it."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_git_env(),
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _repo_root_for(start: Path | None) -> Path | None:
    """Return the git working-tree root containing *start*, if any."""
    probe = start if start is not None else Path.cwd()
    try:
        if probe.is_file():
            probe = probe.parent
    except OSError:
        return None
    result = _run_git(
        probe, "rev-parse", "--show-toplevel", timeout=_UPSTREAM_READ_TIMEOUT_S
    )
    if result is None or result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root) if root else None


def _has_origin(repo_root: Path) -> bool:
    """Return whether the checkout configures an ``origin`` remote."""
    result = _run_git(
        repo_root,
        "config",
        "--get",
        "remote.origin.url",
        timeout=_UPSTREAM_READ_TIMEOUT_S,
    )
    return result is not None and result.returncode == 0 and bool(result.stdout.strip())


def _default_branch_ref(repo_root: Path) -> str | None:
    """Return the default-branch remote-tracking ref, e.g. ``origin/master``."""
    head = _run_git(
        repo_root,
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        timeout=_UPSTREAM_READ_TIMEOUT_S,
    )
    if head is not None and head.returncode == 0:
        ref = head.stdout.strip()
        if ref.startswith("refs/remotes/"):
            return ref.removeprefix("refs/remotes/")
    for candidate in ("origin/master", "origin/main"):
        probe = _run_git(
            repo_root,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/remotes/{candidate}",
            timeout=_UPSTREAM_READ_TIMEOUT_S,
        )
        if probe is not None and probe.returncode == 0:
            return candidate
    return None


def _fetch_default_branch(repo_root: Path, ref: str | None) -> str | None:
    """Fetch the default branch (bounded); return an error summary on failure."""
    branch = ref.rsplit("/", 1)[-1] if ref else None
    args = (
        ("fetch", "--quiet", "origin", branch)
        if branch
        else ("fetch", "--quiet", "origin")
    )
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=_UPSTREAM_FETCH_TIMEOUT_S,
            env=_git_env(),
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"timed out after {_UPSTREAM_FETCH_TIMEOUT_S}s"
    except OSError as exc:
        return str(exc)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        return detail[-1] if detail else f"git {' '.join(args)} failed"
    return None


def _show_upstream_justfile(
    repo_root: Path, ref: str, relnames: tuple[str, ...]
) -> tuple[str | None, str | None]:
    """Return ``(relname, text)`` for the Justfile at *ref*, if readable."""
    for relname in relnames:
        result = _run_git(
            repo_root, "show", f"{ref}:{relname}", timeout=_UPSTREAM_READ_TIMEOUT_S
        )
        if result is not None and result.returncode == 0:
            return relname, result.stdout
    return None, None


def _read_upstream_rows(
    repo_root: Path | None, local_justfile: Path | None
) -> tuple[list[_EpicSymbolEntry], str | None, bool, str | None]:
    """Read default-branch rows; return ``(entries, ref_label, stale, warning)``.

    Never raises and never wedges a close: any fetch or read failure falls
    back to the local Justfile with a loud warning.
    """
    if repo_root is None or not _has_origin(repo_root):
        return [], None, False, None
    relnames: tuple[str, ...]
    if local_justfile is not None:
        try:
            relnames = (local_justfile.relative_to(repo_root).as_posix(),)
        except ValueError:
            relnames = _JUSTFILE_NAMES
    else:
        relnames = _JUSTFILE_NAMES
    ref = _default_branch_ref(repo_root)
    fetch_error = _fetch_default_branch(repo_root, ref)
    if ref is None:
        ref = _default_branch_ref(repo_root)
    if ref is None:
        reason = f" ({fetch_error})" if fetch_error else ""
        return (
            [],
            None,
            False,
            f"warning: cannot consult the upstream Justfile "
            f"(no origin/HEAD, origin/master, or origin/main ref{reason}); "
            f"the close guard sees only the local Justfile and a sibling "
            f"phase's newer row could escape it",
        )
    relname, text = _show_upstream_justfile(repo_root, ref, relnames)
    if text is None:
        reason = f" ({fetch_error})" if fetch_error else ""
        return (
            [],
            None,
            False,
            f"warning: cannot read {ref}:{relnames[0]}{reason}; "
            f"the close guard sees only the local Justfile and a sibling "
            f"phase's newer row could escape it",
        )
    label = f"{ref}:{relname}"
    if fetch_error is not None:
        return (
            _parse_epic_symbol_entries(text, source=None, origins=(ref,)),
            label,
            True,
            f"warning: upstream fetch failed ({fetch_error}); using the "
            f"cached {label}, which may be outdated — the close guard could "
            f"miss a sibling phase's newer row",
        )
    return (
        _parse_epic_symbol_entries(text, source=None, origins=(ref,)),
        label,
        False,
        None,
    )


def load_epic_symbol_scan(start: Path | None = None) -> _EpicSymbolScan:
    """Load local plus default-branch ``--epic-symbol`` rows as one union.

    Rows present in both sources appear once, tagged with both origins.
    """
    justfile = _discover_justfile(start)
    local_entries = (
        _parse_epic_symbol_entries(
            justfile.read_text(encoding="utf-8"), source=justfile
        )
        if justfile is not None
        else []
    )
    repo_root = _repo_root_for(start)
    if repo_root is None and justfile is not None:
        repo_root = _repo_root_for(justfile.parent)
    upstream_entries, upstream_label, stale, warning = _read_upstream_rows(
        repo_root, justfile
    )
    merged: dict[tuple[str, str], _EpicSymbolEntry] = {}
    for entry in local_entries:
        merged[(entry.bead_id, entry.symbol)] = entry
    for entry in upstream_entries:
        key = (entry.bead_id, entry.symbol)
        existing = merged.get(key)
        if existing is None:
            merged[key] = entry
        else:
            merged[key] = replace(
                existing,
                origins=tuple(dict.fromkeys((*existing.origins, *entry.origins))),
            )
    return _EpicSymbolScan(
        entries=tuple(merged.values()),
        local_justfile=justfile,
        upstream_justfile=upstream_label,
        upstream_stale=stale,
        upstream_warning=warning,
    )


def _entry_owned_by(target_id: str, entry_bead_id: str) -> bool:
    """Return whether *entry_bead_id* is *target_id* or one of its descendants."""
    return entry_bead_id == target_id or entry_bead_id.startswith(f"{target_id}.")


def entries_for_beads(
    entries: Iterable[_EpicSymbolEntry], bead_ids: Iterable[str]
) -> list[_EpicSymbolEntry]:
    """Return entries keyed to any of *bead_ids* or their descendant suffixes."""
    targets = tuple(bead_ids)
    return [
        entry
        for entry in entries
        if any(_entry_owned_by(target_id, entry.bead_id) for target_id in targets)
    ]


def _leftover_epic_symbols_for_close(
    issues: Iterable[Issue],
    entries: Iterable[_EpicSymbolEntry],
) -> list[_EpicSymbolEntry]:
    """Return whitelist entries that would go stale if *issues* closed."""
    open_ids = [issue.id for issue in issues if issue.status is not Status.CLOSED]
    if not open_ids:
        return []
    return entries_for_beads(entries, open_ids)


def _entry_source_suffix(entry: _EpicSymbolEntry) -> str:
    """Return the ``[local, origin/master]`` source tag for a row."""
    if not entry.origins:
        return ""
    return f" [{', '.join(entry.origins)}]"


def _leftover_epic_symbols_error_message(
    leftovers: Iterable[_EpicSymbolEntry],
    *,
    close_ids: Iterable[str],
) -> str:
    """Format the close refusal that names every leftover Justfile entry."""
    entries = list(leftovers)
    targets = ", ".join(close_ids)
    lines = [
        f"refusing to close {targets}: Justfile still has --epic-symbol "
        "entries keyed to this bead (they go stale the instant the bead "
        "closes and turn unrelated agents' just check red):",
        *(f"  {entry.flag}{_entry_source_suffix(entry)}" for entry in entries),
        "",
        "Resolve each symbol (wire it up, privatize it, add a non-test "
        "pragma, or delete it) or re-key the Justfile line to a still-open "
        "bead. List them with:",
        f"  sase bead epic-symbols {next(iter(close_ids), '<id>')}",
    ]
    return "\n".join(lines)


def raise_if_leftover_epic_symbols(
    issues: Iterable[Issue],
    *,
    start: Path | None = None,
) -> None:
    """Refuse a close that would stale remaining ``--epic-symbol`` entries.

    Reads the local Justfile and the default branch's Justfile; a fetch or
    read failure warns loudly and falls back to the local rows, never wedging
    the close.
    """
    issue_list = list(issues)
    scan = load_epic_symbol_scan(start)
    if scan.upstream_warning is not None:
        print(scan.upstream_warning, file=sys.stderr)
    leftovers = _leftover_epic_symbols_for_close(issue_list, scan.entries)
    if not leftovers:
        return
    close_ids = [issue.id for issue in issue_list if issue.status is not Status.CLOSED]
    raise _LeftoverEpicSymbolsError(
        _leftover_epic_symbols_error_message(leftovers, close_ids=close_ids)
    )


def _flag_key_name(node: ast.expr | None) -> str:
    """Return the flag key a registry ``key=`` argument spells."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return "<unknown key>"


def _registry_flag_definitions(start: Path | None = None) -> dict[str, list[str]]:
    """Map bead ids to the flag keys the working tree's registry defines for them.

    Parse the registry statically: the running ``sase`` may be a different
    install than the working tree, so importing it could read the wrong file.
    """
    justfile = _discover_justfile(start)
    if justfile is None:
        return {}
    registry = justfile.parent / _FLAG_REGISTRY_RELPATH
    if not registry.is_file():
        return {}
    try:
        tree = ast.parse(registry.read_text(encoding="utf-8"), filename=str(registry))
    except (OSError, SyntaxError, ValueError):
        return {}
    definitions: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        bead = keywords.get("bead")
        if isinstance(bead, ast.Constant) and isinstance(bead.value, str):
            definitions.setdefault(bead.value, []).append(
                _flag_key_name(keywords.get("key"))
            )
    return definitions


def raise_if_surviving_flag_definition(
    issues: Iterable[Issue],
    *,
    start: Path | None = None,
) -> None:
    """Refuse closing a flag bead whose registry definition still exists.

    ``check_feature_flags`` rule 7 fails every workspace once a named flag bead
    is closed while its definition survives, so close must surface it first.
    """
    targets = [
        issue.id
        for issue in issues
        if issue.status is not Status.CLOSED and is_flag_bead(issue)
    ]
    if not targets:
        return
    definitions = _registry_flag_definitions(start)
    surviving = [bead_id for bead_id in targets if bead_id in definitions]
    if not surviving:
        return
    lines = [
        f"refusing to close {', '.join(surviving)}: the feature-flag registry "
        f"({_FLAG_REGISTRY_RELPATH}) still defines a flag naming this bead "
        "(closing it turns unrelated agents' just check red through "
        "check_feature_flags rule 7):",
        *(
            f"  {key} (bead={bead_id})"
            for bead_id in surviving
            for key in definitions[bead_id]
        ),
        "",
        "In the same change, delete each flag's Off branch, make its On branch "
        "unconditional, and remove the registry entry (with its references and "
        "schema entry); or keep the bead open.",
    ]
    raise _LeftoverEpicSymbolsError("\n".join(lines))
