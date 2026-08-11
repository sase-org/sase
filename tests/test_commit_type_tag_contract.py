"""Structural guard for the tracked-commit ``SASE_TYPE=`` provenance invariant.

Every commit SASE creates must carry a ``SASE_TYPE=`` footer tag (see
``sase/memory`` epic ``stitch_origin_badges`` and the classifier this invariant
feeds). This test enumerates every source location that builds a real
``git commit`` invocation with a message argument (``-m``/``-F``/``--amend``)
and requires either evidence, in the same file, of a call to one of the known
commit-tag helpers in ``sase.workflows.commit.runtime_tags``, or an explicit,
commented allowlist entry explaining why the site is still safe.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "sase"

#: Calling any of these anywhere in the same file is treated as evidence that
#: commit messages built in that file are routed through the tag helpers.
_TAG_HELPER_CALL_NAMES = frozenset(
    {
        "apply_runtime_commit_tags",
        "apply_tracked_commit_tags",
        "apply_auto_commit_type_tag",
        "apply_auto_commit_tags",
        "apply_auto_commit_tags_with_runtime",
    }
)

#: Commit-creating call sites with no in-file tag-helper call, and why each is
#: still safe. Fix new hits by routing through a ``runtime_tags`` helper
#: before extending this allowlist.
_ALLOWED_UNTAGGED_COMMIT_SITES = {
    # The commit message is built (and SASE_TYPE stamped) by
    # sase.xprompt.write_targets._commit_push_offer before it ever reaches
    # this file; this only executes the already-tagged message.
    "ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt_git.py:run_git_commit_push_sync",
    # Generic hookspec wrapper with no current callers; any future caller is
    # responsible for tagging the message it supplies.
    "vcs_provider/plugins/_git_core_ops.py:vcs_commit",
    # Generic amend: replaces HEAD's message with whatever the caller
    # supplies. Reword/rewind/accept callers are responsible for preserving
    # an existing footer. See sase-jo.2 PROPOSED FOLLOW-UP for callers that
    # currently build a fresh message instead of preserving one.
    "vcs_provider/plugins/_git_core_ops.py:vcs_amend",
    # Reword replaces the full commit message with caller-supplied text; the
    # ACE reword flow round-trips the existing (tagged) description through
    # an editor, so the footer is preserved unless a human deletes it.
    "vcs_provider/plugins/_git_sync_ops.py:vcs_reword",
    # Appends one KEY=VALUE line to the *existing* full HEAD message fetched
    # via `git log --format=%B`, so any existing footer (including TYPE) is
    # preserved structurally.
    "vcs_provider/plugins/_git_sync_ops.py:vcs_reword_add_tag",
    # `--no-edit`: HEAD's message (and footer) is left untouched.
    "vcs_provider/plugins/_git_commit_dispatch.py:_amend_bead_changes",
    # The tracked `sase stitch create` dispatch target: the payload message is
    # stamped SASE_TYPE=stitch by CommitWorkflow.run() via
    # apply_tracked_commit_tags before dispatch() is called.
    "vcs_provider/plugins/_git_commit_dispatch.py:vcs_create_commit",
    # Deliberately excluded per the stitch-origin-badges plan: PR-branch tags
    # describe the PR body, not a commit. classify_commit_origin's legacy
    # rule 3 (AGENT/BEAD/PLAN present) covers agent-run PRs.
    "vcs_provider/plugins/_git_commit_dispatch.py:vcs_create_pull_request",
}


def test_every_commit_creating_call_site_is_tagged_or_allowlisted() -> None:
    """Fix new hits by tagging the message, not by extending the allowlist."""
    violations, _discovered = _scan_commit_creating_call_sites()
    assert not violations, (
        "commit-creating call site(s) with no SASE_TYPE tag helper in scope:\n"
        + "\n".join(violations)
    )


def test_allowlist_entries_are_all_still_present() -> None:
    """Keep the allowlist from silently accumulating dead entries."""
    _violations, discovered = _scan_commit_creating_call_sites()
    stale = _ALLOWED_UNTAGGED_COMMIT_SITES - discovered
    assert not stale, f"stale allowlist entries, remove them: {sorted(stale)}"


@lru_cache(maxsize=1)
def _scan_commit_creating_call_sites() -> tuple[tuple[str, ...], frozenset[str]]:
    """Return ``(violations, all_discovered_allowlist_keys)``."""
    violations: list[str] = []
    discovered: set[str] = set()
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if '"commit"' not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        sites = _commit_creating_sites(tree)
        if not sites:
            continue
        relpath = path.relative_to(_SRC_ROOT).as_posix()
        file_is_tagged = _calls_tag_helper_anywhere(tree)
        lines = source.splitlines()
        for lineno, symbol in sites:
            key = f"{relpath}:{symbol}"
            discovered.add(key)
            if file_is_tagged or key in _ALLOWED_UNTAGGED_COMMIT_SITES:
                continue
            violations.append(
                f"src/sase/{relpath}:{lineno} ({symbol}): {lines[lineno - 1].strip()}"
            )
    return tuple(violations), frozenset(discovered)


def _commit_creating_sites(tree: ast.AST) -> list[tuple[int, str]]:
    """Return ``(lineno, enclosing_symbol)`` for each ``git commit`` argv list."""
    parents = _ast_parents(tree)
    sites: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.List | ast.Tuple):
            continue
        elts = node.elts
        for index, elt in enumerate(elts):
            if not (isinstance(elt, ast.Constant) and elt.value == "commit"):
                continue
            following = elts[index + 1 : index + 4]
            following_values = [
                item.value for item in following if isinstance(item, ast.Constant)
            ]
            if any(flag in following_values for flag in ("-m", "-F", "--amend")):
                sites.append((node.lineno, _enclosing_symbol(node, parents)))
    return sites


def _calls_tag_helper_anywhere(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name in _TAG_HELPER_CALL_NAMES:
            return True
    return False


def _ast_parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosing_symbol(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return current.name
    return "<module>"
