---
create_time: 2026-06-09
updated_time: 2026-06-09
status: research
---

# `sase doctor` Command Consolidated Research

## Research Request

Would a top-level `sase doctor` command be useful for troubleshooting SASE? If so, what should it check, what should it
output, and what solution should SASE implement?

## Consolidation Notes

This note consolidates the two independent agent research outputs from 2026-06-09. The agents ultimately wrote the same
relative intermediate path, `sdd/research/202606/sase_doctor_command_research.md`, in separate workspaces; the later
version expanded the earlier one. I read both chat transcripts, the earlier committed version, the later/current file,
and the duplicate sibling-workspace copy before writing this final note.

The only meaningful conflict was exit-code policy. This note recommends `WARN` exit `0` by default, with a strict mode
that makes warnings non-zero. That keeps `sase doctor` useful as a first support command without making optional
integration warnings look like hard install failures.

## Bottom Line

Yes. A top-level `sase doctor` would be useful, but mainly as a fast diagnostic aggregator, not as a new validation
suite. SASE already has strong subsystem diagnostics, but they are scattered across commands that users must already
know to run:

- `sase version -j`
- `sase core health -j`
- `sase init -c`
- `sase validate`
- `sase plugin doctor -j`
- `sase agents index status -j`
- `sase workspace list --json`
- `sase project list --json`
- `sase bead doctor`
- `sase memory episodes doctor`
- `sase telemetry status`
- `sase telemetry health -j`

No current command answers the user-facing support question: "Is this SASE install and current workspace healthy enough
for normal use, and if not, what exact thing should I fix?"

The command should become the documented first troubleshooting step: run `sase doctor -v` for a human-readable support
artifact or `sase doctor -j` for machine-readable output.

## Evidence

### Current SASE Surface

Source review and local verification confirm there is no top-level `doctor` command today. `sase --help` lists `core`,
`plugin`, `validate`, `telemetry`, `version`, `workspace`, and other commands, but not `doctor`; `src/sase/main/parser.py`
has no `register_doctor_parser`, and `src/sase/main/entry.py` has no `args.command == "doctor"` dispatch.

Existing diagnostic commands are useful but fragmented:

| Command | Scope | Output shape | Reuse for `sase doctor` |
| --- | --- | --- | --- |
| `sase core health` | Rust `sase_core_rs` import and backend probes | Text / `-j` | Required runtime check. |
| `sase plugin doctor` | Plugin resources, configured chops, GitHub CLI/auth, Telegram env, `pass` | Rich / `-j` | Reuse its `DoctorCheck` model and checks. |
| `sase validate` | `init --check` plus SDD validation | Text | Summarize init and SDD readiness. |
| `sase telemetry status` | Telemetry enablement and endpoint reachability | Rich | Default only when telemetry is enabled. |
| `sase telemetry health` | Recent operational metric health | Rich / `-j` | Deep/ops mode, not default install readiness. |
| `sase bead doctor` | Bead project health | Text | Run only when the current project has bead state. |
| `sase memory episodes doctor` | Episode index/build/orphan checks, optional repair | Text / `-j` | Deep project-state check. |
| `sase version` | Runtime package inventory | Rich / `-j` | Required support metadata. |

The cleanest existing implementation is `src/sase/plugins/doctor.py`: it already defines `DoctorCheck`, `DoctorReport`,
`CheckStatus`, status aggregation, JSON serialization, and actionable `next_steps`. Those primitives should be promoted
to shared diagnostics code instead of copied.

### Local Verification

I re-ran a small read-only verification set in this workspace on 2026-06-09:

| Probe | Result | Implication |
| --- | --- | --- |
| `sase core health -j` | `status=ok`; Rust extension loaded; 4/4 probes passed. | Default `runtime.core` check is cheap and high value. |
| `sase version -j` | Host/core/plugin inventory reports editable installs and git metadata. | Useful support-bundle metadata. |
| `sase init -c` | Initialized; checked `amd`, `memory`, `sdd`, and `skills`. | Default `config.init` check can reuse existing readiness logic. |
| `sase validate` | `ok init --check`; `ok sdd validate`. | SDD drift can be summarized without inventing new logic. |
| `sase plugin doctor -j` | Overall `WARN`: resources/configured chops OK; unconfigured `pushgateway_cleanup`; missing Telegram env vars. | Optional integration warnings should not be treated as install blockers. |
| `sase agents index status -j` | Index exists; schema 3; 4313 visible rows; no repair recommended. | Lightweight state health belongs in default doctor. |
| `sase telemetry status` | Telemetry enabled; Pushgateway reachable; exposition running. | Reachability is a bounded default check when telemetry is enabled. |

One additional finding matters: the active `sase` executable in this ephemeral workspace is an editable install from a
different source root (`/home/bryan/projects/github/sase-org/sase`), not this checkout. That is a concrete example of
the "run `just install` in reused workspaces" problem described in `memory/short/build_and_run.md`. `sase doctor` should
explicitly report when the active executable/import source root does not match the current checkout and recommend
`just install` when appropriate.

### Prior Art

Doctor-style commands are common where a CLI depends on external tools, local state, PATH, project config, or optional
platform integrations:

| Tool | Pattern | Lesson for SASE |
| --- | --- | --- |
| [Homebrew `brew doctor`](https://docs.brew.sh/Manpage#doctor-dr---list-checks---audit-debug-diagnostic_check-) | Checks system problems and supports listing individual checks. | Use stable check IDs and targeted check selection. |
| [npm `npm doctor`](https://docs.npmjs.com/cli/v8/commands/npm-doctor/) | Checks executables, registry, permissions, and cache. | Include PATH, config, state, and provider prerequisites. |
| [Flutter doctor](https://docs.flutter.dev/reference/flutter-cli) | Produces the first support artifact users are asked to attach. | Make verbose doctor output the support front door. |
| [Expo Doctor](https://docs.expo.dev/develop/tools/#expo-doctor) | Checks project config and dependency compatibility. | Include both global and current-project checks. |
| [React Native Doctor](https://reactnative.dev/blog/2019/11/18/react-native-doctor.html) | Checks required platform tools and can guide fixes. | Start with precise manual next steps; defer repair. |
| [pnpm doctor](https://pnpm.io/cli/doctor) | Checks known common configuration issues. | Keep the default bounded to known failure modes. |

The pattern is not "run everything." It is "collect the setup and state facts maintainers need before debugging."

## Scope Principles

Default `sase doctor` should be:

- Read-only.
- Fast enough to run before asking for help.
- Safe in any checkout.
- Scoped to common failure modes.
- Quiet about subsystems the user has not opted into.
- Actionable: every `WARN` or `ERROR` should include exact next-step commands or config hints.

Default `sase doctor` should not:

- Launch an LLM or perform an API-consuming smoke prompt.
- Run `just check`, tests, linters, docs builds, or broad validation suites.
- Run full-history artifact scans.
- Repair state automatically.
- Print secrets or raw environment dumps.
- Treat every optional integration warning as a blocker.

## Recommended Default Checks

Each check should have a stable ID, group, status (`OK`, `WARN`, `ERROR`, `SKIP`), summary, bounded details, exact next
steps, and optional JSON data.

| Group | Check ID | Default status rule |
| --- | --- | --- |
| Runtime | `runtime.version` | `WARN` if runtime inventory reports package warnings; otherwise `OK`. |
| Runtime | `runtime.core` | `ERROR` if `sase_core_rs` cannot import or any core probe fails. |
| Runtime | `runtime.environment` | `ERROR` for unsupported Python; `WARN` for stale install/source-root drift. |
| State | `state.paths` | `ERROR` if required state/workspace dirs are unwritable. |
| VCS | `vcs.git` | `ERROR` if `git` is missing; `WARN` if identity is missing for a git-backed project. |
| Config | `config.layers` | `WARN` on unreadable/invalid YAML or unsupported keys; show active layers. |
| Config | `config.init` | `WARN` for init drift; include exact `sase init ...` next step. |
| Config | `config.sdd` | `WARN` or `ERROR` from SDD validation when an SDD tree exists. |
| Providers | `llm.default` | `ERROR` if the effective default provider executable is missing. |
| Providers | `llm.registry` | `ERROR` if no provider is registered; `WARN` for provider metadata load issues. |
| Plugins | `plugins.doctor` | Adapt existing plugin doctor checks; preserve optional warnings. |
| Project | `project.current` | `WARN` for inactive/unlaunchable current project or parse warnings. |
| Workspace | `workspace.registry` | `WARN` for missing registered checkout paths or repair dry-run changes. |
| State | `state.agent_index` | `WARN` if missing or repair recommended; otherwise summarize schema/rows. |
| Beads | `project.beads` | `SKIP` if no bead store; otherwise adapt `sase bead doctor`. |
| Telemetry | `ops.telemetry_status` | `SKIP` if disabled; `WARN` if configured endpoints are unreachable. |

Important details:

- Provider checks should report the effective default provider, selection reason, configured provider, temporary
  override if active, and executable path. They should check PATH/configured binary presence only; no LLM calls.
- Config checks should not rely only on the merged config. `src/sase/config/core.py` currently returns defaults when a
  YAML layer fails to parse, so doctor should expose invalid/unreadable layers directly.
- Optional integrations should be `SKIP` when not in use, `WARN` when configured but degraded, and `ERROR` only when a
  required workflow is blocked.

## Deep Checks

`-D|--deep` should add checks that are useful but slower, noisier, or more operational than install readiness:

- `state.agent_index_verify`: full `sase agents index verify`.
- `workspace.repair_dry_run`: dry-run workspace repair.
- `workspace.cleanup_dry_run`: stale workspace cleanup candidates without deleting anything.
- `memory.episodes`: `sase memory episodes doctor -p <project> -j` when episode state exists.
- `ops.telemetry_health`: recent Prometheus health; this reflects workload health, not install readiness.
- `ops.axe`: summarize axe/lumberjack status when configured or running.
- `providers.cli_version`: cheap known provider `--version` probes with short timeouts.
- `tools.optional`: `tmux`, `bat`, `pandoc`, `pdftoppm`, `kitten`, a PDF engine, `prettier`; warn only with affected
  feature names.
- Bounded plugin-specific auth/network checks such as `gh auth status`.

Deep mode should still be read-only. Repair should wait for an explicit future flag.

## Output Contract

### Human Output

Default output should be compact, grouped, and actionable. Print all non-OK checks and a short pass summary; show every
OK detail only under `-v|--verbose`.

Example shape:

```text
SASE Doctor: WARN

Runtime
  OK     runtime.core          sase_core_rs loaded; 4/4 probes passed
  WARN   runtime.environment   active sase import root differs from this checkout
         next: run `just install` in this workspace

Providers
  OK     llm.default           codex selected; executable found on PATH

Plugins
  WARN   plugins.telegram_env  Telegram chops installed but SASE_TELEGRAM_* env is missing
         next: set Telegram env vars only if Telegram chops should run

State
  OK     state.agent_index     schema 3; 4313 visible rows; no repair recommended

Summary: 9 OK, 2 WARN, 0 ERROR, 1 SKIP
```

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

Keep full inventories bounded. Put large nested data behind `-v|--verbose` or check-specific compact `data` keys.

### Status And Exit Codes

Use one severity model everywhere:

| Status | Meaning | Default exit |
| --- | --- | --- |
| `OK` | No problems found. | `0` |
| `WARN` | Potential or optional problems found; normal use may still work. | `0` |
| `ERROR` | A required readiness check failed. | `1` |
| `SKIP` | All selected checks skipped. | `0` |

Add `-s|--strict` so scripts can treat `WARN` as non-zero. Leave argparse usage errors at exit `2`.

### Command Shape

Recommended first implementation:

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

Every option should have both a short and long form, matching `memory/short/gotchas.md`.

Future, not MVP:

```bash
sase doctor -R|--repair
sase doctor -B|--support-bundle <dir>
```

## Implementation Approach

1. Promote shared diagnostics primitives out of `src/sase/plugins/doctor.py`:

   ```text
   src/sase/diagnostics/
     __init__.py
     models.py       # DoctorCheck, DoctorReport, CheckStatus, aggregation
     render.py       # JSON and human rendering helpers
   src/sase/doctor/
     __init__.py
     checks.py       # default/deep registry and adapters
   src/sase/main/parser_doctor.py
   src/sase/main/doctor_handler.py
   ```

2. Refactor `sase plugin doctor` to use shared diagnostics models without changing behavior.
3. Reuse direct APIs where available: runtime inventory, core health, plugin doctor, config layers, project lifecycle,
   agent-index status, and workspace helpers. Avoid parsing human text when a structured helper can be extracted.
4. Use subprocesses only where no API exists, with short timeouts and captured output.
5. Redact environment-like details. Do not dump auth tokens, API keys, passwords, cookie paths, or raw provider config.
6. Keep checks independent so one failure does not suppress later findings.
7. Respect the Rust-core boundary: core/backend health verdicts that another frontend would need should live in
   `sase-core` or an existing Rust-backed facade; Python should orchestrate and present.

Recommended tests:

- Severity aggregation, strict exit behavior, and all-skipped behavior.
- JSON schema shape and bounded verbose/non-verbose output.
- Human renderer grouping and next-step formatting.
- Check adapters with fakes for runtime inventory, core health, plugin doctor, providers, config, and project state.
- CLI integration for default, JSON, deep JSON, list-checks, and selected-check runs.
- Regression tests that default doctor does not launch LLMs, mutate state, or run broad test/lint suites.

## Recommended Solution

Implement `sase doctor` as a fast, read-only top-level diagnostic aggregator and make it the first troubleshooting
command referenced by the README, docs, and agent-launch error paths.

The MVP should include runtime/package inventory, Rust core health, environment/source-root freshness, writable state
paths, git identity, config layers, init/SDD readiness, effective LLM provider availability, provider registry health,
plugin/chop health, current project/workspace state, agent-index health, bead health when present, and telemetry
reachability when telemetry is enabled. It should emit grouped human output by default and stable JSON with
`-j|--json`. It should exit `0` for `OK/WARN/SKIP`, exit `1` for `ERROR`, and add `-s|--strict` for scripts that want
warnings to fail.

Do not add automatic repair in the MVP. Instead, every warning/error should name exact next-step commands such as
`just install`, `git config`, `sase init --yes`, `sase core health -j`, `sase plugin doctor -v`,
`sase agents index gc`, `sase workspace repair -n`, or `sase telemetry health -j`. Once the report contract is stable,
consider a separate `-R|--repair` mode that delegates only to established safe repair commands.
