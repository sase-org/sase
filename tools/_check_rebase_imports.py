#!/usr/bin/env python3
"""Resolve first-party imports on a rebased tree for the after-rebase gate.

Stdlib-only: this helper never imports ``sase``. It reads changed ``.py`` files
with :mod:`ast`, then loads first-party targets from the checked checkout's
``src`` via :func:`importlib.util.spec_from_file_location` so an installed
wheel cannot shadow the committed tree.
"""

from __future__ import annotations

import ast
import importlib.abc
import importlib.util
import json
import os
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast


SCHEMA_VERSION = 1
FIRST_PARTY_ROOT = "sase"
CONTEXT_ENV = "SASE_REBASE_CONTEXT"
RESULT_ENV = "SASE_REBASE_RESULT"
SRC_DIRNAME = "src"

#: Exact ``(module, imported_name)`` pairs that may fail at runtime only inside
#: a proven ``TYPE_CHECKING`` block. Derived from an importlib scan of this
#: checkout's ``src``/``tests``/``tools``: every first-party TYPE_CHECKING
#: alias currently resolves, so the set is empty. Never applied to a runtime
#: import of the same name.
TYPE_CHECKING_ALIAS_EXCEPTIONS: frozenset[tuple[str, str]] = frozenset()

_GIT_TIMEOUT_SECONDS = 10.0
_SKIP_CHANGE_KINDS = frozenset({"deleted"})


@dataclass(frozen=True)
class ImportSite:
    """One ``from ... import ...`` name at a concrete source location."""

    path: str
    line: int
    module: str
    imported_name: str
    in_type_checking: bool


@dataclass(frozen=True)
class _NameVerdict:
    status: Literal["ok", "missing_module", "missing_name", "error"]
    explanation: str


class CheckerError(Exception):
    """Infrastructure failure: emit ``status=error`` and fail open."""


class CommittedTree:
    """Read and verify only files named by the committed tree identity."""

    def __init__(self, repo: Path, tree: str) -> None:
        self.repo = repo.resolve()
        self.tree = tree
        self._source_cache: dict[str, bytes] = {}

    def _entry(self, rel_path: str) -> tuple[str, bytes]:
        """Return the committed mode and blob for one exact repository path."""
        completed = subprocess.run(
            ["git", "ls-tree", "-z", self.tree, "--", f":(literal){rel_path}"],
            cwd=self.repo,
            check=False,
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).decode(
                "utf-8", errors="replace"
            ).strip()
            raise CheckerError(f"git ls-tree failed for {rel_path}: {detail}")
        entries = [entry for entry in completed.stdout.split(b"\0") if entry]
        if len(entries) != 1:
            raise CheckerError(
                f"{rel_path} does not resolve to one entry in committed tree {self.tree}"
            )
        metadata, entry_path = entries[0].split(b"\t", 1)
        if os.fsdecode(entry_path) != rel_path:
            raise CheckerError(f"git resolved an unexpected tree path for {rel_path}")
        try:
            mode_bytes, kind, oid = metadata.split()
        except ValueError as exc:
            raise CheckerError(f"malformed git tree entry for {rel_path}") from exc
        if kind != b"blob":
            raise CheckerError(f"{rel_path} is not a committed source blob")
        blob = subprocess.run(
            ["git", "cat-file", "blob", os.fsdecode(oid)],
            cwd=self.repo,
            check=False,
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if blob.returncode != 0:
            detail = (blob.stderr or blob.stdout).decode("utf-8", errors="replace").strip()
            raise CheckerError(f"git cat-file failed for {rel_path}: {detail}")
        return mode_bytes.decode("ascii"), blob.stdout

    def source_bytes(self, rel_path: str) -> bytes:
        """Verify worktree identity and return committed Python source bytes."""
        posix = _posix_relpath(rel_path)
        if (
            not posix
            or posix.startswith("/")
            or "\0" in posix
            or any(part in ("", ".", "..") for part in posix.split("/"))
        ):
            raise CheckerError(f"invalid repository-relative source path {rel_path!r}")
        cached = self._source_cache.get(posix)
        if cached is not None:
            return cached
        source = self.repo / Path(*posix.split("/"))
        mode, committed = self._entry(posix)
        try:
            source_info = source.lstat()
        except OSError as exc:
            raise CheckerError(f"cannot inspect committed source {posix}: {exc}") from exc
        if mode == "120000":
            if not stat.S_ISLNK(source_info.st_mode):
                raise CheckerError(f"committed symlink {posix} is not a worktree symlink")
            try:
                link_target = os.fsencode(os.readlink(source))
            except OSError as exc:
                raise CheckerError(f"cannot read committed symlink {posix}: {exc}") from exc
            if link_target != committed:
                raise CheckerError(f"worktree symlink {posix} differs from committed tree")
            try:
                resolved = source.resolve(strict=True)
                rel_target = resolved.relative_to(self.repo).as_posix()
            except (OSError, ValueError) as exc:
                raise CheckerError(
                    f"committed symlink {posix} resolves outside the repository"
                ) from exc
            if rel_target == posix:
                raise CheckerError(f"committed symlink cycle at {posix}")
            result = self.source_bytes(rel_target)
        else:
            if mode not in ("100644", "100755"):
                raise CheckerError(f"unsupported committed source mode {mode} for {posix}")
            if stat.S_ISLNK(source_info.st_mode) or not stat.S_ISREG(source_info.st_mode):
                raise CheckerError(f"worktree source type for {posix} differs from committed tree")
            try:
                working = source.read_bytes()
            except OSError as exc:
                raise CheckerError(f"cannot read committed source {posix}: {exc}") from exc
            if working != committed:
                raise CheckerError(f"worktree source {posix} differs from committed tree")
            result = committed
        self._source_cache[posix] = result
        return result


class _CommittedSourceLoader(importlib.abc.Loader):
    """Execute first-party modules from verified committed source bytes."""

    def __init__(self, tree: CommittedTree, name: str, source: Path) -> None:
        self.tree = tree
        self.name = name
        self.source = source

    def create_module(self, spec: Any) -> None:
        del spec
        return None

    def exec_module(self, module: Any) -> None:
        rel_path = self.source.relative_to(self.tree.repo).as_posix()
        source = self.tree.source_bytes(rel_path)
        filename = str(self.source)
        module.__file__ = filename
        code = compile(source, filename, "exec")
        exec(code, module.__dict__)


class _MissingFirstPartyLoader(importlib.abc.Loader):
    """Stop missing first-party modules from falling through to site-packages."""

    def __init__(self, name: str) -> None:
        self.name = name

    def create_module(self, spec: Any) -> None:
        del spec
        return None

    def exec_module(self, module: Any) -> None:
        del module
        raise ModuleNotFoundError(f"no committed first-party module named {self.name}")


class _CommittedSourceFinder(importlib.abc.MetaPathFinder):
    """Load every ``sase`` import from the named committed tree."""

    def __init__(self, tree: CommittedTree, src_root: Path) -> None:
        self.tree = tree
        self.src_root = src_root

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: Any = None,
    ) -> Any:
        del path, target
        if not _is_first_party_module(fullname):
            return None
        source = _module_source_path(self.src_root, fullname)
        if source is None:
            return importlib.util.spec_from_loader(
                fullname,
                _MissingFirstPartyLoader(fullname),
                origin="committed-tree-missing",
            )
        loader = _CommittedSourceLoader(self.tree, fullname, source)
        return importlib.util.spec_from_loader(
            fullname,
            loader,
            origin=str(source),
            is_package=source.name == "__init__.py",
        )


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _is_first_party_module(module: str) -> bool:
    return module == FIRST_PARTY_ROOT or module.startswith(FIRST_PARTY_ROOT + ".")


def _posix_relpath(path: str) -> str:
    return path.replace("\\", "/")


def _src_module_for_path(rel_path: str) -> tuple[str, str] | None:
    """Return ``(module_name, __package__)`` for a file under ``src/``."""

    posix = _posix_relpath(rel_path)
    prefix = SRC_DIRNAME + "/"
    if not posix.startswith(prefix):
        return None
    rest = posix[len(prefix) :]
    if rest.endswith("/__init__.py"):
        module = rest[: -len("/__init__.py")].replace("/", ".")
        if not module:
            return None
        return module, module
    if rest.endswith(".py"):
        module = rest[: -len(".py")].replace("/", ".")
        if not module:
            return None
        package = module.rpartition(".")[0]
        return module, package
    return None


def _resolve_from_module(node: ast.ImportFrom, package: str | None) -> str | None:
    if node.level == 0:
        return node.module
    if not package:
        return None
    relative = "." * node.level
    if node.module:
        relative += node.module
    try:
        return importlib.util.resolve_name(relative, package)
    except (ImportError, ValueError):
        return None


def collect_import_sites(source: str, path: str) -> list[ImportSite]:
    """Walk every nested ``ast.ImportFrom`` including TYPE_CHECKING blocks."""

    tree = ast.parse(source, filename=path)
    location = _src_module_for_path(path)
    package = location[1] if location is not None else None
    sites: list[ImportSite] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.in_type_checking = 0

        def visit_If(self, node: ast.If) -> None:
            if _is_type_checking_test(node.test):
                self.in_type_checking += 1
                for child in node.body:
                    self.visit(child)
                self.in_type_checking -= 1
                for child in node.orelse:
                    self.visit(child)
                return
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            module = _resolve_from_module(node, package)
            in_tc = self.in_type_checking > 0
            if module is None:
                if node.level and location is not None:
                    raise CheckerError(
                        f"{path}:{node.lineno}: cannot resolve relative import "
                        f"in first-party file"
                    )
                self.generic_visit(node)
                return
            if not _is_first_party_module(module):
                self.generic_visit(node)
                return
            for alias in node.names:
                sites.append(
                    ImportSite(
                        path=path,
                        line=node.lineno,
                        module=module,
                        imported_name=alias.name,
                        in_type_checking=in_tc,
                    )
                )
            self.generic_visit(node)

    Visitor().visit(tree)
    return sites


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
    )


def _git_text(repo: Path, *args: str) -> str:
    completed = _run_git(repo, *args)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        command = " ".join(("git", *args))
        raise CheckerError(
            f"{command} failed in {repo}" + (f": {detail}" if detail else "")
        )
    return completed.stdout


def _nul_split(payload: str) -> list[str]:
    return [item for item in payload.split("\0") if item]


def _python_paths_not_matching_tree(repo: Path, tree: str) -> list[str]:
    """Return dirty or untracked ``.py`` paths that could shadow the tree."""

    names: list[str] = []
    queries = (
        ("diff", "--name-only", "-z", tree, "--"),
        ("diff", "--cached", "--name-only", "-z", tree, "--"),
        ("ls-files", "-o", "-z", "--"),
        ("ls-files", "-o", "-i", "--exclude-standard", "-z", "--"),
    )
    seen: set[str] = set()
    for args in queries:
        for path in _nul_split(_git_text(repo, *args)):
            posix = _posix_relpath(path)
            if posix.endswith(".py") and posix not in seen:
                seen.add(posix)
                names.append(posix)
    return names


def _verify_committed_tree(repo: Path, current_head: str, current_tree: str) -> None:
    head = _git_text(repo, "rev-parse", "--verify", "HEAD").strip()
    tree = _git_text(repo, "rev-parse", "--verify", "HEAD^{tree}").strip()
    if head != current_head or tree != current_tree:
        raise CheckerError(
            "HEAD/tree does not match the pending rebase context "
            f"(HEAD={head} tree={tree}; "
            f"context HEAD={current_head} tree={current_tree})"
        )
    dirty = _python_paths_not_matching_tree(repo, current_tree)
    if dirty:
        preview = ", ".join(dirty[:8])
        extra = "" if len(dirty) <= 8 else f" (+{len(dirty) - 8} more)"
        raise CheckerError(
            "Python working tree does not match the committed tree "
            f"{current_tree}; refusing to certify dirty paths: {preview}{extra}"
        )


def _module_source_path(src_root: Path, module_name: str) -> Path | None:
    parts = module_name.split(".")
    directory = src_root
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        package_init = directory / part / "__init__.py"
        module_file = directory / f"{part}.py"
        if last:
            if package_init.is_file():
                return package_init
            if module_file.is_file():
                return module_file
            return None
        if not package_init.is_file():
            return None
        directory = directory / part
    return None


def _prepare_import_env(tree: CommittedTree, src_root: Path) -> None:
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    src = str(src_root)
    try:
        sys.path.remove(src)
    except ValueError:
        pass
    sys.path.insert(0, src)
    for name in tuple(sys.modules):
        if name == FIRST_PARTY_ROOT or name.startswith(FIRST_PARTY_ROOT + "."):
            del sys.modules[name]
    sys.meta_path.insert(0, _CommittedSourceFinder(tree, src_root))
    importlib.invalidate_caches()


def _load_first_party(
    tree: CommittedTree,
    src_root: Path,
    module_name: str,
) -> Any | None:
    """Load ``module_name`` from ``src``.

    Returns the module on success, ``None`` when it is absent from ``src``,
    or raises :class:`CheckerError` on a load failure.
    """

    if _module_source_path(src_root, module_name) is None:
        return None
    try:
        return importlib.import_module(module_name)
    except Exception as exc:
        raise CheckerError(
            f"importing first-party module {module_name} from committed tree "
            f"{tree.tree} failed: {type(exc).__name__}: {exc}"
        ) from exc


def _resolve_name(
    tree: CommittedTree,
    src_root: Path,
    module_name: str,
    imported_name: str,
) -> _NameVerdict:
    if not _is_first_party_module(module_name):
        return _NameVerdict("ok", "not a first-party sase import")
    try:
        loaded = _load_first_party(tree, src_root, module_name)
    except CheckerError as exc:
        return _NameVerdict("error", str(exc))
    if loaded is None:
        return _NameVerdict(
            "missing_module",
            f"first-party module {module_name!r} is absent from {SRC_DIRNAME}/",
        )
    if imported_name == "*":
        return _NameVerdict("ok", "star import: module resolved")
    if hasattr(loaded, imported_name):
        return _NameVerdict("ok", "attribute exists")
    submodule = f"{module_name}.{imported_name}"
    sub_source = _module_source_path(src_root, submodule)
    if sub_source is None:
        return _NameVerdict(
            "missing_name",
            f"cannot import name {imported_name!r} from first-party module "
            f"{module_name!r}",
        )
    try:
        _load_first_party(tree, src_root, submodule)
    except CheckerError as exc:
        return _NameVerdict("error", str(exc))
    return _NameVerdict("ok", "package submodule import")


def _inspect_path(tree: CommittedTree, rel_path: str) -> list[ImportSite]:
    try:
        source = tree.source_bytes(rel_path).decode("utf-8")
    except UnicodeError as exc:
        raise CheckerError(f"cannot decode committed Python source {rel_path}: {exc}") from exc
    try:
        return collect_import_sites(source, rel_path)
    except SyntaxError as exc:
        raise CheckerError(
            f"cannot parse {rel_path}: {exc.msg} (line {exc.lineno})"
        ) from exc


def _changed_python_paths(changed_paths: Sequence[Mapping[str, Any]]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for change in changed_paths:
        path = change.get("path")
        kind = change.get("kind")
        if not isinstance(path, str) or not path:
            raise CheckerError("changed path is missing a repository-relative path")
        posix = _posix_relpath(path)
        if kind in _SKIP_CHANGE_KINDS:
            continue
        if not posix.endswith(".py"):
            continue
        if posix not in seen:
            seen.add(posix)
            paths.append(posix)
    return paths


def _require_context_field(context: Mapping[str, Any], key: str) -> Any:
    if key not in context:
        raise CheckerError(f"rebase context is missing {key!r}")
    return context[key]


def _report(
    *,
    head: str,
    tree: str,
    status: Literal["clean", "findings", "error"],
    findings: list[dict[str, Any]],
    diagnostics: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "checked_head": head,
        "checked_tree": tree,
        "status": status,
        "findings": findings,
    }
    if diagnostics:
        payload["diagnostics"] = diagnostics
    return payload


def check_repository(
    context: Mapping[str, Any],
    *,
    exceptions: frozenset[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Inspect changed first-party imports and return a protocol report."""

    allowlist = TYPE_CHECKING_ALIAS_EXCEPTIONS if exceptions is None else exceptions
    schema_version = _require_context_field(context, "schema_version")
    repository_root = _require_context_field(context, "repository_root")
    current_head = _require_context_field(context, "current_head")
    current_tree = _require_context_field(context, "current_tree")
    changed_paths = _require_context_field(context, "changed_paths")
    if schema_version != SCHEMA_VERSION:
        raise CheckerError(
            f"unsupported rebase context schema_version {schema_version!r}"
        )
    if not isinstance(repository_root, str) or not repository_root:
        raise CheckerError("repository_root must be an absolute path")
    if not isinstance(current_head, str) or not isinstance(current_tree, str):
        raise CheckerError("current_head and current_tree must be strings")
    if not isinstance(changed_paths, list):
        raise CheckerError("changed_paths must be a list")

    repo = Path(repository_root).resolve()
    src_root = repo / SRC_DIRNAME
    if not src_root.is_dir():
        raise CheckerError(f"checked repository has no {SRC_DIRNAME}/ directory")

    _verify_committed_tree(repo, current_head, current_tree)
    committed_tree = CommittedTree(repo, current_tree)
    _prepare_import_env(committed_tree, src_root)

    python_paths = _changed_python_paths(
        cast(Sequence[Mapping[str, Any]], changed_paths)
    )
    sites: list[ImportSite] = []
    for rel_path in python_paths:
        sites.extend(_inspect_path(committed_tree, rel_path))

    verdicts: dict[tuple[str, str], _NameVerdict] = {}
    findings: list[dict[str, Any]] = []
    for site in sites:
        if site.in_type_checking and (site.module, site.imported_name) in allowlist:
            continue
        key = (site.module, site.imported_name)
        verdict = verdicts.get(key)
        if verdict is None:
            verdict = _resolve_name(
                committed_tree, src_root, site.module, site.imported_name
            )
            verdicts[key] = verdict
        if verdict.status == "ok":
            continue
        if verdict.status == "error":
            raise CheckerError(verdict.explanation)
        findings.append(
            {
                "path": site.path,
                "line": site.line,
                "module": site.module,
                "imported_name": site.imported_name,
                "explanation": verdict.explanation,
            }
        )

    findings.sort(
        key=lambda item: (
            str(item["path"]),
            int(item["line"]),
            str(item["module"]),
            str(item["imported_name"]),
        )
    )
    if findings:
        return _report(
            head=current_head,
            tree=current_tree,
            status="findings",
            findings=findings,
            diagnostics=None,
        )
    return _report(
        head=current_head,
        tree=current_tree,
        status="clean",
        findings=[],
        diagnostics=None,
    )


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(dict(report), allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _error_report(
    context: Mapping[str, Any] | None, diagnostics: str
) -> dict[str, Any]:
    head = ""
    tree = ""
    if context is not None:
        maybe_head = context.get("current_head")
        maybe_tree = context.get("current_tree")
        if isinstance(maybe_head, str):
            head = maybe_head
        if isinstance(maybe_tree, str):
            tree = maybe_tree
    return _report(
        head=head,
        tree=tree,
        status="error",
        findings=[],
        diagnostics=diagnostics,
    )


def _load_context(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckerError(f"cannot read rebase context {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CheckerError("rebase context must be a JSON object")
    return payload


def _exit_code(status: str) -> int:
    if status == "clean":
        return 0
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Read the gate context, write a protocol result, and return 0 or 1."""

    del argv
    result_raw = os.environ.get(RESULT_ENV, "")
    context_raw = os.environ.get(CONTEXT_ENV, "")
    if not result_raw or not context_raw:
        sys.stderr.write(
            f"{CONTEXT_ENV} and {RESULT_ENV} must name the gate JSON files\n"
        )
        return 2

    result_path = Path(result_raw)
    context: dict[str, Any] | None = None
    try:
        context = _load_context(Path(context_raw))
        report = check_repository(context)
    except CheckerError as exc:
        report = _error_report(context, str(exc))
    except Exception as exc:  # noqa: BLE001 — checker bugs must fail open
        report = _error_report(
            context,
            f"checker bug: {type(exc).__name__}: {exc}",
        )
    try:
        _write_report(result_path, report)
    except OSError as exc:
        sys.stderr.write(f"cannot write rebase result {result_path}: {exc}\n")
        return 2
    return _exit_code(str(report["status"]))


__all__ = [
    "CONTEXT_ENV",
    "CheckerError",
    "ImportSite",
    "RESULT_ENV",
    "SCHEMA_VERSION",
    "TYPE_CHECKING_ALIAS_EXCEPTIONS",
    "check_repository",
    "collect_import_sites",
    "main",
]
