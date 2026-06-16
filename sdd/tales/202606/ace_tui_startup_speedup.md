---
create_time: 2026-06-15 20:55:07
status: wip
prompt: sdd/prompts/202606/ace_tui_startup_speedup.md
---
# Plan: Make `sase ace` TUI startup MUCH faster

## Problem

Launching the `sase ace` TUI takes ~17s on a cold start. That is long enough to feel broken, and it is paid every time
the OS page cache / bytecode cache is cold (fresh machine boot, fresh/ephemeral workspace, right after `just install`,
after a deploy).

## Goal

Cut cold `sase ace` startup from ~17s to a small fraction of that (target: first paint in a few seconds cold,
~sub-second warm), without changing TUI behavior or regressing agent-run processes.

---

## Root cause (measured, not guessed)

Per the TUI-perf memory ("Measure, don't guess"), I profiled before planning. The key finding is that the dominant cost
is **`import sase.ace.tui`**, which the existing `--profile` flag _cannot see_ — in `src/sase/main/ace_handler.py`,
`from sase.ace.tui import AceApp` runs at line 55, **before** `pyinstrument.Profiler.start()` at line 80. The profiler
only covers `app.run()`, so it misses the real bottleneck.

Measurements in this workspace (project venv):

| Measurement                                      | Cold      | Warm   |
| ------------------------------------------------ | --------- | ------ |
| `import sase.ace.tui`                            | **8.4 s** | 1.0 s  |
| `sase --help` (CLI dispatch only, no TUI import) | 0.38 s    | 0.27 s |
| `AceApp.__init__` (`_init_app_state`)            | —         | 0.17 s |

- The CLI/argparse layer is cheap (0.38s). `AceApp.__init__` is cheap (0.17s). The `on_mount` path already pushes heavy
  disk reads off-thread via `asyncio.to_thread` (a prior regression — the 39%/11.6s artifact-index sync — was already
  moved off the paint path). **Almost all of the wall-clock is module import.**
- `import sase.ace.tui` pulls in **1684 modules**. Cold, that is ~6s of reading ~1500 source files from a cold page
  cache + ~2s of bytecode compilation. The user's ~17s is this same cold path on an even colder/slower environment, plus
  first-paint compose.

### Where the import cost goes (self-time, cold compile run)

| Top-level package                                | Self-time  |
| ------------------------------------------------ | ---------- |
| `sase.ace` (475 tui modules + the rest of `ace`) | **974 ms** |
| `sase.xprompt`                                   | 109 ms     |
| `textual`                                        | 98 ms      |
| `sase.core`                                      | 89 ms      |
| `sase.agent`                                     | 78 ms      |
| `sase.llm_provider`                              | 69 ms      |
| `pydantic`                                       | 54 ms      |
| `langchain_core`                                 | 27 ms      |
| `charset_normalizer` / `urllib3` / `requests`    | ~50 ms     |

### Two concrete, high-leverage offenders

1. **The entire LLM / langchain / HTTP stack is eagerly imported at TUI import time, and first paint never needs it.**
   Confirmed in `sys.modules` after importing `sase.ace.tui`: `langchain_core`, `pydantic`, `requests`, `urllib3`,
   `charset_normalizer`, and `sase.llm_provider._invoke` are all present.
   - Chain: `app.py` composes the `LLMOverrideIndicator` widget → `widgets/llm_override_indicator.py:13` does a
     top-level `from sase.llm_provider.registry import format_provider_model_label` → importing
     `sase.llm_provider.registry` first runs `sase/llm_provider/__init__.py`, whose line 7 is
     `from ._invoke import invoke_agent` → that pulls in `langchain_core` and the whole HTTP stack.
   - `registry.py` itself is langchain-free; only the package `__init__` is heavy.
   - `modals/temporary_llm_override_modal.py` is a second eager entry into the same stack.

2. **All 56 modals are eagerly imported at startup**, none of which are needed for first paint. Chain:
   `actions/base.py:16` does a top-level `from ..modals import (...)` → runs `modals/__init__.py`, which eagerly imports
   all 56 modal modules (including the single most expensive module in the whole graph, `agent_run_log_modal` at ~50ms
   self). `marking.py` and `status.py` do the same for `StatusModal`.

Fewer modules on the import path attacks **both** cost components: less bytecode to compile AND fewer files to read from
cold disk.

---

## Proposed approach

Phased, highest-leverage-first. Each phase is independently shippable and independently measurable. The unifying
principle (straight from the TUI-perf memory's "never block, defer work off the first-paint path"): **nothing that first
paint does not need should be imported before first paint.**

### Phase 0 — Make startup measurable (prerequisite, do first)

The current `--profile` flag structurally cannot see import cost. Fix the blind spot so this work (and future
regressions) can be measured:

- Start the profiler in `ace_handler.py` _before_ the `from sase.ace.tui import AceApp` import (or move the import under
  the profiler), so the dominant cost is captured.
- Add a tiny startup-cost guard test/bench that imports `sase.ace.tui` in a fresh subprocess and asserts (a) a ceiling
  on `len(sys.modules)` and (b) that known-heavy, first-paint-irrelevant packages — `langchain_core`, `requests`,
  `urllib3` — are **absent** from `sys.modules`. This pins the wins below against regression and is the acceptance gate
  for the later phases.

### Phase 1 — Break the LLM / langchain / HTTP stack off the startup path (biggest win)

Remove `langchain_core` + `pydantic`(-as-pulled-here) + `requests`/`urllib3`/ `charset_normalizer` +
`llm_provider._invoke` from the TUI import graph.

- Make `sase/llm_provider/__init__.py` import its heavy submodules **lazily** via PEP 562 module-level `__getattr__`, so
  `from sase.llm_provider import invoke_agent` still works for agent-run processes but
  `import sase.llm_provider.registry` no longer forces `_invoke`/langchain to load. The public API (`__all__`) is
  preserved; only the _timing_ of the heavy import changes.
- Point the two TUI offenders at the light surface: `widgets/llm_override_indicator.py` and
  `modals/temporary_llm_override_modal.py` should import only what they use (`format_provider_model_label`, etc.)
  without dragging in `_invoke`.
- Verify no other TUI-path module imports `llm_provider` at module top level (the grep audit shows the remaining
  `llm_provider` imports in the TUI are already function-local / lazy, which is the correct pattern).

This is a pure-Python change. It does **not** cross the Rust core boundary (`llm_provider` is Python in this repo), and
it must not change behavior for agent-run subprocesses, which legitimately need langchain — they will import it on first
use exactly as before, just not at module-load time.

### Phase 2 — Lazy-load modals (second-biggest win)

Modals are only constructed when the user opens them; none are needed for first paint.

- Convert `modals/__init__.py` to lazy exports (PEP 562 `__getattr__` / `__all__`-driven) so importing the package does
  not eagerly pull all 56 modal modules.
- Update the eager top-level importers (`actions/base.py`, `actions/marking.py`, `actions/status.py`,
  `actions/agents/_notification_actions.py`, `actions/navigation/_advanced.py`) so the modal classes resolve on use
  rather than at app-class definition time. Keep type-only references under `TYPE_CHECKING`.

### Phase 3 — Audit and defer the remaining non-essential eager imports

With the two big offenders gone, sweep the rest of the `ace/tui` import path for heavy modules not needed for first
paint, and make them function-local/lazy. Candidates from the self-time table: `sase.xprompt` (esp. the
workflow-executor/expander modules), `sase.workflows`, parts of `sase.agent` and `sase.core.agent_*_wire`, and the
graphics viewer loop. Each deferral is validated against the Phase 0 module-count guard so we only keep changes that
demonstrably shrink the startup graph without breaking behavior.

### Phase 4 — Complementary: precompile bytecode at install time

Lazy-loading removes modules from the path; for the modules that _do_ remain, ensure the cold launch never pays
first-import bytecode compilation:

- Add a `compileall` step to the install flow (e.g. in the `just install` recipe / `_setup` target) so `.pyc` files
  exist immediately after install. This directly addresses the "right after `just install` / fresh ephemeral workspace"
  cold case called out in the build/workspace memory. (Lower priority than Phases 1–3, which also cut the cold
  _disk-read_ cost that precompilation alone cannot.)

---

## Verification / acceptance

- **Primary metric:** cold `import sase.ace.tui` wall-clock (fresh subprocess, cleared `__pycache__`) and cold
  end-to-end `sase ace` to first paint. Record before/after for each phase.
- **Module-count guard** (Phase 0): `len(sys.modules)` after `import sase.ace.tui` drops substantially and stays under a
  pinned ceiling; `langchain_core`/`requests`/`urllib3` stay absent.
- **Behavioral safety:** `just check` (lint + mypy + full test suite incl. PNG visual snapshots) is green. Manually
  exercise the deferred surfaces — open the LLM-override modal/indicator, open several modals, run an agent — to confirm
  lazy imports resolve correctly and agent-run processes still load langchain on use.
- **No Rust boundary change:** all edits are Python presentation glue + a Python `__init__` lazy-loading change; no
  `sase-core` wire/API changes required.

## Risks & mitigations

- _Lazy `__getattr__` masking import errors_ → the Phase 0 guard test and `just check` exercise the real import paths;
  add explicit "import every public name" coverage for the lazified `__init__` modules.
- _Hidden eager re-entry_ (some other module re-imports the heavy stack at top level) → the `sys.modules` absence
  assertion catches it immediately.
- _Agent-run regression_ (subprocesses need langchain) → unchanged at call time; only module-load timing moves. Covered
  by existing agent/llm_provider tests.

## Out of scope

- Rewriting the `on_mount` async loading flow (already off-thread and well-optimized).
- Any change to TUI behavior, layout, keymaps, or rendering.
- `sase-core` Rust changes.
