"""Healer relaunch: plan, guard, execute, and preserve evidence.

Facade over the relaunch split: the claim orchestration lives in
:mod:`sase.agent.auto_restart.healer_relaunch_claim`, launcher helpers in
:mod:`sase.agent.auto_restart._healer_relaunch_launcher`, provenance in
:mod:`sase.agent.auto_restart._healer_relaunch_provenance`, and evidence in
:mod:`sase.agent.auto_restart._healer_relaunch_evidence`.
"""

from __future__ import annotations

from sase.agent.auto_restart.healer_relaunch_claim import relaunch_claimed

__all__ = [
    "relaunch_claimed",
]
