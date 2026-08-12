"""Glob-criterion filters shared by external-mirror issue and PR selection.

Follows ``fileHookFilters``'s pattern language (``wcmatch.glob.globmatch``
under ``DOTGLOB | GLOBSTAR | NEGATE | NEGATEALL``, plus ``IGNORECASE`` since
matching here is case-folded) but evaluates positives and negatives
explicitly rather than relying on a single ``NEGATE`` pass. See
:func:`_evaluate_glob_criterion` for why: ``label_globs`` runs against a
multi-valued field, and OR-ing per-value ``NEGATE`` results across labels
would let one non-matching label clear an exclusion that should apply.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from sase.vcs_provider._types import IssueWire, PullRequestWire

#: Separators chosen to avoid ambiguity with glob characters that may appear
#: in configured patterns (commas, pipes, etc. are all valid glob text).
_VALUE_SEP = "\x1f"
_CRITERION_SEP = "\x1e"


def _glob_flags() -> int:
    from wcmatch import glob

    return glob.DOTGLOB | glob.GLOBSTAR | glob.NEGATE | glob.NEGATEALL | glob.IGNORECASE


def _matches_pattern(pattern: str, value: str) -> bool:
    from wcmatch import glob

    return glob.globmatch(value, pattern, flags=_glob_flags())


def _evaluate_glob_criterion(
    patterns: tuple[str, ...], values: tuple[str, ...]
) -> bool:
    """Return whether *values* pass one ``*_globs`` criterion.

    A record matches if it matches any positive glob (or the criterion has no
    positive globs) and matches no ``!``-prefixed glob. This single rule is
    correct for both single- and multi-valued fields: rejection is "some
    value matches some negative", not "the values, taken together, clear
    every negative" the way a single per-value ``NEGATE`` pass OR-ed across
    values would compute it.
    """
    if not patterns:
        return True
    positives = tuple(p for p in patterns if not p.startswith("!"))
    negatives = tuple(p[1:] for p in patterns if p.startswith("!"))
    if any(
        _matches_pattern(pattern, value) for pattern in negatives for value in values
    ):
        return False
    if not positives:
        return True
    return any(
        _matches_pattern(pattern, value) for pattern in positives for value in values
    )


def _evaluate_state_criterion(states: tuple[str, ...], value: str) -> bool:
    """Case-folded exact membership; an empty criterion accepts everything."""
    if not states:
        return True
    return value.casefold() in {state.casefold() for state in states}


def _fingerprint(criteria: dict[str, tuple[str, ...]]) -> str:
    canonical = _CRITERION_SEP.join(
        f"{key}={_VALUE_SEP.join(criteria[key])}" for key in sorted(criteria)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IssueFilters:
    """Filter criteria applied to :class:`IssueWire` records."""

    author_globs: tuple[str, ...] = ()
    label_globs: tuple[str, ...] = ()
    title_globs: tuple[str, ...] = ()
    states: tuple[str, ...] = ()

    def matches(self, issue: IssueWire) -> bool:
        return (
            _evaluate_glob_criterion(self.author_globs, (issue.author,))
            and _evaluate_glob_criterion(self.label_globs, issue.labels)
            and _evaluate_glob_criterion(self.title_globs, (issue.title,))
            and _evaluate_state_criterion(self.states, issue.state)
        )

    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "author_globs": self.author_globs,
                "label_globs": self.label_globs,
                "title_globs": self.title_globs,
                "states": self.states,
            }
        )


@dataclass(frozen=True)
class PullRequestFilters:
    """Filter criteria applied to :class:`PullRequestWire` records."""

    author_globs: tuple[str, ...] = ()
    base_ref_globs: tuple[str, ...] = ()
    head_ref_globs: tuple[str, ...] = ()
    title_globs: tuple[str, ...] = ()
    states: tuple[str, ...] = ()

    def matches(self, remote: PullRequestWire) -> bool:
        return (
            _evaluate_glob_criterion(self.author_globs, (remote.author,))
            and _evaluate_glob_criterion(self.base_ref_globs, (remote.base_ref,))
            and _evaluate_glob_criterion(self.head_ref_globs, (remote.head_ref,))
            and _evaluate_glob_criterion(self.title_globs, (remote.title,))
            and _evaluate_state_criterion(self.states, remote.state)
        )

    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "author_globs": self.author_globs,
                "base_ref_globs": self.base_ref_globs,
                "head_ref_globs": self.head_ref_globs,
                "title_globs": self.title_globs,
                "states": self.states,
            }
        )


__all__ = ["IssueFilters", "PullRequestFilters"]
