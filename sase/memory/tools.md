---
type: reference
parent: AGENTS.md
description: Read before changing, adding, or vendoring anything under `tools/`.
---

# SASE Tools

Any script under `tools/` whose name ends in `-YYmmdd` (for example `pyscripts-260801`)
was vendored from the chezmoi dotfile repo. Do not edit those files here. Change the
original source in the chezmoi repo, commit it there, then re-vendor with
`basher vendor` or refresh with `basher update` from the `basher` PyPI package.

## `sase_bead`

Thin wrapper that delegates to `sase bead`. It exists for tools (including
[[symvision.md]]) that expect `BD_COMMAND` to be a single executable. Always use
`sase bead` instead of `bd` directly.

## ToolRun smokes

`tools/smoke_sase_core_rs_tool_runs` is an isolated real-binding round trip against the
installed `sase_core_rs` wheel. `tools/smoke_sase_tool_runs` is the black-box harness:
it talks to the real store and CLI for catalog, foreground run, signals, lost-run
recovery, fail-open recording, hand-off, and query contracts. Cases that need the real
monitor/proc supervisors or a cold-start timing measurement are labeled `not-run` unless
`--live` is passed; `--live` runs them too.

Its E3 triage group uses only fixture recipes in an isolated `SASE_HOME`: it proves
all-KNOWN continuation reaches `test (scoped)`, NEW/UNKNOWN stops, exit-code parity and
the missing-`--finish` safety net, retained triage after reaping, and failure grouping.

## Triage backtest

`tools/tool_triage_backtest` replays retained ToolRun logs through the pure triage
bindings. It is read-only with respect to the ledger; its only output is `report.json`
and an `audit.md` worksheet under `--out-dir`. Its added-file metric is per item locator
(not any unrelated scratch path in a run); the report retains the former any-path count
as informational context. The worksheet resolves core witness IDs into run, agent,
workspace, base, and clean-tree evidence, and workspace attribution prefers the ledger
before historical `agent_meta.json` records.
