---
title: Launch Control
description: Launch Control keys for usage, effort, capacity, routing, drain, tmux Agent, and alias history.
---

# Launch Control

This page lists Launch Control keys for usage, effort, capacity, routing, drain, tmux
Agent, and alias history.

## Launch Control {#launch-control-1}

Press `,m` from any tab to open **Launch Control** — one keyboard-driven surface for
launch configuration, model aliases, temporary provider routing, and launching an
interactive agent CLI in a new tmux window. The top level has three visible sections:
**Launch settings**, **Built-in size aliases**, and **Your aliases**. Consecutive
visible sections are separated by exactly one non-selectable blank row; there is no
leading, trailing, or doubled spacer.

Data rows use the grid `ownership gutter | name | value/model | state`. The former row
kind column is gone: labels such as `launch`, `setting`, `role`, `user`, and `bucket` do
not appear as their own column. User-owned aliases and buckets still have the tan `▌`
ownership gutter, misplaced built-in aliases keep a gold `!` marker in the name cell,
and collapsed buckets put `▸` directly before the bucket name.

**Launch settings** contains six rows: `default model`, `epic lander`,
`big epic lander`, `big epic starts at`, `default effort`, and `max runners`. The three
model rows show raw alias/config value → effective provider/model. `big epic starts at`
shows the effective `bead.big_epic_phase_threshold` as `<N> phase` or `<N> phases`:
epics with `N` or more authored phases use the big epic lander, while smaller epics use
the regular epic lander. `default effort` and `max runners` show their launch-effective
scalar values and any active temporary override state.

Alias rows show the alias name, effective provider/model as a provider-themed badge, and
a state tag — `configured`, `implicit` / `implicit → @<fallback>` /
`implicit → @<fallback> @ <effort>`, or an `override · <time> left` /
`override · until cleared` chip when a temporary override is active. Configured
references use the same `configured → @<target> @ <effort>` form. A model-specific
effort carried by an override appears beside the effective provider/model badge. When
one or more providers have temporary routing state, the title adds a compact line for
active priority and/or disables. Priority renders as `priority: CODEX ★ <time>`, hard
disables as `disabled providers: CODEX <time>`, and soft disables as
`CLAUDE soft <time>`.

The alias area is split into **Built-in size aliases** and **Your aliases**. Each header
reports the aliases represented by its rows (including members of collapsed custom
buckets) and its bucket count. **Built-in size aliases** always lists exactly five rows
in size order — `@xsmall`, `@small`, `@medium`, `@large`, `@xlarge` — with no bucket to
drill into; each row is edited, overridden, reset, or cleared directly like any other
alias row. **Your aliases** holds only user-owned aliases and custom buckets, in
alphabetical order. If there are no custom aliases or buckets, **Your aliases** remains
visible with a non-selectable hint naming `llm_provider.model_aliases.custom`.

Custom buckets group your own aliases under a shared display name, either through
`model_aliases.buckets.<name>` or a custom alias's `bucket:` tag; there is no built-in
bucket for a custom alias to join, so every bucket that appears is entirely user-owned.
Each collapsed bucket row reports the member count and active overrides, while the
description strip summarizes distinct effective models. Open a bucket with `l`, Right,
or Enter; return with `h` or Left. Inside the bucket, each alias keeps its own
configured/implicit state and can be edited, reset, overridden, or cleared
independently. A configured description under `model_aliases.buckets.<name>` replaces
the default. A custom bucket renders its bucket state in the ownership accent, and the
drilled-in title ends with `· custom bucket` plus the ownership glyph.

The two-line strip below the list explains the highlighted row. Launch settings show
their config path, effective value, and boundary/override context. Builtin aliases use
fixed descriptions. User aliases use
`llm_provider.model_aliases.custom.<name>.description`; a malformed user alias without
one shows that config path as the fix. A non-pool alias with an explicit effort uses the
second line to say whether it matches or overrides the configured default. For a
selector-valued alias, the strip lists every parsed member with an available/unavailable
marker. A round-robin pool's row state includes an availability count such as `pool 2/2`
that counts only pool members (a last-resort tail does not inflate the denominator), and
`→` marks the exact next peeked selection without advancing its cursor — including when
the tail is selected. After the last pool member, a `fallback:` separator introduces
last-resort rows. An ordered fallback labels candidates in priority order, marks the
current winner, and never reads rotation state. The row's provider/model/effort badge is
derived from that same selected member. Temporarily **hard**-disabled providers count as
unavailable for this display and render as a red `×`. Soft-disabled members stay
selectable and still count in `pool <available>/<total>`: a selected one renders as
amber `→ ✓ provider/model@effort`, and a spared one as amber `× provider/model@effort`,
with no trailing `soft` chip. Temporary provider priority uses distinct wording: the
preferred member is labeled `priority`, and other usable members that remain behind it
are labeled `backup`. If a temporary alias override targets a **hard**-disabled
provider, the override is preserved but paused: the row shows the live fallback/pool
target, the state tag says the override is paused, and the description names the
disabled provider that must expire or be re-enabled before the override resumes. An
active override whose provider remains available, including a soft-disabled one, still
bypasses selector choice for the override's lifetime.

If a builtin size alias is mistakenly configured under
`llm_provider.model_aliases.custom`, opening the panel emits one warning toast listing
every affected `@alias`. A gold warning glyph remains on the affected alias row even
while a temporary override is active, and highlighting it replaces the normal
description with the same actionable advice. Move the entry's `model` value from
`llm_provider.model_aliases.custom` to `llm_provider.model_aliases.builtin`; sase's TUI
identifies the misplaced entry but does not rewrite the configuration automatically.
Because ownership follows the alias kind rather than where it is configured, the
misplaced alias stays in the **Built-in size aliases** section — never inside a custom
bucket — and does not receive the ownership gutter.

Navigate with `j`/`k` (or arrows / `Ctrl+N` / `Ctrl+P`) and act on the highlighted row.
Navigation, and jump hints, skip headers, spacer rows, and the empty-custom hint.

| Key                   | Action                                                                                                              |
| --------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `l` / Right / `Enter` | **Open** the highlighted bucket                                                                                     |
| `h` / Left            | **Back** to the top level from an open bucket                                                                       |
| `'`                   | **Jump** — paint adaptive hints; a hint moves the highlight without activating the row, and a second `'` jumps back |
| `o`                   | **Override** — set/change a time-bound temporary alias/default-effort/runner-limit override                         |
| `x`                   | **Clear** — remove the active temporary override on the highlighted override-capable row                            |
| `e`                   | **Edit** — change the persistent configured value                                                                   |
| `r`                   | **Reset** — unset an alias/model setting or the big-epic threshold                                                  |
| `p`                   | **Providers** — disable, prioritize, or re-enable registered providers for future routing                           |
| `u`                   | **Usage** — inspect cached provider subscription usage and request a bounded update                                 |
| `t`                   | **tmux Agent** — launch an interactive agent CLI in a new tmux window                                               |
| `H`                   | **History** — view recorded prior runs for the highlighted alias, alias-backed launch setting, or bucket            |
| `Ctrl+E`              | **Effort** — persistently edit, temporarily override, or clear the global default effort                            |
| `Ctrl+R`              | **Limit** — persistently edit, temporarily override, or clear the global runner limit                               |
| `Esc` / `q`           | Close the panel                                                                                                     |

### Providers · Usage

Press `u` in Launch Control to open the read-only **Providers · Usage** view. The same
view is available from the global command palette as **Open Providers · Usage**, with
search aliases including usage, quota, limits, capacity, subscription, and providers.

The first paint reads only the local usage cache. Each provider row shows remaining
capacity or collection status, applicable account scope, freshness, and an **Updating…**
marker when a durable refresh is live. Select a provider for its plan, account mode,
collection status, last observation, and per-window remaining percentage, reset, age,
state, and source. The layout drops the meter and combines detail columns as the
terminal narrows.

Rows reserve the orange `⚠ failing` badge for collectors with three or more consecutive
probe failures. The selected provider detail shows collector health for both degraded
and failing states, including the failure streak, failing-since age when known, and last
successful probe age when known. This health describes the collector pipeline only:
stale-but-numeric allowance data can still render, passive stream observations do not
hide a dead probe pipeline, and the indicator never changes launch routing.

The application header groups independently selected usage windows by provider on the
right of the existing title row, for example:

```text
🎭 62% 3d4h · fable 0% 1d8h  🤖 81% 5d2h
```

The title is centered on the header line. Usage occupies a right-docked reserve sized so
the complete title still fits centered; changing usage text never moves the title, and
the navigation and routing controls on the row below stay put. The complete title has
priority: sase's TUI never truncates it merely to show more usage, and a clipped title
keeps the full string in its tooltip.

The rendered segment owns one quiet space before the first provider icon and one after
the block. Each provider icon appears once, followed by one space, and providers are
separated by two quiet spaces with no inter-provider punctuation. Windows of the same
provider are joined with a middle dot (`·`). A single visible window has no extra
separator even when hidden windows remain.

The default weekly all-model window renders as `<remaining-percent> <reset-countdown>`;
additional selected windows include compact names such as `fable`, `5h`, `mo`,
`5h/fable`, or `5h/gemini`. Compact names omit redundant weekly and all-model components
and drop the `family:` prefix of family-scoped windows (`5h/3p`, not `5h/family:3p`)
while retaining model/family distinctions; tooltips (`scope: family: 3p`) and
`sase usage list` (`scope=family:3p`) still show the session scope; `scope?` means the
provider did not expose exact applicability. The name, percentage, and reset countdown
share the window's ten-step remaining-capacity color, from red (nearly exhausted) to
blue (nearly full), except an exact `0%` highlights the window's whole value run — its
name, percentage, and reset countdown together — with the inverted red style. Provider
icons, middle dots, provider gaps, and outer padding keep their normal surfaces; a
non-zero window's name and rejected marker do too. Structural punctuation is neutral,
normal weight in both themes. Which windows appear, and at what remaining percentage, is
fully configurable through
[`llm_provider.usage_metrics.indicator`](../config/llm-provider-behavior.md#llmproviderusagemetrics).

Stale or unknown-age numeric observations render with neutral text and disclose their
freshness in the tooltip instead of adding a visible marker. `<1%` remains a low but
nonzero reading on the normal badge surface. `?% 0h0m↻` means the window's reset has
passed and sase's TUI is awaiting a new observation, retaining the last known percentage
only in the tooltip. A bare `?` in the countdown position means the provider never
reported a reset time. `!` marks a vendor-rejected window that still shows remaining
capacity. An exact `0%` window never shows it, because the inverted red run already
signals exhaustion, so every provider's exhausted window looks the same whether or not
its vendor reports a rejection. Collector failures no longer add a header warning glyph;
selected failing windows keep collector-failure prose in the tooltip, and model picker
hints keep their own separate `⚠ usage failing` identity.

Provider groups always render in provider-name order. Within a provider, the default
weekly all-model window is first, followed by additional windows by window key.
Attention is shown only through color and markers; it never changes order. sase's TUI
shows the longest prefix of complete windows that fits the measured header remainder
after the icon and unclipped title, allowing the final provider group to be partially
visible, before adding a `+N` overflow count. If no complete window prefix plus
disclosure fits, sase's TUI falls back through `usage N`, `N`, and `…`, relaxing the
text-only padding at one-cell boundaries. Every selected and overflowed window's full
identity, exact key, precise percentage, scope, effective display policy, and reset
timestamp are in the tooltip. Clicking the usage cluster — including a window, `+N`,
`usage N`, a bare count, or `…` — opens Providers · Usage at the first displayed
provider and does not expand the header. Clicking the routing pill still opens Config >
Launch. The Usage command is also reachable from Launch Control's `u` and the command
palette when there is no display space at all.

Press `u` inside the view to submit or join bounded refresh work for eligible providers.
The modal stays responsive, reattaches to an in-flight refresh when reopened, reloads
the cache as operations settle, and reports partial failures by provider. `Enter`
focuses the detail table, `Tab` moves focus, `j`/`k` navigate, and `Esc`/`q` closes.
Collection requires `llm_provider.usage_metrics.enabled`; see
[Subscription Usage](../providers/usage.md#subscription-usage).

On `big epic starts at`, `Enter` and `e` open a focused positive-integer editor, and `r`
previews a reset. The input accepts an unsigned base-10 whole number with minimum `1`
and no spaces, signs, floats, or booleans; the inline constraint reads
`minimum 1 · package default 5`. The preview targets the writable user-base `sase.yml`
or its chezmoi source at `bead.big_epic_phase_threshold`. Reset uses an unset operation
so lower-precedence or package defaults resume; it does not write a literal `5`. There
is no temporary threshold override. Pressing `o` or `x` on that row warns and points
back to Edit/Reset.

After a successful threshold write, Launch Control reloads the effective value and the
epic-lander row descriptions from the same provider/launch snapshot. If a
higher-precedence layer keeps the requested user value from winning, the notification
reports the actual effective value and the requested value. Dirty Git-backed targets
receive the standard tracked commit/pull/push offer with
`chore: update big epic phase threshold`.

### Default effort controls

`Ctrl+E` works from every alias and bucket row because default effort is global. The
**Default Effort** card shows the exact value used for new launches and, while a
temporary override is active, the configured value beneath it. Press `e` to edit
permanently, `o` to override temporarily, or `x` to clear the active temporary override;
`x` is shown only when there is something to clear. Explicit prompt effort and effort
carried by an alias or selected pool member still win, and already-running agents are
unaffected.

Both Edit and Override open the same ordered, single-key effort ladder: `1` `none`, `2`
`minimal`, `3` `low`, `4` `medium`, `5` `high`, `6` `xhigh`, and `7` `max`. Edit also
offers `0` **Provider default**. That option writes the schema's empty sentinel into the
user-base `sase.yml`, deliberately masking a lower-precedence package/plugin value;
Override does not offer a pseudo-level, because cancelling or clearing honestly resumes
configured/provider behavior. Config-derived values are best-effort: a provider that
cannot honor a level retains its provider behavior.

Temporary effort Override reuses the model-alias duration workflow unchanged: `15m`,
`30m`, `1h`, `2h`, `4h`, Until cleared, a combined custom duration, or `t` for an exact
local time/date. It is machine-wide state in `~/.sase/llm_effort_override.json`; setting
replaces the prior effort override, expiry is enforced on the next launch, and Clear is
idempotent. This state is independent of `~/.sase/llm_override.json`, which stores
concrete model-alias overrides.

Permanent Edit always targets the writable **user base** config rather than a
project-local layer. Its preview shows `llm_provider.default_effort`, configured
before/after values, the actual target, validation, and the source-preserving YAML diff.
With `use_chezmoi: true`, the actual write goes to the chezmoi source and the target is
applied before sase's TUI reports success. A dirty Git-backed target receives the usual
tracked commit/pull/push offer with `chore: update default model effort`. An active
temporary override remains launch-effective after this write until it expires or is
cleared; the preview and success notification both make that explicit.

### Runner capacity controls

`Ctrl+R` is a fixed Launch Control binding and works from every alias, collapsed bucket,
and open bucket. It is not a leader-keymap setting. The **Runner Capacity** card shows
the current effective capacity budget and, while a temporary override is active, its
remaining time plus the configured value. Press `e` to edit the user-base configuration,
`o` to set a temporary machine-wide override, or `x` to clear an active override.

Edit and Override open a focused positive-integer card. Edit is prefilled with the
configured value; Override is prefilled with the current effective value. The input
accepts an unsigned base-10 whole number with minimum `1` and no product maximum. A
persistent edit previews the exact `max_running_agents` path, actual user or chezmoi
source target, configured before/after values, validation diagnostics, and
source-preserving YAML diff. Its tracked commit offer uses
`chore: update max running agents`. A higher-precedence overlay can keep the configured
effective value different from the requested user-layer value, which the reload
notification reports truthfully.

Temporary Limit overrides reuse the same relative/custom/exact-time duration cards as
model and effort overrides. The versioned machine-wide record is
`~/.sase/max_running_agents_override.json`; setting a value replaces the previous
runner-limit override, `now >= expires_at` expires it, and Clear is idempotent. A
persistent edit does not clear a live temporary override. Lowering the effective cap
never stops an already-running agent: occupied capacity may temporarily exceed the cap,
and new work waits until enough capacity drains. Raising the cap lets eligible parked
agents advance through the existing priority/FIFO gate on their next poll. Launches with
an explicit `%queue(capacity=N)` use that positive-integer budget for their own
admission decision, so they can intentionally start above the global budget while still
holding an ordinary weighted claim once admitted. Question continuations reacquire
against the current effective global cap after their gate turn has released capacity.

### Provider routing controls

Press `p` from Launch Control to open **Provider Routing**. The modal lists every
user-facing registered LLM provider in stable order with its model count and one of
these states:

| State                                            | Meaning                                                              |
| ------------------------------------------------ | -------------------------------------------------------------------- |
| `available`                                      | The provider is registered and its declared CLI is present.          |
| `CLI missing`                                    | Automatic alias routing already skips it because its CLI is missing. |
| `disabled · manual · <time> left`                | Launch Control manually hard-disabled it until expiry or clearing.   |
| `disabled · usage-limit automatic · <time> left` | Usage-limit detection automatically hard-disabled it.                |
| `soft · manual · <time> left`                    | Launch Control manually soft-disabled it until expiry or clearing.   |
| `soft · usage-limit automatic · <time> left`     | A usage-limit automatic disable that was flipped to soft.            |
| `★ priority · <time> left`                       | This provider is preferred in pools that include it.                 |
| `backup · CODEX priority`                        | This provider remains usable behind the active priority provider.    |
| `CLI missing · ★ priority unavailable`           | Priority intent remains, but routing uses backups until it can run.  |

Hidden testing providers stay out of this human-facing modal. Disabling a provider does
not unregister it, change `sase.yml`, change model aliases, or stop provider processes
that are already running. A **hard** disable (`d` / Enter) keeps today's fail-closed
behavior: new launches, follow-ups, later retry/fallback resolution, model pickers, and
`%model` completion drop that provider. A **soft** disable (`s`) spares the provider in
`|` pools while another member can cover, never diverts a `||` fallback, and still
accepts explicit `%model` / picker / completion choices for that provider. Provider
priority (`p` inside the modal) is temporary preference state, not a disable: pools
prefer that provider when it is a usable member, while explicit choices and `||`
fallback order continue to do what they say.

On any row, press `d` or Enter for a hard disable or `s` for a soft disable, then choose
how long. The duration picker is the same set of choices as alias overrides: `15m`,
`30m`, `1h`, `2h`, `4h`, `Until cleared`, a custom duration, or `t` for an exact local
time/date. When the highlighted row already has an active disable in the _other_ mode,
the picker's first row is `x  Keep current window (<time> left)` — one keypress to flip
hard ↔ soft without re-choosing a window. That row is omitted when the mode already
matches, so it is never a no-op. On a disabled row, `x` enables the provider
immediately, including an automatic usage-limit disable. Pressing `x` on an enabled row
warns without mutating state. Successful changes refresh the provider rows, Launch
Control title, alias routing rows, and the top-bar indicators without closing the modal,
so several providers can be managed in one pass. Unknown disable sources are shown as
readable labels instead of being folded into the manual state.

On an enabled, installed, user-facing row, press `p` to set or change provider priority,
then choose the same relative, until-cleared, custom, or exact-time duration used by
provider disables. Press `c` to clear the active priority, even when no selectable
provider rows remain. The modal keeps the current selection after writes and refreshes
the rows in place. If another session changed priority between the modal's snapshot and
the attempted write, the modal reloads the current state and asks you to press `p` or
`c` again against the fresh snapshot. If a write commits but the follow-up refresh
fails, the toast says the routing write succeeded and leaves the modal open for retry.

A sparing (soft) pool member still counts toward `pool <available>/<total>` and remains
selectable. In the alias description it renders as amber `→ ✓ provider/model@effort`
when selected or amber `× provider/model@effort` when skipped, with no `soft` chip.
Priority members render with `priority` and backup members with `backup`, including in
the guided selector builder, model picker, and `%model` completion. Soft-disabled
providers stay in the model picker (header labelled `soft`, rows dimmed one step) and in
`%model` completion (annotated `soft` in the provenance column). Hard-disabled providers
are still omitted from both.

sase's TUI also shows active provider routing state as pills inside the violet
`overrides:` top-bar group (the launch-default and current-project chips moved one row
down, to each tab's status-row launch-context cluster). An active priority renders like
`overrides: CODEX ★ 42m` (with a state word only for soft-disabled or unavailable, such
as `overrides: CODEX ★ soft-disabled 42m`). One hard-disabled provider renders like
`overrides: CLAUDE off 42m`; one soft-disabled provider renders like
`overrides: CLAUDE soft 42m`. Several disables render the most severe (hard first)
provider plus a count, such as `overrides: CLAUDE +2`, and use the soft palette only
when every active disable is soft. When alias, priority, and disable facts are active
their pills sit side by side under the one `overrides:` label. Each pill keeps its color
and its tooltip section, and clicking the group opens Launch Control.

### Disabled-provider launch panel

When sase's TUI is about to launch an agent that can only run on a **hard**-disabled
provider, it opens a one-keypress panel instead of submitting a launch that would fail
at invoke time. Soft disables never open this panel. After the instant input and
project-tag checks pass, the prompt bar is released and the accepted launch appears as a
preparing proc row while the provider check runs. Aborting restores the prompt when the
bar and screen are free; if the user is already typing or another modal owns focus, it
saves the prompt to the stash instead and never steals focus.

The panel is one blocked agent at a time. A four-agent swarm with two blocked units
shows the panel twice in sequence. Enabling a provider while resolving one agent can
unblock a later one, so sase's TUI re-checks after every write.

| Key       | When it appears                                        | Action                                                                                                            |
| --------- | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `e`       | Always                                                 | Enable every provider blocking this agent, then re-check and continue the launch.                                 |
| `s`       | Always                                                 | Soft-enable those providers (same remaining window) so this agent can run while pools still spare them.           |
| `1`…`9`   | Only when two or more providers block this agent       | Enable that one provider and re-check. The panel stays up if another blocker remains.                             |
| `m`       | Only when every slot of this agent agrees on one model | Open the model picker and rewrite this agent's `%model`. A fan-out unit shows a dim edit-the-prompt line instead. |
| `a`       | Always                                                 | Abort this agent. The other agents in the launch still start.                                                     |
| `A`       | Only when the launch has more than one agent           | Abort the whole launch. The label states the real agent total.                                                    |
| `esc`/`q` | Always                                                 | Same as `a`.                                                                                                      |

A single-agent launch that only enables or soft-enables submits the original prompt.
Picking a different model on a one-agent launch rewrites that prompt. Dropping or
re-modelling a unit in a multi-agent launch submits only the agents that remain.

### Automatic provider drain {#automatic-provider-drain}

After a **manual** hard disable in Provider Routing (`p` from Launch Control, above)
newly hard-disables a provider, sase's TUI automatically relaunches the agents that
disable just stranded. No prompt is shown. The drain is submitted only when all of these
hold:

- The write was a **hard** disable (a soft disable never drains — it strands nothing).
- The write transitioned the provider into hard-disabled (no disable → hard, soft →
  hard, or an expired disable → hard). Re-hard-disabling or extending an already
  hard-disabled provider never re-drains; use `sase agent drain <provider>` for that
  case.

The disable write returns immediately with the usual "disabled" toast, then a
`Draining <PROVIDER>` start toast follows. The drain runs as the durable `agent.drain`
proc (`sase agent drain <provider> --yes --json`) with the shared
`provider-drain:<provider>` concurrency key the automatic usage-limit path uses (see
[Draining a Disabled Provider](../providers/usage.md#draining-a-disabled-provider)),
so it appears in the Procs tab and dedups against an automatic drain already in flight
for that provider rather than running twice. A completion toast summarizes the durable
result envelope, and the Procs row holds the full JSON envelope. If the TUI exits first,
the proc still finishes and its result stays in Procs / `sase proc show`.

An empty or no-longer-disabled automatic drain records a successful no-op: when the
drain finds nothing to relaunch (`nothing_to_drain`) or the provider is no longer
hard-disabled by the time the proc plans (`not_disabled`, `soft_disabled`), the proc
succeeds with exit 0 and the completion toast says nothing was drained.

Draining onto a chosen model is still available as
`sase agent drain <provider> -m <model>`.

### tmux Agent {#tmux-agent}

Press `t` from Launch Control to open **tmux Agent**. The panel lists every registered
provider that declares an interactive CLI, in shortcut-key order, and launches the
chosen one in a new tmux window in the current pane's directory. The same catalog and
launch engine back `sase tmux-agent` on the command line; only the presentation differs.
These windows are unmanaged agent CLIs, not SASE agents — they do not appear in
`sase agent list`.

If sase's TUI is not running inside tmux, `t` warns
`sase's TUI is not running inside tmux; start sase's TUI in a tmux window to launch agent CLIs.`
and does not open the panel.

Each row is `<key>  ● <display name>  <vendor>  <state>`: the key in the selector
accent, the bullet and display name in the provider's accent color, the vendor dim, and
the state one of:

| State                            | Meaning                                                                        |
| -------------------------------- | ------------------------------------------------------------------------------ |
| `ready`                          | The CLI is installed and launchable.                                           |
| `not installed`                  | The row is dim and unselectable; the description strip shows the install hint. |
| `routing disabled · <time> left` | Hard-disabled for SASE automatic routing, but still launchable from here.      |
| `soft · <time> left`             | Soft-disabled for SASE routing; still launchable from here.                    |

A disabled-for-routing provider stays selectable because a human choosing an agent CLI
is not automatic routing. The annotation is visible, not a wall.

The two-line description strip shows the exact command that will run, then the preview
window name (`ai`, `ai2`, `ai3`, …) plus effort and bypass state. A skipped
config-default effort is named rather than swallowed. Bypass is on by default (matching
the shell script this feature replaces) and is always visible in the strip; it is never
applied invisibly.

| Key                                 | Action                                                                                     |
| ----------------------------------- | ------------------------------------------------------------------------------------------ |
| `Enter` / the row's assigned key    | Launch the highlighted (or keyed) agent CLI                                                |
| `s`                                 | Launch once without the provider's approval-bypass args                                    |
| `j`/`k` (arrows, `Ctrl+N`/`Ctrl+P`) | Navigate; not-installed rows are skipped                                                   |
| `Esc`                               | Close and return to Launch Control                                                         |
| `q`                                 | Close, but only when no provider claimed `q` (Qwen keeps `q`; the title and footer say so) |

A successful launch notifies `Opened tmux window: <name> · <display name>` and dismisses
back to Launch Control. A failure notifies with an error and leaves the panel open.

See [`sase tmux-agent`](../../cli.md) and the
[`tmux_agent`](../config/agents-and-runners.md#tmux_agent) config block for the
CLI surface, the drop-in tmux binding, and the documented parity recipe against the
script this feature replaces.

### Alias History

Press `H` on an alias row, an alias-backed launch setting (`default model`,
`epic lander`, `big epic lander` when configured as a raw `@alias` reference), or a
collapsed bucket to open **Alias History** — bounded prior runs for that alias or, for a
bucket, every member alias. A concrete (non-alias) launch setting and the
`default effort`, `max runners`, and `big epic starts at` scalar settings are not
aliases; pressing `H` on one of those rows only shows a warning toast. The panel loads
off-thread and never changes Launch Control's own state.

The title names the alias or bucket, keeps the tan ownership accent for a user-owned
source, shows the effective provider/model/effort badge when a single alias supplied it,
and reports the total recorded, returned (currently visible), and done/failed/running
counts. A bucket's runs are grouped under a disabled header per member alias, separated
by the same single-spacer convention used elsewhere in Launch Control; headers, spacers,
and per-group empty hints are never jump targets. Rows render newest first exactly as
recorded, with a status marker, relative time, agent/workflow identity, the configured
project display name, a provider-themed model badge with effort, and one of four
provenance chips:

| Chip         | Meaning                                                                   |
| ------------ | ------------------------------------------------------------------------- |
| `direct`     | An explicit `%model` directive named this alias.                          |
| `default`    | The configured default model resolved to this alias.                      |
| `via @<...>` | This alias was reached indirectly, through an earlier alias in the chain. |
| `unrecorded` | No alias origin was captured for this run — recording predates it.        |

The fixed detail strip below the list explains the highlighted run: the recorded alias
trail resolved to its concrete provider/model/effort, the same origin explanation as the
chip (an honest, non-speculative note for `unrecorded` rather than a guessed reason),
and the prompt snippet plus whichever of project, workspace, bead, Patch, start time and
duration, retry attempt, hidden state, and macro context are actually present — nothing
is invented for a field the query did not return. The returned window is a display
limit, not the full retention history; the title's recorded/shown counts and the
footer's "more available" hint make the difference visible.

Below the detail strip, a compact model-usage region ranks the models the currently
shown runs actually used. Counts cover the loaded window only, after deduplicating the
same artifact directory when a bucket lists one run under more than one member alias; a
dim `(deduped)` marker appears when that filter removed rows. Bar color follows the same
provider palette as the `PROVIDER(model)` badges above. Configured selector members with
no runs in the window render as `unused`; a model that ran but is not in the current
pool is tagged `off-pool`; runs with no recorded model collapse to one `unrecorded` row.
When every counted run for a model shares one effort the row shows `@ <effort>`; mixed
efforts show a dim `@ mixed`. At most four rows render; a `+N more` overflow row carries
the leftover count and percent so the shown shares still total 100%. `Ctrl+J`, `Ctrl+K`,
`r`, and `.` recompute the strip with the new window; `j`/`k` never do.

| Key                                 | Action                                                                                             |
| ----------------------------------- | -------------------------------------------------------------------------------------------------- |
| `j`/`k` (arrows, `Ctrl+N`/`Ctrl+P`) | Navigate                                                                                           |
| `'`                                 | **Jump** — adaptive hints over selectable runs only                                                |
| `Enter`                             | Open the highlighted run's full prompt in the preview panel                                        |
| `y`                                 | Copy the highlighted run's durable `@agent:...` reference                                          |
| `Ctrl+J`                            | **Load more** — add 10 runs to the per-alias limit and reload, keeping the highlighted run         |
| `Ctrl+K`                            | **Unload** — subtract 10 runs, never dropping below the initial `model_alias_history_limit` window |
| `r`                                 | **Refresh** — revalidate this load, bypassing the cache once                                       |
| `.`                                 | Toggle hidden runs in or out of the results                                                        |
| `Esc` / `q`                         | Close and return to Launch Control, unchanged                                                      |

A run without a durable agent name warns instead of copying a guessed reference, and a
missing or unreadable `raw_macros.md` warns instead of closing the panel.

<a id="temporary-overrides"></a>
Moved to [Launch Control overrides](launch-control-overrides.md#temporary-overrides).
<a id="persistent-edits"></a>
Moved to [Launch Control overrides](launch-control-overrides.md#persistent-edits).
<a id="examples-1"></a>
Moved to [Launch Control overrides](launch-control-overrides.md#examples-1).

## Related

- [TUI hub](index.md) — all TUI reference pages.
- [Launch Control overrides](launch-control-overrides.md) — temporary overrides and persistent edits.
- [Provider routing](../providers/routing.md) — temporary overrides, disables, and priority.
- [Models and aliases](../providers/models.md) — catalog, tiers, and aliases.
