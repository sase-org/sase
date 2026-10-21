from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from sase.agents_sync import (
    _commit_publication_locked as publication_locked,
    _commit_publication_support as publication_support,
    inventory,
    inventory_sources,
    publication,
    repository_inspection,
)
from sase.agents_sync.git import run_git
from sase.agents_sync.inventory_models import ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord, ProjectTarget, TargetSelection
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from tests.agents_sync.commit_publication_fixtures import setup_target
from tests.agents_sync.inventory_fixtures import (
    git_log,
    make_record,
    make_target,
    write_artifact,
)

_OWNER = AgentOwnerIdentity("alice", "athena")
_IDENTITY = AgentIdentitySnapshot(_OWNER)
_EXTRA_SHA = "ab" * 20
_UNRELATED_SHA = "cc" * 20


@dataclass
class _GitProbe:
    runner: Callable[..., subprocess.CompletedProcess[str]]
    counts: Counter[str]
    commit_lookups: list[str]


def _session_lane_log(local_name: str, sha: str, committed_at: int) -> str:
    return (
        f"{sha}\x00{committed_at}\x00session lane\x00session lane\n\n"
        f"SASE_AGENT=[alice.athena.{local_name}][2]\n\n"
        "[2]: https://github.com/acme/project--agents/blob/main/"
        f"sessions/alice.athena.{local_name}.md\x00"
    )


def _git_probe(
    primary: Path,
    log: str,
    *,
    extra_commits: dict[str, tuple[int, str]] | None = None,
) -> _GitProbe:
    counts: Counter[str] = Counter()
    commit_lookups: list[str] = []
    known = extra_commits or {}
    primary_root = primary.resolve(strict=False)

    def runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network
        counts[op] += 1
        if args[0] == "log":
            return subprocess.CompletedProcess(args, 0, log, "")
        if args[0] == "config":
            return subprocess.CompletedProcess(args, 1, "", "")
        if args[:2] == ["rev-parse", "--show-toplevel"]:
            resolved = cwd.expanduser().resolve(strict=False)
            if resolved == primary_root:
                return subprocess.CompletedProcess(args, 0, f"{primary_root}\n", "")
            return subprocess.CompletedProcess(args, 1, "", "not a repo")
        if args[0] == "show":
            sha = args[-1].strip().lower()
            commit_lookups.append(sha)
            if sha in known:
                committed_at, subject = known[sha]
                return subprocess.CompletedProcess(
                    args, 0, f"{committed_at}\x00{subject}", ""
                )
            return subprocess.CompletedProcess(args, 1, "", "missing")
        if args[0] == "rev-parse" and "--verify" in args:
            sha = args[-1].replace("^{commit}", "").strip().lower()
            commit_lookups.append(f"verify:{sha}")
            if sha in known or len(sha) == 40:
                return subprocess.CompletedProcess(args, 0, f"{sha}\n", "")
            return subprocess.CompletedProcess(args, 1, "", "missing")
        return subprocess.CompletedProcess(args, 1, "", "unused")

    return _GitProbe(runner, counts, commit_lookups)


def _attach_payloads(
    artifact: Path,
    *,
    chat_path: Path | None = None,
    commit_sha: str | None = None,
    cwd: Path | None = None,
) -> None:
    if chat_path is not None:
        meta = json.loads((artifact / "agent_meta.json").read_text(encoding="utf-8"))
        meta["chat_path"] = str(chat_path)
        (artifact / "agent_meta.json").write_text(json.dumps(meta))
        (artifact / "done.json").write_text(
            json.dumps(
                {
                    **json.loads((artifact / "done.json").read_text(encoding="utf-8")),
                    "response_path": str(chat_path),
                }
            )
        )
    if commit_sha is not None and cwd is not None:
        (artifact / "commit_results.json").write_text(
            json.dumps([{"result": commit_sha, "cwd": str(cwd)}])
        )


def _install_records(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: tuple[Path, ...],
    dismissed: tuple[tuple[dict[str, object], str], ...] = (),
) -> None:
    monkeypatch.setattr(
        inventory,
        "_indexed_records",
        lambda _target: (
            tuple(make_record(path, path.name) for path in artifacts),
            [],
        ),
    )
    monkeypatch.setattr(
        inventory, "_dismissed_records", lambda _target, **_kwargs: dismissed
    )


def test_empty_requested_hoods_returns_no_work_without_git(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    calls: list[list[str]] = []

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network, op
        calls.append(args)
        raise AssertionError("scoped empty inventory must not call git")

    result = inventory.build_project_hood_inventory(
        target,
        _IDENTITY,
        git_runner=runner,
        requested_hoods=frozenset(),
    )

    assert result.runs == ()
    assert result.lane_commits == ()
    assert result.diagnostics == ()
    assert calls == []


def test_scoped_inventory_matches_full_selected_hood_and_skips_unrelated_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    artifacts = home / "projects" / "proj" / "artifacts" / "ace-run"
    target = make_target(tmp_path)
    primary = target.primary_checkout
    selected_live = write_artifact(artifacts, "20260723120001", "foo.bar")
    selected_legacy = write_artifact(artifacts, "20260723120002", "foo.legacy")
    selected_member = write_artifact(artifacts, "20260723120003", "foo.crew--code")
    unrelated = write_artifact(artifacts, "20260723120004", "other.agent")
    unrelated_chat = tmp_path / "unrelated-chat.md"
    unrelated_chat.write_text("UNRELATED CHAT\n")
    _attach_payloads(
        unrelated, chat_path=unrelated_chat, commit_sha=_UNRELATED_SHA, cwd=primary
    )
    _attach_payloads(selected_live, commit_sha=_EXTRA_SHA, cwd=primary)
    dismissed = (
        (
            {
                "agent_name": "foo.old",
                "raw_suffix": "20260723110000",
                "status": "DONE",
            },
            "foo-dismissed.json",
        ),
        (
            {
                "agent_name": "other.dismissed",
                "raw_suffix": "20260723110001",
                "status": "DONE",
                "raw_prompt": "UNRELATED DISMISSED PROMPT",
            },
            "other-dismissed.json",
        ),
    )
    _install_records(
        monkeypatch,
        (selected_live, selected_legacy, selected_member, unrelated),
        dismissed,
    )
    history_names = (
        "foo.bar",
        "foo.legacy",
        "foo.crew--code",
        "foo.ghost",
        "other.agent",
        "other.ghost",
    )
    log = git_log(history_names) + _session_lane_log("foo.crew", "e" * 40, 20)
    probe = _git_probe(
        primary,
        log,
        extra_commits={_EXTRA_SHA: (9, "marker"), _UNRELATED_SHA: (8, "unrelated")},
    )
    full = inventory.build_project_hood_inventory(
        target, _IDENTITY, git_runner=probe.runner
    )
    opened: list[str] = []
    marker_dirs: list[str] = []
    real_read = inventory_sources._read_text_bytes
    real_ref = inventory_sources._read_referenced_text
    real_markers = inventory_sources.commit_markers
    real_commit = inventory_sources.commit_record

    def spy_read(path: Path) -> bytes | None:
        opened.append(str(path))
        return real_read(path)

    def spy_ref(*values: object) -> bytes | None:
        opened.extend(str(value) for value in values if value)
        return real_ref(*values)

    def spy_markers(artifact_dir: Path) -> list[dict[str, object]]:
        marker_dirs.append(str(artifact_dir))
        return real_markers(artifact_dir)

    def spy_commit(repo_root: Path, sha: str, git_runner: object, **kwargs: object):
        opened.append(f"commit:{sha}")
        return real_commit(repo_root, sha, git_runner, **kwargs)

    monkeypatch.setattr(inventory_sources, "_read_text_bytes", spy_read)
    monkeypatch.setattr(inventory_sources, "_read_referenced_text", spy_ref)
    monkeypatch.setattr(inventory_sources, "commit_markers", spy_markers)
    monkeypatch.setattr(inventory_sources, "commit_record", spy_commit)

    scoped = inventory.build_project_hood_inventory(
        target,
        _IDENTITY,
        git_runner=probe.runner,
        requested_hoods={"foo"},
    )

    assert {run.local_name for run in scoped.runs} == {
        "foo.bar",
        "foo.legacy",
        "foo.crew--code",
        "foo.old",
        "foo.ghost",
    }
    assert full.hood_runs("foo") == scoped.hood_runs("foo")
    assert full.agent_session_lane_commits("foo") == scoped.agent_session_lane_commits(
        "foo"
    )
    assert "other.agent" not in {run.local_name for run in scoped.runs}
    assert str(unrelated) not in marker_dirs
    assert str(unrelated_chat) not in opened
    assert f"commit:{_UNRELATED_SHA}" not in opened
    assert any(str(selected_live) in path for path in marker_dirs)


def test_unrelated_population_does_not_increase_expensive_git_lookups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    artifacts = home / "projects" / "proj" / "artifacts" / "ace-run"
    target = make_target(tmp_path)
    primary = target.primary_checkout
    selected = write_artifact(artifacts, "20260723120001", "foo.bar")
    _attach_payloads(selected, commit_sha=_EXTRA_SHA, cwd=primary)
    unrelated = tuple(
        write_artifact(artifacts, f"2026072313{index:04d}", f"other.n{index}")
        for index in range(80)
    )
    for artifact in unrelated:
        _attach_payloads(artifact, commit_sha=_UNRELATED_SHA, cwd=primary)
    _install_records(monkeypatch, (selected, *unrelated))
    log = git_log(("foo.bar",))

    def _count(paths: tuple[Path, ...]) -> Counter[str]:
        _install_records(monkeypatch, paths)
        probe = _git_probe(
            primary,
            log,
            extra_commits={_EXTRA_SHA: (9, "marker"), _UNRELATED_SHA: (8, "unrelated")},
        )
        inventory.build_project_hood_inventory(
            target,
            _IDENTITY,
            git_runner=probe.runner,
            requested_hoods={"foo"},
        )
        return probe.counts

    baseline = _count((selected,))
    grown = _count((selected, *unrelated))
    expensive = ("agents_sync.commit_record", "agents_sync.resolve_sha")
    assert all(grown[op] == baseline[op] for op in expensive)
    assert grown["agents_sync.v2_history"] == baseline["agents_sync.v2_history"] == 1


def test_repeated_marker_shas_and_root_aliases_share_one_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    artifacts = home / "projects" / "proj" / "artifacts" / "ace-run"
    target = make_target(tmp_path)
    primary = target.primary_checkout
    alias = tmp_path / "primary-alias"
    alias.symlink_to(primary)
    first = write_artifact(artifacts, "20260723120001", "foo.one")
    second = write_artifact(artifacts, "20260723120002", "foo.two")
    _attach_payloads(first, commit_sha=_EXTRA_SHA, cwd=primary)
    _attach_payloads(second, commit_sha=_EXTRA_SHA, cwd=alias)
    _install_records(monkeypatch, (first, second))
    probe = _git_probe(
        primary,
        git_log(("foo.one", "foo.two")),
        extra_commits={_EXTRA_SHA: (9, "shared marker")},
    )
    result = inventory.build_project_hood_inventory(
        target,
        _IDENTITY,
        git_runner=probe.runner,
        requested_hoods={"foo"},
    )

    assert {run.local_name for run in result.runs} == {"foo.one", "foo.two"}
    assert probe.counts["agents_sync.commit_record"] == 1
    assert probe.counts["agents_sync.resolve_sha"] == 1
    for run in result.runs:
        assert any(commit.sha == _EXTRA_SHA for commit in run.commits)


def test_history_sha_is_reused_without_per_marker_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    artifacts = home / "projects" / "proj" / "artifacts" / "ace-run"
    target = make_target(tmp_path)
    selected = write_artifact(artifacts, "20260723120001", "foo.bar")
    history_sha = f"{1:040x}"
    _attach_payloads(selected, commit_sha=history_sha, cwd=target.primary_checkout)
    _install_records(monkeypatch, (selected,))
    probe = _git_probe(target.primary_checkout, git_log(("foo.bar",)))
    result = inventory.build_project_hood_inventory(
        target,
        _IDENTITY,
        git_runner=probe.runner,
        requested_hoods={"foo"},
    )

    assert result.runs[0].commits[0].sha == history_sha
    assert probe.counts["agents_sync.commit_record"] == 0
    assert probe.counts["agents_sync.resolve_sha"] == 0


def test_dismissed_summaries_are_filtered_before_json_hydration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_path = tmp_path / "foo.json"
    unrelated_path = tmp_path / "other.json"
    selected_path.write_text(json.dumps({"agent_name": "foo.old", "raw_suffix": "1"}))
    unrelated_path.write_text(
        json.dumps({"agent_name": "other.dismissed", "raw_suffix": "2"})
    )
    reads: list[str] = []
    real = inventory_sources._read_json_object

    def spy(path: Path, required: bool = True) -> dict[str, object] | None:
        reads.append(str(path))
        return real(path, required=required)

    monkeypatch.setattr(inventory_sources, "_read_json_object", spy)
    monkeypatch.setattr(
        inventory_sources,
        "load_dismissed_bundle_summaries",
        lambda **_kwargs: [
            SimpleNamespace(
                bundle_path=str(selected_path),
                agent_name="foo.old",
                cl_name="foo.old",
                agent_session=None,
            ),
            SimpleNamespace(
                bundle_path=str(unrelated_path),
                agent_name="other.dismissed",
                cl_name="other.dismissed",
                agent_session=None,
            ),
        ],
    )
    loaded = inventory_sources.dismissed_records(
        make_target(tmp_path),
        identity=_IDENTITY,
        requested_hoods=frozenset({"foo"}),
    )

    assert [source for _raw, source in loaded] == [str(selected_path)]
    assert str(selected_path) in reads
    assert str(unrelated_path) not in reads


def test_publish_agent_hood_builds_inventory_for_that_hood_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def build(
        _target: ProjectTarget,
        _identity: AgentIdentitySnapshot,
        **kwargs: object,
    ) -> ProjectHoodInventory:
        captured.update(kwargs)
        return ProjectHoodInventory(_OWNER, "proj", ())

    monkeypatch.setattr(publication, "build_project_hood_inventory", build)
    with pytest.raises(AgentsSyncFormatError, match="has no publishable runs"):
        publication.publish_agent_hood(
            make_target(tmp_path),
            tmp_path / "sidecar",
            "foo.bar",
            identity=_IDENTITY,
        )

    assert captured["requested_hoods"] == frozenset({"foo"})


def test_commit_drain_passes_selected_hoods_to_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
    monkeypatch.setattr(
        publication_support,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        publication_support, "require_agent_owner_identity", lambda: _OWNER
    )
    captured: dict[str, object] = {}

    def build(*_args: object, **kwargs: object) -> ProjectHoodInventory:
        captured["requested_hoods"] = kwargs.get("requested_hoods")
        return ProjectHoodInventory(_OWNER, "proj", ())

    monkeypatch.setattr(publication_locked, "build_project_hood_inventory", build)
    monkeypatch.setattr(
        "sase.agents_sync.publication_completion.publication_request_fulfilled",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.deferred.restore_deferred_prompt_archives",
        lambda *_args, **_kwargs: {},
    )
    for hood, revision in (("alpha", "a" * 40), ("beta", "b" * 40)):
        enqueue_agent_publication(
            AgentPublicationOutboxItem(
                project_key="proj",
                project="Project",
                local_agent=f"{hood}--code",
                global_agent=f"alice.athena.{hood}--code",
                primary_revision=revision,
                local_hood=hood,
            )
        )

    publication_locked.publish_queued_locked(target, _OWNER, run_git)

    assert captured["requested_hoods"] == frozenset({"alpha", "beta"})


def test_commit_record_reuses_known_and_cached_lookups(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    known = {"a" * 40: CommitRecord("a" * 40, "from history", 1)}
    cache: repository_inspection.CommitRecordCache = {}
    calls: list[str] = []

    def runner(
        _cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        del network
        calls.append(op)
        if args[0] == "show":
            return subprocess.CompletedProcess(args, 0, "3\x00fresh", "")
        if args[0] == "rev-parse":
            return subprocess.CompletedProcess(args, 0, f"{_EXTRA_SHA}\n", "")
        return subprocess.CompletedProcess(args, 1, "", "")

    reused = repository_inspection.commit_record(
        root, "a" * 40, runner, cache=cache, known=known
    )
    first = repository_inspection.commit_record(
        root, _EXTRA_SHA, runner, cache=cache, known=known
    )
    second = repository_inspection.commit_record(
        root, _EXTRA_SHA, runner, cache=cache, known=known
    )

    assert reused == known["a" * 40]
    assert first == second == CommitRecord(_EXTRA_SHA, "fresh", 3)
    assert calls.count("agents_sync.commit_record") == 1
    assert calls.count("agents_sync.resolve_sha") == 1
