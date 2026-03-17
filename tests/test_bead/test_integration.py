"""Integration tests for beads end-to-end workflows."""

from __future__ import annotations

import json
import subprocess

import pytest

from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject


@pytest.fixture
def project(tmp_path):
    """Create a fresh BeadProject in a temp directory."""
    with BeadProject.init(tmp_path) as proj:
        yield proj


# --- 1. Full epic lifecycle ---


class TestEpicLifecycle:
    def test_full_lifecycle(self, project):
        """init -> create epic -> create children -> update -> close children -> close epic."""
        # Create epic
        epic = project.create(
            "Auth rewrite", IssueType.PLAN, description="Rewrite auth"
        )
        assert epic.status == Status.OPEN
        assert epic.issue_type == IssueType.PLAN

        # Create children
        c1 = project.create("Add OAuth", IssueType.PHASE, parent_id=epic.id)
        c2 = project.create("Write tests", IssueType.PHASE, parent_id=epic.id)
        c3 = project.create("Update docs", IssueType.PHASE, parent_id=epic.id)

        # Verify children are linked
        children = project.get_epic_children(epic.id)
        assert len(children) == 3
        assert {c.id for c in children} == {c1.id, c2.id, c3.id}

        # Update statuses
        project.update(c1.id, status="in_progress", assignee="alice")
        c1_updated = project.show(c1.id)
        assert c1_updated.status == Status.IN_PROGRESS
        assert c1_updated.assignee == "alice"

        # Close children one by one
        project.close([c1.id], reason="shipped")
        c1_closed = project.show(c1.id)
        assert c1_closed.status == Status.CLOSED
        assert c1_closed.close_reason == "shipped"
        assert c1_closed.closed_at is not None

        # Close remaining children in batch
        project.close([c2.id, c3.id])

        # Verify all children closed
        all_children = project.get_epic_children(epic.id)
        assert all(c.status == Status.CLOSED for c in all_children)

        # Close epic
        project.close([epic.id], reason="all children done")
        epic_closed = project.show(epic.id)
        assert epic_closed.status == Status.CLOSED

        # Stats reflect final state
        stats = project.stats()
        assert stats["total"] == 4
        assert stats["closed"] == 4
        assert stats.get("open", 0) == 0


# --- 2. Dependency chains ---


class TestDependencyChains:
    def test_chain_a_b_c(self, project):
        """Create chain A->B->C, verify blocked/ready at each step."""
        epic = project.create("Epic", IssueType.PLAN)
        a = project.create("Task A", IssueType.PHASE, parent_id=epic.id)
        b = project.create("Task B", IssueType.PHASE, parent_id=epic.id)
        c = project.create("Task C", IssueType.PHASE, parent_id=epic.id)

        # B depends on A, C depends on B
        project.add_dependency(b.id, a.id)
        project.add_dependency(c.id, b.id)

        # Initially: only epic and A are ready, B and C are blocked
        ready_ids = {i.id for i in project.ready()}
        assert a.id in ready_ids
        assert epic.id in ready_ids
        assert b.id not in ready_ids
        assert c.id not in ready_ids

        blocked_ids = {i.id for i in project.blocked()}
        assert b.id in blocked_ids
        assert c.id in blocked_ids

        # Close A -> B becomes ready, C still blocked
        project.close([a.id])
        ready_ids = {i.id for i in project.ready()}
        assert b.id in ready_ids
        assert c.id not in ready_ids

        blocked_ids = {i.id for i in project.blocked()}
        assert c.id in blocked_ids
        assert b.id not in blocked_ids

        # Close B -> C becomes ready
        project.close([b.id])
        ready_ids = {i.id for i in project.ready()}
        assert c.id in ready_ids
        assert {i.id for i in project.blocked()} == set()

    def test_diamond_dependency(self, project):
        """Diamond: D depends on B and C, both depend on A."""
        epic = project.create("Epic", IssueType.PLAN)
        a = project.create("A", IssueType.PHASE, parent_id=epic.id)
        b = project.create("B", IssueType.PHASE, parent_id=epic.id)
        c = project.create("C", IssueType.PHASE, parent_id=epic.id)
        d = project.create("D", IssueType.PHASE, parent_id=epic.id)

        project.add_dependency(b.id, a.id)
        project.add_dependency(c.id, a.id)
        project.add_dependency(d.id, b.id)
        project.add_dependency(d.id, c.id)

        # Only A and epic are ready
        ready_ids = {i.id for i in project.ready()}
        assert ready_ids == {epic.id, a.id}

        # Close A -> B and C become ready, D still blocked
        project.close([a.id])
        ready_ids = {i.id for i in project.ready()}
        assert b.id in ready_ids
        assert c.id in ready_ids
        assert d.id not in ready_ids

        # Close B only -> D still blocked by C
        project.close([b.id])
        assert d.id not in {i.id for i in project.ready()}
        assert d.id in {i.id for i in project.blocked()}

        # Close C -> D becomes ready
        project.close([c.id])
        assert d.id in {i.id for i in project.ready()}


# --- 3. JSONL round-trip ---


class TestJsonlRoundTrip:
    def test_delete_db_reconstruct_from_jsonl(self, project):
        """Create issues, delete SQLite, reconstruct from JSONL, verify identical state."""
        epic = project.create(
            "Round-trip epic", IssueType.PLAN, description="testing round-trip"
        )
        c1 = project.create("Child 1", IssueType.PHASE, parent_id=epic.id)
        c2 = project.create("Child 2", IssueType.PHASE, parent_id=epic.id)
        project.add_dependency(c2.id, c1.id)
        project.update(c1.id, status="in_progress", assignee="bob")
        project.close([c1.id], reason="done")

        # Capture state before
        issues_before = project.list_issues()
        issues_before.sort(key=lambda i: i.id)

        # Delete SQLite files
        db_path = project.beads_dir / "beads.db"
        for suffix in ("", "-shm", "-wal"):
            p = db_path.parent / (db_path.name + suffix)
            if p.exists():
                p.unlink()

        # Reopen project (triggers JSONL rebuild)
        with BeadProject(project.root_dir) as proj2:
            issues_after = proj2.list_issues()
            issues_after.sort(key=lambda i: i.id)

            # Same number of issues
            assert len(issues_after) == len(issues_before)

            # Compare each issue
            for before, after in zip(issues_before, issues_after, strict=True):
                assert before.id == after.id
                assert before.title == after.title
                assert before.status == after.status
                assert before.issue_type == after.issue_type
                assert before.parent_id == after.parent_id
                assert before.description == after.description

            # Verify dependency survived
            c2_after = proj2.show(c2.id)
            dep_targets = [d.depends_on_id for d in c2_after.dependencies]
            assert c1.id in dep_targets

    def test_jsonl_format_is_valid_json(self, project):
        """Each line in issues.jsonl is valid JSON."""
        project.create("E1", IssueType.PLAN)
        project.create("E2", IssueType.PLAN)

        jsonl_path = project.beads_dir / "issues.jsonl"
        lines = jsonl_path.read_text().strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            data = json.loads(line)
            assert "id" in data
            assert "title" in data
            assert "status" in data

    def test_jsonl_sorted_by_id(self, project):
        """JSONL entries are sorted by issue ID."""
        for i in range(5):
            project.create(f"Epic {i}", IssueType.PLAN)

        jsonl_path = project.beads_dir / "issues.jsonl"
        lines = jsonl_path.read_text().strip().splitlines()
        ids = [json.loads(line)["id"] for line in lines]
        assert ids == sorted(ids)


# --- 4. Concurrent workspaces ---


class TestConcurrentWorkspaces:
    def test_two_instances_interleaved(self, tmp_path):
        """Two BeadProject instances interleaved: create on one, reload other."""
        with BeadProject.init(tmp_path):
            pass

        with BeadProject(tmp_path) as proj1:
            e1 = proj1.create("From proj1", IssueType.PLAN)

            # Second instance loads after first created (gets updated counter)
            with BeadProject(tmp_path) as proj2:
                e2 = proj2.create("From proj2", IssueType.PLAN)

                # IDs must be different
                assert e1.id != e2.id

                # Both instances see both issues via shared SQLite WAL
                issues1 = proj1.list_issues()
                issues2 = proj2.list_issues()

                ids1 = {i.id for i in issues1}
                ids2 = {i.id for i in issues2}
                assert e1.id in ids1
                assert e2.id in ids2
                assert e1.id in ids2  # proj2 sees proj1's issue too

    def test_counter_isolation(self, tmp_path):
        """Two instances don't produce duplicate IDs in sequence."""
        with BeadProject.init(tmp_path) as proj:
            e1 = proj.create("E1", IssueType.PLAN)
            e2 = proj.create("E2", IssueType.PLAN)
            e3 = proj.create("E3", IssueType.PLAN)

            all_ids = [e1.id, e2.id, e3.id]
            assert len(all_ids) == len(set(all_ids)), "IDs must be unique"


# --- 5. Git sync workflow ---


class TestGitSyncWorkflow:
    @pytest.fixture
    def git_project(self, tmp_path):
        """Create a git repo with beads initialized."""
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        # Initial commit so git has a HEAD
        (tmp_path / ".gitignore").write_text("*.db\n*.db-shm\n*.db-wal\n")
        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        with BeadProject.init(tmp_path) as proj:
            yield proj

    def test_sync_commits_jsonl(self, git_project):
        """Create issues, sync, verify JSONL committed."""
        git_project.create("Test epic", IssueType.PLAN)
        git_project.sync()

        # Check git log for sync commit
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=git_project.root_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "beads: sync issues" in result.stdout

    def test_sync_is_clean_after_sync(self, git_project):
        """After sync, sync_is_clean returns True."""
        # First sync to get JSONL tracked by git
        git_project.sync()
        assert git_project.sync_is_clean()

        # Create an issue — JSONL changes are now detectable
        git_project.create("Epic", IssueType.PLAN)
        assert not git_project.sync_is_clean()

        git_project.sync()
        assert git_project.sync_is_clean()

    def test_sync_no_op_when_clean(self, git_project):
        """Sync with no changes doesn't create a commit."""
        # First sync to establish baseline (commits the empty JSONL)
        git_project.sync()
        result_before = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=git_project.root_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        # Second sync with no changes
        git_project.sync()
        result_after = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=git_project.root_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result_before.stdout.strip() == result_after.stdout.strip()


# --- 6. Edge cases ---


class TestEdgeCases:
    def test_empty_project(self, project):
        """Empty project has no issues, ready returns empty, stats are zero."""
        assert project.list_issues() == []
        assert project.ready() == []
        assert project.blocked() == []
        stats = project.stats()
        assert stats.get("total", 0) == 0

    def test_close_already_closed(self, project):
        """Closing an already-closed issue succeeds (idempotent)."""
        epic = project.create("Epic", IssueType.PLAN)
        project.close([epic.id])
        # Close again — should not raise
        closed = project.close([epic.id])
        assert closed[0].status == Status.CLOSED

    def test_show_nonexistent_raises(self, project):
        """Showing a nonexistent issue raises KeyError."""
        with pytest.raises(KeyError, match="not-real"):
            project.show("not-real")

    def test_close_nonexistent_raises(self, project):
        """Closing a nonexistent issue raises KeyError."""
        with pytest.raises(KeyError):
            project.close(["not-real"])

    def test_missing_beads_dir(self, tmp_path):
        """Opening a project without .beads/ raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            BeadProject(tmp_path)

    def test_phase_requires_parent(self, project):
        """Creating a phase without parent_id raises ValueError."""
        with pytest.raises(ValueError):
            project.create("Orphan phase", IssueType.PHASE)

    def test_plan_with_parent_is_valid(self, project):
        """Creating a plan with parent_id succeeds (sub-plan)."""
        e1 = project.create("E1", IssueType.PLAN)
        e2 = project.create("E2", IssueType.PLAN, parent_id=e1.id)
        assert e2.parent_id == e1.id
        assert e2.issue_type == IssueType.PLAN

    def test_doctor_reports_healthy(self, project):
        """Doctor on a fresh project reports OK."""
        messages = project.doctor()
        assert any("OK" in m for m in messages)

    def test_update_multiple_fields(self, project):
        """Update multiple fields in a single call."""
        epic = project.create("Original", IssueType.PLAN, description="old desc")
        updated = project.update(
            epic.id,
            title="New Title",
            description="new desc",
            notes="some notes",
            design="some design",
        )
        assert updated.title == "New Title"
        assert updated.description == "new desc"
        assert updated.notes == "some notes"
        assert updated.design == "some design"

    def test_list_filter_combined(self, project):
        """Filter by both status and type simultaneously."""
        epic = project.create("Epic", IssueType.PLAN)
        c1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
        project.create("C2", IssueType.PHASE, parent_id=epic.id)
        project.close([c1.id])

        open_children = project.list_issues(
            status=Status.OPEN, issue_type=IssueType.PHASE
        )
        assert len(open_children) == 1
        assert open_children[0].issue_type == IssueType.PHASE
        assert open_children[0].status == Status.OPEN
