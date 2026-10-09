---
keyword: Global Install Is Human-Only
aliases:
  [
    global installers refuse in agents,
    install-dev human only,
    SASE_GLOBAL_INSTALL_BYPASS,
  ]
summary:
  just install and just install-dev refuse inside SASE agents and monitors unless
  SASE_GLOBAL_INSTALL_BYPASS holds a reason; agents propose global reinstalls through
  /sase_gate.
metadata:
  status: accepted
  decided: 2026-10-09
---

**Claim.** `just install` and `just install-dev` refuse inside SASE agents and monitors
(exit 2) unless `SASE_GLOBAL_INSTALL_BYPASS` holds a non-empty reason, and agents
propose global reinstalls through `/sase_gate`. When the bypass is used, the installer
prints a one-line note naming the reason. This pairs with [[decisions/guarded-recipes]]:
guarded-recipes routes agent runs into recorded ToolRuns, while this guard protects the
host those runs execute on. Do not edit `guarded-recipes`; this record links it.

**Why.** Both commands replace the global `sase` that every agent and the scheduler
import, so a stray run inside an agent can break every concurrent run and the scheduler.
Rejected alternatives: a banner-only warning still lets the stray run proceed, and
guarding `install-venv` would block the routine workspace repair agents legitimately
need — the venv recipe never touches the global `sase`, so it stays unguarded.

**Cost.** The guard is a guardrail against habit, not a security boundary (clearing the
agent marker variables defeats it; the bypass is deliberately easier). A human running a
global install non-interactively (no TTY) must still pass `-y`.

**Reopens when.** A sandboxed per-agent `sase` exists, so replacing the global install
no longer affects running agents.
