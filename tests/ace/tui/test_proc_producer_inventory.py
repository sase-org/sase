"""AST conformance for the ACE proc-producer inventory."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.proc_producer_sites import (
    CallKind,
    INFRASTRUCTURE,
    PRODUCTION_PRODUCERS,
)


@dataclass(frozen=True, slots=True)
class FoundProducerCall:
    """One production submit call discovered by the AST scanner."""

    source_path: str
    function: str
    kind: CallKind
    proc_type: str
    index: int

    @property
    def site_key(self) -> tuple[str, str, str, str, int]:
        return (
            self.source_path,
            self.function,
            self.kind,
            self.proc_type,
            self.index,
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _relpath(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _function_name(node: ast.AST, parents: list[ast.AST]) -> str:
    for parent in reversed(parents):
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return parent.name
    return "<module>"


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _proc_type_from_arg(node: ast.AST | None) -> str:
    literal = _const_str(node)
    if literal is not None:
        return literal
    if isinstance(node, ast.JoinedStr):
        prefix = _const_str(node.values[0]) if node.values else None
        if prefix == "bead-":
            return "bead-*"
        if prefix == "bead-issue-":
            return "bead-issue-*"
        if prefix is not None and prefix.endswith("-"):
            return f"{prefix}*"
        return "dynamic"
    if node is None:
        return "dynamic"
    return "dynamic"


def _proc_type_from_keyword(
    node: ast.Call, name: str, *, name_fallback: bool
) -> str:
    for keyword in node.keywords:
        if keyword.arg != name:
            continue
        literal = _const_str(keyword.value)
        if literal is not None:
            return literal
        if name_fallback and isinstance(keyword.value, ast.Name):
            return keyword.value.id
        return "dynamic"
    return "dynamic"


def _durable_proc_type(node: ast.Call) -> str:
    for keyword in node.keywords:
        if keyword.arg == "proc_type":
            return _proc_type_from_keyword(node, "proc_type", name_fallback=False)
    return _proc_type_from_keyword(node, "operation", name_fallback=True)


def _getattr_target(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Name) or func.id != "getattr":
        return None
    if len(node.args) < 2:
        return None
    return _const_str(node.args[1])


def _scan_production_submit_calls(root: Path | None = None) -> list[FoundProducerCall]:
    """Return every production ACE submit call in ``src/sase``."""
    repo = root or _repo_root()
    src = repo / "src" / "sase" / "ace"
    found: list[FoundProducerCall] = []
    counters: dict[tuple[str, str, str, str], int] = {}
    for path in sorted(src.rglob("*.py")):
        rel = _relpath(path, repo)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        found.extend(_SubmitCallVisitor(rel, counters).collect(tree))
    return found


class _SubmitCallVisitor(ast.NodeVisitor):
    """Collect submit calls while tracking getattr bindings and parents."""

    def __init__(
        self, rel: str, counters: dict[tuple[str, str, str, str], int]
    ) -> None:
        self.rel = rel
        self.counters = counters
        self.parents: list[ast.AST] = []
        self.bound: dict[str, str] = {}
        self.found: list[FoundProducerCall] = []

    def collect(self, tree: ast.AST) -> list[FoundProducerCall]:
        self.visit(tree)
        return self.found

    def generic_visit(self, node: ast.AST) -> None:
        self.parents.append(node)
        super().generic_visit(node)
        self.parents.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        target_attr = _getattr_target(node.value)
        if target_attr in {
            "_submit_durable_proc",
            "_submit_tracked_proc",
            "_submit_proc",
            "_submit_session_worker",
        }:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.bound[target.id] = target_attr
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        target_attr = _getattr_target(node.value) if node.value else None
        if isinstance(node.target, ast.Name) and target_attr in {
            "_submit_durable_proc",
            "_submit_tracked_proc",
            "_submit_proc",
            "_submit_session_worker",
        }:
            self.bound[node.target.id] = target_attr
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        function = _function_name(node, self.parents)
        kind: CallKind | None = None
        proc_type = "dynamic"
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "_submit_durable_proc",
            "_submit_proc",
            "_submit_session_worker",
            "_submit_tracked_proc",
        }:
            proc_type = (
                _durable_proc_type(node)
                if node.func.attr == "_submit_durable_proc"
                else _proc_type_from_arg(node.args[0] if node.args else None)
            )
            if function == "_submit_proc" and node.func.attr == "_submit_tracked_proc":
                kind = "adapter_forward"
                proc_type = "passthrough"
            elif node.func.attr == "_submit_durable_proc":
                kind = "direct_submit_durable"
            elif node.func.attr == "_submit_proc":
                kind = "direct_submit_proc"
            elif node.func.attr == "_submit_session_worker":
                kind = "session_worker"
            else:
                kind = "direct_submit_tracked"
        elif isinstance(node.func, ast.Name) and node.func.id in self.bound:
            target_attr = self.bound[node.func.id]
            if target_attr == "_submit_durable_proc":
                kind = "duck_submit_durable"
                proc_type = _durable_proc_type(node)
            elif target_attr == "_submit_session_worker":
                kind = "session_worker"
                proc_type = _proc_type_from_arg(node.args[0] if node.args else None)
            else:
                kind = "duck_submit"
                proc_type = _proc_type_from_arg(node.args[0] if node.args else None)
        if kind is not None:
            key = (self.rel, function, kind, proc_type)
            index = self.counters.get(key, 0)
            self.counters[key] = index + 1
            self.found.append(
                FoundProducerCall(
                    source_path=self.rel,
                    function=function,
                    kind=kind,
                    proc_type=proc_type,
                    index=index,
                )
            )
        self.generic_visit(node)


def _inventoried_call_keys() -> list[tuple[str, str, str, str, int]]:
    """Return inventory keys for production producer calls, including indexes."""
    counters: dict[tuple[str, str, str, str], int] = {}
    keys: list[tuple[str, str, str, str, int]] = []
    for site in PRODUCTION_PRODUCERS:
        if site.kind in {"definition", "ui_worker"}:
            continue
        key4 = (site.source_path, site.function, str(site.kind), site.proc_type)
        index = counters.get(key4, 0)
        counters[key4] = index + 1
        keys.append((*key4, index))
    return keys


def _compare_inventory_to_source() -> tuple[
    list[FoundProducerCall], list[tuple[str, str, str, str, int]], list[str]
]:
    """Return found calls, missing inventory keys, and duplicate site ids."""
    found = _scan_production_submit_calls()
    expected = _inventoried_call_keys()
    found_keys = [item.site_key for item in found]
    missing = [key for key in expected if key not in found_keys]
    unexpected = [item for item in found if item.site_key not in expected]
    seen_ids: set[str] = set()
    duplicates: list[str] = []
    for site in (*PRODUCTION_PRODUCERS, *INFRASTRUCTURE):
        if site.site_id in seen_ids:
            duplicates.append(site.site_id)
        seen_ids.add(site.site_id)
    return unexpected, missing, duplicates


def test_inventory_matches_live_production_source() -> None:
    unexpected, missing, duplicates = _compare_inventory_to_source()

    assert not duplicates, f"duplicate inventory site ids: {duplicates}"
    assert not missing, f"stale inventory entries not found in source: {missing}"
    assert not unexpected, (
        "unlisted or structurally changed production producers: "
        f"{[item.site_key for item in unexpected]}"
    )


def test_inventory_allows_only_the_adapter_forwarding_edge() -> None:
    found = _scan_production_submit_calls()
    forwards = [item for item in found if item.kind == "adapter_forward"]

    assert len(forwards) == 1
    assert forwards[0].source_path.endswith("proc_actions.py")
    assert forwards[0].function == "_submit_proc"
    assert (
        sum(1 for site in PRODUCTION_PRODUCERS if site.kind == "adapter_forward") == 1
    )


def test_inventory_records_infrastructure_and_classifications() -> None:
    assert any(site.site_id == "infra.proc_queue" for site in INFRASTRUCTURE)
    assert any(site.site_id == "infra.proc_mirror" for site in INFRASTRUCTURE)
    assert any(site.function == "_submit_durable_proc" for site in INFRASTRUCTURE)
    assert any(
        site.classification == "ui_only" and site.site_id == "prompt.stash"
        for site in PRODUCTION_PRODUCERS
    )
    durable = [
        site for site in PRODUCTION_PRODUCERS if site.classification == "durable"
    ]
    assert durable
    assert len(PRODUCTION_PRODUCERS) == 37
