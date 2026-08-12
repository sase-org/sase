"""External-mirror filter config checks for ``sase doctor``."""

from __future__ import annotations

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS

#: ``(legacy key, path to its modern criterion, modern criterion's dotted label)``.
_LEGACY_KEYS = (
    (
        "exclude_labels",
        ("issues", "filters", "label_globs"),
        "external_mirror.issues.filters.label_globs",
    ),
    (
        "pr_authors",
        ("pull_requests", "filters", "author_globs"),
        "external_mirror.pull_requests.filters.author_globs",
    ),
)


def check_config_external_mirror() -> DiagnosticCheck:
    """Surface deprecated external_mirror knobs that need migrating (sase-k2.2).

    ``external_mirror.exclude_labels`` and ``external_mirror.pr_authors`` are
    deprecated aliases for ``external_mirror.issues.filters.label_globs`` and
    ``external_mirror.pull_requests.filters.author_globs``. The fold in
    :mod:`sase.external_mirror.config` applies a legacy value only when its
    modern criterion is empty, so a legacy key set alongside a non-empty
    modern criterion is silently ignored today — this check calls that out
    louder than the plain deprecation notice.
    """
    from sase.config.core import load_merged_config

    config = load_merged_config()
    raw_section = config.get("external_mirror")
    section = raw_section if isinstance(raw_section, dict) else {}

    problems: list[dict[str, str]] = []
    for legacy_key, modern_path, modern_label in _LEGACY_KEYS:
        legacy_value = section.get(legacy_key)
        if not isinstance(legacy_value, list) or not legacy_value:
            continue
        modern_value = _nested(section, modern_path)
        if isinstance(modern_value, list) and modern_value:
            problems.append(
                {
                    "key": f"external_mirror.{legacy_key}",
                    "message": (
                        f"external_mirror.{legacy_key} is set alongside a "
                        f"non-empty {modern_label}; the deprecated key is "
                        "ignored because the modern criterion wins once it "
                        f"is non-empty. Remove external_mirror.{legacy_key} "
                        "or merge its entries into the modern criterion."
                    ),
                }
            )
        else:
            problems.append(
                {
                    "key": f"external_mirror.{legacy_key}",
                    "message": (
                        f"external_mirror.{legacy_key} is deprecated; move its "
                        f"entries to {modern_label}."
                    ),
                }
            )

    status: CheckStatus = "WARN" if problems else "OK"
    summary = (
        f"{len(problems)} external mirror filter config issue(s) found"
        if problems
        else "external mirror filter config is current"
    )
    next_steps = (
        (
            "Move deprecated external_mirror.exclude_labels / pr_authors "
            "entries to external_mirror.issues.filters / "
            "external_mirror.pull_requests.filters, then rerun "
            "`sase doctor -C config.external_mirror`.",
        )
        if problems
        else ()
    )

    return DiagnosticCheck(
        id="config.external_mirror",
        group="config",
        status=status,
        title="External mirror filter config",
        summary=summary,
        details=tuple(row["message"] for row in problems)[:MAX_DETAIL_ROWS],
        next_steps=next_steps,
        data={"problems": problems},
    )


def _nested(section: dict, path: tuple[str, ...]) -> object:
    node: object = section
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


__all__ = ["check_config_external_mirror"]
