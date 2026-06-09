---
create_time: 2026-06-09 11:53:23
status: done
prompt: sdd/prompts/202606/namespace_template_review.md
---
# Review & Objective Improvements: Namespace-Aware Agent Name Templates

## Context

Commit `75f999ecd` (sase) + `aad7963` (sase-core) implemented namespace-aware `%name` `@` template allocation. I
reviewed both diffs end-to-end: the Rust namespace primitive, the in-memory `AgentNameNamespaceReservationIndex`, the
durable registry batch reservation, the `PlannedNameAllocator` group/single paths, and the xprompt-group threading
through the CWD/TUI launch paths.

**Correctness verdict: the change is correct and well-tested.** I traced the namespace semantics (exact-name vs.
dotted-prefix, `research.1` vs `research.10` non-collision), the in-memory/registry consistency, same-group namespace
sharing, stale-snapshot recovery, and segment/`template_groups` alignment through the home-mode rebuild. I found no
correctness bugs.

What follows are **objective, behavior-preserving improvements** — type safety, performance, and de-duplication. No
functional change is intended; existing tests must continue to pass unchanged.

## Improvements

### 1. Restore type safety on the namespace index (HIGH value, no risk)

`PlannedNameAllocator` types the new index as `Any`, disabling mypy on a non-trivial new abstraction:

- `multi_prompt_reference_allocator.py:7` — `from typing import Any`
- `:36` — `self._template_index: Any | None = None`
- `:525` — `def _template_reservation_index(self) -> Any:`

`Any` is used _only_ for the index in this file. Replace with the real type via a `TYPE_CHECKING`-guarded import (free
at runtime, sidesteps the existing lazy-import / circular-import pattern):

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sase.agent.names import AgentNameNamespaceReservationIndex
...
self._template_index: "AgentNameNamespaceReservationIndex | None" = None
def _template_reservation_index(self) -> "AgentNameNamespaceReservationIndex":
```

Then drop the now-unused `from typing import Any`. This restores static checking over `candidate_available`, `add_name`,
`update_names`, etc.

### 2. Hoist the loop-invariant namespace template out of token loops (HIGH value, no risk)

`render_agent_name_template_namespace(template, token)` internally re-derives
`agent_name_template_namespace_template(template)` (a Rust parse) on **every** token iteration, even though it depends
only on `template`, not `token`. This contradicts the plan's own performance note ("build the occupied set once", "stop
as soon as a token passes"). Affected hot loops:

- `names/_templates.py::allocate_agent_name_template` (`:187-190`)
- `multi_prompt_reference_allocator.py::_allocate_template_name` single-token loop (`:506-508`)
- `multi_prompt_reference_allocator.py::_template_candidates` (`:621`), invoked per token inside the group loop —
  re-derives the namespace template for every template on every token.

Fix: derive the namespace template once per template (outside the loop), then render the namespace from it per token:

```python
ns_template = agent_name_template_namespace_template(template)
for token in iter_agent_name_template_tokens():
    candidate = render_agent_name_template(template, token)
    namespace = render_agent_name_template(ns_template, token)
    ...
```

For the group path, precompute `[(template, ns_template), ...]` once in `planned_names_for_template_group` and have
`_template_candidates` accept the pre-derived namespace templates (or inline the precompute). Removes one Rust
round-trip per token per template on the collision path.

### 3. Build the occupied-namespace set once per registry batch (MEDIUM value, secondary)

`_registry.py::_namespace_conflict_name` scans **all** registry entries for **each** name in a reservation batch →
O(K·N) under the global `_registry_mutation_lock`. The in-memory side already solved this with a prefix set; mirror it
registry-side. Build the occupied-namespace set once from `entries` (excluding `allowed_existing_names`) and do
set-membership checks:

```python
occupied = {
    prefix
    for existing in entries
    if existing not in allowed
    for prefix in _dotted_namespace_prefixes(existing)
}
# conflict iff namespace in occupied
```

This reduces under-lock work from O(K·N) to O(N + K·depth). Keep a small local prefix helper in `_registry.py` (do
**not** import from `_templates.py` — `_templates` already imports `_registry`, so the reverse would be circular).
Benefit is bounded (batches are small; single-name path is already O(N)), so this is secondary — include it for
lock-hold-time and parity with the in-memory index, but it can be dropped if it adds noticeable complexity.

### 4. De-duplicate the auto-name token loop (LOW value, optional)

`names/_auto.py::allocate_auto_names` reimplements the token-iteration + index loop instead of reusing
`allocate_agent_name_template`, and hardcodes `name = token` / `namespace = name`, silently baking in the assumption
that the `@` template renders the token verbatim. The reason for the reimplementation was to share one index across
`count` iterations (avoid rebuilding per call).

Preferred fix: add an optional `index` parameter to `allocate_agent_name_template` so `allocate_auto_names` can pass a
shared index and reuse the single allocation contract, eliminating the duplication and the `@`-coupling. Tradeoff:
reintroduces one Rust `render("@", token)` call per token that the inline version avoids — negligible (auto-name
allocation normally resolves on the first token). Mark optional; if not taken, at minimum add a comment documenting the
`@`-template coupling.

## Non-changes (considered and deliberately left alone)

- **Dual state `_template_reserved` + `index.exact_names`**: not vestigial — `_template_reserved` backs
  `_latest_template_name` (`%wait`/`#fork` resolution) via `_template_reserved_names()`. Keep both.
- **Triple duplicate-shape guard** (`_ensure_unique_group_render_shapes` raise, `_template_candidates_available` set
  check, registry duplicate-name raise): defense-in-depth across layers; the first gives the clear user-facing error.
  Leave as-is.
- **`reserve_registered_template_name` (singular)**: not dead — covered by `tests/test_agent_name_registry.py`. Keep.
- **`_dotted_namespace_prefixes` O(parts²)**: names have few dotted parts; negligible. Not worth touching.

## Scope & verification

- Files: `names/_templates.py`, `names/_auto.py`, `names/_registry.py`, `multi_prompt_reference_allocator.py` (all sase
  Python; **no sase-core / Rust changes** — the core primitive is correct as-is).
- All changes are behavior-preserving; **no existing test should need editing**. If any test changes, that signals an
  unintended behavior change to re-examine.
- Add a focused micro-test only if useful (e.g. asserting `allocate_auto_names` shares one index — optional).
- Run: `just install` then `just check` (lint + mypy + full test suite). The type-safety item (#1) is specifically
  validated by the mypy phase.

## Recommended order

Items **1 and 2** are unambiguous wins (do both). Items **3 and 4** are optional cleanups — implement only if they land
cleanly without added complexity.
