"""Patch/stitch terminology audit for maintained SASE repositories."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path


LEGACY_TOKEN_RE = re.compile(
    r"(?i:change[-_]?specs?[A-Za-z0-9_-]*)"
    r"|CommitEntry[A-Za-z0-9_]*"
    r"|commit_entry[A-Za-z0-9_]*"
    r"|COMMITS:"
)


@dataclass(frozen=True, slots=True)
class _RepoSpec:
    name: str
    root: Path


@dataclass(frozen=True, slots=True)
class _Candidate:
    repo: str
    path: str
    line: int
    matched: str
    classification: str
    rule: str
    reason: str
    text: str


@dataclass(frozen=True, slots=True)
class _Rule:
    name: str
    classification: str
    reason: str
    predicate: Callable[[str, str, str, str], bool]
    required: bool = False


@dataclass(frozen=True, slots=True)
class _AuditReport:
    candidates: tuple[_Candidate, ...]
    stale_rules: tuple[str, ...]

    @property
    def defects(self) -> tuple[_Candidate, ...]:
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.classification == "defect"
        )

    @property
    def counts_by_classification(self) -> dict[str, int]:
        return dict(Counter(candidate.classification for candidate in self.candidates))

    @property
    def counts_by_rule(self) -> dict[str, int]:
        return dict(Counter(candidate.rule for candidate in self.candidates))


def _default_repo_specs(repo_root: Path) -> tuple[_RepoSpec, ...]:
    """Return the maintained repositories visible from a SASE workspace."""
    linked_root = repo_root / "sase" / "repos" / "linked"
    specs = [_RepoSpec("main", repo_root)]
    for name in ("sase-core", "sase-github", "sase-telegram", "sase-nvim", "chezmoi"):
        root = linked_root / name
        if root.is_dir():
            specs.append(_RepoSpec(name, root))
    return tuple(specs)


def _parse_repo_spec(value: str) -> _RepoSpec:
    """Parse ``NAME=PATH`` CLI values."""
    name, sep, raw_path = value.partition("=")
    if not sep or not name or not raw_path:
        raise argparse.ArgumentTypeError("repo specs must use NAME=PATH")
    return _RepoSpec(name, Path(raw_path).expanduser())


def _tracked_files(root: Path) -> tuple[Path, ...]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return tuple(root / raw.decode("utf-8") for raw in proc.stdout.split(b"\0") if raw)


def _text_lines(path: Path) -> tuple[str, ...] | None:
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return tuple(data.decode("utf-8").splitlines())
    except UnicodeDecodeError:
        return None


def _path_contains(path: str, *needles: str) -> bool:
    return any(needle in path for needle in needles)


def _line_contains(line: str, *needles: str) -> bool:
    return any(needle in line for needle in needles)


def _is_audit_contract(repo: str, path: str, line: str, match: str) -> bool:
    del repo, line, match
    return path in {
        "src/sase/patch_stitch_audit.py",
        "tests/test_patch_stitch_terminology_audit.py",
        "tools/audit_patch_stitch_terminology",
    }


def _is_generated_provider_copy(repo: str, path: str, line: str, match: str) -> bool:
    del line, match
    if repo == "main" and path in {
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        "OPENCODE.md",
        "QWEN.md",
    }:
        return True
    if repo == "chezmoi" and "/skills/" in path:
        return True
    return False


def _is_immutable_history(repo: str, path: str, line: str, match: str) -> bool:
    del repo, line, match
    return (
        path.endswith("CHANGELOG.md")
        or path.startswith(".beads/")
        or path.startswith("sdd/tales/")
        or path.startswith("docs/blog/posts/")
    )


def _is_stable_documentation_reference(
    repo: str, path: str, line: str, match: str
) -> bool:
    del repo, match
    if not (
        path in {"INSTALL.md", "Justfile", "README.md", "mkdocs.yml"}
        or path.startswith("docs/")
        or path.startswith("sase/memory/")
        or path.startswith("src/sase/xprompts/skills/")
    ):
        return False
    return _line_contains(
        line,
        "change_spec",
        "changespec",
        "ChangeSpec",
        "CHANGESPEC",
        "sase_changespecs",
        "changespec-tags",
        "transition_changespec_status",
        "build_changespec_graph_index",
        "find_all_changespecs",
        "all_changespecs.json",
        "filtered_changespecs.json",
    )


def _is_legacy_compatibility_boundary(
    repo: str, path: str, line: str, match: str
) -> bool:
    del repo, match
    if path in {
        "src/sase/core/changespec.py",
        "src/sase/main/changespec_handler.py",
        "src/sase/main/parser_changespec.py",
        "src/sase/workflows/commit/changespec_operations.py",
        "src/sase/workflows/commit/changespec_queries.py",
        "src/sase/workspace_provider/changespec.py",
    }:
        return True
    if path.startswith("src/sase/ace/changespec/"):
        return True
    return _line_contains(
        line,
        "legacy",
        "Legacy",
        "compat",
        "Compat",
        "alias",
        "aliases=",
        "Older supported SASE releases",
        "mixed-version",
        "fallback",
    )


def _is_source_legacy_api_boundary(repo: str, path: str, line: str, match: str) -> bool:
    del repo, line, match
    if path.startswith("tools/"):
        return True
    if not path.startswith("src/sase/"):
        return False
    return path.startswith(
        (
            "src/sase/ace/",
            "src/sase/agent/",
            "src/sase/agents/",
            "src/sase/axe/",
            "src/sase/bead/",
            "src/sase/bug_links.py",
            "src/sase/chops/",
            "src/sase/config/",
            "src/sase/core/",
            "src/sase/doctor/",
            "src/sase/history/",
            "src/sase/integrations/",
            "src/sase/llm_provider/",
            "src/sase/logs/",
            "src/sase/main/",
            "src/sase/notifications/",
            "src/sase/plugins/",
            "src/sase/project_",
            "src/sase/prompt/",
            "src/sase/running_field/",
            "src/sase/scripts/",
            "src/sase/sdd/",
            "src/sase/stats/",
            "src/sase/status_state_machine/",
            "src/sase/vcs_provider/",
            "src/sase/workflows/",
            "src/sase/workspace_provider/",
            "src/sase/xprompt/",
        )
    )


def _is_legacy_serialized_data(repo: str, path: str, line: str, match: str) -> bool:
    del repo, path, match
    return _line_contains(
        line,
        "COMMITS:",
        "commits",
        "CommitEntry",
        "commit_entry",
        "changespec_name",
        "changespec_bug_id",
        "commit_changespec_name",
        "meta_changespec",
        "all_changespecs.json",
        "filtered_changespecs.json",
        "SASE_AGENT_CL_NAME",
        "changespec_subcommand",
        "--changespec",
        "sase changespec",
        "sase_changespecs",
        "sase.ace.changespec",
    )


def _is_stable_public_path(repo: str, path: str, line: str, match: str) -> bool:
    del repo, line, match
    return _path_contains(
        path,
        "changespec",
        "change_spec",
        "sase_changespecs",
        "changespec-tags",
    )


def _is_compatibility_test_or_fixture(
    repo: str, path: str, line: str, match: str
) -> bool:
    del repo, line, match
    return path.startswith("tests/") or path.startswith("smoke/")


def _is_external_legacy_boundary(repo: str, path: str, line: str, match: str) -> bool:
    del match
    if repo in {"sase-core", "sase-github", "sase-telegram", "sase-nvim"}:
        return "changespec" in line.lower() or _line_contains(
            line, "ChangeSpec", "CommitEntry", "commit_entry", "COMMITS:"
        )
    if repo in {"sase-github", "sase-telegram"}:
        return _line_contains(
            line,
            "Older supported SASE releases",
            "legacy",
            "changespec_name",
            "sase.ace.changespec",
            "changespec_tags",
            "_list_changespec_xprompt_tags",
        )
    if repo == "sase-nvim":
        return _line_contains(line, "COMMITS:", 'kind = "changespec"')
    if repo == "sase-core":
        return _line_contains(
            line,
            "ChangeSpecWire",
            "ChangeSpec metadata",
            "changespec_name",
            "changespec_bug_id",
            "commit_changespec_name",
            "commit_entry",
            "COMMITS:",
            "commits",
            "serde",
            'alias = "changespec"',
            '"changespec"',
            "legacy",
            "Legacy",
        ) or path.startswith("crates/sase_core/tests/")
    return False


_RULES: tuple[_Rule, ...] = (
    _Rule(
        "audit_contract",
        "audit-contract",
        "The audit implementation and tests necessarily name the audited tokens.",
        _is_audit_contract,
    ),
    _Rule(
        "generated_provider_copy",
        "generated-provider-copy",
        "Generated provider instruction copies are checked for idempotence, not hand-edited here.",
        _is_generated_provider_copy,
    ),
    _Rule(
        "immutable_history",
        "immutable-history",
        "Changelogs, archived beads, and published historical posts preserve old terminology.",
        _is_immutable_history,
    ),
    _Rule(
        "stable_documentation_reference",
        "stable-public-path",
        "Maintained docs may mention stable legacy file names, routes, tab IDs, and API identifiers.",
        _is_stable_documentation_reference,
    ),
    _Rule(
        "legacy_compatibility_boundary",
        "legacy-compatibility-boundary",
        "Explicit compatibility shims, aliases, and mixed-version adapters retain old names.",
        _is_legacy_compatibility_boundary,
        required=True,
    ),
    _Rule(
        "legacy_serialized_data",
        "legacy-serialized-data",
        "Old wire keys, durable metadata, saved state, command aliases, and fixture headings stay readable.",
        _is_legacy_serialized_data,
        required=True,
    ),
    _Rule(
        "source_legacy_api_boundary",
        "legacy-compatibility-boundary",
        "Existing Python public APIs and host glue retain old identifiers behind canonical imports.",
        _is_source_legacy_api_boundary,
    ),
    _Rule(
        "external_legacy_boundary",
        "legacy-compatibility-boundary",
        "Linked integration/core repositories retain tested mixed-version or wire-schema names.",
        _is_external_legacy_boundary,
    ),
    _Rule(
        "stable_public_path",
        "stable-public-path",
        "Legacy module, command, skill, document, and route paths stay importable/linkable.",
        _is_stable_public_path,
        required=True,
    ),
    _Rule(
        "compatibility_test_or_fixture",
        "legacy-data-test-fixture",
        "Tests and smoke fixtures exercise retained old inputs and public aliases.",
        _is_compatibility_test_or_fixture,
    ),
)


def _classify_candidate(
    repo: str, path: str, line: str, match: str
) -> tuple[str, str, str]:
    """Classify one audited token occurrence."""
    for rule in _RULES:
        if rule.predicate(repo, path, line, match):
            return rule.classification, rule.name, rule.reason
    return (
        "defect",
        "unclassified",
        "Current source/prose should use Patch/stitch terminology.",
    )


def _iter_candidates(repo: _RepoSpec) -> Iterable[_Candidate]:
    """Yield audited token candidates in tracked text files for one repo."""
    root = repo.root.resolve()
    for path in _tracked_files(root):
        lines = _text_lines(path)
        if lines is None:
            continue
        rel_path = path.relative_to(root).as_posix()
        for line_number, line in enumerate(lines, start=1):
            for match in LEGACY_TOKEN_RE.finditer(line):
                classification, rule, reason = _classify_candidate(
                    repo.name, rel_path, line, match.group(0)
                )
                yield _Candidate(
                    repo=repo.name,
                    path=rel_path,
                    line=line_number,
                    matched=match.group(0),
                    classification=classification,
                    rule=rule,
                    reason=reason,
                    text=line.strip(),
                )


def _audit_repositories(repos: Sequence[_RepoSpec]) -> _AuditReport:
    """Scan repositories and return candidates plus stale required rules."""
    candidates = tuple(
        candidate for repo in repos for candidate in _iter_candidates(repo)
    )
    used_rules = {candidate.rule for candidate in candidates}
    stale_rules = tuple(
        rule.name for rule in _RULES if rule.required and rule.name not in used_rules
    )
    return _AuditReport(candidates=candidates, stale_rules=stale_rules)


def _retained_report(report: _AuditReport) -> str:
    """Render a concise retained-token summary for handoffs."""
    lines = ["Patch/stitch terminology audit retained-token summary:"]
    for classification, count in sorted(report.counts_by_classification.items()):
        lines.append(f"- {classification}: {count}")
    if report.defects:
        lines.append(f"- defects: {len(report.defects)}")
    if report.stale_rules:
        lines.append(f"- stale rules: {', '.join(report.stale_rules)}")
    return "\n".join(lines)


def _candidate_to_json(candidate: _Candidate) -> dict[str, object]:
    return asdict(candidate)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit retained legacy Patch/stitch terminology boundaries.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="main repository root used for default linked-repo discovery",
    )
    parser.add_argument(
        "--repo",
        action="append",
        type=_parse_repo_spec,
        default=None,
        help="explicit repo spec NAME=PATH; repeatable",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON findings")
    parser.add_argument(
        "--all",
        action="store_true",
        help="print every retained candidate instead of only defects",
    )
    args = parser.parse_args(argv)

    repos = tuple(args.repo) if args.repo else _default_repo_specs(args.repo_root)
    report = _audit_repositories(repos)

    if args.json:
        print(
            json.dumps(
                {
                    "counts_by_classification": report.counts_by_classification,
                    "counts_by_rule": report.counts_by_rule,
                    "stale_rules": list(report.stale_rules),
                    "defects": [_candidate_to_json(item) for item in report.defects],
                    "candidates": [
                        _candidate_to_json(item) for item in report.candidates
                    ]
                    if args.all
                    else None,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(_retained_report(report))
        for candidate in report.defects if not args.all else report.candidates:
            print(
                f"{candidate.repo}:{candidate.path}:{candidate.line}: "
                f"{candidate.matched}: {candidate.classification} "
                f"({candidate.rule}) {candidate.text}"
            )

    return 1 if report.defects or report.stale_rules else 0


__all__ = [
    "main",
]
