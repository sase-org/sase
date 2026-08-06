"""Diff-scoped test selection over a cached static import graph.

This module lives beside ``tests/_suite_gate.py`` for the same reasons: it is
repository build tooling rather than product code, ``tools/run_pytest`` already
imports its shared runner logic from a private ``tests/_*.py`` module, and code
under ``tests/`` sits outside symvision's ``src/sase`` scan and outside mypy's
``files = ["src"]``.

The selector answers one question: given a change set, which ``test_*.py``
files plausibly cover it? It answers it with a *depth-bounded* reverse walk of
the in-repo import graph, because ``src/sase`` contains a single 497-module
strongly-connected component whose members transitively reach ~87% of the test
suite. Unbounded reverse closure is therefore not a selector; depth-bounding is
the mechanism, not a tuning knob.

Selection is deliberately a heuristic. The broadening rules, the escalation
threshold, the always-included contract set, and the manifest that records
every decision all exist because the closure is unsound.
"""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any

from tests._test_selection_graph import (
    ImportGraph,
    SelectionError,
    build_import_graph,
    is_test_file,
    is_visual_path,
    run_git,
)


MANIFEST_SCHEMA = 1

DEFAULT_DEPTH = 2
DEFAULT_MAX_RATIO = 0.25
DEFAULT_BASE_REF = "origin/master"

DEPTH_ENV = "SASE_TEST_SELECTION_DEPTH"
MAX_RATIO_ENV = "SASE_TEST_SELECTION_MAX_RATIO"
BASE_ENV = "SASE_CHECK_BASE"

SELECTION_DIRECTORY = Path(".pytest_cache") / "sase-selection"
GRAPH_CACHE_FILENAME = "graph.json"
MANIFEST_FILENAME = "manifest.json"

CONTRACT_MANIFEST_PATH = "tests/contract_manifest.txt"

FULL_SUITE = "FULL_SUITE"

RULE_BASE_UNRESOLVED = "base-unresolved"
RULE_ROOT_CONFTEST = "root-conftest"
RULE_PACKAGING_CONFIG = "packaging-config"
RULE_JUSTFILE = "justfile"
RULE_SRC_DATA_ASSET = "src-data-asset"
RULE_SELECTION_TOOLING = "selection-tooling"
RULE_CORE_IDENTITY_CHANGED = "core-identity-changed"
RULE_DIRECTORY_CONFTEST = "directory-conftest"
RULE_CONTRACT_SET_ALWAYS = "contract-set-always"
RULE_CONTRACT_SET_ONLY = "contract-set-only"
RULE_RENAME_OR_DELETE = "rename-or-delete"
RULE_RATIO_EXCEEDED = "selection-ratio-exceeded"

#: Rules whose only sound response is to run everything.
FULL_SUITE_RULES = frozenset(
    {
        RULE_BASE_UNRESOLVED,
        RULE_ROOT_CONFTEST,
        RULE_PACKAGING_CONFIG,
        RULE_JUSTFILE,
        RULE_SRC_DATA_ASSET,
        RULE_SELECTION_TOOLING,
        RULE_CORE_IDENTITY_CHANGED,
    }
)

#: The root conftest and every module it imports from within the repository.
#: A change to any of them can alter fixture behaviour for the whole suite.
ROOT_CONFTEST_PATHS = frozenset(
    {
        "tests/conftest.py",
        "tests/_suite_gate.py",
        "tests/_tmp_leak_guard.py",
        "tests/_project_display_case.py",
    }
)
PACKAGING_CONFIG_PATHS = frozenset({"pyproject.toml", "uv.lock", "tox.ini"})
JUSTFILE_PATHS = frozenset({"Justfile", "justfile"})
SELECTION_TOOLING_PATHS = frozenset(
    {
        "tools/run_pytest",
        "tools/select_tests",
        "tests/_test_selection.py",
        "tests/_test_selection_graph.py",
        CONTRACT_MANIFEST_PATH,
    }
)
SRC_DATA_ASSET_SUFFIXES = (".yml", ".yaml", ".json")

_SASE_CORE_DIR_ENV_VARS = (
    "SASE_CORE_DIR",
    "SASE_LINKED_REPO_SASE_CORE_DIR",
    "SASE_SIBLING_REPO_SASE_CORE_DIR",
    "SASE_SIBLING_REPO_CORE_DIR",
)
_WORKSPACE_SASE_CORE_DIR = Path("sase/repos/linked/sase-core")


# --------------------------------------------------------------------------
# Change set
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ChangeSet:
    paths: tuple[str, ...]
    base_ref: str
    merge_base: str | None
    has_rename_or_delete: bool
    head: str | None
    tree_dirty: bool


def _parse_name_status_z(raw: str) -> tuple[list[str], bool]:
    """Parse ``git diff --name-status -z`` into paths and a rename/delete flag.

    With ``-z`` each status code is its own NUL-separated field, and a rename
    or copy is followed by *two* path fields (old, then new). Both are kept:
    the old path seeds nothing but the new one does, and callers only need to
    know that some path moved.
    """
    fields = raw.split("\0")
    paths: list[str] = []
    special = False
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if not status:
            continue
        code = status[0]
        if code in {"R", "C"}:
            special = special or code == "R"
            for _ in range(2):
                if index < len(fields):
                    if fields[index]:
                        paths.append(fields[index])
                    index += 1
            continue
        if index < len(fields):
            if fields[index]:
                paths.append(fields[index])
            index += 1
        if code == "D":
            special = True
    return paths, special


def _parse_porcelain_z(raw: str) -> tuple[list[str], bool]:
    """Parse ``git status --porcelain -z`` into paths and a rename/delete flag.

    Each entry is ``XY<space><path>``; a rename or copy puts the original path
    in the following NUL-separated field. Untracked (``??``) entries are
    included so a brand-new test file participates in the change set.
    """
    fields = raw.split("\0")
    paths: list[str] = []
    special = False
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        paths.append(path)
        if "R" in status or "C" in status:
            if index < len(fields) and fields[index]:
                paths.append(fields[index])
            index += 1
            special = special or "R" in status
        if "D" in status:
            special = True
    return paths, special


def compute_change_set(root: Path, base_ref: str) -> ChangeSet:
    """Union the merge-base diff with the working tree's own changes.

    A stale or missing base ref is not an error the selector may paper over:
    the caller sees ``merge_base is None`` and escalates to the full suite,
    because failing toward *more* testing is the only safe direction.
    """
    try:
        merge_base = run_git(root, "merge-base", "HEAD", base_ref).strip() or None
    except SelectionError:
        merge_base = None
    try:
        head = run_git(root, "rev-parse", "HEAD").strip() or None
    except SelectionError:
        head = None

    paths: list[str] = []
    has_rename_or_delete = False
    if merge_base is not None:
        diff_paths, diff_special = _parse_name_status_z(
            run_git(root, "diff", "--name-status", "-M", "-z", merge_base)
        )
        paths.extend(diff_paths)
        has_rename_or_delete = has_rename_or_delete or diff_special

    status_paths, status_special = _parse_porcelain_z(
        run_git(root, "status", "--porcelain", "-z")
    )
    paths.extend(status_paths)
    has_rename_or_delete = has_rename_or_delete or status_special

    return ChangeSet(
        paths=tuple(sorted(set(paths))),
        base_ref=base_ref,
        merge_base=merge_base,
        has_rename_or_delete=has_rename_or_delete,
        head=head,
        tree_dirty=bool(status_paths),
    )


# --------------------------------------------------------------------------
# Broadening rules
# --------------------------------------------------------------------------


def _is_src_data_asset(path: str) -> bool:
    return path.startswith("src/") and path.endswith(SRC_DATA_ASSET_SUFFIXES)


def _is_directory_conftest(path: str) -> bool:
    return (
        path.startswith("tests/")
        and path.endswith("/conftest.py")
        and path != "tests/conftest.py"
    )


@dataclass(frozen=True)
class RuleEvaluation:
    rules: tuple[str, ...]
    conftest_directories: tuple[str, ...]

    @property
    def forces_full_suite(self) -> bool:
        return any(rule in FULL_SUITE_RULES for rule in self.rules)


def evaluate_broadening_rules(
    changed_paths: Iterable[str],
    *,
    base_resolved: bool,
    core_identity_changed: bool,
    has_rename_or_delete: bool,
    graph: ImportGraph,
) -> RuleEvaluation:
    """Classify the change set into the named rules it triggers."""
    rules: list[str] = []
    conftest_directories: list[str] = []
    known_module_paths = 0

    if not base_resolved:
        rules.append(RULE_BASE_UNRESOLVED)
    if core_identity_changed:
        rules.append(RULE_CORE_IDENTITY_CHANGED)

    for path in changed_paths:
        if path in ROOT_CONFTEST_PATHS:
            rules.append(RULE_ROOT_CONFTEST)
        elif path in PACKAGING_CONFIG_PATHS:
            rules.append(RULE_PACKAGING_CONFIG)
        elif path in JUSTFILE_PATHS:
            rules.append(RULE_JUSTFILE)
        elif path in SELECTION_TOOLING_PATHS:
            rules.append(RULE_SELECTION_TOOLING)
        elif _is_src_data_asset(path):
            rules.append(RULE_SRC_DATA_ASSET)
        elif _is_directory_conftest(path):
            rules.append(RULE_DIRECTORY_CONFTEST)
            conftest_directories.append(path[: -len("/conftest.py")])
        if path in graph.paths:
            known_module_paths += 1

    if has_rename_or_delete:
        rules.append(RULE_RENAME_OR_DELETE)
    if known_module_paths == 0 and not conftest_directories:
        # Docs, sdd/**, .github/**, and friends contribute no seeds at all.
        rules.append(RULE_CONTRACT_SET_ONLY)

    ordered = tuple(sorted(set(rules)))
    return RuleEvaluation(
        rules=ordered,
        conftest_directories=tuple(sorted(set(conftest_directories))),
    )


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionOptions:
    base_ref: str = DEFAULT_BASE_REF
    depth: int = DEFAULT_DEPTH
    max_ratio: float = DEFAULT_MAX_RATIO
    use_cache: bool = True

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        base_ref: str | None = None,
        depth: int | None = None,
        max_ratio: float | None = None,
        use_cache: bool = True,
    ) -> SelectionOptions:
        environ = os.environ if environ is None else environ
        if base_ref is None:
            base_ref = environ.get(BASE_ENV) or DEFAULT_BASE_REF
        if depth is None:
            depth = _positive_int(environ.get(DEPTH_ENV), DEFAULT_DEPTH, DEPTH_ENV)
        if max_ratio is None:
            max_ratio = _ratio(environ.get(MAX_RATIO_ENV), DEFAULT_MAX_RATIO)
        return cls(
            base_ref=base_ref, depth=depth, max_ratio=max_ratio, use_cache=use_cache
        )


def _positive_int(raw: str | None, default: int, name: str) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise SelectionError(f"{name} must be a non-negative integer") from error
    if value < 0:
        raise SelectionError(f"{name} must be a non-negative integer")
    return value


def _ratio(raw: str | None, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise SelectionError(f"{MAX_RATIO_ENV} must be a number in (0, 1]") from error
    if not 0 < value <= 1:
        raise SelectionError(f"{MAX_RATIO_ENV} must be a number in (0, 1]")
    return value


@dataclass(frozen=True)
class Selection:
    selected: tuple[str, ...]
    escalated: bool
    rules: tuple[str, ...]
    manifest: dict[str, Any]
    explanations: dict[str, tuple[str, int]]
    universe_count: int

    @property
    def paths_output(self) -> str:
        if self.escalated:
            return FULL_SUITE
        return "\n".join(self.selected)


def load_contract_manifest(root: Path, path: str = CONTRACT_MANIFEST_PATH) -> list[str]:
    """Read the committed contract-set manifest, if the ``contract`` phase landed.

    An absent manifest is a valid input: it means the contract set is empty.
    """
    try:
        raw = (root / path).read_text(encoding="utf-8")
    except OSError:
        return []
    return sorted(
        {
            line.strip()
            for line in raw.splitlines()
            if line.strip() and not line.startswith("#")
        }
    )


def _closure(
    graph: ImportGraph,
    seeds: Sequence[str],
    depth: int,
) -> dict[str, tuple[str, int]]:
    """Walk reverse import edges ``depth`` times from ``seeds``.

    Terminal (test) modules reached at any hop join the selection; expandable
    modules join the next frontier. After the bounded walk, the direct terminal
    importers of every expandable module reached are harvested, so a depth of
    ``N`` means "``N`` hops of production/helper modules, then the tests".
    """
    terminals: dict[str, tuple[str, int]] = {}
    reached: dict[str, tuple[str, int]] = {}
    frontier: dict[str, tuple[str, int]] = {}

    for module in seeds:
        path = graph.path_for(module)
        if path is None:
            continue
        if is_test_file(path):
            terminals.setdefault(module, (module, 0))
            continue
        reached.setdefault(module, (module, 0))
        frontier.setdefault(module, (module, 0))

    for hop in range(1, depth + 1):
        next_frontier: dict[str, tuple[str, int]] = {}
        for module, (seed, _) in frontier.items():
            for importer in graph.importers.get(module, ()):
                importer_path = graph.path_for(importer)
                if importer_path is None:
                    continue
                if is_test_file(importer_path):
                    terminals.setdefault(importer, (seed, hop))
                    continue
                if importer in reached:
                    continue
                reached[importer] = (seed, hop)
                next_frontier[importer] = (seed, hop)
        frontier = next_frontier
        if not frontier:
            break

    for module, (seed, hop) in reached.items():
        for importer in graph.importers.get(module, ()):
            importer_path = graph.path_for(importer)
            if importer_path is not None and is_test_file(importer_path):
                terminals.setdefault(importer, (seed, hop + 1))

    return terminals


def _tests_under(graph: ImportGraph, directory: str) -> list[str]:
    prefix = f"{directory}/"
    return [
        path for path in graph.paths if path.startswith(prefix) and is_test_file(path)
    ]


def select_tests(
    root: Path,
    options: SelectionOptions | None = None,
    *,
    graph: ImportGraph | None = None,
    change_set: ChangeSet | None = None,
    contract_set: Sequence[str] | None = None,
    environment: str | None = None,
    previous_manifest: Mapping[str, Any] | None = None,
) -> Selection:
    """Select the test files that plausibly cover the current change set."""
    options = options or SelectionOptions.from_environment()
    if graph is None:
        graph = build_import_graph(
            root,
            cache_path=root / SELECTION_DIRECTORY / GRAPH_CACHE_FILENAME,
            use_cache=options.use_cache,
        )
    if change_set is None:
        change_set = compute_change_set(root, options.base_ref)
    if contract_set is None:
        contract_set = load_contract_manifest(root)
    if environment is None:
        environment = environment_fingerprint(root)
    if previous_manifest is None:
        previous_manifest = read_manifest(
            root / SELECTION_DIRECTORY / MANIFEST_FILENAME
        )

    previous_environment = (
        (previous_manifest or {}).get("baseline", {}).get("environment")
    )
    core_identity_changed = bool(
        environment and previous_environment and environment != previous_environment
    )

    evaluation = evaluate_broadening_rules(
        change_set.paths,
        base_resolved=change_set.merge_base is not None,
        core_identity_changed=core_identity_changed,
        has_rename_or_delete=change_set.has_rename_or_delete,
        graph=graph,
    )

    universe = sorted(
        path for path in graph.paths if is_test_file(path) and not is_visual_path(path)
    )
    rules = list(evaluation.rules)

    selected: set[str] = set()
    explanations: dict[str, tuple[str, int]] = {}
    if not evaluation.forces_full_suite:
        # A rename or deletion moves importers around in ways one hop of the
        # graph no longer describes; buy back that hop rather than build
        # bespoke machinery for it.
        depth = options.depth + (1 if change_set.has_rename_or_delete else 0)
        seeds = [
            graph.paths[path]
            for path in change_set.paths
            if path in graph.paths and not is_test_file(path)
        ]
        terminals = _closure(graph, seeds, depth)
        for module, origin in terminals.items():
            path = graph.path_for(module)
            if path is None:
                continue
            selected.add(path)
            explanations[path] = origin

        for directory in evaluation.conftest_directories:
            for path in _tests_under(graph, directory):
                selected.add(path)
                explanations.setdefault(path, (f"{directory}/conftest.py", 0))

        for path in change_set.paths:
            if is_test_file(path):
                selected.add(path)
                explanations.setdefault(path, (path, 0))

        for path in contract_set:
            selected.add(path)
            explanations.setdefault(path, (CONTRACT_MANIFEST_PATH, 0))
        if contract_set:
            rules.append(RULE_CONTRACT_SET_ALWAYS)

        selected = {path for path in selected if not is_visual_path(path)}

    escalated = evaluation.forces_full_suite
    if not escalated and len(selected) > options.max_ratio * len(universe):
        escalated = True
        rules.append(RULE_RATIO_EXCEEDED)
    if escalated:
        selected = set()
        explanations = {}

    ordered_rules = tuple(sorted(set(rules)))
    ordered_selected = tuple(sorted(selected))
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "base": {"ref": change_set.base_ref, "merge_base": change_set.merge_base},
        "changed_files": list(change_set.paths),
        "depth": options.depth,
        "max_ratio": options.max_ratio,
        "rules_fired": list(ordered_rules),
        "escalated": escalated,
        "selected": list(ordered_selected),
        "selected_count": len(ordered_selected),
        "universe_count": len(universe),
        "baseline": {
            "environment": environment,
            "head": change_set.head,
            "tree_dirty": change_set.tree_dirty,
        },
        "graph": dict(graph.stats),
    }
    return Selection(
        selected=ordered_selected,
        escalated=escalated,
        rules=ordered_rules,
        manifest=manifest,
        explanations=explanations,
        universe_count=len(universe),
    )


# --------------------------------------------------------------------------
# Manifest and environment identity
# --------------------------------------------------------------------------


def read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def sase_core_directory(root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Mirror the Justfile's ``sase_core_dir`` resolution order."""
    environ = os.environ if environ is None else environ
    for name in _SASE_CORE_DIR_ENV_VARS:
        value = environ.get(name)
        if value:
            candidate = Path(value)
            return candidate if candidate.is_absolute() else root / candidate
    workspace_checkout = root / _WORKSPACE_SASE_CORE_DIR
    if workspace_checkout.exists():
        return workspace_checkout
    return root.parent / "sase-core"


def _load_validator_module(root: Path) -> ModuleType | None:
    script = root / "tools" / "validate_test_environment"
    if not script.exists():
        return None
    loader = SourceFileLoader("sase_validate_test_environment", str(script))
    spec = importlib.util.spec_from_file_location(
        "sase_validate_test_environment", script, loader=loader
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


def environment_fingerprint(root: Path) -> str | None:
    """Digest the installed environment, including the ``sase_core_rs`` identity.

    The Rust extension's identity is invisible to ``git diff`` — the wheel
    lives in the venv and its source lives in a sibling repo — so the selector
    reuses the fingerprint ``tools/validate_test_environment`` already computes
    rather than inventing a second, divergent one. An unavailable fingerprint
    is recorded as ``None``, never as a change.
    """
    module = _load_validator_module(root)
    if module is None:
        return None
    try:
        return str(
            module._input_fingerprint(
                venv_dir=root / ".venv",
                pyproject=root / "pyproject.toml",
                uv_lock=root / "uv.lock",
                sase_core_dir=sase_core_directory(root),
            )
        )
    except Exception:
        return None


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def summary_line(selection: Selection) -> str:
    rules = ", ".join(selection.rules) or "none"
    if selection.escalated:
        return (
            f"test selection escalated to the full suite "
            f"(rules: {rules}); {selection.universe_count} test files in scope"
        )
    return (
        f"selected {len(selection.selected)} of {selection.universe_count} "
        f"test files (rules: {rules})"
    )


def explain_lines(selection: Selection, *, sample: int = 20) -> list[str]:
    """Render why the selection looks the way it does."""
    lines = [summary_line(selection)]
    lines.append(f"rules fired: {', '.join(selection.rules) or 'none'}")
    if selection.escalated:
        lines.append("no per-file selection: the run escalates to the full suite")
        return lines
    lines.append(f"selected files (showing up to {sample}):")
    for path in selection.selected[:sample]:
        seed, hop = selection.explanations.get(path, ("?", -1))
        lines.append(f"  {path}  <- seed {seed} at hop {hop}")
    if len(selection.selected) > sample:
        lines.append(f"  ... and {len(selection.selected) - sample} more")
    return lines
