from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.sdd import plan_refs
from sase.sdd.store import SddStore


def test_resolve_plan_roots_is_store_first_and_deduplicated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_root = tmp_path / "store" / "plans"
    local_root = tmp_path / "local" / "plans"
    calls: list[tuple[str | Path, int]] = []
    store = SimpleNamespace(kind_root=lambda kind: store_root)
    monkeypatch.setattr(
        plan_refs,
        "resolve_sdd_store",
        lambda workspace, number: (
            calls.append((workspace, number)),
            store,
        )[1],
    )
    monkeypatch.setattr(plan_refs, "sase_subdir", lambda _kind: local_root)

    assert plan_refs.resolve_plan_roots(tmp_path / "workspace", 7) == (
        store_root,
        local_root,
    )
    assert calls == [(tmp_path / "workspace", 7)]

    monkeypatch.setattr(plan_refs, "sase_subdir", lambda kind: store_root)
    assert plan_refs.resolve_plan_roots(tmp_path / "workspace", 7) == (store_root,)


def test_parse_and_render_use_rust_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[Any, ...]]] = []

    def require(name: str) -> Any:
        def binding(*args: Any) -> Any:
            calls.append((name, args))
            if name == "plan_reference_parse":
                return {
                    "kind": "plans",
                    "path": "202607/plan.md",
                    "legacy": False,
                    "rendered": "plans:202607/plan.md",
                }
            return "plans:202607/plan.md"

        return binding

    monkeypatch.setattr(plan_refs, "require_rust_binding", require)

    assert plan_refs.parse_plan_reference("plans:202607/plan.md") == (
        plan_refs.ParsedPlanReference(
            kind="plans",
            path="202607/plan.md",
            legacy=False,
            rendered="plans:202607/plan.md",
        )
    )
    assert plan_refs.render_plan_reference("202607/plan.md") == "plans:202607/plan.md"
    assert calls == [
        (
            "plan_reference_parse",
            ("plans:202607/plan.md",),
        ),
        (
            "plan_reference_render",
            ("plans", "202607/plan.md"),
        ),
    ]


def test_canonicalize_and_resolve_use_discovered_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots = (tmp_path / "store", tmp_path / "local")
    calls: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(plan_refs, "resolve_plan_roots", lambda *_: roots)

    def require(name: str) -> Any:
        def binding(*args: Any) -> Any:
            calls.append((name, args))
            if name == "plan_reference_resolution_wire_schema_version":
                return 1
            if name == "plan_reference_canonicalize":
                return "plans:202607/plan.md"
            return {
                "schema_version": 1,
                "status": "missing",
                "resolved_path": None,
                "candidates": [
                    str(roots[0] / "202607/plan.md"),
                    str(roots[1] / "202607/plan.md"),
                ],
            }

        return binding

    monkeypatch.setattr(plan_refs, "require_rust_binding", require)
    plan_path = roots[0] / "202607/plan.md"

    assert (
        plan_refs.canonicalize_plan_reference(
            plan_path,
            workspace_dir=tmp_path,
            workspace_num=4,
        )
        == "plans:202607/plan.md"
    )
    resolution = plan_refs.resolve_plan_reference(
        "plans:202607/plan.md",
        workspace_dir=tmp_path,
        workspace_num=4,
    )
    assert resolution.status == "missing"
    assert resolution.resolved_path is None
    assert resolution.best_path == roots[0] / "202607/plan.md"
    assert calls == [
        (
            "plan_reference_canonicalize",
            (str(plan_path), [str(root) for root in roots]),
        ),
        (
            "plan_reference_resolution_wire_schema_version",
            (),
        ),
        (
            "plan_reference_resolve",
            (
                "plans:202607/plan.md",
                [str(root) for root in roots],
            ),
        ),
    ]


def test_plan_ref_for_store_prefers_canonical_store_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SddStore(
        storage="in_tree",
        sdd_dir=tmp_path / "workspace" / "sdd",
        repo_root=tmp_path / "workspace" / "sdd",
    )
    local_root = tmp_path / "home" / "plans"
    plan_path = store.kind_root("plans") / "202607" / "rollout.md"
    calls: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(plan_refs, "sase_subdir", lambda _kind: local_root)

    def require(name: str) -> Any:
        def binding(*args: Any) -> Any:
            calls.append((name, args))
            path = Path(str(args[0]))
            for raw_root in args[1]:
                root = Path(str(raw_root))
                try:
                    return f"plans:{path.relative_to(root).as_posix()}"
                except ValueError:
                    continue
            return None

        return binding

    monkeypatch.setattr(plan_refs, "require_rust_binding", require)

    assert (
        plan_refs.plan_ref_for_store(
            plan_path,
            store,
            workspace_dir=tmp_path / "workspace",
        )
        == "plans:202607/rollout.md"
    )
    assert calls == [
        (
            "plan_reference_canonicalize",
            (
                str(plan_path.expanduser().resolve(strict=False)),
                [
                    str(store.kind_root("plans").expanduser().resolve(strict=False)),
                    str(local_root.expanduser().resolve(strict=False)),
                ],
            ),
        )
    ]


def test_plan_ref_for_store_keeps_legacy_fallback_for_external_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=tmp_path / "workspace" / "sase" / "repos" / "plans",
        repo_root=tmp_path / "workspace" / "sase" / "repos" / "plans",
    )
    external = tmp_path / "workspace" / "drafts" / "rollout.md"
    monkeypatch.setattr(plan_refs, "sase_subdir", lambda _kind: tmp_path / "local")
    monkeypatch.setattr(
        plan_refs,
        "require_rust_binding",
        lambda _name: lambda *_args: None,
    )

    assert (
        plan_refs.plan_ref_for_store(
            external,
            store,
            workspace_dir=tmp_path / "workspace",
        )
        == "drafts/rollout.md"
    )


def test_canonicalize_with_explicit_roots_deduplicates_and_normalizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "plans"
    plan_path = root / "202607/plan.md"
    calls: list[tuple[str, list[str]]] = []

    def require(name: str) -> Any:
        assert name == "plan_reference_canonicalize"

        def binding(path: str, roots: list[str]) -> str:
            calls.append((path, roots))
            return "plans:202607/plan.md"

        return binding

    monkeypatch.setattr(plan_refs, "require_rust_binding", require)

    assert (
        plan_refs.canonicalize_plan_reference_from_roots(
            plan_path,
            roots=(root, root / "."),
        )
        == "plans:202607/plan.md"
    )
    assert calls == [(str(plan_path), [str(root)])]


def test_resolve_rejects_a_stale_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plan_refs, "resolve_plan_roots", lambda *_: ())
    monkeypatch.setattr(
        plan_refs,
        "require_rust_binding",
        lambda _name: lambda: 99,
    )

    with pytest.raises(RuntimeError, match="wire is stale"):
        plan_refs.resolve_plan_reference(
            "plans:202607/plan.md",
            workspace_dir=tmp_path,
            workspace_num=1,
        )
