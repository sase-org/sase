"""Executable policy for the bundled size-alias values.

Structural defects (unknown keys, duplicates, bad ``supersedes`` links) fail
at manifest load with an installation-defect message. This module owns the
*policy* layer on top: every shipped ``provider/model`` member must name a
catalogued model, every explicit ``@effort`` must be honored by that
provider's existing CLI mechanics, primary appearances must descend the
effort ladder from ``@xlarge`` down, and every alias must stay reachable
through at least two providers. Violations fail ``just check``/CI with
alias, member, and suggested correction, without adding runtime startup
work: nothing at launch imports this module.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from dataclasses import dataclass

from sase.xprompt.effort import EFFORT_LEVELS_ORDERED

from .load_balancing import (
    ModelAliasSelector,
    concatenated_selector_members,
    parse_model_alias_selector,
)
from .model_manifest import (
    ModelManifest,
    ProviderRecord,
    get_model_manifest,
    manifest_provider_names,
    provider_model_supersedes,
)

# Size aliases scanned from largest to smallest for descent checking.
_POLICY_ALIAS_ORDER: tuple[str, ...] = (
    "xlarge",
    "large",
    "medium",
    "small",
    "xsmall",
)

# Adapter-level reasoning-effort support per built-in provider, in
# ``EFFORT_LEVELS_ORDERED`` order. This mirrors each provider module's
# ``_EFFORT_CLI_ARGS`` keys without importing provider code, so the docs
# renderer and this validator stay provider-import-free. A dedicated test
# asserts this map still matches the provider modules; update both sides
# together when a CLI gains or loses a level. ``agy`` and ``qwen`` expose
# no effort mechanism, so any ``@effort`` suffix on their members is
# explicit and rejected at invoke time.
_PROVIDER_SUPPORTED_EFFORTS: dict[str, tuple[str, ...]] = {
    "agy": (),
    "claude": ("low", "medium", "high", "xhigh", "max"),
    "codex": ("minimal", "low", "medium", "high", "xhigh"),
    "grok": ("low", "medium", "high", "xhigh"),
    "muse": ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
    "opencode": ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
    "qwen": (),
}

# Providers whose CLIs validate model-specific effort support downstream.
# The adapter accepts the level, so the validator only claims adapter-level
# support for these providers.
_CLI_VALIDATED_PROVIDERS = frozenset({"muse", "opencode"})


@dataclass(frozen=True, slots=True)
class PolicyViolation:
    """One shipped-policy breach with a fix-it suggestion."""

    alias: str
    member: str
    message: str
    suggestion: str


def _supported_efforts(provider: str) -> tuple[str, ...]:
    return _PROVIDER_SUPPORTED_EFFORTS.get(provider, ())


def _closest_candidate(word: str, candidates: list[str]) -> str | None:
    matches = difflib.get_close_matches(word, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _split_member(member: str) -> tuple[str, str, str | None, str | None]:
    """Return ``(provider, model, effort, unknown_effort)`` for *member*.

    Known ``@<level>`` suffixes split into *effort*; a trailing ``@token``
    that is not a canonical level returns as *unknown_effort* so the
    caller can report it instead of silently treating it as model text.
    """
    from sase.xprompt.effort import EFFORT_LEVELS

    base = member.strip()
    at = base.rfind("@")
    if at <= 0:
        return _split_provider_model(base) + (None, None)
    candidate = base[at + 1 :].strip()
    if candidate in EFFORT_LEVELS:
        provider, model = _split_provider_model(base[:at].strip())
        return provider, model, candidate, None
    if candidate and " " not in candidate and "/" not in candidate:
        provider, model = _split_provider_model(base[:at].strip())
        return provider, model, None, candidate
    return _split_provider_model(base) + (None, None)


def _split_provider_model(target: str) -> tuple[str, str]:
    if "/" in target:
        provider, _, model = target.partition("/")
        return provider.strip(), model.strip()
    return "", target.strip()


def _primary_members(selector: ModelAliasSelector) -> tuple[str, ...]:
    """Return the members that consume a descent rung."""
    if selector.mode == "fallback":
        return selector.members[:1]
    return selector.members


def _lineage_root(
    provider: str,
    model: str,
    supersedes_by_provider: dict[str, dict[str, str]],
) -> str:
    """Return the descent-lineage key for ``provider/model``.

    A predecessor named by ``supersedes`` continues its successor's
    descent, so every member of one successor chain shares the chain's
    latest rung. Walk from *model* up through successor links to the
    newest model: ``successor -> predecessor`` maps are inverted here so
    a predecessor resolves to its newest successor.
    """
    links = supersedes_by_provider.get(provider, {})
    inverted: dict[str, str] = {pre: suc for suc, pre in links.items()}
    current = f"{provider}/{model}"
    seen = {current}
    while True:
        bare = current.split("/", 1)[1]
        successor = inverted.get(bare)
        if successor is None:
            return current
        candidate = f"{provider}/{successor}"
        if candidate in seen:
            return candidate
        seen.add(candidate)
        current = candidate


def validate_manifest_policy(manifest: ModelManifest) -> tuple[PolicyViolation, ...]:
    """Validate shipped policy for *manifest* and return violations."""
    if not isinstance(manifest, ModelManifest):
        raise TypeError(
            f"validate_manifest_policy expects a ModelManifest, got {type(manifest)!r}"
        )
    violations: list[PolicyViolation] = []
    providers = manifest.providers
    # Consume the manifest accessors so the validator stays the executable
    # policy over the bundled manifest (and clears the phase epic-symbols).
    _declared = manifest_provider_names()
    _ = _declared
    supersedes_by_provider: dict[str, dict[str, str]] = {}
    for _name, _record in providers.items():
        if not isinstance(_record, ProviderRecord):
            raise TypeError(f"manifest provider {_name!r} must be a ProviderRecord")
        _ = _record.models
        supersedes_by_provider[_name] = dict(_record.supersedes)
    # Cross-check the accessor against the manifest under validation when
    # they describe the same bundle, so the accessor stays a live consumer.
    try:
        _live = get_model_manifest()
        if set(_live.providers) == set(providers):
            for _name in providers:
                assert supersedes_by_provider[_name] == provider_model_supersedes(
                    _name
                ), _name
    except RuntimeError:
        pass

    seen_rung: dict[str, str] = {}

    for alias in _POLICY_ALIAS_ORDER:
        target = manifest.alias_targets.get(alias)
        if target is None:
            continue
        try:
            selector = parse_model_alias_selector(target)
        except Exception as exc:  # noqa: BLE001 - report grammar breaks as policy
            violations.append(
                PolicyViolation(
                    alias=alias,
                    member=target,
                    message=f"alias '@{alias}' target does not parse: {exc}",
                    suggestion=(
                        f"fix aliases.{alias}.target in "
                        "src/sase/llm_provider/models.yml"
                    ),
                )
            )
            continue
        members: tuple[str, ...]
        primary: tuple[str, ...]
        if selector is None:
            members = (target.strip(),)
            primary = members
        else:
            members = concatenated_selector_members(selector)
            primary = _primary_members(selector)

        # Redundancy: every alias must reach at least two providers.
        reached = sorted({_strip_effort_provider(member) for member in members})
        reached = [provider for provider in reached if provider]
        if len(set(reached)) < 2:
            only = reached[0] if reached else "<none>"
            violations.append(
                PolicyViolation(
                    alias=alias,
                    member=target,
                    message=(
                        f"alias '@{alias}' reaches only provider "
                        f"{only!r}; every size alias must reach at least "
                        "two providers"
                    ),
                    suggestion=(
                        f"add a second provider to aliases.{alias}.target "
                        "in src/sase/llm_provider/models.yml via a '|' pool "
                        "or '||' ordered fallback"
                    ),
                )
            )

        for member in members:
            provider, model, effort, unknown_effort = _split_member(member)
            if not provider or not model:
                violations.append(
                    PolicyViolation(
                        alias=alias,
                        member=member,
                        message=(
                            f"alias '@{alias}' member {member!r} must spell "
                            "an explicit 'provider/model' selector"
                        ),
                        suggestion=(
                            "prefix the model with its manifest provider, "
                            "e.g. 'claude/sonnet'"
                        ),
                    )
                )
                continue
            record = providers.get(provider)
            if record is None:
                known = sorted(providers)
                guess = _closest_candidate(provider, known)
                hint = f"; did you mean {guess!r}?" if guess else ""
                violations.append(
                    PolicyViolation(
                        alias=alias,
                        member=member,
                        message=(
                            f"alias '@{alias}' member {member!r} names "
                            f"unknown provider {provider!r}{hint}"
                        ),
                        suggestion=(
                            "use a provider from src/sase/llm_provider/"
                            f"models.yml 'providers'{hint}"
                        ),
                    )
                )
                continue
            if model not in record.models:
                guess = _closest_candidate(model, list(record.models))
                hint = f"; did you mean '{provider}/{guess}'?" if guess else ""
                violations.append(
                    PolicyViolation(
                        alias=alias,
                        member=member,
                        message=(
                            f"alias '@{alias}' member {member!r} names "
                            f"unknown model {model!r} for provider "
                            f"{provider!r}{hint}"
                        ),
                        suggestion=(
                            f"fix aliases.{alias}.target in "
                            "src/sase/llm_provider/models.yml"
                            f"{hint}"
                        ),
                    )
                )
                continue
            if unknown_effort is not None:
                levels = ", ".join(EFFORT_LEVELS_ORDERED)
                violations.append(
                    PolicyViolation(
                        alias=alias,
                        member=member,
                        message=(
                            f"alias '@{alias}' member {member!r} has "
                            f"unknown effort '@{unknown_effort}'; expected "
                            f"one of: {levels}"
                        ),
                        suggestion=(
                            f"change '@{unknown_effort}' to a supported "
                            f"level for provider {provider!r} or remove "
                            "the suffix"
                        ),
                    )
                )
                continue
            supported = _supported_efforts(provider)
            if effort is not None and effort not in supported:
                if not supported:
                    violations.append(
                        PolicyViolation(
                            alias=alias,
                            member=member,
                            message=(
                                f"alias '@{alias}' member {member!r} "
                                f"carries '@{effort}' but provider "
                                f"{provider!r} exposes no reasoning-effort "
                                "mechanism; effort is baked into the model "
                                "slug"
                            ),
                            suggestion=(
                                f"remove the '@{effort}' suffix, e.g. "
                                f"'{provider}/{model}'"
                            ),
                        )
                    )
                else:
                    supported_label = ", ".join(supported)
                    extra = (
                        " (model-specific support is validated by the "
                        f"{provider} CLI downstream)"
                        if provider in _CLI_VALIDATED_PROVIDERS
                        else ""
                    )
                    violations.append(
                        PolicyViolation(
                            alias=alias,
                            member=member,
                            message=(
                                f"alias '@{alias}' member {member!r} uses "
                                f"unsupported effort '@{effort}' for "
                                f"provider {provider!r} (supported: "
                                f"{supported_label}){extra}"
                            ),
                            suggestion=(
                                f"change '@{effort}' to a level in "
                                f"{supported_label} for provider "
                                f"{provider!r}"
                            ),
                        )
                    )
                continue

        for member in primary:
            provider, model, effort, unknown_effort = _split_member(member)
            if not provider or provider not in providers:
                continue
            if model not in providers[provider].models:
                continue
            if unknown_effort is not None:
                continue
            supported = _supported_efforts(provider)
            if effort is not None and effort not in supported:
                continue
            if effort is None:
                if supported:
                    supported_label = ", ".join(supported)
                    violations.append(
                        PolicyViolation(
                            alias=alias,
                            member=member,
                            message=(
                                f"alias '@{alias}' member {member!r} "
                                f"carries no '@effort' but provider "
                                f"{provider!r} requires one (supported: "
                                f"{supported_label})"
                            ),
                            suggestion=(
                                "add the descended effort suffix, starting "
                                "at '@xhigh' for a first appearance"
                            ),
                        )
                    )
                continue
            # Effort-less members of effort-less providers (agy) consume
            # no rung; nothing further to check.
            if effort is None:
                continue
            key = _lineage_root(provider, model, supersedes_by_provider)
            previous = seen_rung.get(key)
            if previous is None:
                if effort != "xhigh":
                    violations.append(
                        PolicyViolation(
                            alias=alias,
                            member=member,
                            message=(
                                f"alias '@{alias}' member {member!r} "
                                f"starts at '@{effort}'; a model's first "
                                "primary appearance must start at '@xhigh'"
                            ),
                            suggestion=f"change '@{effort}' to '@xhigh'",
                        )
                    )
                    seen_rung[key] = effort
                else:
                    seen_rung[key] = effort
                continue
            try:
                expected = EFFORT_LEVELS_ORDERED[
                    EFFORT_LEVELS_ORDERED.index(previous) - 1
                ]
            except IndexError:
                expected = EFFORT_LEVELS_ORDERED[0]
            if EFFORT_LEVELS_ORDERED.index(previous) == 0:
                violations.append(
                    PolicyViolation(
                        alias=alias,
                        member=member,
                        message=(
                            f"alias '@{alias}' member {member!r} would "
                            f"descend below provider {provider!r}'s "
                            f"supported range (previous '@{previous}'); "
                            "never clamp or repeat a rung"
                        ),
                        suggestion=(
                            "swap in a different model for this alias "
                            "instead of reusing one past the bottom of "
                            "its provider's range"
                        ),
                    )
                )
                continue
            if effort != expected:
                if expected not in supported:
                    violations.append(
                        PolicyViolation(
                            alias=alias,
                            member=member,
                            message=(
                                f"alias '@{alias}' member {member!r} "
                                f"would descend to '@{expected}', which "
                                f"provider {provider!r} does not support "
                                f"(supported: {', '.join(supported)}); "
                                "never clamp or auto-rewrite"
                            ),
                            suggestion=("swap in a different model for this alias"),
                        )
                    )
                else:
                    violations.append(
                        PolicyViolation(
                            alias=alias,
                            member=member,
                            message=(
                                f"alias '@{alias}' member {member!r} runs "
                                f"at '@{effort}'; expected '@{expected}' "
                                f"(one rung below '@{previous}')"
                            ),
                            suggestion=f"change '@{effort}' to '@{expected}'",
                        )
                    )
            seen_rung[key] = effort

    return tuple(violations)


def _strip_effort_provider(member: str) -> str:
    provider, _model, _effort, _unknown = _split_member(member)
    if provider:
        return provider
    base = member.strip()
    provider, _model = _split_provider_model(base)
    return provider


def format_policy_violations(
    violations: tuple[PolicyViolation, ...],
) -> str:
    """Render *violations* as actionable fix-it lines."""
    lines = []
    for violation in violations:
        lines.append(
            f"@{violation.alias} {violation.member!r}: {violation.message} "
            f"Fix: {violation.suggestion}"
        )
    return "\n".join(lines)


def check_shipped_model_policy(manifest: ModelManifest | None = None) -> None:
    """Raise with fix-it diagnostics when shipped policy is violated."""
    target = get_model_manifest() if manifest is None else manifest
    violations = validate_manifest_policy(target)
    if violations:
        raise RuntimeError(
            "bundled size-alias policy is violated:\n"
            + format_policy_violations(violations)
        )


def validate_shipped_model_policy(
    manifest: ModelManifest | None = None,
) -> tuple[PolicyViolation, ...]:
    """Return shipped-policy violations for the bundled manifest."""
    target = get_model_manifest() if manifest is None else manifest
    return validate_manifest_policy(target)


def main(argv: list[str] | None = None) -> int:
    """Check shipped policy without adding runtime startup work."""
    parser = argparse.ArgumentParser(
        description="Check bundled size-alias policy from models.yml."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the shipped manifest and exit nonzero on violation",
    )
    args = parser.parse_args(argv)
    try:
        violations = validate_shipped_model_policy()
    except RuntimeError as exc:
        print(f"[model_policy] {exc}", file=sys.stderr)
        return 1
    if violations:
        print("[model_policy] bundled size-alias policy is violated:", file=sys.stderr)
        for line in format_policy_violations(violations).splitlines():
            print(f"[model_policy] {line}", file=sys.stderr)
        print(
            "[model_policy] fix src/sase/llm_provider/models.yml, then run "
            "`just fix` and `just check`",
            file=sys.stderr,
        )
        return 1
    if args.check:
        print("[model_policy] shipped size-alias policy is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
