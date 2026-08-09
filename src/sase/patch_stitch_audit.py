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

_EXPECTED_LINKED_REPOS = (
    "sase-core",
    "sase-github",
    "sase-telegram",
    "sase-nvim",
    "chezmoi",
)

_COMPATIBILITY_SHIM_PATHS = frozenset(
    {
        "src/sase/core/changespec.py",
        "src/sase/main/changespec_handler.py",
        "src/sase/main/parser_changespec.py",
        "src/sase/workflows/commit/changespec_operations.py",
        "src/sase/workflows/commit/changespec_queries.py",
        "src/sase/workspace_provider/changespec.py",
    }
)

_DECLARED_COMPATIBILITY_MARKERS = (
    "legacy",
    "compat",
    "alias",
    "deprecated",
    "retained",
    "mixed-version",
    "older supported",
    "backward",
    "fallback",
)

_RETAINED_SERIALIZED_MARKERS = (
    "COMMITS:",
    "## ChangeSpec",
    "CommitEntry",
    "commit_entry",
    "changespec_name",
    "changespec_bug_id",
    "commit_changespec_name",
    "meta_changespec",
    "all_changespecs.json",
    "filtered_changespecs.json",
    "changespec_subcommand",
)

_RETAINED_PUBLIC_MARKERS = (
    "sase.ace.changespec",
    "sase changespec",
    "--changespec",
    "sase_changespecs",
    "/sase_changespecs",
    "docs/change_spec.md",
    "changespec-tags",
    "changespecs-in-practice",
)

_STABLE_PUBLIC_REFERENCE_RE = re.compile(
    r"\b(?:from|import)\s+sase[\w.]*?(?:change_spec|changespec)[\w.]*\b"
    r"|['\"](?:src/|docs/|tests/|tools/|sase/)[^'\"]*"
    r"(?:change_spec|changespec)[^'\"]*['\"]",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _RepoSpec:
    name: str
    root: Path


@dataclass(frozen=True, slots=True)
class _RepoDiscovery:
    repos: tuple[_RepoSpec, ...]
    missing: tuple[str, ...]


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
    predicate: Callable[[str, str, str, str, str], bool]
    required: bool = False


@dataclass(frozen=True, slots=True)
class _AuditReport:
    candidates: tuple[_Candidate, ...]
    stale_rules: tuple[str, ...]
    scanned_repos: tuple[str, ...] = ()
    missing_repos: tuple[str, ...] = ()

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


def _discover_default_repo_specs(repo_root: Path) -> _RepoDiscovery:
    """Return visible maintained repositories plus expected linked repos missing."""
    linked_root = repo_root / "sase" / "repos" / "linked"
    specs = [_RepoSpec("main", repo_root)]
    missing: list[str] = []
    for name in _EXPECTED_LINKED_REPOS:
        root = linked_root / name
        if root.is_dir():
            specs.append(_RepoSpec(name, root))
        else:
            missing.append(name)
    return _RepoDiscovery(tuple(specs), tuple(missing))


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


def _line_contains(line: str, *needles: str) -> bool:
    return any(needle in line for needle in needles)


def _context_contains(context: str, *needles: str) -> bool:
    folded = context.casefold()
    return any(needle.casefold() in folded for needle in needles)


def _declares_compatibility_boundary(context: str) -> bool:
    return _context_contains(context, *_DECLARED_COMPATIBILITY_MARKERS)


def _mentions_retained_serialized_marker(text: str, match: str) -> bool:
    if match in {"COMMITS:"} or match.startswith(("CommitEntry", "commit_entry")):
        return True
    return _context_contains(text, *_RETAINED_SERIALIZED_MARKERS)


def _mentions_retained_public_marker(text: str) -> bool:
    return _context_contains(text, *_RETAINED_PUBLIC_MARKERS) or bool(
        _STABLE_PUBLIC_REFERENCE_RE.search(text)
    )


def _is_compatibility_shim_path(path: str) -> bool:
    return path in _COMPATIBILITY_SHIM_PATHS or path.startswith(
        "src/sase/ace/changespec/"
    )


def _is_audit_contract(
    repo: str, path: str, line: str, match: str, context: str
) -> bool:
    del repo, line, match, context
    return path in {
        "src/sase/patch_stitch_audit.py",
        "tests/test_patch_stitch_terminology_audit.py",
        "tools/audit_patch_stitch_terminology",
    }


def _is_generated_provider_copy(
    repo: str, path: str, line: str, match: str, context: str
) -> bool:
    del line, match, context
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


def _is_immutable_history(
    repo: str, path: str, line: str, match: str, context: str
) -> bool:
    del repo, line, match, context
    return (
        path.endswith("CHANGELOG.md")
        or path.startswith(".beads/")
        or path.startswith("sdd/tales/")
        or path.startswith("docs/blog/posts/")
    )


def _is_stable_documentation_reference(
    repo: str, path: str, line: str, match: str, context: str
) -> bool:
    del repo, match, context
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
    repo: str, path: str, line: str, match: str, context: str
) -> bool:
    del repo, line, match
    if _is_compatibility_shim_path(path):
        return True
    return _declares_compatibility_boundary(context)


def _is_source_legacy_api_boundary(
    repo: str, path: str, line: str, match: str, context: str
) -> bool:
    del line, match, context
    if repo != "main" or not path.startswith("src/sase/"):
        return False
    return _is_compatibility_shim_path(path)


def _is_legacy_serialized_data(
    repo: str, path: str, line: str, match: str, context: str
) -> bool:
    del repo, path, context
    return _mentions_retained_serialized_marker(line, match)


def _is_stable_public_path(
    repo: str, path: str, line: str, match: str, context: str
) -> bool:
    del repo, path, match, context
    return _mentions_retained_public_marker(line)


def _is_compatibility_test_or_fixture(
    repo: str, path: str, line: str, match: str, context: str
) -> bool:
    del repo
    if not (path.startswith("tests/") or path.startswith("smoke/")):
        return False
    return (
        _declares_compatibility_boundary(context)
        or _mentions_retained_serialized_marker(line, match)
        or _mentions_retained_public_marker(line)
    )


def _is_external_legacy_boundary(
    repo: str, path: str, line: str, match: str, context: str
) -> bool:
    if repo not in _EXPECTED_LINKED_REPOS:
        return False
    if _declares_compatibility_boundary(context):
        return True
    if _mentions_retained_serialized_marker(line, match):
        return True
    if _mentions_retained_public_marker(line):
        return True
    if repo == "sase-core":
        return _line_contains(
            line,
            "CHANGESPEC_WIRE_SCHEMA_VERSION",
            "ChangeSpecTag",
            "ChangeSpecWire",
            "ChangespecChildWire",
            "ChangeSpecTagsQuery",
            "JumpToChangeSpec",
            "changespec_metadata",
            "changespec_status",
            "changespec_tags",
            "list_changespec_tags",
            'alias = "changespec"',
            '"changespec"',
            "serde",
        )
    if repo in {"sase-github", "sase-telegram"}:
        return _line_contains(
            line,
            "changespec_tags",
            "_list_changespec_xprompt_tags",
        )
    if repo == "sase-nvim":
        return _line_contains(line, 'kind = "changespec"')
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
        "compatibility_test_or_fixture",
        "legacy-data-test-fixture",
        "Tests and smoke fixtures exercise retained old inputs and public aliases.",
        _is_compatibility_test_or_fixture,
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
)


def _classify_candidate(
    repo: str, path: str, line: str, match: str, context: str | None = None
) -> tuple[str, str, str]:
    """Classify one audited token occurrence."""
    context = line if context is None else context
    for rule in _RULES:
        if rule.predicate(repo, path, line, match, context):
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
        for index, line in enumerate(lines):
            line_number = index + 1
            context = "\n".join(lines[max(0, index - 1) : min(len(lines), index + 2)])
            for match in LEGACY_TOKEN_RE.finditer(line):
                classification, rule, reason = _classify_candidate(
                    repo.name, rel_path, line, match.group(0), context
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


def _audit_repositories(
    repos: Sequence[_RepoSpec], *, missing_repos: Sequence[str] = ()
) -> _AuditReport:
    """Scan repositories and return candidates plus stale required rules."""
    candidates = tuple(
        candidate for repo in repos for candidate in _iter_candidates(repo)
    )
    used_rules = {candidate.rule for candidate in candidates}
    stale_rules = tuple(
        rule.name for rule in _RULES if rule.required and rule.name not in used_rules
    )
    return _AuditReport(
        candidates=candidates,
        stale_rules=stale_rules,
        scanned_repos=tuple(repo.name for repo in repos),
        missing_repos=tuple(missing_repos),
    )


def _retained_report(report: _AuditReport) -> str:
    """Render a concise retained-token summary for handoffs."""
    lines = ["Patch/stitch terminology audit retained-token summary:"]
    scanned = ", ".join(report.scanned_repos) if report.scanned_repos else "(none)"
    lines.append(f"- scanned repos: {scanned}")
    if report.missing_repos:
        lines.append(f"- missing expected repos: {', '.join(report.missing_repos)}")
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
    parser.add_argument(
        "--allow-missing-linked-repos",
        action="store_true",
        help="do not fail when default linked-repo discovery cannot find every expected repo",
    )
    args = parser.parse_args(argv)

    if args.repo:
        repos = tuple(args.repo)
        missing_repos: tuple[str, ...] = ()
    else:
        discovery = _discover_default_repo_specs(args.repo_root)
        repos = discovery.repos
        missing_repos = discovery.missing
    report = _audit_repositories(repos, missing_repos=missing_repos)

    if args.json:
        print(
            json.dumps(
                {
                    "counts_by_classification": report.counts_by_classification,
                    "counts_by_rule": report.counts_by_rule,
                    "missing_repos": list(report.missing_repos),
                    "scanned_repos": list(report.scanned_repos),
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

    missing_repos_error = (
        bool(report.missing_repos) and not args.allow_missing_linked_repos
    )
    return 1 if report.defects or report.stale_rules or missing_repos_error else 0


__all__ = [
    "main",
]
