# Improving Sase Startup Time: Research & Recommendation

## Goal

Cut the wall-clock time between a user typing `sase <something>` and the command starting useful work.
Startup latency directly affects shell ergonomics (tab-completion, `sase` in tight loops, hooks invoked
per-tool-call), editor integrations that shell out to `sase` on every keystroke (sase-nvim's
`<ctrl+t>` flow uses `sase file list` / `sase file-history list`), and TUI launch perceived snappiness.

This document scopes "startup" as **everything up to argparse-dispatched handler entry** — i.e. cold-process
import cost and parser construction. Per-command business logic is out of scope, except where a parser
gratuitously runs business logic at construction time.

## Measured Baseline (2026-05-01)

All measurements taken on the user's primary box, `time` of the installed `sase` shim, three runs.

| Command                       | Wall                  | Notes                                                        |
| ----------------------------- | --------------------- | ------------------------------------------------------------ |
| `python3 -c "import sys"`     | ~85 ms                | Bare interpreter floor. Anything below this is free.         |
| `sase bead list` (Rust path)  | ~50 ms                | **Below baseline** — uses bare `python -m sase.main.entry` interpreter; Rust fast path skips parser/handler imports entirely. Good. |
| `sase --help`                 | ~155–165 ms           | Builds full argparse but does no command-handler imports.    |
| `sase changespec --help`      | ~155–165 ms           | Same: parser-only path.                                      |
| `sase ace --help`             | ~165–175 ms           | Same.                                                        |
| `sase bead --help`            | ~155–170 ms           | Argparse path; bypasses bead Rust fast path because of `-h`. |
| `sase chat --help`            | ~155 ms               |                                                              |
| `sase run --help`             | **~370–390 ms**       | Worst observed. Triggers `query_handler` special-case path.  |

So the budget shape is: **Python interpreter floor ~85 ms, Sase parser tax ~70 ms baseline, +200 ms only
on `sase run`.** TUI launch (`sase ace` w/o `--help`) was not benchmarked here but inherits the parser tax
plus textual/Rust binding init; that warrants a separate pass.

## Where the Time Actually Goes

`python -X importtime` for the parser-only path (`sase --help`) and the run path show four cumulative-time
hot spots that account for the bulk of the parser tax. Numbers below are **cumulative microseconds** as
reported by `-X importtime` (so they include downstream chains, not just the one module).

### Hot spot 1 — `sase.ace/__init__.py` barrel (≈68 ms cumulative on every command)

`src/sase/ace/__init__.py` re-exports `CommitEntry` from `.changespec`. That re-export is harmless on its
own — but `src/sase/ace/changespec/__init__.py` is itself a barrel that imports **everything** in the
package: `locking`, `models`, `cache`, `parser`, `archive`, `raw_text`, `validation`. So any consumer that
touches `sase.ace.<anything>` pays for the whole ChangeSpec parsing/locking/validation graph, plus its
transitive deps (`yaml`, `sase.config.core`, `sase.telemetry`, `sase.ace.hooks`).

The trigger on every `sase` invocation is `parser_ace.py:5`:

```python
from sase.ace.saved_queries import load_first_saved_query, load_last_query
```

Even though `sase.ace.saved_queries` is itself a 30-line stdlib-only module, `import sase.ace.saved_queries`
runs `sase/ace/__init__.py` first, which imports `.changespec`, which re-runs `sase/ace/changespec/__init__.py`,
which fans out across the package. Importtime trace excerpt:

```
17556 us  sase                    (<-- triggered by sase.ace.saved_queries)
17690 us  sase.ace.changespec
56920 us  sase.ace.changespec.section_parsers
35458 us  sase.ace.hooks
27135 us  sase.telemetry.metrics  (urllib.request, ssl, http.client)
16328 us  yaml                    (full PyYAML loader+resolver)
```

`section_parsers` alone pulls in `pathlib` (15 ms), `logging`, `tempfile`, `inspect`, `dataclasses` —
all just to define dataclass-driven section parsers that the help screen will never use.

### Hot spot 2 — `parser_commit.py` reaches into `sase.workflows.commit.workflow` (≈57 ms)

`src/sase/main/parser_commit.py:66` does:

```python
from sase.workflows.commit.workflow import METHOD_ALIASES, VALID_METHODS

commit_parser.add_argument(
    "-t", "--type", dest="method",
    choices=[*VALID_METHODS, *METHOD_ALIASES],
    ...
)
```

This is a **constants-only** import, but the module that defines them (`sase.workflows.commit.workflow`)
is the full commit-workflow implementation. It transitively imports:

- `sase.output` (which imports `rich.console`, `rich.live`, `rich.panel`, `rich.syntax`, `rich.table`)
- `rich.syntax` pulls the entire `pygments` lexer-mapping graph (`pygments.lexers._mapping`,
  `pygments.styles`, `importlib.metadata` with `zipfile._path`)
- `sase.vcs_provider` (with `pluggy` plugin manager init)
- `sase.ace.deltas`, `sase.workflows.commit.checkpoint`, `precommit_hooks`, `pr_operations`

This 57 ms tax is paid on **every `sase` invocation that goes through argparse**, including `sase --help`
and tab-completion, even though no commit is being run.

### Hot spot 3 — `sase.main.query_handler/__init__.py` barrel (`sase run` only, ≈108 ms extra)

`entry.py:18-22` does an early-import for `sase run` so it can intercept queries containing spaces
before argparse mangles them:

```python
if len(sys.argv) >= 2 and sys.argv[1] == "run":
    from .query_handler import handle_run_special_cases
```

Direct import of `sase.main.query_handler.special_cases` measures ~230 ms cold; importing
`sase.main.query_handler` (which goes through `__init__.py`) measures ~338 ms cold — a **108 ms
penalty** purely from the barrel re-exporting `_embedded_workflows` and `_standalone_steps`. Those
two modules pull `xprompt` (107 ms cumulative), `jsonschema` (32 ms), `jinja2` (15 ms),
`rich.syntax` again (already counted), `sase.agent.launcher`, etc. None of it is needed to handle
the special case of a quoted query; the heavy parts are only needed once we've decided the query
should actually be expanded.

### Hot spot 4 — `parser_ace.py` runs disk I/O at parse-construction time

```python
ace_parser.add_argument(
    "query",
    nargs="?",
    default=load_last_query() or load_first_saved_query() or "!!!",
    ...
)
```

Every `sase` invocation reads `~/.sase/last_query.txt` and `~/.sase/saved_queries.json` — even
`sase bead list -h`, even on a machine that has never run `sase ace`. The cost in time is small
(~1 ms unless the FS is cold) but it matters because (a) it's wasted work for non-`ace` commands,
(b) it fails the "argparse construction should be pure" invariant, and (c) it makes the cost of
adding more "smart defaults" tempting and load-bearing.

### Smaller offenders worth listing

- **`sase.telemetry.metrics`** is imported transitively by the changespec graph. It pulls
  `urllib.request` → `http.client` → `ssl` (≈22 ms). No `--help` path needs telemetry.
- **`sase.config.core`** is pulled in by `sase.ace.display_helpers` to read the YAML config; this
  brings in PyYAML's full loader/dumper (16 ms) regardless of subcommand.
- **`pyinstrument`** is a `dependencies = [...]` requirement (used by `sase ace -p`) but is not
  imported at startup — confirmed clean. Leave alone.
- **`textual[syntax]`** is the heaviest dep but is only loaded by the TUI, not the CLI startup
  path. Out of scope here, but TUI startup needs its own profiling pass.
- The 24 `parser_*` modules are all imported by `parser.py` regardless of which subcommand the
  user picked. Each is small (~100 µs) but they collectively trigger the hot spots above by
  pulling their respective business modules.

## Architectural Patterns at Fault

The hot spots above are not isolated bugs — they're four instances of three recurring patterns:

1. **Barrel `__init__.py` files that re-export submodules** (`sase.ace`, `sase.ace.changespec`,
   `sase.main.query_handler`). Convenient for callers (`from sase.ace.changespec import X`) but
   they convert "import one symbol" into "execute everything". Under PEP 562, package `__getattr__`
   gives you the same ergonomics with lazy load — see the proposal section.
2. **Argparse `choices=` / `default=` that calls into business modules**. `parser_commit.py`
   (constants from `workflows.commit.workflow`) and `parser_ace.py` (`load_last_query()`) are the
   two examples, but the pattern is easy to repeat. Argparse construction should be a pure function
   of stdlib + lightweight metadata.
3. **Cross-cutting "infrastructure" modules imported at top of business modules** (telemetry,
   `sase.output`/rich). Once these become unconditional top-of-module imports, they bleed cost
   into every consumer. They should be deferred until first use.

## Proposed Fixes

Ordered by impact-per-effort. Estimated wall-time savings are upper bounds (cumulative microseconds
overlap, so combined real saving will be smaller).

### Tier 1 — high impact, low risk

**T1.1 — Slim `sase/ace/__init__.py` and `sase/ace/changespec/__init__.py`.**
Estimated saving: 60–80 ms on every command, 100 ms on `sase run`.

Two surgical changes:

- Delete `from .changespec import CommitEntry` from `sase/ace/__init__.py`. Anyone who actually
  needs `CommitEntry` already imports `sase.ace.changespec.CommitEntry` (or re-exports it through
  the changespec barrel). Audit: `grep -rn "from sase.ace import"` shows callers, and most of them
  reach for things that don't exist on `sase.ace` directly anyway.
- Replace `sase/ace/changespec/__init__.py`'s ≈30 explicit re-exports with a PEP 562 lazy
  `__getattr__`:

  ```python
  _LAZY = {
      "ChangeSpec": ".models",
      "CommitEntry": ".models",
      "parse_project_file": ".parser",
      "ChangeSpecSnapshotCache": ".cache",
      # ... etc
  }
  def __getattr__(name: str) -> object:
      target = _LAZY.get(name)
      if target is None:
          raise AttributeError(name)
      module = importlib.import_module(target, __name__)
      value = getattr(module, name)
      globals()[name] = value
      return value
  ```

  Public API preserved; submodules load only when an attribute is actually accessed. `__all__`
  stays intact (PEP 562 lazy attrs participate in `dir()` if you maintain it explicitly).

**T1.2 — Defer the `METHOD_ALIASES`/`VALID_METHODS` import in `parser_commit.py`.**
Estimated saving: 30–55 ms on every command.

Either:

- Move the constants into a tiny `sase/workflows/commit/_methods.py` that has no other imports.
  Then `parser_commit.py` imports from there. The "real" workflow module re-exports them so
  existing call sites don't break.
- Or replace `choices=` with a custom `type=` callable that imports lazily on actual use:

  ```python
  def _commit_method(value: str) -> str:
      from sase.workflows.commit.workflow import METHOD_ALIASES, VALID_METHODS
      if value not in {*VALID_METHODS, *METHOD_ALIASES}:
          raise argparse.ArgumentTypeError(...)
      return value
  ```

  This loses argparse's auto-generated `--help` enumeration of choices, which is a real downside.
  Prefer the dedicated constants module.

**T1.3 — Slim `sase/main/query_handler/__init__.py`.**
Estimated saving: 100+ ms on `sase run` (only).

`entry.py` already imports the symbol it needs by path: `from .query_handler import handle_run_special_cases`.
Change `__init__.py` so it does **not** eagerly import `_embedded_workflows` or `_standalone_steps`. Use
PEP 562 lazy `__getattr__` for `EmbeddedWorkflowResult`, `expand_embedded_workflows_in_query`, and
`execute_standalone_steps`. The entry-point fast path then only pays for `special_cases.py`'s direct
imports (which are themselves still heavy and a candidate for follow-up profiling).

**T1.4 — Make `parser_ace.py` defaults pure.**
Estimated saving: ~1 ms wall, but unblocks T1.1 and matches the project convention from
`memory/short/gotchas.md`.

```python
# at parser-build time:
default=_LAST_QUERY_SENTINEL,  # an object()
# in handle_ace_command:
if args.query is _LAST_QUERY_SENTINEL:
    args.query = load_last_query() or load_first_saved_query() or "!!!"
```

This also stops `sase --help` from touching the user's home dir.

### Tier 2 — medium impact, moderate risk

**T2.1 — Lazy-import `sase.output` at use-site only.**
Estimated saving: 30–50 ms across commands that don't actually print rich-styled output.

`sase.output` is imported by `sase.workflows.commit.workflow` (top-of-module). Since `workflow` is
itself going to be deferred via T1.2, this becomes mostly moot — but it's worth establishing the
rule: never import `sase.output` at module top. `--help` and pure-data subcommands (`sase path`,
`sase file list`) never need rich.

**T2.2 — Defer telemetry HTTP libs.**
Estimated saving: ~22 ms on every command that touches telemetry-imports transitively.

`sase.telemetry.metrics` does `import urllib.request` at module top, presumably for a Pushgateway
client. Move that import inside the function that talks to Pushgateway. The metric-registration
side has no use for `urllib`.

**T2.3 — Lazy parser registration.**
Estimated saving: 10–30 ms (mostly accumulated parser-module fixed cost) and decouples
new-subcommand growth from startup cost.

Today `create_parser()` calls 24 `register_*` functions unconditionally. Argparse needs the full
table for `sase --help` and for unknown commands, but for any **known** subcommand we can take a
two-pass approach:

```python
def create_parser_for(argv: list[str]) -> argparse.ArgumentParser:
    if argv and argv[0] in _KNOWN_COMMANDS and argv[0] not in {"-h", "--help"}:
        return _build_single_command_parser(argv[0])
    return _build_full_parser()
```

This is implementable as a thin pre-dispatcher in `entry.py` analogous to the existing bead/run
fast-paths. Care needed: subcommand aliases, `sase` (no args) → full help, and `sase <unknown>`
must still surface argparse's "invalid choice" message with the full known set. The simplest
discipline is to fall through to the full parser whenever we're not 100% sure.

### Tier 3 — high impact, larger surface change

**T3.1 — Push more commands into the Rust fast path.**
Estimated saving: drop from ~155 ms → ~50 ms for any command moved.

`sase bead` already demonstrates the model: `bead_fast_path.py` calls into `sase_core_rs`'s
`bead_cli_execute` and bails out cleanly when the binding can't handle the case. Strong candidates,
based on the rust_core_backend_boundary memory ("if a web app or editor would need the behavior to
match the TUI, it's core") and on the editor-integration commands listed in
`memory/short/build_and_run.md`:

- `sase file-history list` / `delete` — already JSON helpers, no Python-only logic.
- `sase file list` — file-glob + token filter; pure Rust win.
- `sase changespec list <project>` (read path) — `.gp` files are line-oriented and already parsed in Rust core.
- `sase agents list` (read path) — directory-scan over `~/.sase/projects/*/artifacts/`.

Each one moved cuts that command's startup from ~155 ms to ~50 ms. Editor integrations that hit
these on every keystroke benefit most. **Caveat**: pushing a command into Rust commits to keeping
behavior in lockstep; for unstable surfaces (e.g. `sase ace`'s query-history defaults changing
shape), keep them in Python.

**T3.2 — A `sase`-shim in Rust that intercepts known fast-path commands without booting Python.**
Estimated saving: drop from ~50 ms → ~5–10 ms for fast-pathed commands.

Today's bead fast path still pays Python's ~85 ms interpreter floor (the floor we measure with
`python -c "import sys"`). A Rust-binary entry that dispatches `sase bead list`, `sase file list`,
etc. without ever loading Python would close that gap. The implementation could be a small Rust
binary in `sase-core/crates/sase_core` that, on miss, `exec`s the existing Python `sase` shim. This
is a much larger surface change (packaging, plugin dispatch, install paths via uv-tool) and should
only be considered after T1/T2 land and we know the Python startup is as flat as it can be.

**T3.3 — A "no business code in `__init__.py`" lint rule.**
Estimated saving: prevents regressions of T1.1/T1.3.

Add a ruff custom rule (or a unit test that imports `sase.ace`, `sase.main.query_handler`,
`sase.workflows.commit`, `sase.ace.changespec` and asserts `sys.modules` does not contain the
expensive submodules). Failing tests catch the next person who adds a "convenient" re-export.

### Considered and rejected

- **AOT bytecode cache (`.pyc`).** Python already caches compiled bytecode in `__pycache__`. After
  the first run of any version, `.pyc` is what's being read. Pre-warming would only matter on first
  invocation per Python version per file — not a recurring cost.
- **Compiling sase to a single zipapp/PEX.** zipimport has its own overhead (we see `zipimport`
  showing up in importtime when stdlib `importlib.metadata` walks the `.dist-info` set). It rarely
  improves Python startup and complicates editable installs.
- **Switching to typer/click for parser construction.** Both are heavier than argparse on cold
  start. `argparse` itself measures ~6 ms in the trace; replacing it would lose, not save.
- **mypyc/Cython compilation of the parser path.** Would help, but most of the cost is *import*
  time of unrelated modules, not Python execution speed of parser-build code. The fixes above
  attack the root cause.

## Suggested Order of Operations

1. Land T1.1 first — biggest single saving, contained surface, easy to verify by re-running
   `python -X importtime -c "from sase.main.parser import create_parser; create_parser()"`.
2. Land T1.2 (constants module). Once both T1.1 and T1.2 are in, re-measure: target is `sase --help`
   under ~110 ms (parser tax cut from ~70 ms to ~25 ms).
3. Add the lint test from T3.3 to lock in the win before adding more changes.
4. Land T1.3 next; target is `sase run --help` under ~250 ms.
5. Land T1.4, T2.1, T2.2 as a cleanup batch (uncontroversial).
6. Decide whether T2.3 (lazy parser registration) is worth its complexity given the new baseline.
   If parser tax is already <15 ms, probably not.
7. T3.1 (more Rust fast-path commands) is independent and can run in parallel; pick the editor-hit
   commands first.
8. Defer T3.2 (Rust shim) until after the above; it's a packaging change with downstream impact
   on plugin discovery (`sase_llm`, `sase_vcs`, `sase_workspace` entry points).

## How to Verify

A reliable repro sits in three commands:

```bash
SASE_PY=/home/bryan/.local/share/uv/tools/sase/bin/python
# Cold (drop FS cache between runs in a clean shell):
for i in 1 2 3; do (time sase --help >/dev/null) 2>&1 | grep total; done
# Importtime trace, sorted by cumulative for top-level entries:
$SASE_PY -X importtime -c "from sase.main.parser import create_parser; create_parser()" 2> /tmp/it.log
awk '/^import time:/ {match($0, /^import time: *([0-9]+) *\| *([0-9]+) *\| *(.*)$/, a); if (a[1]!="" && match(a[3],/[^ ]/)<=5) printf "%8d %s\n", a[2]+0, a[3]}' /tmp/it.log | sort -rn | head -20
```

For per-fix verification, the cleanest assertion is "after my change, `sys.modules` does not contain
`sase.ace.changespec.parser` after `from sase.main.parser import create_parser; create_parser()`."
That's what the proposed lint test in T3.3 should encode.

## Out of Scope (but related)

- **TUI launch latency** (`sase ace` without `--help`). Likely dominated by `textual` import,
  Rust binding init, and `~/.sase/projects/*` scan rather than the parser tax. Needs its own
  pyinstrument run.
- **Hook startup overhead.** Sase invokes `sase chop_*` scripts as hooks; the entry points listed
  in `pyproject.toml` (`sase_chop_pending_checks_poll`, etc.) each pay the Python floor on every
  hook fire. If hook frequency turns out to matter, a single long-lived hook supervisor process
  would amortize startup across hook invocations — but only worth it if profiling shows hooks are
  bottlenecking a real workflow.
- **Per-agent runtime startup**: Claude/Gemini/Codex providers each have their own boot sequence.
  Distinct from CLI startup, distinct measurement, distinct fix set.
