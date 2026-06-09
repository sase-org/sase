---
create_time: 2026-06-09
updated_time: 2026-06-09
status: research
---

# `sase doctor` Command Research

## Research Request

Would a top-level `sase doctor` command be useful for troubleshooting SASE? If so, what should it check, what should it
output, and what solution should SASE implement?

## Executive Summary

Yes. `sase doctor` would be useful, but its value is consolidation and prioritization, not inventing a new validation
suite. SASE already has useful health signals spread across subsystem commands:

- `sase version -j` reports the active host/core/plugin package inventory.
- `sase core health -j` validates `sase_core_rs` import plus parser, launch-planning, and bead binding probes.
- `sase init -c` checks AMD, memory, SDD, and skills initialization drift.
- `sase validate` runs init drift plus SDD validation.
- `sase plugin doctor -j` checks plugin resource loading, configured chops, GitHub CLI/auth when relevant, and Telegram
  prerequisites when Telegram chops are installed.
- `sase agents index status -j`, `sase workspace list --json`, `sase project list --json`, `sase bead doctor`,
  `sase memory episodes doctor`, and `sase telemetry status/health` expose useful subsystem health, but require users
  to know which subsystem to inspect.

There is no single command today that answers the support question users actually have: "Is my SASE install and current
workspace healthy enough for normal use, and if not, what do I fix?"

The recommended command should be a fast, read-only, top-level aggregator. It should run the highest-value readiness
checks by default, emit grouped human output, expose stable JSON for support and scripts, and preserve deeper repair or
state-inspection commands as subsystem-specific next steps.

This also directly satisfies the readiness gap identified in
[`sase_install_use_understand_readiness_consolidated.md`](./sase_install_use_understand_readiness_consolidated.md): a
single readiness path that reports versions, Rust-core status, init drift, provider CLI availability, and plugin
environment guidance.

## Prior Art

Doctor-style commands are common in CLIs with external dependencies, local state, or project-specific setup.

| Tool | What its doctor/check surface does | Lesson for SASE |
| --- | --- | --- |
| [Homebrew `brew doctor`](https://docs.brew.sh/Manpage#doctor-dr---list-checks---audit-debug-diagnostic_check-) | Checks the system for potential problems, can list individual checks, and exits non-zero when problems are found. Homebrew also cautions that warnings are support diagnostics, not always user-blocking. | Use stable check IDs, support running individual checks, and distinguish optional warnings from blockers. |
| [npm `npm doctor`](https://docs.npmjs.com/cli/v8/commands/npm-doctor/) | Checks environment prerequisites such as executable tools, registry reachability, writable directories, and cache integrity because many issues are outside npm itself. | Check PATH/config/state/provider prerequisites, not just Python imports. |
| [Flutter `flutter doctor`](https://docs.flutter.dev/reference/flutter-cli) | Shows installed tooling; install and bug-report docs ask users to run verbose doctor output. | Make `sase doctor -v` the first support artifact requested from users. |
| [Expo Doctor](https://docs.expo.dev/develop/tools/#expo-doctor) | Runs from the project root and checks config, package metadata, dependency compatibility, and project health. | Include both global runtime checks and current-project checks with next-step commands. |
| [React Native Doctor](https://reactnative.dev/blog/2019/11/18/react-native-doctor.html) | Helps with getting started and troubleshooting, checks required platform tools, can offer fixes, and links to manual repair guidance. | A future `--repair` is useful, but the MVP should first emit precise manual next steps. |
| [pnpm `pnpm doctor`](https://pnpm.io/cli/doctor) | Checks known common pnpm configuration issues. | Keep the default command scoped to known failure modes; avoid turning it into broad lint/test. |

The common pattern is not "doctor runs everything." The pattern is "doctor collects setup and state facts a maintainer
needs before debugging."

## Current SASE Evidence

I verified these commands in this workspace on 2026-06-09:

| Existing command | Result in this workspace | Reuse in `sase doctor` |
| --- | --- | --- |
| `sase core health -j` | `status=ok`; `sase_core_rs` loaded; all four probes passed: `parse_query`, `agent_launch_wire_schema_version`, `plan_agent_launch_fanout`, `bead_cli_execute`. | Default `runtime.core` check. `ERROR` if unhealthy. |
| `sase version -j` | Host `sase` and `sase-core-rs` both editable, both with source roots and git metadata; Python 3.12.11. | Default `runtime.version` and support-bundle metadata. |
| `sase init -c` | Initialized; checked `amd`, `memory`, `sdd`, and `skills`. | Default `config.init` check. |
| `sase validate` | `ok init --check`; `ok sdd validate`. | Default SDD validation or summarized by `config.init` plus `project.sdd`. |
| `sase plugin doctor -j` | Overall `WARN`: plugin resources OK, configured chops OK, unconfigured `pushgateway_cleanup`, missing Telegram env vars, `pass` available. | Default plugin/chop check; preserve optional `WARN` behavior. |
| `sase agents index status -j` | Index exists, schema version 3, 4313 visible rows, no repair recommended, `sase agents index gc` listed as repair command. | Default lightweight `state.agent_index` check. Full verify belongs in `--deep`. |
| `sase workspace list --json` | Current `sase` project uses `xdg-state`; listed checkouts exist; output is large. | Default should summarize registry health only; verbose mode can include counts and root paths. |
| `sase project list --json` | `sase` and `bob-cli` active; current `sase` project has active claims and no parse warnings. | Default current-project lifecycle/workspace check. |
| `sase bead doctor` | `OK: no issues found`. | Run only when bead storage exists in the current project. |
| `sase memory episodes doctor -p sase -j` | `OK`: build state valid, index has rows, no abandoned temp dirs. | Useful, but project-specific. Put in `--deep` by default. |
| `sase telemetry status` | Telemetry enabled, Pushgateway reachable, exposition running. | Default operational reachability check when telemetry is enabled. |
| `sase telemetry health -j` | `critical` due recent metrics: Axe errors and agent/LLM warning-rate thresholds. | Do not run by default; it reflects recent workload health, not install readiness. Include under `--deep` or `--ops`. |

Source-level review also found several diagnostic commands with different output and exit-code conventions:

| Command | Scope | Output | Source |
| --- | --- | --- | --- |
| `sase core health` | Rust binding import plus backend probes | Text / `-j` | `src/sase/core/health.py` |
| `sase plugin doctor` | Plugin resources, chops, `gh`, Telegram env, `pass` | Rich / `-j` | `src/sase/plugins/doctor.py` |
| `sase validate` | `init --check` plus `sdd validate` | Text | `src/sase/main/validate_handler.py` |
| `sase telemetry health` | Recent Prometheus subsystem health | Rich / `-j` | `src/sase/telemetry/cli_health.py` |
| `sase telemetry status` | Telemetry enablement and endpoint reachability | Rich | `src/sase/telemetry/cli_status.py` |
| `sase bead doctor` | Bead project state | Text | `src/sase/bead/cli_admin.py` |
| `sase memory episodes doctor` | Episode index/build/orphan checks, optional repair | Text / `-j` | `src/sase/memory/episodes/_auto_build_doctor.py` |
| `sase version` | Runtime package inventory | Rich / `-j` | `src/sase/main/version_handler.py` |

There is no top-level `doctor` registration in `src/sase/main/parser.py` today. Existing diagnostic commands are useful,
but fragmented enough that users cannot easily provide one support artifact.

## Why It Would Be Useful

### 1. The troubleshooting surface is fragmented

Today a user must already know which subsystem failed:

- Rust failure: `sase core health`
- Plugin/chop failure: `sase plugin doctor`
- First-run drift: `sase init -c` or `sase validate`
- TUI load/index issue: `sase agents index status` or `sase agents index verify`
- Workspace issue: `sase workspace list`, `sase workspace repair`, or `sase workspace cleanup`
- Memory episode issue: `sase memory episodes doctor`
- Telemetry issue: `sase telemetry status` or `sase telemetry health`

A top-level command creates one support reflex: run `sase doctor -v` for humans or attach `sase doctor -j` for machines.

### 2. SASE has many runtime preconditions

Normal SASE use can fail because of:

- Missing, stale, or ABI-incompatible `sase_core_rs`.
- Python below the supported `>=3.12` range.
- A stale ephemeral workspace environment where `just install` has not refreshed the checkout.
- Missing LLM provider CLIs such as `claude`, `gemini`, `codex`, `qwen`, or `opencode`.
- A configured provider that differs from the provider auto-detection would choose.
- Missing or misconfigured `git`, `git user.name`, or `git user.email` for VCS flows.
- Missing `gh` auth when GitHub integration is in use.
- Config layering surprises between built-in defaults, plugin defaults, user config, overlays, and local `sase.yml`.
- Invalid YAML that falls back to defaults and therefore looks like a different configuration problem later.
- Unwritable `$SASE_HOME` or workspace roots.
- Broken project metadata, missing workspace paths, active claims, or workspace registry rows.
- Stale agent artifact index state.
- Optional telemetry, bead, episode, mobile, render-tool, or Telegram setup.

These are exactly the categories where doctor commands help: dependencies, PATH, config, state, and current-project
context.

### 3. SASE is approaching public-user readiness

The command name matches user expectations from Homebrew, npm, Flutter, Expo, React Native, and pnpm. It also creates a
natural destination for README quickstart docs, troubleshooting docs, and agent-launch error messages.

## Scope Principles

Default `sase doctor` should be:

- Read-only.
- Fast enough to run as a first troubleshooting step.
- Safe in any checkout.
- Scoped to known failure modes.
- Quiet about subsystems the user has not opted into.
- Actionable: every `WARN` or `ERROR` should include an exact next-step command or configuration hint.

Default `sase doctor` should not:

- Launch an LLM or perform an API-consuming smoke prompt.
- Run `just check`, tests, linters, docs builds, or broad validation suites.
- Run full-history artifact scans.
- Repair state automatically.
- Print secrets or raw environment dumps.
- Treat every optional integration warning as a blocker.

## What `sase doctor` Should Check

Each check should carry a stable ID, group, status (`OK`, `WARN`, `ERROR`, `SKIP`), one-line summary, optional detail
lines, exact next steps, bounded data for JSON, and duration in verbose JSON.

### Default Checks

| Group | Check ID | Status rule | Data and next step |
| --- | --- | --- | --- |
| Runtime | `runtime.version` | `WARN` if runtime inventory has package warnings; otherwise `OK`. | SASE executable, Python executable/version, host package version/source, core package version/source, plugin package summary. |
| Runtime | `runtime.core` | `ERROR` if `sase_core_rs` cannot import or any core probe fails. | Probe pass count; next step `sase core health -j`. |
| Runtime | `runtime.environment` | `ERROR` if Python is unsupported; `WARN` if editable checkout or installed package versions suggest stale environment drift. | Expected Python/package facts; next step `just install` when applicable. |
| VCS | `vcs.git` | `ERROR` if `git` is missing; `WARN` if author identity is missing and a git-backed project is active. | `git --version`, `user.name`, `user.email`; next step `git config`. |
| Config | `config.layers` | `WARN` on unreadable or invalid YAML layer; otherwise `OK`. | Loaded default/user/overlay/local layers; include paths in verbose/JSON. |
| Config | `config.init` | `WARN` if `sase init -c` reports drift; `ERROR` only for blockers. | AMD/memory/SDD/skills summary; next step `sase init --yes` or exact subcommand. |
| Config | `config.sdd` | `WARN` or `ERROR` from SDD validation when a local SDD tree exists. | Next step `sase sdd validate` or `sase sdd repair-links`. |
| Providers | `llm.default` | `ERROR` if the configured/effective default provider executable is missing; `WARN` for non-default missing providers. | Effective provider, selection reason, executable path, configured provider, temporary override if active. |
| Providers | `llm.registry` | `ERROR` if no LLM provider is registered; `WARN` for plugin metadata load problems. | Registered providers and autodetect order. |
| Plugins | `plugins.doctor` | Adapt existing `sase plugin doctor`: `ERROR` for load/missing configured chop failures, `WARN` for optional integration gaps. | Include existing check summaries and exact next steps. |
| Project | `project.current` | `WARN` for inactive/unlaunchable current project or parse warnings; `ERROR` if current project is required and cannot be resolved. | Project name, state, workspace path existence, active claim count. |
| Workspace | `workspace.registry` | `WARN` for missing registered checkout paths or repair dry-run changes; `OK` otherwise. | Root policy, root dir, registered count, missing count, repair command. |
| State | `state.paths` | `ERROR` if required state directories are not writable; `WARN` if optional dirs are missing and will be lazily created. | `$SASE_HOME`, workspace root, cache/log dirs. |
| State | `state.agent_index` | `WARN` if missing or repair recommended; `OK` otherwise. | Index path, schema version, visible row count, repair/verify commands. |
| Beads | `project.beads` | `SKIP` if no current bead store; otherwise `OK` or `ERROR` from bead doctor. | Preserve `sase bead doctor` messages. |
| Telemetry | `ops.telemetry_status` | `SKIP` if telemetry disabled; `WARN` if configured endpoints are unreachable. | Pushgateway/exposition reachability. |

### Deep Checks

`-D|--deep` should add checks that are useful but slower, noisier, or more operational than install-readiness oriented:

- `state.agent_index_verify`: run the full `sase agents index verify` source scan.
- `workspace.repair_dry_run`: run or emulate `sase workspace repair -n`.
- `workspace.cleanup_dry_run`: report stale cleanup candidates without deleting anything.
- `memory.episodes`: run `sase memory episodes doctor -p <project> -j` when an episodes directory exists.
- `ops.telemetry_health`: run `sase telemetry health -j` and include recent metric health.
- `ops.axe`: summarize axe daemon/lumberjack status when axe is configured or running.
- `providers.cli_version`: try cheap `--version` or equivalent provider commands with short timeouts where known.
- `tools.optional`: check optional render/view tools such as `tmux`, `bat`, `pandoc`, `pdftoppm`, `kitten`, a PDF
  engine, and `prettier`; warn only with the feature that degrades.
- Plugin-specific network/auth checks that are available and bounded, such as `gh auth status`.

Deep mode should still be read-only unless a future explicit repair flag is added.

## Output Design

### Human Output

Use a compact grouped report with stable IDs and terse next steps. Do not print full inventories unless
`-v|--verbose` is set.

Example:

```text
SASE Doctor: WARN

Runtime
  OK     runtime.version       sase 0.1.3+40.gd3017da06; python 3.12.11
  OK     runtime.core          sase_core_rs loaded; 4/4 probes passed
  OK     runtime.environment   editable checkout matches installed packages

Configuration
  OK     config.layers         default, user, overlay:sase_athena.yml, local
  OK     config.init           amd, memory, sdd, skills up to date

Providers
  OK     llm.default           codex selected; executable found on PATH

Plugins
  WARN   plugins.telegram_env  Telegram chops installed but SASE_TELEGRAM_* env is missing
  WARN   plugins.chops.extra   pushgateway_cleanup installed but not configured

Project
  OK     project.current       sase active; workspace exists; 6 active claims
  OK     workspace.registry    xdg-state root; 23 registered, 0 missing
  OK     state.agent_index     schema 3; 4313 visible rows; no repair recommended

Next steps
  - Telegram warnings matter only if Telegram chops should run.
  - Run `sase doctor -D` for full artifact, episode, workspace, and telemetry checks.
```

The output should lead with the aggregate status, then show each group. A warning should always say whether it blocks
normal local use.

### JSON Output

`-j|--json` should be stable enough for support bundles and scripts:

```json
{
  "schema_version": 1,
  "command": "doctor",
  "status": "WARN",
  "generated_at": "2026-06-09T16:00:00Z",
  "cwd": "/path/to/current/workspace",
  "sase_home": "/home/user/.sase",
  "project": "sase",
  "checks": [
    {
      "id": "runtime.core",
      "group": "runtime",
      "status": "OK",
      "summary": "sase_core_rs loaded; 4/4 probes passed",
      "details": [],
      "next_steps": [],
      "data": {
        "rust_extension_loaded": true,
        "probes": {
          "parse_query": true,
          "agent_launch_wire_schema_version": true,
          "plan_agent_launch_fanout": true,
          "bead_cli_execute": true
        }
      }
    }
  ]
}
```

Keep plugin, version, workspace, and telemetry details summarized in top-level checks. Full nested reports should appear
only in verbose JSON, or under check-specific `data` keys with bounded size.

### Status And Exit Codes

Use a small severity model shared with `sase plugin doctor`:

| Aggregate status | Meaning | Default exit |
| --- | --- | --- |
| `OK` | No problems found. | `0` |
| `WARN` | Potential or optional problems found; normal local use might still work. | `0` |
| `ERROR` | A required readiness check failed. | `1` |
| `SKIP` | Every selected check skipped. | `0` |

Add `-s|--strict` so scripts can treat `WARN` as non-zero. Keep usage errors as argparse exit `2`.

## Command Shape

Recommended flags:

```bash
sase doctor
sase doctor -j|--json
sase doctor -v|--verbose
sase doctor -D|--deep
sase doctor -s|--strict
sase doctor -L|--list-checks
sase doctor -C|--check <id-or-group>   # repeatable
sase doctor -p|--project <project>
```

Every option should have both short and long form, matching the repo's CLI convention.

Future flags, not MVP:

```bash
sase doctor -R|--repair
sase doctor -B|--support-bundle <dir>
```

`--repair` should only run safe, established repair commands such as init refresh, workspace repair, agent index GC, and
episode doctor repair, and should require explicit opt-in. `--support-bundle` could write `doctor.json`, config-layer
summary, version inventory, selected logs, and redacted environment hints.

## Implementation Notes

Promote shared diagnostics primitives rather than copying the plugin doctor implementation:

```text
src/sase/diagnostics/
  __init__.py
  models.py       # DoctorCheck, DoctorReport, CheckStatus, aggregation
  render.py       # shared JSON and human helpers
src/sase/doctor/
  __init__.py
  checks.py       # default/deep check registry and adapters
src/sase/main/parser_doctor.py
src/sase/main/doctor_handler.py
```

Implementation details:

- Refactor `sase plugin doctor` to import shared diagnostics models without changing its current behavior.
- Reuse direct APIs where they already exist:
  - `sase.version.collect_runtime_version_inventory`
  - `sase.core.health.check_backend_health`
  - `sase.plugins.doctor.build_plugin_doctor_report`
  - agent index status helper logic, ideally refactored from `sase.agents.cli_index`
  - project lifecycle/read helpers
- Use subprocess only for checks that do not yet expose a reusable API, with short timeouts and captured output.
- Redact environment-like details before rendering. Do not dump auth tokens, API keys, passwords, cookie files, or full
  provider config.
- Keep each check independent: one failed check should not prevent later checks from running.
- Include check duration in verbose JSON so slow checks can be identified.
- Keep the default check set deterministic and bounded.
- Respect the Rust-core boundary: reusable backend health verdicts that a web UI/editor would need should remain in
  `sase-core` or existing Rust-backed facades; Python should orchestrate and present.

This can stay Python-owned initially. The top-level doctor is orchestration and presentation glue.

## Tests

Recommended test coverage:

- Unit tests for status aggregation: `ERROR > WARN > OK`, all-skipped behavior, and strict exit behavior.
- Unit tests for JSON schema shape and bounded verbose/non-verbose output.
- Renderer tests for grouped human output and next-step lines.
- Check adapter tests with fake runtime, core health, plugin doctor, provider registry, and project/workspace data.
- CLI integration tests for `sase doctor`, `sase doctor -j`, `sase doctor -D -j`, `sase doctor -L`, and
  `sase doctor -C runtime.core`.
- Regression tests proving default doctor does not launch provider CLIs beyond cheap PATH/version checks and does not
  mutate workspace or state files.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Doctor becomes noisy and users ignore it. | Default to fast readiness checks; make optional integration warnings explicit; put operational checks in `--deep`. |
| Warnings break scripts. | Exit `0` on `WARN` by default; add `--strict`. |
| Output gets too large. | Compact human output; bounded JSON; verbose mode for inventories. |
| Provider checks consume API quota or hang. | No model calls; PATH checks by default; known `--version` probes only in deep mode with timeouts. |
| Repair causes data loss. | No repair in MVP; future `--repair` only delegates established safe repair commands and shows planned actions first where possible. |
| Duplicate logic drifts from subsystem commands. | Refactor reusable check functions from existing command handlers instead of parsing their text output. |
| Git/working-tree checks report too much noise in contributor workspaces. | Separate required runtime checks from project hygiene warnings and explain whether each warning blocks normal use. |

## Recommended Solution

Implement `sase doctor` as a fast, read-only top-level diagnostic aggregator and make it the first troubleshooting
command referenced by docs and support responses.

The MVP should include `runtime.version`, `runtime.core`, `runtime.environment`, `vcs.git`, `config.layers`,
`config.init`, `config.sdd`, `llm.default`, `llm.registry`, `plugins.doctor`, `project.current`, `workspace.registry`,
`state.paths`, `state.agent_index`, optional `project.beads`, and optional `ops.telemetry_status`. It should emit grouped
human output by default and stable JSON with `-j|--json`. It should use `OK`, `WARN`, `ERROR`, and `SKIP`, exit `0` for
`OK/WARN/SKIP`, exit `1` for `ERROR`, and add `-s|--strict` for scripts that want warnings to fail.

Add `-D|--deep`, `-L|--list-checks`, `-C|--check`, `-p|--project`, and `-v|--verbose` in the first implementation. Do
not add automatic repair in the MVP. Instead, every warning/error should include exact next-step commands such as
`just install`, `git config`, `sase init --yes`, `sase core health -j`, `sase plugin doctor -v`,
`sase agents index gc`, `sase workspace repair -n`, or `sase telemetry health -j`.

Build it by promoting the existing plugin-doctor data model into shared diagnostics primitives, then adding a small
top-level orchestration package that reuses existing subsystem checks. This gives users and maintainers one command to
start troubleshooting while preserving the existing subsystem commands as the detailed repair and inspection tools.
