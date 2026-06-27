---
create_time: 2026-06-27 09:59:52
status: done
prompt: sdd/prompts/202606/reserved_jinja_globals.md
---
# Plan: Make reserved Jinja globals (`root`) statically known for lint/inference

## Problem

`just test` fails non-deterministically with two failures:

```
FAILED tests/ace/tui/widgets/test_local_xprompt_conversion.py::test_infer_known_globals_are_not_inputs
FAILED tests/ace/tui/widgets/test_prompt_local_xprompt_convert.py::test_gx_does_not_infer_known_globals_as_inputs
AssertionError: assert [InputArg(name='root', ...)] == []
```

Both assert that the reserved Jinja global `root` is **never inferred as a user input** when a prompt body contains
`{{ root }}`. Run in isolation, both tests pass. Run inside the full parallel suite, they intermittently fail.

## Root Cause (confirmed)

The set of "known top-level global names" used for input inference, lint, and completion is derived from the _runtime
values_ of those globals, and that derivation is CWD-dependent and cached process-wide:

- `infer_local_xprompt_inputs(body)` (in `src/sase/ace/tui/widgets/_local_xprompt_conversion.py`) treats any undeclared
  Jinja variable that is **not** in the known-globals set as a required `TEXT` input. It gets the known set from
  `jinja_inspect.inspect_template`.
- `known_toplevel_context()` (in `src/sase/xprompt/jinja_inspect.py`) is `@lru_cache(maxsize=1)` and returns
  `set(get_global_template_vars())`.
- `get_global_template_vars()` (in `src/sase/xprompt/_jinja.py`) only includes `root` **when
  `resolve_primary_workspace()` resolves a workspace from the current working directory**; otherwise it omits it.

Consequently the _name_ `root` is only "known" when a workspace happens to resolve from CWD. Because
`known_toplevel_context()` is `lru_cache`d, the **first** call within a given pytest-xdist worker freezes the value for
the whole worker. Many tests `monkeypatch.chdir(tmp_path)` into a directory where no workspace resolves; if such a test
warms the cache first, it caches `set()` (no `root`), and every later test in that worker that relies on the real `root`
being known then fails. This is order- and worker-dependent, which is why the failure is intermittent and disappears in
isolation.

Reproduced deterministically in-process: warming `known_toplevel_context()` from a tmp dir caches `set()`, after which
`infer_local_xprompt_inputs("Path is {{ root }}")` returns `[InputArg(name='root', ...)]` instead of `[]` — exactly the
suite failure.

This is not merely a test-isolation defect; it is a latent **product bug**: when a user triggers `gX` (or any top-level
Jinja lint/completion) from a directory where the workspace can't be resolved, `root` is wrongly treated as an
undeclared variable — inferred as a required input, flagged by the unknown-variable lint, and dropped from completion
candidates — even though `root` is a global the renderer reserves and injects whenever it can.

## Design

Separate two concerns that are currently conflated:

1. **Which global names the renderer reserves/injects** — a static, CWD-independent fact (lint, inference, and
   completion care about this).
2. **The runtime values of those globals** — CWD-dependent; a value may be unresolvable right now (rendering cares about
   this, and correctly leaves an unresolved global undefined so `StrictUndefined` still errors).

Introduce a single static source of truth for the reserved global **names** and drive lint/inference/completion from it,
while leaving value resolution (and thus actual rendering behavior) unchanged.

### Changes

- **`src/sase/xprompt/_jinja.py`**: Add a module-level constant naming the reserved top-level globals, e.g.
  `RESERVED_GLOBAL_NAMES: frozenset[str] = frozenset({"root"})`. Keep `get_global_template_vars()` resolving values only
  for those names (still omitting `root` when the workspace can't resolve — rendering behavior is unchanged). The
  constant documents that `get_global_template_vars` must only ever produce names within it.

- **`src/sase/xprompt/jinja_inspect.py`**: Change `known_toplevel_context()` to return the static reserved-name set
  (`set(RESERVED_GLOBAL_NAMES)`) instead of `set(get_global_template_vars())`. This makes it CWD-independent and
  deterministic. Remove the now-pointless `@lru_cache(maxsize=1)` (it returns a constant, and the cache was the
  mechanism that froze a polluted value) — or keep a trivial cache; removing it is cleaner and eliminates the
  stale-cache hazard entirely.

This is the minimal change that fixes both the flakiness and the underlying product bug, and it keeps a single source of
truth: reserved names live in one constant; value resolution stays in `get_global_template_vars`.

### Why this is safe for the other consumers

- **Inference** (`infer_local_xprompt_inputs`): `root` is always known → never inferred as an input. Correct.
- **Unknown-variable lint** (`inspect_template` / `unknown_variables` default path): `root` is always known → never
  flagged. Correct.
- **Completion** (`jinja_completion._candidates_for_prefix`): `root` is always offered as a variable candidate, which is
  desirable since it resolves at launch time. The existing completion tests already monkeypatch `known_toplevel_context`
  to `{"root"}`, so the new static behavior matches their expectation.
- Callers that pass an explicit `known=` set (e.g. `test_xprompt_jinja_inspect.py`) are unaffected.
- `get_global_template_vars()` (rendering, workflow scope merge) is unchanged, so no rendering behavior changes.

## Testing

- Add a regression test (in `tests/test_xprompt_jinja_inspect.py` or alongside the conversion tests) that pins the
  invariant directly: with `resolve_primary_workspace` forced to return `None` (or CWD pointed at a non-project dir),
  `known_toplevel_context()` still contains `root`, and `infer_local_xprompt_inputs("{{ root }}")` returns `[]`. This
  guards against the CWD/cache dependence regressing, independent of test ordering.
- Confirm the two originally-failing tests pass, and that they pass even when the cache/CWD would previously have
  poisoned them.
- Run the full `just check` (lint + mypy + full parallel test suite, including visual snapshots) to confirm the
  intermittent failure is gone and nothing else regressed. Because the bug is order-dependent, also run the suite a
  second time (or run the two test files together with a known-polluting test) to gain confidence it is deterministic
  now.

## Out of Scope

- Changing rendering semantics for an unresolved `root` (it should remain undefined so `StrictUndefined` surfaces a
  clear error at render time).
- Auditing every other `lru_cache` in the codebase for similar CWD coupling — noted as a possible follow-up but not
  required to fix this failure.
