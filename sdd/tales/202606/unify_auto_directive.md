---
create_time: 2026-06-24 15:10:13
status: done
prompt: sdd/prompts/202606/unify_auto_directive.md
---
# Plan: Unify `%plan` / `%tale` / `%epic` into a single `%auto` directive

## Goal & product context

Today there are three separate prompt directives that all auto-approve a submitted plan, differing only in how the plan
is committed:

| Directive       | Alias | Effect                                                         |
| --------------- | ----- | -------------------------------------------------------------- |
| `%plan`         | `%p`  | Auto-approve the submitted plan as a **normal plan**           |
| `%tale`         | `%t`  | Plan first, then auto-approve & commit the plan as a **tale**  |
| `%epic`         | —     | Plan first, then auto-approve & commit the plan as an **epic** |
| `%approve`/`%a` | —     | Deprecated hidden aliases of `%plan`                           |

Collapse these into **one** directive, `%auto`, that takes a string/enum argument:

- `%auto` (bare) → `plan` (the default)
- `%auto:plan` → normal-plan auto-approval
- `%auto:tale` → tale auto-approval
- `%auto:epic` → epic auto-approval
- Any other value → a `DirectiveError` listing the valid modes.

### Decisions (already settled with the user)

1. **No back-compat.** `%plan`, `%tale`, `%epic`, `%approve`, and the short aliases `%p`/`%t` are removed entirely. They
   become _unknown_ tokens (left as literal text, not stripped). This matches the "not referenced anywhere" requirement.
   The deprecated-alias machinery is removed, not just emptied.
2. **`%a` is the short alias for `%auto`** (advertised, not deprecated). `%p` and `%t` are dropped.
3. **Single internal field.** Replace the three booleans `approve` / `tale` / `epic` on `PromptDirectives` with one
   field `auto_mode: str | None` (values `"plan" | "tale" | "epic" | None`).
4. **Docs scope includes the published blog posts.** Rewrite the three blog posts that mention the old directives; leave
   dated SDD/research/CHANGELOG/historical content alone.

### Scope of "remove all references"

Active code, config, docs, the Rust core mirror, the user's chezmoi config, and tests must stop referencing
`%plan`/`%tale`/`%epic`/`%approve` (and `%p`/`%t` in their auto-approve sense). Explicitly **out of scope**
(historical/dated — leave untouched): everything under `sdd/` (beads, tales, epics, prompts, research, legends),
`CHANGELOG.md` files, and `docs/images/*.critique.md`. `sase-nvim` needs **no** changes (it resolves directives
dynamically over LSP; it hardcodes no directive-name list).

### Important non-goals / things NOT to touch

- The **agent-model** `approve` field and the meta-wire `approve` key (`Agent.approve`, `meta.approve`, `done.approve`,
  `cli_list.py`, the `_loaders`, `_dedup`, `_meta_enrichment_*`, `_approve.py`, `agent_scan` wire/scanner, the mobile
  `PlanActionChoiceWire`, `auto_approve_modal.py`). These are a _downstream_ representation of auto-approval state,
  distinct from the `PromptDirectives` parse fields. The migration only changes how the directive is **parsed** and the
  one place that translates parsed directives into agent meta. The `auto_approve_plan_action` values (`"tale"`/`"epic"`)
  and the `approve`/`plan` meta keys keep their current names and semantics.
- `plan_chain.py`'s `.epic`/`-epic` legacy suffixes — these are plan-chain agent-name suffixes, unrelated to the
  directive.

---

## Architecture & boundary

Directive parsing is **mirrored in two languages** and must be kept in parity:

- **Python** (this repo) owns the runtime parse + effect: `src/sase/xprompt/` extracts directives into
  `PromptDirectives`; `src/sase/axe/run_agent_directives.py` is the _only_ consumer of the auto-approve fields and
  writes them into agent meta.
- **Rust core** (`../sase-core`, crate `sase_core`) owns the **editor** experience: directive metadata, alias
  resolution, completion, hover, diagnostics (`crates/sase_core/src/editor/directive.rs`). The fan-out planner
  (`agent_launch/mod.rs`) defers to the editor registry's `canonical_directive_name` for alias normalization; it has no
  per-directive auto-approve logic.

Per the repo's core-backend boundary rule, the editor/directive registry is shared backend logic — the Rust change must
land alongside the Python change so the editor (Neovim LSP) and the Python TUI advertise the same directive set. There
is **no shared golden-vector fixture** for directives; each language keeps its own metadata table, so parity is
maintained by editing both tables to match.

---

## Implementation

### Part A — Python parser & types (`src/sase/xprompt/`)

**`_directive_types.py`**

- `_KNOWN_DIRECTIVES`: remove `"plan"`, `"tale"`, `"epic"`; add `"auto"`.
- `_DIRECTIVE_ALIASES`: remove `"a": "plan"`, `"approve": "plan"`, `"p": "plan"`, `"t": "tale"`; add `"a": "auto"`.
  (`%time` keeps no short alias, unchanged.)
- Remove `_DEPRECATED_DIRECTIVE_ALIASES` entirely (no deprecated aliases remain) and update its importers (see
  `directive_completion.py`).
- `PromptDirectives` dataclass: remove the `approve`, `tale`, `epic` boolean fields; add `auto_mode: str | None = None`.
  Update the surrounding docstring/comments that describe the old fields.

**`directives.py`**

- In `extract_prompt_directives`, replace the `approve=/epic=/tale=` construction with a single `auto_mode` derivation
  from the `%auto` argument:
  - If `"auto"` not in expanded args → `auto_mode = None`.
  - Else take the raw arg; bare (`""`) and the plus-suffix form (`"true"`) → `"plan"` (default).
  - Validate the value is one of `{"plan", "tale", "epic"}`; otherwise raise `DirectiveError` with a message listing
    valid modes (e.g. `"Unknown %auto mode 'foo'; valid modes are: plan, tale, epic"`).
- Update the explanatory comments (the block at the `PromptDirectives(...)` build site and the `%t`-means-`%tale`
  comment in `has_deferred_start_directive`) to describe `%auto`.
- Note: `_directive_alt.py`, `multi_prompt_*`, `retry_prompt.py`, `names/_resume.py`, `launch_validation.py`,
  `history/prompt_metadata.py` all consume `_DIRECTIVE_ALIASES`/`_KNOWN_DIRECTIVES` **dynamically** — they need no logic
  changes; they automatically follow the new tables. Verify nothing hardcodes the literal strings
  `"plan"`/`"tale"`/`"epic"` as directive names (grep confirms none do).

### Part B — Python consumer (`src/sase/axe/run_agent_directives.py`)

This is the single place that turns parsed auto-approve directives into agent meta. Replace the `directives.approve` /
`directives.epic` / `directives.tale` branches with `auto_mode` logic that preserves today's exact meta output:

- `auto_mode == "plan"` → `agent_meta["approve"] = True` (no `plan` key).
- `auto_mode == "epic"` → `agent_meta["auto_approve_plan_action"] = "epic"` and `agent_meta["plan"] = True`.
- `auto_mode == "tale"` → `agent_meta["auto_approve_plan_action"] = "tale"` and `agent_meta["plan"] = True`.
- The returned `AgentInfo`: `approve=(auto_mode == "plan")`, `plan=(auto_mode in {"epic", "tale"})`.

(Behavior is byte-for-byte identical to today; only the source field changes.)

### Part C — Directive emitters (literal `%plan` / `%epic` in generated prompts)

- **`src/sase/bead/work.py`**: replace the emitted literal `"%plan"` lines with `"%auto"`, and the emitted `"%epic"`
  line with `"%auto:epic"`. (Epic-work phase/land segments use `%plan`→`%auto`; legend epic-planning segments use
  `%epic`→`%auto:epic`; the trailing land segments use `%plan`→`%auto`.)
- **`xprompts/pylimit_split.yml`**: the generated agent line `... %group:chop %plan ...` → `... %group:chop %auto ...`.

### Part D — Python editor/completion widget (`src/sase/ace/tui/widgets/directive_completion.py`)

- Drop the `_DEPRECATED_DIRECTIVE_ALIASES` import and the filtering branch in `_aliases_by_directive` (nothing is
  deprecated anymore).
- `_DIRECTIVE_ARGUMENT_HINTS`: remove `plan`/`tale`/`epic`; add `"auto": ":plan|tale|epic"` (it now takes an argument).
- `_DIRECTIVE_DESCRIPTIONS`: remove `plan`/`tale`/`epic`; add an `"auto"` description, e.g.
  `"auto-approve the submitted plan as plan (default), tale, or epic"`.
- `_USER_FACING_DIRECTIVES` derives from `_KNOWN_DIRECTIVES`, so it updates automatically.
- (Python TUI does **not** do directive argument-value completion — only static hints — so no value-list arm is needed
  here. Argument-value suggestions live only in the Rust/LSP path; see Part F.)

### Part E — Code comments referencing the old directives

Sweep and update stale code comments that name the old directives so nothing in active source references them. Known
sites: `src/sase/ace/tui/models/agent.py` (~232), `src/sase/ace/tui/widgets/_agent_list_styling.py` (~85),
`src/sase/ace/tui/models/_loaders/_meta_enrichment_filesystem.py` (~250), `src/sase/ace/tui/actions/agents/_approve.py`.
These are comment-only edits (the code keys off the unchanged `auto_approve_plan_action`/`approve` meta, not the
directive).

### Part F — Rust core mirror (`../sase-core`, crate `sase_core`)

Open the linked repo via `sase workspace open -p sase-core -r "<reason>" <workspace_num>` and edit there.

**`crates/sase_core/src/editor/directive.rs`**

- `DIRECTIVES` table: remove the `plan`, `tale`, `epic` entries; add one `auto` entry: `name: "auto"`,
  `alias: Some("a")`, `takes_argument: true`, `allows_multiple: false`, with a description covering the plan|tale|epic
  modes.
- `DEPRECATED_ALIASES`: remove the `("approve","plan")` / `("a","plan")` entries — simplify to an empty slice or delete
  the constant and the loop in `canonical_directive_name` that consults it.
- `directive_argument_candidates`: remove `plan`/`tale`/`epic` from the empty-`&[]` arm; add an `"auto"` arm returning
  `[("plan", …), ("tale", …), ("epic", …)]` so the editor suggests the three modes.
- Tests in this file: rewrite/replace `resolves_documented_aliases`,
  `plan_and_tale_are_the_advertised_auto_approve_directives`, `directive_completion_t_prefix_yields_tale_and_time`, and
  `approve_is_a_hidden_deprecated_alias_of_plan` to reflect: `%a`→`auto`; `%auto` advertised with arg candidates
  plan/tale/epic; `%p`/`%t`/`%approve` no longer resolve; `%t`-prefix now yields only `time`.

**`crates/sase_core/src/agent_launch/mod.rs`**

- The fan-out planner uses `canonical_directive_name` dynamically — no logic change. Update the test assertion that
  expects `canonical_directive_name("t") == "tale"` (it no longer resolves) and refresh the nearby comment that
  enumerates `%p`→`plan` / `%t`→`tale` / `%a`/`%approve`→`plan`.

**CHANGELOG** — the sase-core (and main repo) changelogs are conventional-commit generated; the breaking change is
captured by the commit message, not a manual edit.

### Part G — Documentation (active docs + blog posts)

Rewrite to present `%auto` (with `%a` alias and the `:plan|tale|epic` argument; default `plan`) as the single directive,
removing the three-row tables and the `%approve`/`%a`/`%p`/`%t` deprecation notes:

- `docs/xprompt.md` — the main reference: the directive table rows, the example code blocks, the per- directive
  "Plan/Tale/Epic Directive" sections, and the deprecation notes. Consolidate into one `%auto` entry/section documenting
  the argument. (Leave the unrelated `%time`/`%t` and `%edit` lines — except the note "`%t` now means `%tale`", which
  should be removed since `%t` no longer exists.)
- `docs/ace.md` — the `⚡`/`⚡T`/`⚡E` icon descriptions and the `%plan`/`%tale`/`%epic` mention in the auto-approve
  section → describe them as `%auto` / `%auto:tale` / `%auto:epic`.
- `docs/beads.md` — the bead-work explanation that references emitted `%plan`/`%epic` → `%auto`/`%auto:epic`.
- `docs/workflow_spec.md` — the `#!sase/pylimit_split %plan` example → `%auto`.
- `docs/blog/posts/xprompts-in-depth.md`, `docs/blog/posts/why-coding-agents-need-orchestration.md`,
  `docs/blog/posts/beads-and-sdd.md` — rewrite the directive tables/examples to `%auto`.
- Leave `docs/images/xprompt-resolution-infographic.critique.md` (historical critique).

### Part H — User chezmoi config

- `~/.local/share/chezmoi/home/dot_config/sase/sase_athena.yml` (line ~76): the axe lumberjack agent line ends with
  `%approve` → change to `%auto`. (Apply with `chezmoi apply` after editing the source, per the user's normal dotfile
  workflow.)

### Part I — Tests

Update the test suite to the new directive and field. Major buckets:

- **Directive parse tests** — `tests/test_directives_flags.py` (the bulk: all `%plan`/`%p`/`%plan+`/
  `%tale`/`%t`/`%tale+`/`%epic`/`%approve`/`%a` cases and `.approve`/`.tale`/`.epic` assertions),
  `tests/test_directives_extract.py`, `tests/test_directives_time.py`, `tests/test_directives_time_repeat.py`,
  `tests/test_directives_has_helpers.py`. Replace with `%auto` / `%auto:tale` / `%auto:epic` / `%a` cases asserting
  `directives.auto_mode == …`, plus new cases: bare `%auto` → `"plan"`, invalid `%auto:foo` raises,
  `%p`/`%t`/`%approve`/`%a`(old sense) no longer resolve (now unknown tokens), and `%t`/`%time` behavior.
- **Completion tests** — `tests/ace/tui/widgets/test_directive_completion.py`: assert `%auto` is advertised with the
  `%a` alias; `%plan`/`%tale`/`%epic`/`%approve` no longer appear; the deprecated-alias-hiding tests are removed.
- **Bead rendering tests** — `tests/test_bead/test_work_rendering.py`, `tests/test_bead/test_work_legend_plan.py`,
  `tests/test_bead/test_cli_work_legend.py`, `tests/test_bead/test_cli_work_epic_launch.py`,
  `tests/test_bead/test_work_epic_plan.py`: update expected prompt strings (`%plan`→`%auto`, `%epic`→`%auto:epic`) and
  the `"%plan"`/`"%epic"` substring/count assertions.
- **Meta / agent-name tests** — `tests/test_agent_names_extract.py` (the `%epic`/`%tale` directive →
  `auto_approve_plan_action` tests now drive the directive as `%auto:epic`/`%auto:tale`). The downstream
  `auto_approve_plan_action`/`agent.approve`/visual-snapshot tests that already use
  `auto_approve_plan_action="tale"/"epic"` directly (e.g. `test_enrich_agent_plan_meta.py`,
  `test_agent_toggle_approve.py`, `test_core_agent_scan_records.py`, the PNG snapshot interactions) stay as they test
  the unchanged downstream representation — only update any that _parse a directive_.
- **History/metadata tests** — `tests/history/test_prompt_metadata.py`: the summarized directive token for the
  auto-approve directive changes from `p` to `a` (so a `%plan`+`%model` summary `"%mp"` becomes a `%auto`+`%model`
  summary `"%ma"`). `tests/history/test_chat_resume_sanitize.py`: the `%approve` sanitization case → use `%auto` (since
  `%approve` is now an unknown token that is _not_ stripped).
- **Visual PNG snapshots** — if any directive/footer rendering snapshot shifts, re-accept intentionally with
  `just test-visual --sase-update-visual-snapshots`.

---

## Risks & sequencing

- **Python↔Rust parity**: land the Python and Rust changes together; a mismatch makes the Neovim editor and the Python
  TUI advertise different directive sets. There is no shared fixture to diff, so the parity is enforced by review.
- **Silent breakage of saved prompts**: by decision (1), any saved prompt-stash pin / history entry / personal xprompt
  still using `%plan`/`%tale`/`%epic`/`%approve` stops being recognized and is left as literal text. This is the
  accepted, intended outcome. The chezmoi `%approve` site (Part H) is the one known live config that must be migrated to
  avoid a broken agent launch.
- **`%auto` argument edge cases**: bare and `+`-suffix forms default to `plan`; only the colon form selects a mode;
  invalid modes raise a clear `DirectiveError`. Cover these in tests.

## Validation

- `just install` (ephemeral workspace) then `just check` (ruff + mypy + pytest, incl. PNG snapshots) in the main repo.
  Note: a pre-existing set of ~8 `llm_provider` `invoke_agent` failures from the dev env's `default_effort: xhigh` is
  unrelated to this change.
- In `../sase-core`: `cargo test -p sase_core` (and `cargo fmt`/`clippy` per that repo's check).
- Manual smoke: `%auto`, `%auto:tale`, `%auto:epic`, `%a`, and an invalid `%auto:foo` through directive extraction;
  confirm `sase bead work` emits `%auto`/`%auto:epic`; confirm editor completion of `%a`/`%auto` in both the Python TUI
  prompt bar and the Neovim LSP.
- A repo-wide grep for `%plan`/`%tale`/`%epic`/`%approve` returns only historical (`sdd/`, `CHANGELOG.md`,
  `*.critique.md`) hits, and the same grep across `../sase-core` and the chezmoi repo returns nothing active.
