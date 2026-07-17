"""Shared AST scanners for agent artifact marker audit tests."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TRACKED_MARKER_LITERALS = (
    "agent_meta.json",
    "done.json",
    "running.json",
    "waiting.json",
    "pending_question.json",
    "workflow_state.json",
    "plan_path.json",
    "prompt_step_",
)
_MUTATION_CALL_NAMES = {
    "_write_json_file",
    "copy",
    "copy2",
    "copyfile",
    "copytree",
    "dump",
    "mkstemp",
    "move",
    "remove",
    "rename",
    "rmtree",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}
_LIFECYCLE_CALL_NAMES = {
    "update_agent_artifact_index_for_marker_mutation",
    "upsert_agent_artifact_index_artifacts",
    "delete_agent_artifact_index_artifacts",
    "delete_agent_artifact_index_artifacts_bounded",
    "sync_dismissed_agent_artifact_index",
}
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_NESTED_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

_UPDATE_INDEX = "update_agent_artifact_index_for_marker_mutation"
_UPSERT_INDEX = "upsert_agent_artifact_index_artifacts"
_DELETE_INDEX = "delete_agent_artifact_index_artifacts"
_DELETE_INDEX_BOUNDED = "delete_agent_artifact_index_artifacts_bounded"
_SYNC_DISMISSED_INDEX = "sync_dismissed_agent_artifact_index"
_SCHEDULE_DISMISSED_INDEX = "_schedule_artifact_index_maintenance"


@dataclass(frozen=True)
class BatchedCoverage:
    """A helper mutates markers and a known caller refreshes the index in batch."""

    caller_context: str
    helper_call: str
    lifecycle_call: str


@dataclass(frozen=True)
class DelegatedCoverage:
    """A context delegates marker mutation to another reviewed helper/context."""

    caller_context: str
    helper_call: str
    coverage_context: str


@dataclass(frozen=True)
class Review:
    """Expected mutation shape and lifecycle coverage for one mutation context."""

    mutation_calls: tuple[str, ...]
    lifecycle_calls: tuple[str, ...] = ()
    batched_by: tuple[BatchedCoverage, ...] = ()
    delegated: DelegatedCoverage | None = None
    exemption: str = ""


@dataclass(frozen=True)
class ContextInfo:
    """Observed audit details for one marker mutation context."""

    mutation_calls: tuple[str, ...]
    lifecycle_calls: tuple[str, ...]


@dataclass(frozen=True)
class DirOpReview:
    """Lifecycle coverage shape for a whole-directory operation context."""

    lifecycle_calls: tuple[str, ...] = ()
    batched_by: tuple[BatchedCoverage, ...] = ()
    delegated: DelegatedCoverage | None = None
    exemption: str = ""


@dataclass(frozen=True)
class PathPassingReview:
    """Coverage declaration for a tracked-marker path-passing context."""

    lifecycle_coverage: str = ""
    exemption: str = ""


def _own_descendants(root: ast.AST) -> list[ast.AST]:
    descendants: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(root))
    while stack:
        node = stack.pop()
        if isinstance(node, _NESTED_SCOPE_NODES):
            continue
        descendants.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return descendants


def _contains_tracked_marker_literal(nodes: list[ast.AST]) -> bool:
    for node in nodes:
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if any(marker in node.value for marker in _TRACKED_MARKER_LITERALS):
            return True
    return False


def _is_write_mode_open(call: ast.Call) -> bool:
    for arg in call.args[1:]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if "w" in arg.value:
                return True
    for keyword in call.keywords:
        if (
            keyword.arg == "mode"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
            and "w" in keyword.value.value
        ):
            return True
    return False


def _generic_call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _mutation_call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        if func.id == "open" and _is_write_mode_open(call):
            return "open"
        if func.id in _MUTATION_CALL_NAMES:
            return func.id
        return None
    if not isinstance(func, ast.Attribute):
        return None
    if (
        func.attr == "replace"
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
    ):
        return "os.replace"
    if func.attr in _MUTATION_CALL_NAMES:
        return func.attr
    return None


def _lifecycle_call_name(call: ast.Call) -> str | None:
    name = _generic_call_name(call)
    if name in _LIFECYCLE_CALL_NAMES:
        return name
    return None


def _source_ordered_calls(nodes: list[ast.AST]) -> list[ast.Call]:
    calls = [node for node in nodes if isinstance(node, ast.Call)]
    return sorted(
        calls,
        key=lambda call: (
            getattr(call, "lineno", 0),
            getattr(call, "col_offset", 0),
        ),
    )


def _contains_marker_mutation_call(nodes: list[ast.AST]) -> bool:
    return any(_mutation_call_name(call) for call in _source_ordered_calls(nodes))


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _context_node(context: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    rel_path, name = context.split(":", 1)
    path = _REPO_ROOT / rel_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, _FUNCTION_NODES) and node.name == name:
            return node
    raise AssertionError(f"missing context {context}")


def _context_call_names(context: str) -> tuple[str, ...]:
    node = _context_node(context)
    calls = (
        _generic_call_name(call)
        for call in _source_ordered_calls(_own_descendants(node))
    )
    return tuple(name for name in calls if name is not None)


def _iter_source_files(root: Path) -> list[Path]:
    return sorted((root / "src" / "sase").rglob("*.py"))


def _function_name_used_by_call(call: ast.Call, name: str) -> bool:
    if _generic_call_name(call) == name:
        return True
    return any(isinstance(arg, ast.Name) and arg.id == name for arg in call.args)


def _dismissed_save_contexts(root: Path = _REPO_ROOT) -> dict[str, tuple[str, ...]]:
    dismissed_projection_call_names = _LIFECYCLE_CALL_NAMES | {
        _SCHEDULE_DISMISSED_INDEX
    }
    contexts: dict[str, tuple[str, ...]] = {}
    for path in _iter_source_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel_path = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, _FUNCTION_NODES):
                continue
            calls = _source_ordered_calls(_own_descendants(node))
            if not any(
                _function_name_used_by_call(call, "save_dismissed_agents")
                for call in calls
            ):
                continue
            lifecycle_calls = tuple(
                dict.fromkeys(
                    name
                    for name in dismissed_projection_call_names
                    if any(_function_name_used_by_call(call, name) for call in calls)
                )
            )
            contexts[f"{rel_path}:{node.name}"] = lifecycle_calls
    return contexts


def _build_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _enclosing_function(
    node: ast.AST, parent_map: dict[ast.AST, ast.AST]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    cur: ast.AST | None = parent_map.get(node)
    while cur is not None and not isinstance(cur, _FUNCTION_NODES):
        cur = parent_map.get(cur)
    return cur


def _marker_mutation_contexts(
    root: Path = _REPO_ROOT,
) -> dict[str, ContextInfo]:
    contexts: dict[str, ContextInfo] = {}
    for path in _iter_source_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel_path = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, _FUNCTION_NODES):
                continue
            descendants = _own_descendants(node)
            if not _contains_tracked_marker_literal(descendants):
                continue
            if not _contains_marker_mutation_call(descendants):
                continue
            mutation_calls = tuple(
                name
                for call in _source_ordered_calls(descendants)
                if (name := _mutation_call_name(call)) is not None
            )
            lifecycle_calls: tuple[str, ...] = tuple(
                name
                for call in _source_ordered_calls(descendants)
                if (name := _lifecycle_call_name(call)) is not None
            )
            contexts[f"{rel_path}:{node.name}"] = ContextInfo(
                mutation_calls=mutation_calls,
                lifecycle_calls=_unique(lifecycle_calls),
            )
    return contexts


def _has_lifecycle_coverage(review: Review) -> bool:
    return bool(review.lifecycle_calls or review.batched_by or review.delegated)


_DIR_OPERATION_CALL_KINDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("shutil", "rmtree"),
        ("shutil", "move"),
        ("os", "rename"),
    }
)


def _dir_operation_call_label(call: ast.Call) -> str | None:
    func = call.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return None
    pair = (func.value.id, func.attr)
    if pair in _DIR_OPERATION_CALL_KINDS:
        return f"{pair[0]}.{pair[1]}"
    return None


def _artifact_directory_operation_contexts(
    root: Path = _REPO_ROOT,
) -> dict[str, tuple[str, ...]]:
    contexts: dict[str, set[str]] = {}
    for path in _iter_source_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel_path = path.relative_to(root).as_posix()
        parent_map = _build_parent_map(tree)
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            label = _dir_operation_call_label(call)
            if label is None:
                continue
            enclosing = _enclosing_function(call, parent_map)
            if enclosing is None:
                continue
            contexts.setdefault(f"{rel_path}:{enclosing.name}", set()).add(label)
    return {key: tuple(sorted(value)) for key, value in contexts.items()}


_SAFE_PATH_CALLEES: frozenset[str] = frozenset(
    {
        # Path / string coercion
        "Path",
        "PurePath",
        "PurePosixPath",
        "PureWindowsPath",
        "str",
        "fspath",
        # File I/O (write-mode open is pattern 1's responsibility)
        "open",
        # Read-only Path / fs queries
        "read_text",
        "read_bytes",
        "exists",
        "is_file",
        "is_dir",
        "is_symlink",
        "stat",
        "lstat",
        "iterdir",
        "glob",
        "rglob",
        "samefile",
        # JSON / pickle read
        "load",
        "loads",
        # os.path read helpers
        "join",
        "dirname",
        "basename",
        "splitext",
        "isfile",
        "isdir",
        "abspath",
        "realpath",
        "normpath",
        "getmtime",
        "getsize",
        "getatime",
        "getctime",
        # Builtins / coercions
        "bool",
        "int",
        "float",
        "len",
        "list",
        "dict",
        "tuple",
        "set",
        "frozenset",
        "sorted",
        "reversed",
        "any",
        "all",
        "max",
        "min",
        "sum",
        # Project read-only helpers
        "_read_json_object",
        "read_json_object",
        "_read_json",
        "_read_json_dict",
        "read_json_dict",
        "_read_json_string_field",
        "_read_path_from_json",
        "marker_signature",
        "_payload_names_include",
        "_has_done_marker",
        "_seed_payload_path",
        # Logging / formatting (marker filenames appear in warning/log strings)
        "print",
        "print_status",
        "format",
        # Wire-type constructors over read-only data
        "AgentArtifactScanOptionsWire",
        "AgentArtifactScanStatsWire",
    }
    | _LIFECYCLE_CALL_NAMES
)


def _arg_carries_marker_construction(arg: ast.expr) -> bool:
    if isinstance(arg, ast.Constant):
        return False
    for node in ast.walk(arg):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(m in node.value for m in _TRACKED_MARKER_LITERALS):
                return True
    return False


def _path_passing_contexts(root: Path = _REPO_ROOT) -> set[str]:
    found: set[str] = set()
    for path in _iter_source_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel_path = path.relative_to(root).as_posix()
        parent_map = _build_parent_map(tree)
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            name = _generic_call_name(call)
            if name is None or name in _SAFE_PATH_CALLEES:
                continue
            args: list[ast.expr] = list(call.args) + [kw.value for kw in call.keywords]
            if not any(_arg_carries_marker_construction(a) for a in args):
                continue
            enclosing = _enclosing_function(call, parent_map)
            if enclosing is None:
                continue
            found.add(f"{rel_path}:{enclosing.name}")
    return found
