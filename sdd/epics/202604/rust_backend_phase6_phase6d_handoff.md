---
create_time: 2026-04-29 18:30:00
status: done
bead_id: sase-1b.4
---
# Rust Backend Phase 6D Handoff — Backend Health Check And User-Facing Diagnostics

## Scope landed in this phase

Phase 6D adds one cheap, scriptable answer to the question "is the active
sase.core backend loadable and healthy?". A new `sase.core.health` module
collects a frozen `BackendHealthReport` (selected backend, dual-run flag,
`sase_core_rs` import / module path / version, Python version, platform tag,
and the result of a single `parse_query("status:Ready")` probe). A new
`sase core health` CLI command prints the report (human-readable by default,
`-j` / `--json` for machine output) and exits non-zero whenever the report
is `status="error"`. CI install-smoke (`.github/workflows/ci.yml`) and
release install-smoke (`.github/workflows/publish.yml`) now invoke
`sase core health --json` instead of open-coded import / binding probes.
The default backend is **unchanged** — Python is still the default through
Phase 6E and Phase 6F is the flip.

## Behavior contract

| Selected backend           | `sase_core_rs` state                       | `status` | exit |
| -------------------------- | ------------------------------------------ | -------- | ---- |
| `rust` (and Phase 6F+ default) | importable, `parse_query` works        | `ok`     | 0    |
| `rust`                     | not importable (`ImportError`)             | `error`  | 1    |
| `rust`                     | importable but missing `parse_query`       | `error`  | 1    |
| `rust`                     | importable but `parse_query` raises        | `error`  | 1    |
| `rust`                     | non-`ImportError` import failure (misbuilt wheel) | `error` | 1 |
| `python`                   | any (including missing or misbuilt)        | `ok`     | 0    |

Key non-obvious choices:

- **Probe is `parse_query("status:Ready")`** — same input documented as the
  Phase 6A wheel smoke and Phase 6B install smoke. Reusing it means the
  health check, the wheel smoke, and the install smoke all agree on what
  "the binding works" means. No negative parse probe was added; per Phase
  6D's plan, we only call a cheap negative input "if the expected error
  shape is stable" and `parse_query`'s error shape currently isn't pinned
  by a contract test we can reuse.
- **Misbuilt-wheel import errors propagate into the report** rather than
  being silently swallowed. `sase.core.health` catches the exception and
  surfaces it in `error` / `error_kind`, exiting non-zero. This matches
  `is_rust_available()`'s philosophy (only `ImportError` is forgiven; other
  errors mean the wheel is broken and the user needs to know).
- **Explicit Python mode is permissive even when the extension is broken.**
  Phase 6/7 promises `SASE_CORE_BACKEND=python` is the escape hatch; making
  the health check refuse to be `ok` under Python mode just because the
  optional Rust wheel is broken would punish users who picked the escape
  hatch precisely to work around a broken wheel.
- **Top-level `sase core` subcommand**, not an extension of an existing
  command. The plan preferred the narrower `sase core health` form; mixing
  this into `sase telemetry health` (which assesses metric pushgateway /
  exposition health) would overload the meaning of "health".

## Changes in this repo

- `src/sase/core/health.py` (new): `BackendHealthReport` (frozen dataclass)
  and `check_backend_health()`. Pure-Python; only depends on
  `sase.core.backend`, `platform`, and `sys`.
- `src/sase/main/parser_core.py` (new): registers `sase core` and
  `sase core health [-j/--json]`. Short option per repo convention.
- `src/sase/main/core_handler.py` (new): `handle_core_command` /
  `handle_core_health` — JSON output via `json.dumps(..., sort_keys=True)`
  for stable CI logs, human output is a short line-oriented block.
- `src/sase/main/parser.py`: registers `register_core_parser` (alphabetical
  position between `config` and `file`).
- `src/sase/main/entry.py`: dispatches `args.command == "core"` to
  `handle_core_command` (alphabetical position after `config`).
- `tests/test_core_health.py` (new): 15 tests covering Python-mode-without-
  extension, Python-mode-with-extension, Rust-mode happy path, missing
  extension under Rust mode, misbuilt extension under Rust mode, missing
  `parse_query` attribute, broken `parse_query` raise path, dual-run flag
  reporting, JSON serializability, plus 5 CLI tests for human output, JSON
  output, both `-j` and `--json` flags, the non-zero exit on Rust-missing,
  and the Python-mode permissive path.
- `docs/rust_backend.md`: added "Backend Health Check" subsection (table of
  exit codes plus the dual `sase core health` / `--json` invocations) and a
  Phase 6D roadmap entry.
- `.github/workflows/ci.yml`: `install-smoke` job now runs
  `sase core health --json` for both default and `SASE_CORE_BACKEND=python`
  modes instead of inline `python -c "import sase_core_rs..."` probes.
- `.github/workflows/publish.yml`: same swap for the release install-smoke
  job — wheels prove they install + start without a local Rust toolchain by
  running the new health command.

## Tests run in this workspace

```
.venv/bin/pytest tests/test_core_health.py \
                 tests/test_core_backend.py \
                 tests/test_core_facade/test_backend_contract.py
```

15 + existing backend / contract tests pass locally. `.venv/bin/sase core
health` and `.venv/bin/sase core health --json` were exercised by hand
against the live `sase_core_rs` install (status `ok`, exit 0) and against
`SASE_CORE_BACKEND=python` (status `ok`, exit 0, `rust_required: false`).

`just check` was run in this workspace after the edits and stays green.

## Out of scope (handed to later subphases)

- `Phase 6E` — `is_workflow_complete` regression resolution. Phase 6D adds
  no new ports and does not touch `src/sase/agent/names/_lookup.py`.
- `Phase 6F` — flipping `DEFAULT_BACKEND` to `Backend.RUST`. The health
  command's exit-code contract is the prerequisite for Phase 6F's
  release-job assertion that "default Rust comes up healthy on a clean
  install"; the flip itself is Phase 6F's job.
- `Phase 6G` — full CI matrix and dual-run parity gate. The CI install-smoke
  job is now health-checked but the broader test-matrix and dual-run parity
  gate are still Phase 6G's responsibility.

## Exit criteria

- [x] `sase core health` is a single scriptable command for "is the active
      backend loadable and healthy?".
- [x] Default Rust with a missing or broken `sase_core_rs` exits non-zero
      and surfaces the specific failure (`ImportError`, `AttributeError`,
      probe `Exception`, or misbuilt-wheel `RuntimeError`).
- [x] Explicit `SASE_CORE_BACKEND=python` reports Python mode and does not
      require `sase_core_rs`.
- [x] Misbuilt extension import failures are not silently swallowed — they
      flow into `report.error` / `report.error_kind` and exit non-zero
      under Rust mode.
- [x] Tests exercise fake import failures and fake extension modules at
      both the helper and CLI layers.
- [x] CI install-smoke (Phase 6B scaffolding) and release install-smoke
      both call `sase core health --json` so the wheel install path is
      exercised end-to-end through the new contract.
