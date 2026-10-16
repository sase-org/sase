---
title: Launch Control overrides
description: Temporary overrides, persistent alias edits, and examples in sase TUI Launch Control.
---

# Launch Control overrides

This page lists temporary overrides, persistent alias edits, and examples in sase TUI
Launch Control.

## Temporary overrides

`Edit` and `Override` open the shared model picker with an `ALIASES` group before the
provider-grouped concrete models. Alias rows show the exact `@name` token and its
current effective provider/model; filter by either `@medium` or `medium`, an alias kind
or description, or the displayed target. For persistent edits, the current alias and any
alias that would introduce a direct or transitive cycle remain visible but unavailable
with a concise reason. `Custom...` accepts a concrete model string, `provider/model`
path, or bare `@alias` reference in both flows and applies the same safety check to
free-form `@alias` values. Concrete model rows for **hard**-disabled providers are
omitted; **soft**-disabled providers stay in the picker (header labelled `soft`, rows
dimmed one step), priority providers are labeled `priority`, and priority backups are
labeled `backup`. Alias rows remain visible and show their current live fallback target.
Free-form explicit input is validated before submission and reports the same
disabled-provider diagnostic as a launch. In `Edit`, `Custom...` additionally accepts a
typed `|` pool or `||` fallback expression and opens prefilled with the alias's current
value, so changing one member of an existing selector does not mean retyping the whole
expression; `Edit` also offers a guided `Pool / fallback...` row next to `Custom...`
that builds a selector from the picker without typing `|` by hand (see
[Persistent edits](#persistent-edits) below). In `Override`, a typed pool or fallback is
refused outright with a message pointing at `e` — selectors are config-only and
overrides take a single target, so `Override`'s `Custom...` never shows the
`Pool / fallback...` row.

`Override` continues from the picker to the duration picker (`15m`, `30m`, `1h`, `2h`,
`4h`, `Until cleared`, or a custom duration like `45m`, `1h30m`, `90m`). Press `t` in
the duration picker to choose **Until a specific time**. The focused time popup accepts
local forms such as `5pm`, `5:30 PM`, `17:30`, `1730`, `today 5pm`, `tomorrow 9am`, and
`2026-07-12 09:00`. An undated clock means its next occurrence (later today or
tomorrow); an explicit day/date must still be in the future.

The popup previews the resolved weekday/date, local time and abbreviation, configured
IANA timezone, and remaining duration before Enter writes anything. Daylight-saving gaps
are rejected; repeated fall-back times require an offset-qualified ISO value such as
`2026-11-01T01:30-04:00`. Invalid input stays focused with an inline explanation. `Esc`
goes back to the duration picker, where a second `Esc` cancels the override flow.
Overrides are per-alias and per-launch-setting, and independent:

- An override on **`default model`** drives the no-`%model` launch default. It renders
  in a gold status-row pill as `PROVIDER(model)[@<effort>] <time-left>` — the model half
  of the launch-context cluster at the far right of each tab's status row.
- An override on **any built-in size alias or custom alias** takes effect wherever that
  alias is resolved. A size-specific phase or task override affects only that alias. An
  override on a selector-valued alias — a `|` load-balanced pool, `||` ordered fallback,
  or parenthesized `(A | B) || C` last-resort, such as the shipped size-alias selectors
  (see the generated
  [shipped size-alias defaults](../providers/models.md#implicit-role-aliases)) —
  suspends that alias's own rotation/fallback for a single concrete target until the
  override expires or is cleared.
- An override on **`epic lander`** or **`big epic lander`** affects only epic land
  agents below, or at/above, `bead.big_epic_phase_threshold`, independently of
  `default model` and of each other.

Every non-default override (an alias, `epic lander`, or `big epic lander`) is surfaced
by the alias pill inside the labeled `overrides:` violet top-bar group: a single active
override renders as `overrides: @<alias>[@<effort>] <time-left>` or as
`overrides: epic lander <time-left>` / `overrides: big epic lander <time-left>`, and
several render as `overrides: <first> +N`, naming the alphabetically first overridden
alias or launch-setting label and counting the rest. That alias pill sits beside the
priority and disable pills when those are active. In both pills, lane color carries the
"override" meaning while the effort suffix and time use a recessive tone; `∞` means
until cleared. Hover the group for full target and expiry details, or click it to open
Launch Control.

When no override is active, the same status-row chip instead names the current launch
default — the smallest `%model` value that would pin this exact target (a bare model
name such as `grok-4.7` when the model unambiguously names its provider, otherwise the
explicit `codex/o3` form) plus the optional `[@<effort>]` suffix, with no background
accent — and stays live for the whole sase's TUI session. The label is toned with the
launch default's provider: the model name takes the provider's model hue (the same one
the model picker uses, for example Grok cyan, Claude amber, or Codex mint) and the
`@<effort>` suffix takes a recessive tone from the same hue family, so the two-tone
shape matches the override pills. Provider hue is the calm lane's identity axis, while
the override lanes keep their gold and violet accents for the override meaning. While
the default is still resolving (`...`) or unavailable, the pill keeps a neutral dim-cyan
tone rather than guessing a provider. A model alias is never used as the pill's subject,
since an alias may be a rotating pool rather than one concrete model. The optional
`@<effort>` suffix is the launch-effective default a no-`%model` / no-`%effort` prompt
will actually receive (alias-borne effort, a temporary default-effort override, or
`llm_provider.default_effort`); it is omitted when that value is unset. If
`llm_provider.default_model` (directly or through a referenced alias, such as a shipped
size-alias pool) resolves to a load-balanced `|` pool, the pill follows the pool's
round-robin cursor as it advances: a launch consumes one member, and within a few
seconds the pill flips to name whichever member runs next. For a cross-provider `|` pool
the pill's hue flips with it, so the color tells you which provider the _next_ launch
will actually hit. It never resolves on the UI thread and never advances the cursor
itself — it only reflects state that a real launch already changed. Hover the pill for a
`<alias> rotates across N models; PROVIDER(model) is next` line whenever the default
routes through such a pool. The tooltip deliberately keeps the provider-qualified
`PROVIDER(model)` form: the pill is the width-constrained surface and stays compact, and
color is never the only carrier of the provider, so hovering is the authoritative
confirmation of which provider the launch default resolves to.

Overrides do not displace explicit launch intent: explicit prompt directives
(`%model:codex/o3`, `%model:opencode/anthropic/claude-sonnet-4-5`) and an explicit
`provider_name` argument always win, already-running agents keep their current
provider/model. A temporary **hard** provider disable is different: an explicit request
for a hard-disabled provider fails with a provider-and-expiry diagnostic rather than
silently switching providers. A **soft** disable never fails that explicit request.
Override state is persisted to `~/.sase/llm_override.json` — shared across all sase
processes on the machine — and is best-effort self-cleaning: expired or malformed
entries are pruned on next read. `Until cleared` is a no-expiry mode — convenient, but
still a _temporary_ state, not a permanent config edit. The temporary override is
independent of `SASE_MODEL_TIER_OVERRIDE`; a concrete override takes the full
provider/model path, while the tier override only applies when no concrete override is
active.

Delegated launches (plan coder follow-ups and `sase bead work` phase, task, and land
agents) route directly through the
[built-in size aliases](../providers/models.md#role-aliases-for-delegated-work)
configured under `llm_provider.model_aliases.builtin`, plus the
`epic lander`/`big epic lander` launch settings — there is no more role-alias
indirection through a separate `default`/`smart`/`cheap`/etc. lane. A phase or task
selects `@xsmall`, `@small`, `@medium`, `@large`, or `@xlarge` by its normalized size
directly; a phase or task without size metadata uses the `@small` fallback. Epic land
agents without an explicit land model use `epic_lander_model` (shipped `@large`) below
`bead.big_epic_phase_threshold`, or `big_epic_lander_model` (shipped `@xlarge`) at or
above it. Because `epic lander` and `big epic lander` are configured as raw alias
references, a temporary override on the alias they reference (`@large` and `@xlarge` by
default) cascades into their effective resolution; overriding `epic lander` or
`big epic lander` directly takes precedence over that nested reference. A temporary
override on a selector-valued built-in size alias — any shipped size-alias pool or
fallback (see the generated
[shipped size-alias defaults](../providers/models.md#implicit-role-aliases)) —
suspends only that alias's own rotation/fallback and does not cascade to any other alias
or launch setting.

## Persistent edits

`Edit` and `Reset` change the alias's value in `sase.yml` itself, written through the
Rust-backed, source-preserving config-edit path (comments and key order are preserved).
The change is shown in a preview/confirm step before it is written, and after a
successful write the panel offers to **commit and push** it (`y`/`n`). With
`use_chezmoi: true` the edit targets the chezmoi source and the commit/push runs against
the chezmoi repo followed by `chezmoi apply`; when the target file is not in a git repo
the commit offer is skipped and the file is simply written. An active temporary override
visually "wins" the effective-target column even after a persistent edit; the state tag
distinguishes the _configured_ value from the _currently effective (overridden)_ one.

Selecting an alias during `Edit` stores the raw reference (for example, editing
`epic lander` to `@xlarge`), so it remains a dynamic link and follows future changes to
`@xlarge`. Selecting an alias during `Override` instead resolves it when the override is
written and stores that concrete provider/model snapshot together with the raw token;
later changes to the referenced alias do not change the active override. A canonical
trailing effort is snapshotted with the target and shown in the row, success
notification, and single-override pill (the gold status-row chip for a `default model`
override, the violet top-bar pill otherwise). A known suffix on an alias reference is
ignored for dependency/cycle checks but retained for the written value; unknown trailing
`@token` text is not treated as effort.

Builtin aliases edit under `llm_provider.model_aliases.builtin.<name>`. User aliases
under `llm_provider.model_aliases.custom.<name>` edit their `model` field and reset by
deleting the whole custom alias entry. The custom input also accepts a `|`-separated
load-balanced pool, a `||`-separated ordered fallback, or a parenthesized `(A | B) || C`
last-resort. The editor rejects empty or unparenthesized mixed selectors and alias
references that would reach any nested selector before opening the write preview.

Choosing `Pool / fallback...` from the `e` picker opens a guided builder instead of
typing an expression by hand. It seeds its state from the alias's current value — an
existing `|` or `||` expression expands into its members and mode, a parenthesized
`(A | B) || C` value populates the pool plus last-resort tail, a single target becomes a
one-member list, and an empty value starts blank — and shows the live normalized
expression as members change. `a` adds a pool member through the same model picker and
effort ladder used elsewhere in the panel (its own `Custom...` accepts a bare model,
`provider/model` path, or `@alias`, with an optional trailing `@effort`); `f` adds a
last-resort candidate the same way; `d` removes the highlighted member; `J` / `K`
reorder it down and up without crossing the pool/tail boundary; `E` sets or clears that
member's effort; `w` / `W` raise and lower a pool member's weight and ignore last-resort
rows; `t` toggles between round-robin pool and ordered fallback, and refuses while a
last-resort tail is present; `enter` confirms and routes the composed expression to the
same preview/write path as a typed value; `esc` cancels back to the picker. As in the
top-level Edit picker, an alias reference that would reach another pool or fallback is
unselectable here. Confirm is blocked, with an inline reason, while the selector has
fewer than two pool members or the live validation line reports an error.

## Examples {#examples-1}

- Highlight `default model`, `o`, pick `codex/o3`, duration `1h` — launches with no
  `%model` directive use Codex `o3` for the next hour, then revert to the configured
  default.
- Highlight `@medium`, `o`, pick a model, then `t`, enter `5pm` — the preview resolves
  the next 5:00 PM in the configured timezone and the override expires at that exact
  instant.
- Highlight `@small`, `o`, pick `claude/opus`, and choose `Until cleared` — small phases
  and tasks without an explicit model use CLAUDE(opus) until you clear it; the violet
  non-default pill appears in the top bar.
- Highlight `@large`, `e`, pick `claude/opus`, and confirm — only large phases and tasks
  without an explicit model use that target, replacing the shipped pool (see the
  generated
  [shipped size-alias defaults](../providers/models.md#implicit-role-aliases));
  other-sized phase/task routing is unchanged.
- Highlight `@xlarge`, `e`, pick `claude/opus`, and confirm — xlarge phases and tasks
  use that target directly, and `big epic lander` (left at its shipped `@xlarge`
  reference) inherits the same change.
- Leave `@xlarge` implicit — xlarge phases, tasks, and threshold-selected epic landers
  (which reference `@xlarge` by default) select the first available member of its
  fallback chain (see the generated
  [shipped size-alias defaults](../providers/models.md#implicit-role-aliases)).
- Highlight `@xsmall`, `e`, choose `Custom...`, enter
  `claude/haiku@minimal | codex/gpt-4.1-mini@low`, and confirm — xsmall phases and tasks
  round-robin across installed providers while the panel continues to show the next
  selection without consuming it.
- Highlight `@small`, `e`, choose `Custom...`, enter
  `claude/haiku | codex/gpt-4.1-mini`, and confirm — small phases and tasks round-robin
  across this independent pool without consuming the `@xsmall` cursor.
- Highlight `@medium`, `e`, choose `Custom...`, enter
  `claude/haiku@minimal | codex/gpt-4o-mini`, and confirm — medium phases and tasks
  round-robin across this independent pool without consuming the `@xsmall` or `@small`
  cursor.
- Press `t` — open tmux Agent, then `c` or Enter on Claude Code to launch it in a new
  `ai` window; `s` launches once without approval-bypass flags.
- Press `p`, highlight `claude`, `d`, choose `1h` — new alias-backed launches route
  around Claude for the next hour, direct `%model:claude/opus` launches fail explicitly,
  and already-running Claude processes continue.
- With `claude` disabled, an override on `@medium` that targets `claude/opus` pauses;
  the row shows the live fallback target until Claude is re-enabled or the disable
  expires.
- Highlight `big epic lander`, `e`, pick a model, and confirm — only threshold-selected
  epic landers use that persistent target; leaving it implicit inherits through its
  shipped `@xlarge` reference, independently of `epic lander`.
- Highlight `big epic lander`, `e`, filter for `@large`, select it, and confirm — the
  persistent value is the dynamic `@large` reference, not a copied concrete model.
- Highlight `@medium`, press `o`, select `@xlarge`, then choose `1h` — the override
  records the concrete provider/model to which `@xlarge` resolves at write time while
  retaining `@xlarge` as its raw input.
- Highlight an alias or launch setting, `x` — clear its temporary override; `r` — unset
  its configured value back to its implicit fallback.

See
[Temporary model overrides](../providers/routing.md#temporary-model-overrides)
for the resolution order and state-file format.

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Launch Control](launch-control.md) — usage, effort, capacity, routing, drain, and tmux Agent.
- [Provider routing](../providers/routing.md) — temporary overrides, disables, and priority.
