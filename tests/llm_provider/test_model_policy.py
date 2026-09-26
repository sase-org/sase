"""Executable policy for the bundled size-alias values.

The shipped catalog stays data-driven through ``models.yml``: these tests
assert the validator's contract (membership, effort support and descent,
redundancy, diagnostics) with synthetic manifests, plus one test that the
shipped bundle itself is valid. Behavioral product claims (Muse
contributor inclusion, Antigravity placement) stay in their dedicated
test modules, not in the generic validator rules.
"""

from __future__ import annotations

import yaml  # type: ignore[import-untyped]

from sase.llm_provider import model_manifest, model_policy
from sase.llm_provider.model_policy import (
    PolicyViolation,
    format_policy_violations,
    validate_manifest_policy,
    validate_shipped_model_policy,
)


def _parse(data: dict) -> model_manifest.ModelManifest:
    return model_manifest._parse_model_manifest(
        yaml.safe_dump(data, sort_keys=False),
        source="test policy manifest",
    )


def _base_manifest(
    aliases: dict[str, str] | None = None,
    providers: dict | None = None,
) -> model_manifest.ModelManifest:
    default_providers = {
        "claude": {
            "models": ["c-large", "c-small"],
            "tiers": {"large": "c-large", "small": "c-small"},
        },
        "codex": {
            "models": ["x-big", "x-small"],
            "tiers": {"large": "x-big", "small": "x-small"},
        },
        "grok": {
            "models": ["g-7", "g-6"],
            "tiers": {"large": "g-7", "small": "g-6"},
        },
    }
    default_aliases = {
        "xlarge": {
            "target": "claude/c-large@xhigh || codex/x-big@xhigh",
            "description": "xlarge.",
        },
        "large": {
            "target": "claude/c-large@high | codex/x-big@xhigh",
            "description": "large.",
        },
        "medium": {
            "target": "claude/c-small@xhigh | codex/x-small@xhigh",
            "description": "medium.",
        },
        "small": {
            "target": "claude/c-small@high | codex/x-small@high",
            "description": "small.",
        },
        "xsmall": {
            "target": "claude/c-small@medium | codex/x-small@medium",
            "description": "xsmall.",
        },
    }
    if aliases is not None:
        for name, target in aliases.items():
            default_aliases[name] = {"target": target, "description": f"{name}."}
    return _parse(
        {
            "schema_version": 1,
            "providers": providers or default_providers,
            "aliases": default_aliases,
        }
    )


def _messages(violations: tuple[PolicyViolation, ...]) -> str:
    return format_policy_violations(violations)


def test_shipped_policy_is_valid(real_model_alias_defaults: None) -> None:
    assert validate_shipped_model_policy() == ()


def test_shipped_grok_predecessor_continues_descent(
    real_model_alias_defaults: None,
) -> None:
    manifest = model_manifest.get_model_manifest()
    assert manifest.providers["grok"].supersedes.get("grok-4.7") == "grok-4.6"
    assert validate_shipped_model_policy() == ()


def test_typo_names_member_and_suggests_correction() -> None:
    manifest = _base_manifest({"medium": "claude/c-larg@xhigh | codex/x-small@xhigh"})
    violations = validate_manifest_policy(manifest)
    assert any(
        violation.alias == "medium"
        and "c-larg" in violation.member
        and "c-large" in violation.message
        for violation in violations
    )
    assert "Fix:" in _messages(violations)


def test_unsupported_effort_names_supported_levels() -> None:
    manifest = _base_manifest({"medium": "claude/c-small@xhigh | codex/x-small@max"})
    violations = validate_manifest_policy(manifest)
    assert any(
        "codex/x-small@max" in violation.member
        and "unsupported effort" in violation.message
        and "minimal, low, medium, high, xhigh" in violation.message
        for violation in violations
    )


def test_agy_effort_suffix_is_rejected() -> None:
    providers = {
        "agy": {
            "models": ["flash-high"],
            "tiers": {"large": "flash-high", "small": "flash-high"},
        },
        "claude": {
            "models": ["c-small"],
            "tiers": {"large": "c-small", "small": "c-small"},
        },
    }
    aliases = {
        "xlarge": "claude/c-small@xhigh || agy/flash-high",
        "large": "claude/c-small@high | agy/flash-high",
        "medium": "claude/c-small@medium | agy/flash-high",
        "small": "claude/c-small@low | agy/flash-high",
        "xsmall": "claude/c-small@low | agy/flash-high@high",
    }
    manifest = _base_manifest(dict(aliases), providers=providers)
    violations = validate_manifest_policy(manifest)
    assert any(
        "agy/flash-high@high" in violation.member
        and "no reasoning-effort mechanism" in violation.message
        and "remove the '@high' suffix" in violation.suggestion
        for violation in violations
    )


def test_wrong_rung_suggests_expected_effort() -> None:
    manifest = _base_manifest({"small": "claude/c-small@xhigh | codex/x-small@high"})
    violations = validate_manifest_policy(manifest)
    assert any(
        violation.alias == "small"
        and "c-small@xhigh" in violation.member
        and "'@high'" in violation.message
        for violation in violations
    )


def test_supersedes_predecessor_continues_descent() -> None:
    providers = {
        "grok": {
            "models": ["g-7", "g-6"],
            "supersedes": {"g-7": "g-6"},
            "tiers": {"large": "g-7", "small": "g-6"},
        },
        "claude": {
            "models": ["c-large", "c-small"],
            "tiers": {"large": "c-large", "small": "c-small"},
        },
    }
    manifest = _base_manifest(
        {
            "xlarge": "claude/c-large@xhigh || grok/g-7@xhigh",
            "large": "grok/g-7@xhigh | claude/c-large@high",
            "medium": "grok/g-6@high | claude/c-small@xhigh",
            "small": "grok/g-6@medium | claude/c-small@high",
            "xsmall": "grok/g-6@low | claude/c-small@medium",
        },
        providers=providers,
    )
    assert validate_manifest_policy(manifest) == ()


def test_supersedes_restart_is_rejected() -> None:
    providers = {
        "grok": {
            "models": ["g-7", "g-6"],
            "supersedes": {"g-7": "g-6"},
            "tiers": {"large": "g-7", "small": "g-6"},
        },
        "claude": {
            "models": ["c-large", "c-small"],
            "tiers": {"large": "c-large", "small": "c-small"},
        },
    }
    manifest = _base_manifest(
        {
            "xlarge": "claude/c-large@xhigh || grok/g-7@xhigh",
            "large": "grok/g-7@xhigh | claude/c-large@high",
            "medium": "grok/g-6@xhigh | claude/c-small@xhigh",
            "small": "grok/g-6@medium | claude/c-small@high",
            "xsmall": "grok/g-6@low | claude/c-small@medium",
        },
        providers=providers,
    )
    violations = validate_manifest_policy(manifest)
    assert any(
        "grok/g-6@xhigh" in violation.member and "'@high'" in violation.message
        for violation in violations
    )


def test_broken_supersedes_link_fails_at_load() -> None:
    data = {
        "schema_version": 1,
        "providers": {
            "claude": {
                "models": ["c-large"],
                "supersedes": {"c-large": "missing-model"},
                "tiers": {"large": "c-large", "small": "c-large"},
            },
            "codex": {
                "models": ["x-big"],
                "tiers": {"large": "x-big", "small": "x-big"},
            },
        },
        "aliases": {
            name: {"target": "claude/c-large", "description": f"{name}."}
            for name in ("xsmall", "small", "medium", "large", "xlarge")
        },
    }
    try:
        _parse(data)
    except RuntimeError as exc:
        assert "installation defect" in str(exc)
    else:  # pragma: no cover - loader must reject unknown supersedes
        raise AssertionError("broken supersedes link loaded without error")


def test_single_provider_alias_is_rejected() -> None:
    manifest = _base_manifest({"large": "claude/c-large@high"})
    violations = validate_manifest_policy(manifest)
    assert any(
        violation.alias == "large"
        and "at least two providers" in violation.message
        and "'|' pool" in violation.suggestion
        for violation in violations
    )


def test_non_primary_fallback_members_do_not_consume_rungs() -> None:
    manifest = _base_manifest(
        {
            "xlarge": "claude/c-large@xhigh || codex/x-big@xhigh",
            "large": "codex/x-big@xhigh | claude/c-large@high",
            "medium": "claude/c-small@xhigh | codex/x-small@xhigh",
            "small": "claude/c-small@high | codex/x-small@high",
            "xsmall": "claude/c-small@medium | codex/x-small@medium",
        }
    )
    # codex/x-big appears as a non-primary @xhigh in @xlarge, then again
    # as a primary @xhigh in @large: no rung consumed, no violation.
    assert validate_manifest_policy(manifest) == ()


def test_descent_below_supported_range_is_rejected_not_clamped() -> None:
    manifest = _base_manifest(
        {
            "xlarge": "grok/g-7@xhigh || claude/c-large@xhigh",
            "large": "grok/g-7@high | claude/c-large@high",
            "medium": "grok/g-7@medium | claude/c-small@xhigh",
            "small": "grok/g-7@low | claude/c-small@high",
            "xsmall": "grok/g-7@low | claude/c-small@medium",
        }
    )
    violations = validate_manifest_policy(manifest)
    assert any(
        "grok/g-7" in violation.member
        and ("below" in violation.message or "swap in" in violation.suggestion)
        for violation in violations
    )


def test_supported_efforts_match_provider_cli_mechanics() -> None:
    """The validator's support map must track each provider's CLI args.

    Capability lists live in provider Python code, never in YAML; this
    test fails when a provider gains or loses a level without updating
    ``model_policy._PROVIDER_SUPPORTED_EFFORTS`` alongside it. Muse and
    OpenCode adapter support is intentionally broader than per-model CLI
    acceptance, which the validator states instead of over-claiming.
    """
    from sase.llm_provider import agy, claude, codex, grok, muse, opencode, qwen

    expected = {
        "agy": (),
        "claude": tuple(sorted(claude._EFFORT_CLI_ARGS, key=_rung_index)),
        "codex": tuple(sorted(codex._EFFORT_CLI_ARGS, key=_rung_index)),
        "grok": tuple(sorted(grok._EFFORT_CLI_ARGS, key=_rung_index)),
        "muse": tuple(sorted(muse._EFFORT_CLI_ARGS, key=_rung_index)),
        "opencode": tuple(sorted(opencode._EFFORT_CLI_ARGS, key=_rung_index)),
        "qwen": (),
    }
    assert agy.AgyProvider is not None
    assert qwen.QwenProvider is not None
    assert model_policy._PROVIDER_SUPPORTED_EFFORTS == expected


def _rung_index(level: str) -> int:
    from sase.xprompt.effort import EFFORT_LEVELS_ORDERED

    return EFFORT_LEVELS_ORDERED.index(level)
