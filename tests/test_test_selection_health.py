"""Unit tests for the selection-health store, correlator, and report.

Everything here runs against a synthetic store under ``tmp_path`` with an
injected ancestry oracle. The point of this phase is to measure whether the
selection heuristic has ever been wrong, so these tests pin the two halves of
that measurement: what gets written, and what the correlator concludes from it.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests._test_selection_health import (
    FULL_SUITE_WORKER_SECONDS,
    count_pre_schema_records,
    find_false_negatives,
    git_ancestor_oracle,
    nodeid_test_file,
    summarize,
)
from tests._test_selection_health_records import load_records
from tests._test_selection_health_report import health_payload, render_report
from tests._test_selection_health_store import (
    KIND_FULL_RUN,
    PROJECT_KEY_ENV,
    RECORD_ENV,
    SASE_HOME_ENV,
    STORE_ENV,
    allocate_record_path,
    full_run_record,
    project_key,
    prune_store,
    record_selection,
    store_directory,
    workspace_identity,
    write_record,
)
from tests._test_selection_health_plugin import (
    FullRunFailureRecorder,
    pytest_configure,
)


NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
#: The default workspace both record kinds claim, so correlation is on unless
#: a test deliberately turns it off.
WORKSPACE = "/workspaces/sase_11"
CHANGED = ("src/sase/alpha.py",)


def _git_init(root: Path, *, remote: str | None) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    if remote is not None:
        subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)


def _manifest(
    *,
    head: str,
    selected: tuple[str, ...] = (),
    escalated: bool = False,
    rules: tuple[str, ...] = ("contract-set-always",),
    duration: float | None = 80.0,
    outcome: str = "passed",
    contexts: dict[str, object] | None = None,
    changed_files: tuple[str, ...] | None = CHANGED,
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema": 2,
        "escalated": escalated,
        "rules_fired": list(rules),
        "selected": list(selected),
        "selected_count": len(selected),
        "universe_count": 2400,
        "baseline": {"head": head, "environment": "digest", "tree_dirty": False},
    }
    if changed_files is not None:
        manifest["changed_files"] = list(changed_files)
    if duration is not None:
        manifest["duration"] = duration
    manifest["outcome"] = outcome
    if contexts is not None:
        manifest["contexts"] = contexts
    return manifest


def _write_selection(
    store: Path,
    manifest: dict[str, object],
    *,
    minute: int = 0,
    workspace: str | None = WORKSPACE,
) -> Path:
    return record_selection(
        store,
        manifest,
        workspace=workspace,
        pid=1000 + minute,
        now=NOW + timedelta(minutes=minute),
    )


def _write_full_run(
    store: Path,
    *,
    head: str,
    failures: tuple[str, ...],
    minute: int = 30,
    workspace: str | None = WORKSPACE,
    changed_files: tuple[str, ...] | None = CHANGED,
) -> Path:
    when = NOW + timedelta(minutes=minute)
    path = allocate_record_path(
        store, KIND_FULL_RUN, head=head, pid=2000 + minute, now=when
    )
    write_record(
        path,
        full_run_record(
            head=head,
            mode="fast",
            failures=failures,
            exit_status=1,
            workspace=workspace,
            changed_files=changed_files,
            now=when,
        ),
    )
    return path


def _linear_ancestry(*commits: str):
    """Every commit is an ancestor of the ones listed after it."""
    order = {commit: index for index, commit in enumerate(commits)}

    def _is_ancestor(ancestor: str, descendant: str) -> bool:
        if ancestor not in order or descendant not in order:
            return False
        return order[ancestor] <= order[descendant]

    return _is_ancestor


# --------------------------------------------------------------------------
# Store location
# --------------------------------------------------------------------------


def test_project_key_matches_the_projectspec_key_for_a_github_remote(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sase_11"
    root.mkdir()
    _git_init(root, remote="https://github.com/sase-org/sase.git")

    assert project_key(root, {}) == "gh_sase-org__sase"


def test_project_key_falls_back_to_the_workspace_stripped_directory_name(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sase_11"
    root.mkdir()
    _git_init(root, remote=None)

    assert project_key(root, {}) == "sase"


def test_project_key_environment_override_wins(tmp_path: Path) -> None:
    assert project_key(tmp_path, {PROJECT_KEY_ENV: "custom"}) == "custom"


def test_store_directory_lives_under_sase_home_by_project(tmp_path: Path) -> None:
    root = tmp_path / "sase_3"
    root.mkdir()
    _git_init(root, remote="git@github.com:sase-org/sase.git")
    home = tmp_path / "home"

    store = store_directory(root, {SASE_HOME_ENV: str(home)})

    assert store == home / "test-selection" / "gh_sase-org__sase"


def test_workspace_identity_is_the_resolved_root(tmp_path: Path) -> None:
    root = tmp_path / "sase_11"
    root.mkdir()
    link = tmp_path / "current"
    link.symlink_to(root)

    assert workspace_identity(link) == str(root.resolve())


def test_store_directory_environment_override_wins(tmp_path: Path) -> None:
    override = tmp_path / "elsewhere"

    assert store_directory(tmp_path, {STORE_ENV: str(override)}) == override


# --------------------------------------------------------------------------
# Writing, pruning, loading
# --------------------------------------------------------------------------


def test_recording_a_selection_writes_a_timestamped_record(tmp_path: Path) -> None:
    path = _write_selection(tmp_path / "store", _manifest(head="a" * 40))

    assert path.name == f"20260805T120000Z-{'a' * 12}-1000.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == "selection"
    assert payload["manifest"]["selected_count"] == 0


def test_pruning_drops_records_past_retention_and_keeps_the_rest(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    old = _write_selection(store, _manifest(head="a" * 40), minute=0)
    recent = record_selection(
        store,
        _manifest(head="b" * 40),
        workspace=WORKSPACE,
        pid=7,
        now=NOW + timedelta(days=29),
    )
    unfamiliar = store / "notes.txt"
    unfamiliar.write_text("hand-written", encoding="utf-8")

    removed = prune_store(store, now=NOW + timedelta(days=31))

    assert removed == [old]
    assert not old.exists()
    assert recent.exists()
    assert unfamiliar.exists()


def test_allocating_a_record_path_prunes_the_store(tmp_path: Path) -> None:
    store = tmp_path / "store"
    stale = _write_selection(store, _manifest(head="a" * 40))

    allocate_record_path(
        store, KIND_FULL_RUN, head="b" * 40, pid=9, now=NOW + timedelta(days=45)
    )

    assert not stale.exists()


def test_loading_records_separates_kinds_and_ignores_junk(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="a" * 40))
    _write_full_run(store, head="b" * 40, failures=("tests/test_x.py::test_y",))
    (store / "20260805T120000Z-cccccccccccc-3.json").write_text(
        "not json", encoding="utf-8"
    )

    records = load_records(store)

    assert len(records.selections) == 1
    assert len(records.full_runs) == 1
    assert records.full_runs[0].failures == ("tests/test_x.py::test_y",)


def test_loading_an_absent_store_is_empty_not_an_error(tmp_path: Path) -> None:
    records = load_records(tmp_path / "missing")

    assert records.selections == ()
    assert records.full_runs == ()


# --------------------------------------------------------------------------
# False-negative detection
# --------------------------------------------------------------------------


def test_a_failure_excluded_by_an_ancestor_selection_is_a_false_negative(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa", selected=("tests/test_kept.py",)))
    _write_full_run(store, head="bbb", failures=("tests/test_missed.py::test_x",))

    found = find_false_negatives(
        load_records(store), is_ancestor=_linear_ancestry("aaa", "bbb")
    )

    assert len(found) == 1
    assert found[0].nodeid == "tests/test_missed.py::test_x"
    assert found[0].test_file == "tests/test_missed.py"
    assert found[0].rules == ("contract-set-always",)
    assert found[0].workspace == WORKSPACE
    assert found[0].selection_changed_files == CHANGED


def test_a_failure_from_another_workspace_is_never_a_false_negative(
    tmp_path: Path,
) -> None:
    # The store is shared across numbered workspaces, and they all sit on the
    # same master HEAD: without this restriction every manifest matches every
    # other workspace's failures, which is the defect this phase fixes.
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa"), workspace="/workspaces/sase_3")
    _write_full_run(
        store,
        head="bbb",
        failures=("tests/test_missed.py::test_x",),
        workspace="/workspaces/sase_11",
    )

    assert not find_false_negatives(
        load_records(store), is_ancestor=_linear_ancestry("aaa", "bbb")
    )


def test_a_full_run_of_a_disjoint_change_is_never_a_false_negative(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa", changed_files=("docs/a.md",)))
    _write_full_run(
        store,
        head="bbb",
        failures=("tests/test_missed.py::test_x",),
        changed_files=("src/sase/beta.py",),
    )

    assert not find_false_negatives(
        load_records(store), is_ancestor=_linear_ancestry("aaa", "bbb")
    )


def test_a_full_run_that_grew_the_scoped_change_set_still_matches(
    tmp_path: Path,
) -> None:
    # Agents commit as they go, so the full run normally sees a superset of
    # what the earlier scoped run over the same change saw.
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa", changed_files=("src/sase/a.py",)))
    _write_full_run(
        store,
        head="bbb",
        failures=("tests/test_missed.py::test_x",),
        changed_files=("src/sase/a.py", "src/sase/b.py"),
    )

    found = find_false_negatives(
        load_records(store), is_ancestor=_linear_ancestry("aaa", "bbb")
    )

    assert [match.nodeid for match in found] == ["tests/test_missed.py::test_x"]


def test_records_without_the_schema_2_identity_are_skipped_and_counted(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa", changed_files=None))
    _write_selection(store, _manifest(head="aaa"), minute=1, workspace=None)
    _write_full_run(
        store,
        head="bbb",
        failures=("tests/test_missed.py::test_x",),
        changed_files=None,
    )
    records = load_records(store)

    assert not find_false_negatives(records, is_ancestor=_linear_ancestry("aaa", "bbb"))
    pre_schema = count_pre_schema_records(records)
    assert (pre_schema.selections, pre_schema.full_runs, pre_schema.total) == (2, 1, 3)


def test_a_selected_failure_is_not_a_false_negative(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa", selected=("tests/test_x.py",)))
    _write_full_run(store, head="bbb", failures=("tests/test_x.py::test_y",))

    assert not find_false_negatives(
        load_records(store), is_ancestor=_linear_ancestry("aaa", "bbb")
    )


def test_an_escalated_selection_can_never_be_a_false_negative(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa", escalated=True, outcome="escalated"))
    _write_full_run(store, head="bbb", failures=("tests/test_x.py::test_y",))

    assert not find_false_negatives(
        load_records(store), is_ancestor=_linear_ancestry("aaa", "bbb")
    )


def test_a_selection_that_is_not_an_ancestor_is_ignored(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="zzz"))
    _write_full_run(store, head="bbb", failures=("tests/test_x.py::test_y",))

    assert not find_false_negatives(
        load_records(store), is_ancestor=_linear_ancestry("aaa", "bbb")
    )


def test_visual_failures_are_never_false_negatives(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa"))
    _write_full_run(
        store,
        head="bbb",
        failures=("tests/ace/tui/visual/test_png.py::test_snapshot",),
    )

    assert not find_false_negatives(
        load_records(store), is_ancestor=_linear_ancestry("aaa", "bbb")
    )


def test_the_git_ancestor_oracle_answers_false_for_unknown_commits(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git_init(root, remote=None)

    assert git_ancestor_oracle(root)("a" * 40, "b" * 40) is False


def test_nodeid_test_file_strips_the_node_part() -> None:
    assert nodeid_test_file("tests/a/test_b.py::TestC::test_d") == "tests/a/test_b.py"
    assert nodeid_test_file("tests/a/test_b.py") == "tests/a/test_b.py"


# --------------------------------------------------------------------------
# Summary and report
# --------------------------------------------------------------------------


def test_summary_reports_coverage_escalation_and_savings(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_selection(
        store,
        _manifest(head="aaa", selected=("tests/test_a.py",), duration=50.0),
        minute=0,
    )
    _write_selection(
        store,
        _manifest(
            head="bbb",
            selected=("tests/test_a.py", "tests/test_b.py", "tests/test_c.py"),
            duration=150.0,
        ),
        minute=1,
    )
    _write_selection(
        store,
        _manifest(head="ccc", escalated=True, rules=("justfile",), duration=0.0),
        minute=2,
    )

    health = summarize(load_records(store), is_ancestor=lambda _a, _b: False)

    assert health.scoped_runs == 3
    assert health.escalated_runs == 1
    assert health.escalation_rate == pytest.approx(1 / 3)
    assert health.median_selected == pytest.approx(2.0)
    assert health.median_duration == pytest.approx(100.0)
    assert health.worker_seconds_saved == pytest.approx(
        2 * FULL_SUITE_WORKER_SECONDS - 200.0
    )
    assert health.rule_histogram == {"contract-set-always": 2, "justfile": 1}
    assert health.universe_count == 2400
    assert health.median_selected_ratio == pytest.approx(2 / 2400)


def test_summary_of_an_empty_store_is_reportable(tmp_path: Path) -> None:
    health = summarize(load_records(tmp_path), is_ancestor=lambda _a, _b: False)

    assert health.scoped_runs == 0
    assert health.escalation_rate is None
    assert "No runs recorded yet." in "\n".join(render_report(health))


def test_report_states_a_clean_bill_of_health_explicitly(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa", selected=("tests/test_a.py",)))

    report = "\n".join(
        render_report(summarize(load_records(store), is_ancestor=lambda _a, _b: False))
    )

    assert "false negatives: 0" in report
    assert "worker-seconds avoided" in report


def test_report_counts_coverage_context_baselines_and_staleness(
    tmp_path: Path,
) -> None:
    """Whether contexts reach real runs is what says if they earn their CI cost."""
    store = tmp_path / "store"
    _write_selection(
        store,
        _manifest(
            head="aaa",
            selected=("tests/test_a.py",),
            contexts={"baseline": "abc123", "stale": False, "selected_count": 3},
        ),
        minute=0,
    )
    _write_selection(
        store,
        _manifest(
            head="bbb",
            selected=("tests/test_b.py",),
            contexts={"baseline": "abc123", "stale": True, "selected_count": 2},
        ),
        minute=1,
    )
    _write_selection(
        store, _manifest(head="ccc", selected=("tests/test_c.py",)), minute=2
    )

    health = summarize(load_records(store), is_ancestor=lambda _a, _b: False)

    assert (health.context_runs, health.context_stale_runs) == (2, 1)
    assert health.context_selected_total == 5
    report = "\n".join(render_report(health))
    assert "runs with a baseline:  2 of 3" in report
    assert "runs on a stale one:   1" in report


def test_report_points_at_the_remedy_when_no_baseline_is_cached(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa", selected=("tests/test_a.py",)))

    report = "\n".join(
        render_report(summarize(load_records(store), is_ancestor=lambda _a, _b: False))
    )

    assert "just refresh-contexts-baseline" in report


def test_report_lists_every_false_negative_and_what_to_do(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa", selected=("tests/test_kept.py",)))
    _write_full_run(store, head="bbb", failures=("tests/test_missed.py::test_x",))

    health = summarize(load_records(store), is_ancestor=_linear_ancestry("aaa", "bbb"))
    report = "\n".join(render_report(health))

    assert "false negatives: 1" in report
    assert "tests/test_missed.py::test_x" in report
    assert "SASE_TEST_SELECTION_DEPTH" in report


def test_report_states_the_matching_rule_whatever_the_count(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa"))

    report = "\n".join(
        render_report(summarize(load_records(store), is_ancestor=lambda _a, _b: False))
    )

    assert "matching rule:" in report
    assert "same workspace" in report
    assert "covers the scoped run's" in report


def test_report_says_how_many_records_predate_the_schema(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa"), workspace=None)
    _write_full_run(store, head="bbb", failures=(), changed_files=None)

    report = "\n".join(
        render_report(summarize(load_records(store), is_ancestor=lambda _a, _b: False))
    )

    assert "2 record(s) predate schema 2" in report
    assert "excluded from correlation" in report


def test_report_flags_a_nodeid_matched_across_unrelated_changes(
    tmp_path: Path,
) -> None:
    # Two scoped runs over different changes, both charged with the same
    # failure: repetition across unrelated change sets reads as a flake.
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa", changed_files=("src/sase/a.py",)))
    _write_selection(
        store,
        _manifest(head="aaa", changed_files=("src/sase/b.py",)),
        minute=1,
    )
    _write_full_run(
        store,
        head="bbb",
        failures=("tests/test_flaky.py::test_x",),
        changed_files=("src/sase/a.py", "src/sase/b.py"),
    )

    health = summarize(load_records(store), is_ancestor=_linear_ancestry("aaa", "bbb"))
    report = "\n".join(render_report(health))

    assert "false negatives: 1 (2 scoped run/failure matches)" in report
    assert "distinct change sets: 2" in report
    assert "suspect a flake before a miss" in report


def test_health_payload_is_machine_readable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _write_selection(store, _manifest(head="aaa", selected=("tests/test_kept.py",)))
    _write_full_run(store, head="bbb", failures=("tests/test_missed.py::test_x",))

    payload = health_payload(
        summarize(load_records(store), is_ancestor=_linear_ancestry("aaa", "bbb"))
    )

    assert json.loads(json.dumps(payload))["false_negatives"][0]["test_file"] == (
        "tests/test_missed.py"
    )


# --------------------------------------------------------------------------
# The full-lane recorder plugin
# --------------------------------------------------------------------------


class _FakeReport:
    def __init__(self, nodeid: str, *, failed: bool) -> None:
        self.nodeid = nodeid
        self.failed = failed


class _FakePluginManager:
    def __init__(self) -> None:
        self.registered: dict[str, object] = {}

    def register(self, plugin: object, name: str) -> None:
        self.registered[name] = plugin


class _FakeConfig:
    def __init__(self) -> None:
        self.pluginmanager = _FakePluginManager()


def test_recorder_writes_only_the_failures_it_saw(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    recorder = FullRunFailureRecorder(
        path,
        head="abc",
        mode="fast",
        workspace=WORKSPACE,
        changed_files=CHANGED,
    )

    for _ in range(2):
        recorder.pytest_runtest_logreport(
            _FakeReport("tests/test_a.py::test_x", failed=True)
        )
    recorder.pytest_runtest_logreport(
        _FakeReport("tests/test_b.py::test_y", failed=False)
    )
    recorder.pytest_collectreport(_FakeReport("tests/test_c.py", failed=True))
    recorder.pytest_sessionfinish(1)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == KIND_FULL_RUN
    assert payload["head"] == "abc"
    assert payload["failures"] == ["tests/test_a.py::test_x", "tests/test_c.py"]
    assert payload["workspace"] == WORKSPACE
    assert payload["changed_files"] == list(CHANGED)


def test_recorder_never_fails_a_run_over_an_unwritable_store(tmp_path: Path) -> None:
    # A directory is not a writable record path; telemetry must swallow that.
    recorder = FullRunFailureRecorder(tmp_path, head=None, mode="fast")

    recorder.pytest_sessionfinish(0)


def test_plugin_registers_a_recorder_and_consumes_the_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record_path = tmp_path / "record.json"
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.setenv(
        RECORD_ENV,
        json.dumps(
            {
                "path": str(record_path),
                "head": "abc",
                "mode": "cov",
                "workspace": WORKSPACE,
                "changed_files": list(CHANGED),
            }
        ),
    )
    config = _FakeConfig()

    pytest_configure(config)

    recorder = config.pluginmanager.registered["sase-selection-health-recorder"]
    assert isinstance(recorder, FullRunFailureRecorder)
    recorder.pytest_sessionfinish(0)
    written = json.loads(record_path.read_text(encoding="utf-8"))
    assert written["workspace"] == WORKSPACE
    assert written["changed_files"] == list(CHANGED)
    # Popped so nested pytest subprocesses cannot overwrite this run's record.
    assert RECORD_ENV not in os.environ


def test_plugin_does_nothing_without_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RECORD_ENV, raising=False)
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    config = _FakeConfig()

    pytest_configure(config)

    assert not config.pluginmanager.registered


def test_plugin_leaves_recording_to_the_xdist_controller(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    monkeypatch.setenv(RECORD_ENV, json.dumps({"path": str(tmp_path / "record.json")}))
    config = _FakeConfig()

    pytest_configure(config)

    assert not config.pluginmanager.registered
