"""Deterministic fake agent CLI used by SASE tests and demos."""

from sase.fakey.scenario import ResolvedScenario, ScenarioError, resolve_scenario

__all__ = ["ResolvedScenario", "ScenarioError", "resolve_scenario"]
