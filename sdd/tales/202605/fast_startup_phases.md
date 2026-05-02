---
create_time: 2026-05-01 18:28:03
status: wip
prompt: sdd/prompts/202605/fast_startup_phases.md
---
# Plan: Make Sase Startup Much Faster

## Context

Recent startup research is consolidated in `sdd/research/202605/startup_time.md`, with the source chats:

- `sase-ace_run-260501_180846` / `~/.sase/chats/202605/sase-ace_run-260501_180846.md`
- `sase-ace_run-260501_181431` / `~/.sase/chats/202605/sase-ace_run-260501_181431.md`

The measured shape is:

- Parser/help startup is dominated by accidental imports during argparse construction.
- `sase --help` is roughly 155-200 ms depending on environment.
- `sase run --help` is much worse, roughly 370-420 ms, due to pre-argparse `query_handler` imports.
- `sase file list` is the largest editor hot spot, roughly 750-800 ms locally, because a pure filesystem completion
  helper imports the TUI package path and Textual.
- Existing `sase bead` Rust fast path proves that bypassing the full Python parser can get command startup near or below
  the Python interpreter floor.

This plan is intentionally phased so each phase can be completed by a distinct agent instance. Earlier phases reduce
import cost and add guardrails; later phases move tiny helper commands onto fast paths. Do not start Rust-shim packaging
work until the Python import graph is flattened and remeasured.

## Goals

- Bring ordinary parser/help startup close to the Python interpreter floor plus a small argparse tax.
- Bring `sase run --help` close to ordinary parser/help startup.
- Bring editor helper commands, especially `sase file list` and `sase file-history list`, down from hundreds of
  milliseconds to a practical keystroke-friendly budget.
- Preserve existing CLI behavior, help output, and public import compatibility unless a phase explicitly documents a
  narrow compatibility shim.
- Add regression tests that prevent barrel imports from quietly returning.

## Non-Goals

- Do not optimize `sase ace` full TUI launch in this project. It has different bottlenecks: Textual import, Rust binding
  init, and artifact/project scans.
- Do not change agent runtime startup for Claude, Gemini, Codex, or provider subprocesses.
- Do not introduce runtime-specific behavior. All agent runtimes keep the same capabilities.
- Do not start with a Rust binary shim. That is a packaging project and should happen only after lower-risk Python/Rust
  command fast paths are exhausted.

## Phase 1: Startup Measurement And Import Guardrails

**Owner scope:** tests, perf helper scripts, and documentation only. Avoid production behavior changes.

Add a small repeatable startup measurement harness and import-contract tests before changing the import graph. This
gives later agents a stable way to prove they improved startup without relying on one-off shell timing.

Implementation direction:

- Add a lightweight perf script under `tests/perf/`, for example `bench_cli_startup.py`, that can time:
  - `.venv/bin/python -c "import sys"`
  - `.venv/bin/sase --help`
  - `.venv/bin/sase run --help`
  - `.venv/bin/sase file-history list`
  - `.venv/bin/sase file list -t src`
- Add focused unit tests that import known lightweight surfaces and assert expensive modules are absent from
  `sys.modules`:
  - importing `sase.ace.saved_queries` must not import `sase.ace.changespec.parser`
  - importing the future neutral file-completion module must not import `textual` or `sase.ace.tui.app`
  - importing `sase.telemetry.metrics` must not import `urllib.request`
- Keep perf thresholds non-gating initially unless there is already an established local performance-gate pattern. The
  import-contract tests should be gating.
- Document how to run the harness in `sdd/research/202605/startup_time.md` or a short adjacent note.

Acceptance:

- `just install` then focused tests pass.
- The benchmark can be run locally and emits machine-readable JSON or a clearly parseable table.
- Import-contract tests fail on the current bad patterns and are adjusted as each later phase lands, or are introduced
  with expected current contracts only where the target module already exists.

## Phase 2: Parser-Only Import Cleanup

**Owner scope:** parser construction and package barrels. Avoid editor completion and `sase run` special-case work.

Remove the highest-cost parser-only imports so `sase --help` and most subcommand `--help` paths stop loading ChangeSpec,
commit workflow, telemetry, YAML, Rich syntax, and user query history.

Implementation direction:

- Slim `src/sase/ace/__init__.py` so importing `sase.ace.saved_queries` does not import `sase.ace.changespec`.
- Replace `src/sase/ace/changespec/__init__.py` eager re-exports with a PEP 562 lazy `__getattr__` map while preserving
  `__all__` and existing public imports such as `from sase.ace.changespec import CommitEntry`.
- Move `METHOD_ALIASES` and `VALID_METHODS` from `src/sase/workflows/commit/workflow.py` into a tiny import-light
  module, for example `src/sase/workflows/commit/_methods.py`. Re-export them from `workflow.py` for compatibility and
  update `parser_commit.py` and `cl_handler.py` to import from the light module where possible.
- Make `src/sase/main/parser_ace.py` parser construction pure. Use a sentinel default for the optional query and resolve
  `load_last_query() or load_first_saved_query() or "!!!"` inside `handle_ace_command`.
- Add or update import-contract tests for these exact surfaces.

Acceptance:

- `sase --help` no longer imports `sase.ace.changespec.parser`, `sase.ace.hooks`, `sase.workflows.commit.workflow`,
  `rich.syntax`, or `pygments` during parser construction.
- `sase ace` still resolves the same default query when no query is passed.
- Existing ChangeSpec import call sites continue to work.
- Focused parser, ace handler, commit workflow, and import-contract tests pass; run `just check` before handing off.

## Phase 3: Neutral File Completion Engine

**Owner scope:** file completion module movement and callers. Avoid entry-point fast paths.

Fix the largest missed hot spot: `sase file list` must not import the TUI package or Textual just to list filesystem
completion candidates.

Implementation direction:

- Move the pure logic from `src/sase/ace/tui/widgets/file_completion.py` into a neutral module such as
  `src/sase/completion/file.py`.
- Update `src/sase/main/file_handler.py` to import the neutral module.
- Update TUI callers (`_file_completion.py`, `prompt_text_area.py`, `prompt_input_bar.py`, `xprompt_completion.py`) to
  use the neutral module for shared types and constants.
- Leave a compatibility re-export at `sase.ace.tui.widgets.file_completion` if existing tests or external callers rely
  on that import path. The compatibility module may import the neutral module, but it should not cause neutral CLI
  imports to go through the TUI package path.
- Move or duplicate the pure module tests so the neutral module is tested directly.

Acceptance:

- `import sase.completion.file` does not import `textual`, `sase.ace.tui.app`, or TUI widget barrels.
- `sase file list -t src` no longer imports Textual before producing JSON.
- Existing TUI file completion behavior and tests continue to pass.
- Focused tests for `tests/main/test_file_handler.py`, file completion unit tests, and relevant prompt completion tests
  pass; run `just check` before handing off.

## Phase 4: Cheap `sase run` Special-Case Probe

**Owner scope:** `src/sase/main/entry.py` and `src/sase/main/query_handler/*`. Avoid parser-only barrel work already
owned by Phase 2.

Make the pre-argparse `sase run` path cheap when no actual special case is handled. The probe should parse simple argv
shape, decide whether it must intervene, and only then import chat history, agent launch, xprompt, artifacts, Rich, and
execution machinery.

Implementation direction:

- Change `entry.py` to import `handle_run_special_cases` from the narrow module path if that is cleaner than importing
  through the package barrel.
- Slim `src/sase/main/query_handler/__init__.py` using PEP 562 lazy exports for `_embedded_workflows` and
  `_standalone_steps` APIs while preserving existing public imports.
- Move top-level imports in `special_cases.py` into the specific branches that use them: `list_chat_histories`,
  `create_artifacts_directory`, `run_query_daemon`, `open_editor_for_prompt`, `show_prompt_history_picker`, `run_query`,
  and `handle_run_with_resume`.
- Keep branch behavior identical for `sase run`, `sase run .`, `sase run -l`, `sase run -r`, workflow references, direct
  spaced queries, daemon mode, and multi-prompt routing.
- Add import-contract tests showing `sase run --help` does not import agent launcher, xprompt execution, or artifacts
  before argparse help is printed.

Acceptance:

- `sase run --help` is close to normal parser/help startup after Phase 2.
- Existing run special-case tests pass, and new tests cover the branch-lazy imports.
- `sase run "<query with spaces>"`, `sase run .`, `sase run -l`, and `sase run -r` remain behavior-compatible.
- Run focused query-handler tests plus `just check`.

## Phase 5: Telemetry And Output Import Hygiene

**Owner scope:** telemetry package exports and obvious rich-output import leaks. Avoid parser and run special-case files
unless a test failure requires a narrow adjustment.

Clean up remaining cross-cutting infrastructure imports so lightweight modules do not transitively import HTTP, SSL,
Rich, or config/YAML when they do not emit telemetry or styled output.

Implementation direction:

- Make `src/sase/telemetry/__init__.py` lazy, or stop re-exporting `_registry` helpers eagerly.
- Move `_registry` imports of `urllib.request` / `urllib.error` into the functions that use them.
- Audit `from sase.output import ...` imports on startup-adjacent paths and defer them to use-sites where possible.
- Keep metric singleton behavior compatible with existing telemetry tests; do not reintroduce the historical
  import-before-init stub binding bug.

Acceptance:

- `import sase.telemetry.metrics` does not import `urllib.request`, `ssl`, or config loading.
- Existing telemetry tests continue to pass.
- Parser construction still avoids telemetry registry imports after Phase 2.
- Run telemetry tests, focused import-contract tests, and `just check`.

## Phase 6: Python Pre-Dispatch For Tiny Helper Commands

**Owner scope:** `entry.py` plus new tiny fast-path modules under `src/sase/main/`. Depends on Phase 3 for `file list`.

Before adding more Rust, add conservative Python pre-dispatch for simple JSON/path helpers. This skips full argparse for
the editor and shell-helper commands that have fixed, easy-to-validate argv shapes.

Implementation direction:

- Add an early fast-path in `entry.py`, similar to the existing bead fast path, for exact safe forms only.
- Candidate commands:
  - `sase file-history list`
  - `sase file-history delete -p <path>`
  - `sase file list [-p PATH] [-t TOKEN]`
  - `sase path config-schema`
  - `sase path xprompts-dir`
  - `sase path xprompts-schema`
  - `sase path xprompts-collection-schema`
- Fall through to argparse for `-h/--help`, unknown flags, missing values, repeated ambiguous options, and any shape not
  explicitly handled.
- Reuse the same business helpers as normal handlers where possible, but keep the imported graph light.
- Add tests for both handled and fallthrough cases, including help behavior.

Acceptance:

- Tiny helper commands produce byte-for-byte equivalent output to the argparse handler for supported forms.
- Help and error cases still use argparse.
- `sase file-history list` and `sase file list` avoid full parser construction.
- Focused main handler tests, new fast-path tests, and `just check` pass.

## Phase 7: Rust Core Fast Paths For Editor/Core Helpers

**Owner scope:** Rust core repo plus Python bindings/facades in this repo. Coordinate with the `../sase-core` boundary.
Do not start until Phases 1-6 are landed and remeasured.

Move stable editor/core helper behavior into `sase-core` where matching behavior is needed by editor integrations,
future web surfaces, and the CLI.

Implementation direction:

- Start with the lowest-risk commands:
  - `file-history list/delete`
  - `file list`
- Add Rust APIs and bindings in `../sase-core/crates/sase_core`, then expose through `sase_core_rs`.
- Keep Python fallback behavior for missing/unbuilt Rust bindings.
- Extend the Python pre-dispatch from Phase 6 to call Rust when available and fall back cleanly.
- Add parity tests with JSON fixtures for the Rust and Python implementations.

Acceptance:

- Rust and Python implementations produce equivalent JSON for representative path, dotfile, symlink, tilde, and history
  cases.
- Missing Rust binding falls back to Python without breaking pure-Python development.
- Editor helper startup improves beyond the Python pre-dispatch baseline where the Rust binding is available.
- Run Rust tests, Python parity tests, and `just check`.

## Phase 8: Decide On Lazy Parser Registration Or Rust Shim

**Owner scope:** design spike plus a small proof of concept only if measurements justify it.

After Phases 1-7, remeasure. If ordinary parser/help startup is still materially above the interpreter floor, consider
lazy parser registration. If editor helper commands still need sub-10 ms startup, consider a Rust binary shim.

Decision criteria:

- If parser construction is still a meaningful cost for normal Python commands, implement a two-pass
  `create_parser_for(argv)` that builds only the selected known subcommand parser and falls back to full argparse for
  help/unknown/ambiguous cases.
- If fast-pathed editor commands still pay too much Python interpreter overhead, design a Rust `sase` executable that
  intercepts known fast-path commands and `exec`s the existing Python shim on miss.
- Treat the Rust shim as a packaging/install-path project. Include uv-tool installs, editable installs, plugin
  discovery, and platform behavior in the design before implementation.

Acceptance:

- A written measurement comparison shows whether this phase is worth implementing.
- If implemented, fallback behavior is transparent and help/error output remains compatible.
- Packaging smoke tests cover editable and installed modes.

## Cross-Phase Verification

Every implementation phase should run:

```bash
just install
just check
```

Each phase should also run the startup harness from Phase 1 for the surfaces it changes and paste the before/after
numbers into its final response or phase notes.

Suggested steady-state targets after the relevant phases:

- `sase --help`: no expensive business modules during parser construction; close to interpreter floor plus argparse.
- `sase run --help`: within a small delta of `sase --help`.
- `sase file list -t src`: no Textual/TUI imports; eventually fast-pathed through Python, then Rust if justified.
- `sase file-history list`: skips full parser after Phase 6.

## Phase Dependencies

- Phase 1 should land first.
- Phase 2 and Phase 3 are mostly independent after Phase 1.
- Phase 4 should land after Phase 2, because it measures against the cleaned parser baseline.
- Phase 5 can run after Phase 2; it should not block Phase 3 or Phase 4.
- Phase 6 depends on Phase 3 for `file list`; other tiny helpers can be added even if `file list` is deferred.
- Phase 7 depends on Phase 6 and the Rust core boundary.
- Phase 8 is explicitly post-measurement and should not be started speculatively.
