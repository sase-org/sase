"""Facade tests for ``sase.plan_search``.

Exercises root resolution (``--source`` mapping, repo/local dir resolution) and
drives the real Rust ``plan_search`` binding end-to-end over a temp repo ``sdd/``
tree plus a temp local archive: query vs browse, kind/status/date filters,
limit, and repo-prioritized ranking.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.sdd_policy_helpers import set_sdd_policy

from sase.plan_search import facade
from sase.sdd.store import write_sdd_store_record


def _write_plan(
    path: Path,
    *,
    title: str,
    status: str,
    create_time: str,
    body: str,
    tier: str = "tale",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntier: {tier}\ncreate_time: {create_time}\nstatus: {status}\n---\n# {title}\n\n{body}\n"
    )


def _write_prompt(
    path: Path,
    *,
    title: str,
    create_time: str,
    body: str,
    plan: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if plan.startswith("["):
        path.write_text(
            f"---\ncreate_time: {create_time}\n---\n\n"
            f"- **PLAN:** {plan}\n\n# {title}\n\n{body}\n"
        )
    else:
        path.write_text(
            f"---\ncreate_time: {create_time}\nplan: '{plan}'\n---\n"
            f"# {title}\n\n{body}\n"
        )


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[Path, Path]:
    """Build a temp repo ``sdd/`` tree and a temp local archive."""
    sdd = tmp_path / "sdd"
    local = tmp_path / "local_plans"

    _write_plan(
        sdd / "plans" / "202606" / "auth_token_refresh.md",
        title="Refresh auth tokens on 401",
        status="wip",
        create_time="2026-06-18 21:29:20",
        body="Retry the request once after refreshing the auth token.",
    )
    _write_plan(
        sdd / "plans" / "202605" / "unified_auth.md",
        title="Unified auth across providers",
        status="done",
        create_time="2026-05-10 09:00:00",
        body="Consolidate the providers behind one interface.",
        tier="epic",
    )
    _write_plan(
        sdd / "plans" / "202601" / "login_flow.md",
        title="Login flow",
        status="wip",
        create_time="2026-01-05 12:00:00",
        body="Document the sign-in steps.",
    )
    _write_plan(
        local / "202604" / "auth_login_fix.md",
        title="Fix login auth race",
        status="done",
        create_time="2026-04-02 08:30:00",
        body="Guard the session write behind a lock.",
    )
    _write_plan(
        local / "flat_note.md",
        title="Flat note",
        status="wip",
        create_time="2026-03-01 00:00:00",
        body="A loose local plan with no shard dir.",
    )
    return sdd, local


def _names(matches: list) -> list[str]:
    return [match.plan.name for match in matches]


def _search(corpus: tuple[Path, Path], **kwargs: object) -> list:
    sdd, local = corpus
    return facade.search(repo_root=sdd, local_dir=local, **kwargs)  # type: ignore[arg-type]


def _patch_sdd_storage(monkeypatch: pytest.MonkeyPatch, storage: str) -> None:
    set_sdd_policy(monkeypatch, storage)


# --- root resolution -----------------------------------------------------


def test_local_plans_dir_honors_sase_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    assert facade._local_plans_dir() == tmp_path / ".sase" / "plans"


def test_local_plans_dir_override_wins() -> None:
    assert facade._local_plans_dir("/custom/plans") == Path("/custom/plans")


def test_repo_sdd_root_resolves_from_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "sdd").mkdir()
    _patch_sdd_storage(monkeypatch, "in_tree")
    assert facade._repo_sdd_root(cwd=tmp_path) == (tmp_path / "sdd").resolve()


def test_repo_sdd_root_resolves_local_store_from_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = tmp_path / ".sase" / "sdd"
    store.mkdir(parents=True)
    _patch_sdd_storage(monkeypatch, "local")

    assert facade._repo_sdd_root(cwd=tmp_path) == store.resolve()


def test_search_uses_resolved_local_sdd_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    local = tmp_path / "local_plans"
    store = repo / ".sase" / "sdd"
    _write_plan(
        store / "plans" / "202607" / "local_store_plan.md",
        title="Local store plan",
        status="wip",
        create_time="2026-07-01 10:00:00",
        body="This plan lives in the resolved SDD store.",
    )
    _patch_sdd_storage(monkeypatch, "local")

    matches = facade.search(
        "resolved",
        source=facade.SOURCE_REPO,
        cwd=repo,
        local_dir=local,
    )

    assert _names(matches) == ["local_store_plan"]


def test_search_indexes_flat_sidecar_plans_root(tmp_path: Path) -> None:
    plans = tmp_path / "repo--plans"
    local = tmp_path / "local"
    _write_plan(
        plans / "202607" / "flat_sidecar.md",
        title="Flat sidecar plan",
        status="wip",
        create_time="2026-07-11 19:00:00",
        body="This plan lives at the plans sidecar root.",
    )

    matches = facade.search(
        "sidecar",
        source=facade.SOURCE_REPO,
        repo_root=plans,
        local_dir=local,
    )

    assert _names(matches) == ["flat_sidecar"]


def test_search_indexes_flat_sidecar_root_with_readme_only_plans_subdir(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "repo--plans"
    local = tmp_path / "local"
    (plans / "plans").mkdir(parents=True)
    (plans / "plans" / "README.md").write_text("generated directory guide\n")
    _write_plan(
        plans / "202607" / "flat_sidecar.md",
        title="Flat sidecar plan",
        status="wip",
        create_time="2026-07-11 19:00:00",
        body="README-only child directories must not shadow flat sidecar plans.",
    )

    assert facade._is_flat_plans_root(plans)

    matches = facade.search(
        "shadow",
        source=facade.SOURCE_REPO,
        repo_root=plans,
        local_dir=local,
    )

    assert _names(matches) == ["flat_sidecar"]


def test_search_treats_monthly_plans_subdir_as_nested_root(tmp_path: Path) -> None:
    root = tmp_path / "sdd"
    local = tmp_path / "local"
    _write_plan(
        root / "202607" / "flat_shadowed.md",
        title="Flat shadowed plan",
        status="wip",
        create_time="2026-07-11 19:00:00",
        body="This flat plan should be ignored once a nested plans root exists.",
    )
    _write_plan(
        root / "plans" / "202608" / "nested_wins.md",
        title="Nested wins plan",
        status="wip",
        create_time="2026-08-01 09:00:00",
        body="The nested plans root remains authoritative.",
    )

    assert not facade._is_flat_plans_root(root)

    matches = facade.search(
        "nested",
        source=facade.SOURCE_REPO,
        repo_root=root,
        local_dir=local,
    )

    assert _names(matches) == ["nested_wins"]


def test_search_discovers_configured_document_sidecars(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sidecars = {
        role: {
            "repo": f"owner/project--{role}",
            "remote_url": f"git@github.com:owner/project--{role}.git",
        }
        for role in ("plans", "research", "designs", "beads")
    }
    write_sdd_store_record(
        workspace,
        {
            "schema_version": 3,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": sidecars,
        },
    )
    sidecar_root = workspace / "sase" / "repos"
    _write_plan(
        sidecar_root / "plans" / "202607" / "canonical.md",
        title="Canonical plan",
        status="wip",
        create_time="2026-07-01 09:00:00",
        body="Canonical plan body.",
    )
    _write_plan(
        sidecar_root / "research" / "202607" / "findings.md",
        title="Research findings",
        status="done",
        create_time="2026-07-02 09:00:00",
        body="Research body.",
        tier="epic",
    )
    _write_plan(
        sidecar_root / "designs" / "interface.md",
        title="Interface design",
        status="wip",
        create_time="2026-07-03 09:00:00",
        body="Custom document role body.",
        tier="epic",
    )
    _write_prompt(
        sidecar_root / "plans" / "202607" / "prompts" / "canonical.md",
        title="Canonical prompt",
        create_time="2026-07-04 09:00:00",
        body="Prompt snapshot body.",
        plan="../canonical.md",
    )

    matches = facade.search(
        source=facade.SOURCE_REPO,
        cwd=workspace,
        local_dir=tmp_path / "local",
    )

    assert {(match.plan.name, match.plan.kind) for match in matches} == {
        ("canonical", "tale"),
        ("findings", "research"),
        ("interface", "designs"),
        ("canonical", "prompt"),
    }
    assert facade.available_kinds(cwd=workspace) == (
        "tale",
        "epic",
        "prompt",
        "designs",
        "research",
    )
    assert _names(
        facade.search(
            source=facade.SOURCE_REPO,
            kinds=["designs"],
            cwd=workspace,
            local_dir=tmp_path / "local",
        )
    ) == ["interface"]
    assert _names(
        facade.search(
            source=facade.SOURCE_REPO,
            kinds=["research"],
            cwd=workspace,
            local_dir=tmp_path / "local",
        )
    ) == ["findings"]
    assert _names(
        facade.search(
            source=facade.SOURCE_REPO,
            kinds=["prompt"],
            cwd=workspace,
            local_dir=tmp_path / "local",
        )
    ) == ["canonical"]


def test_available_kinds_omits_unconfigured_research_sidecar(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_sdd_store_record(
        workspace,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                role: {
                    "repo": f"owner/project--{role}",
                    "remote_url": f"git@github.com:owner/project--{role}.git",
                }
                for role in ("plans", "designs")
            },
        },
    )

    assert facade.available_kinds(cwd=workspace) == (
        "tale",
        "epic",
        "prompt",
        "designs",
    )


@pytest.mark.parametrize("flat", [False, True])
def test_search_indexes_prompt_inventory(tmp_path: Path, flat: bool) -> None:
    repo = tmp_path / ("repo--plans" if flat else "sdd")
    plans_root = repo if flat else repo / "plans"
    plan_label = (
        "../202607/deploy_widget.md" if flat else "../sdd/plans/202607/deploy_widget.md"
    )
    _write_prompt(
        plans_root / "202607" / "prompts" / "deploy_widget.md",
        title="Deploy widget",
        create_time="2026-07-12 09:30:00",
        body="Capture the deployment request.",
        plan=f"[{plan_label}](../deploy_widget.md)",
    )

    matches = facade.search(
        source=facade.SOURCE_REPO,
        kinds=["prompt"],
        repo_root=repo,
        local_dir=tmp_path / "local",
    )

    assert _names(matches) == ["deploy_widget"]
    assert matches[0].plan.source == "repo"
    assert matches[0].plan.kind == "prompt"
    assert matches[0].plan.relpath.endswith("202607/prompts/deploy_widget.md")
    assert matches[0].plan.prompt_link == plan_label
    assert (
        matches[0].plan.body == "# Deploy widget\n\nCapture the deployment request.\n"
    )


def test_prompt_inventory_participates_in_unfiltered_query(tmp_path: Path) -> None:
    sdd = tmp_path / "sdd"
    _write_prompt(
        sdd / "plans" / "202607" / "prompts" / "deploy_widget.md",
        title="Deploy widget",
        create_time="2026-07-12 09:30:00",
        body="Capture the deployment request.",
        plan="plans/202607/deploy_widget.md",
    )

    matches = facade.search(
        "deployment request",
        source=facade.SOURCE_REPO,
        repo_root=sdd,
        local_dir=tmp_path / "local",
    )

    assert _names(matches) == ["deploy_widget"]
    assert matches[0].matched_fields == ["body"]


def test_invalid_source_raises() -> None:
    with pytest.raises(ValueError, match="invalid source"):
        facade.search("auth", source="bogus")


# --- end-to-end search over the temp corpus ------------------------------


def test_query_ranks_repo_above_local(corpus: tuple[Path, Path]) -> None:
    matches = _search(corpus, query="auth")
    # Both repo auth plans outrank the matching local plan (repo boost), and the
    # title+name+path+body hit ranks first.
    assert _names(matches) == [
        "auth_token_refresh",
        "unified_auth",
        "auth_login_fix",
    ]
    assert matches[0].plan.source == "repo"
    assert matches[-1].plan.source == "local"
    assert matches[0].matched_fields == ["title", "name", "path", "body"]


def test_source_repo_excludes_local(corpus: tuple[Path, Path]) -> None:
    matches = _search(corpus, source=facade.SOURCE_REPO)
    assert all(match.plan.source == "repo" for match in matches)
    assert set(_names(matches)) == {
        "auth_token_refresh",
        "unified_auth",
        "login_flow",
    }


def test_source_local_excludes_repo(corpus: tuple[Path, Path]) -> None:
    matches = _search(corpus, source=facade.SOURCE_LOCAL)
    assert all(match.plan.source == "local" for match in matches)
    assert set(_names(matches)) == {"auth_login_fix", "flat_note"}


def test_browse_without_query_sorts_by_recency(
    corpus: tuple[Path, Path],
) -> None:
    matches = _search(corpus)
    assert _names(matches) == [
        "auth_token_refresh",
        "unified_auth",
        "auth_login_fix",
        "flat_note",
        "login_flow",
    ]
    assert all(match.matched_fields == [] for match in matches)


def test_kind_filter_narrows_repo(corpus: tuple[Path, Path]) -> None:
    matches = _search(corpus, source=facade.SOURCE_REPO, kinds=["epic"])
    assert _names(matches) == ["unified_auth"]


def test_status_filter(corpus: tuple[Path, Path]) -> None:
    matches = _search(corpus, statuses=["done"])
    assert set(_names(matches)) == {"unified_auth", "auth_login_fix"}


def test_since_filter_excludes_older_plans(corpus: tuple[Path, Path]) -> None:
    matches = _search(corpus, since="2026-05-01")
    assert _names(matches) == ["auth_token_refresh", "unified_auth"]


def test_until_filter_excludes_newer_plans(corpus: tuple[Path, Path]) -> None:
    matches = _search(corpus, until="2026-04-30")
    assert set(_names(matches)) == {"auth_login_fix", "flat_note", "login_flow"}


def test_limit_caps_results(corpus: tuple[Path, Path]) -> None:
    matches = _search(corpus, limit=2)
    assert _names(matches) == ["auth_token_refresh", "unified_auth"]


def test_no_match_returns_empty(corpus: tuple[Path, Path]) -> None:
    assert _search(corpus, query="nonexistent-needle") == []
