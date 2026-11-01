#!/usr/bin/env python3
"""Normalized first-party source footprint of an import closure.

Developer-only measurement infrastructure shared by ``tools/tui_import_closure``
and ``tests/ace/tui/test_app_import_budget.py``. It is deliberately outside the
product import graph (nothing under ``src/`` imports it).

The import-budget guard used to count first-party modules, so a mechanical
module split (a facade plus helper files holding the same code) consumed budget
for pure import/``__all__``/docstring boilerplate. The *footprint* charges the
implementation instead: the sum of UTF-8 byte lengths of the significant Python
tokens of the unique source files behind the imported first-party modules.

Excluded from the metric (:data:`FOOTPRINT_METRIC_VERSION` 1):

* whitespace, indentation, newlines, comments, and encoding/end markers;
* ``import`` / ``from ... import`` statements wherever they appear;
* actual module, class, and function docstrings;
* a plain module-level assignment of a literal string list/tuple to ``__all__``.

Everything else counts: ordinary literals, annotations, decorators, function
bodies, executable statements, ``__all__ +=`` and computed ``__all__`` values.
``ast`` identifies the excluded source spans and ``tokenize`` measures the
original source text, so the result never depends on ``ast.unparse`` spelling.

The probe imports the target in a fresh interpreter and captures the stopwatch,
``sys.modules`` and deferred-module results immediately afterwards. Source files
are then read and parsed in the *calling* process, so the measurement machinery
cannot inflate the measured interpreter's module counts or CPU time.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import textwrap
import tokenize
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


FOOTPRINT_METRIC_VERSION = 1
APP_MODULE = "sase.ace.tui.app"
FIRST_PARTY_ROOT = "sase"

#: Token types that never carry implementation weight.
_TRIVIA_TOKENS = frozenset(
    {
        tokenize.COMMENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
        tokenize.INDENT,
        tokenize.NEWLINE,
        tokenize.NL,
    }
)
#: Interpolated-string text tokens. Their ``string`` collapses escaped braces
#: (``{{`` -> ``{``) and their own span skips the dropped brace, so they are
#: measured to the start of the following token instead.
_MIDDLE_TOKENS = frozenset(
    getattr(tokenize, name)
    for name in ("FSTRING_MIDDLE", "TSTRING_MIDDLE")
    if hasattr(tokenize, name)
)
_BLOCK_FIELDS = ("body", "orelse", "finalbody", "handlers", "cases")
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

_PROBE_SNIPPET = textwrap.dedent(
    """
    import importlib
    import json
    import sys
    import time

    request = json.loads(sys.argv[1])
    root = request["root"]
    prefix = root + "."

    started = time.process_time()
    importlib.import_module(request["target"])
    elapsed = time.process_time() - started

    snapshot = list(sys.modules.items())
    first_party = sorted(
        name for name, _ in snapshot if name == root or name.startswith(prefix)
    )
    deferred = [name for name in request["deferred"] if name in sys.modules]
    sources = {}
    for name in first_party:
        module = sys.modules.get(name)
        spec = getattr(module, "__spec__", None)
        file = getattr(module, "__file__", None)
        if file is None and spec is not None and spec.has_location:
            file = spec.origin
        sources[name] = {
            "file": file,
            "namespace": (
                file is None
                and spec is not None
                and spec.origin is None
                and spec.submodule_search_locations is not None
            ),
        }

    print(json.dumps({
        "elapsed_seconds": elapsed,
        "module_count": len(snapshot),
        "first_party_modules": first_party,
        "deferred_modules": deferred,
        "sources": sources,
    }))
    """
)


class ImportProbeError(RuntimeError):
    """The fresh-interpreter import of the measured target failed."""


class FootprintError(RuntimeError):
    """An imported first-party source could not be read or parsed."""


@dataclass(frozen=True)
class ModuleSource:
    """Where one imported first-party module claims its source lives."""

    file: str | None
    namespace: bool = False


@dataclass(frozen=True)
class SourceFootprint:
    """Normalized footprint of an import closure.

    ``module_bytes`` maps the canonical (lexicographically first) module name of
    each unique source file to its bytes; names aliasing an already-counted file
    and genuine namespace packages are absent.
    """

    total_bytes: int
    module_bytes: Mapping[str, int]


@dataclass(frozen=True)
class ImportMeasurement:
    """One fresh-interpreter import measurement."""

    elapsed_seconds: float
    module_count: int
    first_party_modules: tuple[str, ...]
    deferred_modules: tuple[str, ...]
    footprint: SourceFootprint

    @property
    def first_party_count(self) -> int:
        return len(self.first_party_modules)

    @property
    def footprint_bytes(self) -> int:
        return self.footprint.total_bytes


def is_first_party_module(name: str, root: str = FIRST_PARTY_ROOT) -> bool:
    """Return True for the *root* package and its submodules."""
    return name == root or name.startswith(root + ".")


# --------------------------------------------------------------------------
# Per-file metric
# --------------------------------------------------------------------------

_Position = tuple[int, int]
_Span = tuple[_Position, _Position]


def decode_source(data: bytes) -> str:
    """Decode Python source bytes with universal newlines, like the compiler."""
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return io.TextIOWrapper(io.BytesIO(data), encoding=encoding, newline=None).read()


def _iter_statements(body: Sequence[ast.AST]) -> Iterator[ast.AST]:
    """Yield every statement-level node, descending only through blocks."""
    stack = list(reversed(body))
    while stack:
        node = stack.pop()
        yield node
        for field in _BLOCK_FIELDS:
            children = getattr(node, field, None)
            if isinstance(children, list):
                stack.extend(reversed(children))


def _docstring_statement(node: ast.AST) -> ast.stmt | None:
    body = getattr(node, "body", None)
    if not isinstance(body, list) or not body:
        return None
    first = body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return first
    return None


def _is_literal_all_assignment(node: ast.AST) -> bool:
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return False
    target = node.targets[0]
    if not isinstance(target, ast.Name) or target.id != "__all__":
        return False
    return isinstance(node.value, (ast.List, ast.Tuple)) and all(
        isinstance(element, ast.Constant) and isinstance(element.value, str)
        for element in node.value.elts
    )


def _excluded_statements(tree: ast.Module) -> list[ast.stmt]:
    excluded: list[ast.stmt] = []
    docstring = _docstring_statement(tree)
    if docstring is not None:
        excluded.append(docstring)
    for statement in tree.body:
        if _is_literal_all_assignment(statement):
            excluded.append(statement)
    for node in _iter_statements(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            excluded.append(node)
        elif isinstance(node, (ast.ClassDef, *_FUNCTION_NODES)):
            docstring = _docstring_statement(node)
            if docstring is not None:
                excluded.append(docstring)
    return excluded


def _character_column(line: str, byte_column: int) -> int:
    """Translate an ``ast`` UTF-8 byte column into a ``tokenize`` character column."""
    if line.isascii():
        return byte_column
    return len(line.encode("utf-8")[:byte_column].decode("utf-8"))


def _statement_span(statement: ast.stmt, lines: Sequence[str]) -> _Span:
    end_line = statement.end_lineno or statement.lineno
    end_column = statement.end_col_offset or 0
    return (
        (
            statement.lineno,
            _character_column(lines[statement.lineno - 1], statement.col_offset),
        ),
        (end_line, _character_column(lines[end_line - 1], end_column)),
    )


def _merged(spans: list[_Span]) -> list[_Span]:
    merged: list[_Span] = []
    for start, end in sorted(spans):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _span_bytes(lines: Sequence[str], start: _Position, end: _Position) -> int:
    """UTF-8 width of the source text between two tokenizer positions."""
    (start_row, start_col), (end_row, end_col) = start, end
    if start_row == end_row:
        text = lines[start_row - 1][start_col:end_col]
    else:
        text = "\n".join(
            [
                lines[start_row - 1][start_col:],
                *lines[start_row : end_row - 1],
                lines[end_row - 1][:end_col],
            ]
        )
    return len(text) if text.isascii() else len(text.encode("utf-8"))


def source_footprint(text: str) -> int:
    """Return the normalized token bytes of decoded, newline-normalized *text*.

    Raises :class:`SyntaxError` or :class:`tokenize.TokenError` when the source
    cannot be parsed.
    """
    tree = ast.parse(text)
    lines = text.split("\n")
    spans = _merged(
        [_statement_span(node, lines) for node in _excluded_statements(tree)]
    )
    total = 0
    index = 0
    pending: tokenize.TokenInfo | None = None
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if pending is not None:
            # Literal text inside an interpolated string runs up to the next
            # token, and the tokenizer drops one brace of each escaped pair
            # from both ``string`` and the token's own span; the gap holds it.
            total += _span_bytes(lines, pending.start, token.start)
            pending = None
        if token.type in _TRIVIA_TOKENS:
            continue
        while index < len(spans) and spans[index][1] <= token.start:
            index += 1
        if index < len(spans) and spans[index][0] <= token.start:
            continue
        if token.type in _MIDDLE_TOKENS:
            pending = token
            continue
        string = token.string
        total += len(string) if string.isascii() else len(string.encode("utf-8"))
    return total


# --------------------------------------------------------------------------
# Closure footprint
# --------------------------------------------------------------------------


def resolve_source_path(name: str, source: ModuleSource, base_dir: Path) -> Path:
    """Return the readable ``.py`` source behind an imported module.

    Source-backed ``.pyc`` paths map back to their source file. A module with no
    Python source (extension, sourceless bytecode, missing file) is a hard
    :class:`FootprintError`, never a silent zero.
    """
    if source.file is None:
        raise FootprintError(
            f"cannot measure {name!r}: the interpreter reported no source file"
        )
    path = Path(source.file)
    if not path.is_absolute():
        path = base_dir / path
    if path.suffix == ".pyc":
        candidates = [path.with_suffix(".py")]
        try:
            candidates.insert(0, Path(importlib.util.source_from_cache(str(path))))
        except ValueError:
            pass
        found = next((item for item in candidates if item.is_file()), None)
        if found is None:
            raise FootprintError(
                f"cannot measure {name!r}: only compiled bytecode {path} is "
                "available (no matching .py source)"
            )
        return found
    if path.suffix != ".py":
        raise FootprintError(
            f"cannot measure {name!r}: {path} is not a Python source file"
        )
    if not path.is_file():
        raise FootprintError(f"cannot measure {name!r}: source {path} does not exist")
    return path


class FootprintCache:
    """Content-addressed memo of per-file footprints.

    Parsing a whole TUI closure costs 10-20s, almost all of it ``ast.parse``, and
    consecutive measurements (a ``--diff`` pair, or repeated test runs in one
    checkout) share nearly every file. Entries are keyed by the SHA-256 of the
    raw source bytes, so a hit is exactly what a fresh parse would return. The
    persisted file name embeds a salt derived from this helper's own source and
    the interpreter, so any change to the metric or interpreter starts empty.
    A missing, corrupt, or unwritable cache file is ignored, never an error.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self._path = (
            None if directory is None else directory / f"footprint-{_cache_salt()}.json"
        )
        self._known: dict[str, int] = {}
        self._used: dict[str, int] = {}
        self._dirty = False
        if self._path is not None:
            try:
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
                self._known = {
                    str(key): int(value)
                    for key, value in loaded.items()
                    if isinstance(value, int)
                }
            except (OSError, ValueError, AttributeError):
                self._known = {}

    def lookup(self, digest: str) -> int | None:
        value = self._known.get(digest)
        if value is not None:
            self._used[digest] = value
        return value

    def store(self, digest: str, value: int) -> None:
        self._known[digest] = value
        self._used[digest] = value
        self._dirty = True

    def save(self) -> None:
        """Persist the entries used by this run (bounding the file's growth)."""
        if self._path is None or not (self._dirty or len(self._used) < len(self._known)):
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_text(json.dumps(self._used), encoding="utf-8")
            os.replace(temporary, self._path)
        except OSError:
            return


def _cache_salt() -> str:
    material = Path(__file__).read_bytes() + sys.version.encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


def file_footprint(name: str, path: Path, cache: FootprintCache | None = None) -> int:
    """Return the footprint of one source file, naming *name* on failure."""
    try:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        cached = cache.lookup(digest) if cache is not None else None
        if cached is not None:
            return cached
        value = source_footprint(decode_source(data))
        if cache is not None:
            cache.store(digest, value)
        return value
    except OSError as error:
        raise FootprintError(
            f"cannot read source of {name!r} at {path}: {error}"
        ) from error
    except (SyntaxError, ValueError, tokenize.TokenError) as error:
        raise FootprintError(
            f"cannot parse source of {name!r} at {path}: {error}"
        ) from error


def measure_footprint(
    sources: Mapping[str, ModuleSource],
    *,
    base_dir: Path,
    cache: FootprintCache | None = None,
) -> SourceFootprint:
    """Sum the footprint of the unique source files behind *sources*.

    Two module names aliasing one file count it once under the lexicographically
    first name. Genuine namespace packages have no source and contribute zero.
    A *cache* is saved once every file has been measured.
    """
    by_path: dict[str, tuple[str, Path]] = {}
    for name in sorted(sources):
        source = sources[name]
        if source.namespace:
            continue
        path = resolve_source_path(name, source, base_dir)
        by_path.setdefault(os.path.realpath(path), (name, path))
    module_bytes = {
        name: file_footprint(name, path, cache) for name, path in by_path.values()
    }
    if cache is not None:
        cache.save()
    return SourceFootprint(
        total_bytes=sum(module_bytes.values()), module_bytes=module_bytes
    )


# --------------------------------------------------------------------------
# Fresh-interpreter probe
# --------------------------------------------------------------------------


def measure_import(
    target: str = APP_MODULE,
    *,
    root: str = FIRST_PARTY_ROOT,
    cwd: Path | None = None,
    extra_paths: Sequence[Path] = (),
    deferred_modules: Sequence[str] = (),
    cache: FootprintCache | None = None,
) -> ImportMeasurement:
    """Import *target* in a fresh interpreter and measure its closure.

    ``extra_paths`` are prepended to ``PYTHONPATH`` (a historical tree's
    ``src``). Sources are resolved from the modules the interpreter actually
    imported and read right after the import, so a temporary checkout must still
    exist when this returns.
    """
    env = dict(os.environ)
    if extra_paths:
        prefix = os.pathsep.join(str(path) for path in extra_paths)
        previous = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{prefix}{os.pathsep}{previous}" if previous else prefix
    request = {"target": target, "root": root, "deferred": list(deferred_modules)}
    result = subprocess.run(
        [sys.executable, "-c", _PROBE_SNIPPET, json.dumps(request)],
        check=False,
        text=True,
        capture_output=True,
        cwd=cwd,
        env=env,
    )
    if result.returncode != 0:
        detail = (result.stderr + result.stdout).strip().splitlines()
        tail = "\n".join(detail[-15:])
        raise ImportProbeError(f"import of {target} failed:\n{tail}")
    payload = json.loads(result.stdout)
    sources = {
        name: ModuleSource(file=item["file"], namespace=bool(item["namespace"]))
        for name, item in payload["sources"].items()
    }
    footprint = measure_footprint(sources, base_dir=cwd or Path.cwd(), cache=cache)
    return ImportMeasurement(
        elapsed_seconds=float(payload["elapsed_seconds"]),
        module_count=int(payload["module_count"]),
        first_party_modules=tuple(payload["first_party_modules"]),
        deferred_modules=tuple(payload["deferred_modules"]),
        footprint=footprint,
    )
