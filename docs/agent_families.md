# Agent Clans, Families, and Tribes

SASE uses three different kinds of agent grouping:

| Concept          | Directive or naming form                  | Purpose                                                              |
| ---------------- | ----------------------------------------- | -------------------------------------------------------------------- |
| **Agent clan**   | `%clan:<name>` / `%id(<id>, clan=<name>)` | Declare or join a named, rootless container for parallel agents      |
| **Agent family** | `%i(<suffix>, family=<parent>)`           | A strictly sequential chain named `<family>--<suffix>`               |
| **Agent tribe**  | `%id([<id>], tribe=<name>)` / `#tribe`    | A user-managed label displayed with an `@` prefix, such as `@review` |

Dot-separated names also define an agent _hood_: `foo.bar` and `foo.baz` are neighbors in hood `foo`. A deeper name
belongs to every hood along its dotted path, so ACE can group `foo.bar.worker` with peers under `foo.bar` and cousins
under `foo`. Clans use that namespace rule deliberately, while dotted names alone do not create clan or family
membership.

## Parallel Agent Clans

An agent clan is a container, never an agent. A `%clan` prompt spells its full hood-qualified `%id`; other members can
use `%id(<id>, clan=<name>)` to derive that name and join the same clan:

```text
%id:release.build
%clan:release
Compile the release.
---
%id(test, clan=release)
Test the release.
---
%id(land, clan=release)
%wait:release.build,release.test
Publish the release after both members finish.
```

The short form is `%c:release`. `%clan` is create-only: exactly one prompt may declare a clan, and declaring a clan that
already exists is an error. Use `%clan(<name>, tribe=<tribe>)` (or the `%c(...)` alias) to assign the declaration's
tribe to the entire clan generation; `tribe=` on `%id` cannot be combined with clan membership. Every other member uses
`clan=`. That form joins an existing clan or creates it implicitly without a tribe, takes exactly one member id, allows
dotted ids, and accepts a leading `!` for forced reuse. Static names and templates such as `%id(cld, clan=research.@)`
work; the derived `research.@.cld` name flows through normal template allocation.

### Launch-time clan summaries

The declaring member can attach a short description to its clan generation. ACE displays this description near the top
of the clan's `CLAN` panel; it is metadata and is not sent to the member as work instructions. Use a literal for stable
context, the double-colon shorthand for a larger text block, or an executable when the description depends on state
available as the runner starts. A literal keeps the work prompt immediately below the declaration:

```text
%id:research.lead
%clan(research, tribe=study, summary="Audit authentication and authorization")
Review the security boundary.
```

The text-block shorthand ends when the next top-level directive or xprompt reference begins:

```text
%id:release.lead
%clan:release:: Coordinate the release checks and summarize blockers.
#release_work
```

For a computed description, name an executable instead:

```text
%id:triage.lead
%clan(triage, summary_script=./describe-triage)
Triage the current failures.
```

The value may also contain shell-style quoted arguments. Use the directive text-block form when the command itself
contains spaces or quotes:

```text
%id:release.lead
%clan(release, summary_script=[[sase_clan_summary_plan "plans/release plan.md"]])
Coordinate the release.
```

`sase_clan_summary_plan` renders any valid tale or epic plan with the same logical PLAN-lane presentation used by ACE.
Its first argument is the plan reference; when that argument is omitted, it reads `SASE_EPIC_PLAN_REF` instead.

`summary=` accepts the usual directive values: a bare token, a quoted string for text containing spaces or special
characters, or a multiline `[[...]]` text block. The `::` shorthand requires a space after `::` and captures everything
until the next top-level line that starts a directive (`%`) or xprompt reference (`#`). That captured text becomes only
the summary, so use `summary=` when ordinary work instructions follow the declaration directly. `summary=` and
`summary_script=` are mutually exclusive, and both belong only on the create-only `%clan` declaration;
`%id(..., clan=...)` joiners cannot declare or replace a summary.

A summary executable may run synchronously twice: first while SASE extracts launch directives, before dependency waits,
runner-slot admission, and workspace preparation, and again after the primary workspace and every applicable sidecar and
linked-repository workspace have been prepared. The first attempt uses the workspace path with which the runner started;
for a deferred-workspace launch, that is the placeholder workspace. The second attempt uses the real prepared workspace
claimed after the wait. A waiting runner that re-execs to load updated SASE code can repeat this sequence, so summary
executables must be read-only and idempotent.

A bare executable name is resolved next to the running Python interpreter and then on `PATH`; a value containing `/` is
resolved as an executable absolute path or a path relative to that initial workspace. SASE first probes the complete
value as a literal executable, preserving executable filenames that contain spaces. If that fails, it applies
shell-style quoting, resolves the first token by the same rules, and passes the remaining tokens directly as argv; it
never invokes a shell.

Each attempt inherits the runner environment available at that point. The post-preparation attempt therefore sees
environment updates made while preparing the workspace and linked repositories. SASE gives both attempts the same
identity contract: it overrides `SASE_CLAN_NAME`, `SASE_CLAN_GENERATION`, and, when the declaration has one,
`SASE_CLAN_TRIBE` (otherwise an ambient clan-tribe value is removed). Epic work also provides `SASE_EPIC_PLAN_REF`,
`SASE_EPIC_PLAN_SNAPSHOT`, `SASE_EPIC_BEAD_ID`, `SASE_PHASE_BEAD_ID`, and `SASE_EPIC_CLAN_TRIBE`; SASE reconstructs
these values from persisted agent metadata after launch-only variables have been consumed. The snapshot is an absolute,
project-scoped, guaranteed-local best-effort copy used by the built-in epic summary script after ordinary checkout
candidates. The original plan reference remains the displayed and persisted association.

Standard output becomes the summary and standard error is appended to the agent log. Every attempt has the same
20-second timeout and non-fatal failure handling, and the stored summary is capped at 32 KiB of UTF-8. Missing
executables, malformed quoting, timeouts, nonzero exits, and empty output are logged without blocking the agent launch.
SASE uses the last successful non-empty output: a successful post-preparation attempt replaces the extraction-time
value, while a later failed or empty attempt leaves the newest successful summary untouched.

SASE trims trailing whitespace and persists the result as `clan_summary` on the declaring agent's metadata. The scan
contract resolves summaries within one clan generation deterministically, using the newest explicit declaration if it
must read older or externally-authored artifacts with more than one. Rich markup is rendered when valid and shown as
literal text when invalid. The saved description is distinct from the foldable sections that ACE synthesizes below it
from member artifacts and activity.

Clan membership is execution-neutral. It does not add waits, change launch order, choose a workspace or model, or
otherwise rewrite launch behavior. Use `%wait` explicitly wherever ordering is required. The `clan=`, `family=`, and
`tribe=` keywords on `%id` are mutually exclusive, and none can be combined with `%clan` in the same segment.

The clan name is permanently reserved as a container name and cannot also belong to an agent. Each member must be named
`<clan>.<suffix>`; launch planning rejects an out-of-hood name before spawning it. A clan may contain ordinary agents,
workflow steps, and sequential families whose names stay inside the same hood.

`%wait:<clan>` waits for every member of the newest clan generation. An exact member name targets only that member.
Killing or dismissing the synthetic clan row cascades to its live members, while acting on one member leaves the rest of
the clan alone.

Retrying a clan member from ACE keeps it in the same named clan. ACE rewrites the prompt into
`%id(<new-member-id>, clan=<clan>)`, where the member id carries the retry suffix. It does not repeat the create-only
`%clan` declaration. If the original prompt used a clan template such as `research.@`, ACE first substitutes the
member's concrete clan, such as `research.2`.

ACE renders every grouping row with a trailing color-coded name and no kind icon. A clan is synthetic and ends with an
orchid `<name>` after its rolled-up status counts; its `@tribe` labels follow the name. A real multi-member family root
ends with its bare azure container `<name>`, while its concrete member rows retain their exact `--<suffix>` names. Plain
agent annotations and a lone plan proposer with only its display-only planner child remain gold. Press `l` once on a
collapsed clan to reveal its direct members. The clan's outer fold is binary, so move to a family or workflow row and
press `l` there to reveal that row's descendants. Lowercase `h` moves from any agent, Bash, Python, parallel, embedded,
or compatibility workflow step to its validated immediate workflow, family, clan, or tribe parent without changing fold
state. Uppercase `H` collapses the focused workflow, family, or clan before falling back to grouping collapse. Selecting
the clan row shows an aggregate `CLAN` header and a navigable summary of every section represented across its members.
In the Agents list, direct members sort by status priority — Failed, Stopped, Running/Starting, Waiting, Done — and then
by launch recency within a bucket. The metadata roster uses chronological launch order instead, keeping its
number-to-member mapping stable while statuses change. The runtime is the union of member run intervals, with human-wait
windows excluded, so concurrent members are not double-counted.

### Clan summary folding

Clan summaries collect member errors, output and workflow variables, replies, SASE context, slow tool calls, and prompts
beneath the `MEMBERS` table. Known-empty section kinds are omitted. If required disk-backed content is not known yet,
the document ends with one dim `⋯ scanning member data…` tail instead of showing a placeholder for each section. Up to
100 direct members receive fixed jump numbers: `0`–`9` for rosters with at most ten entries, or `00`–`99` for the first
100 entries in a larger roster. Additional members appear only in an unnumbered remainder count. Press a number while
the clan is selected to expand only that member's ancestor chain and jump to its row; `Esc` cancels a pending first
digit. Use `Ctrl+J` and `Ctrl+K` to move between the visible section headings.

The summary has three session-only fold levels:

| Level | Clan summary content                                                                                           |
| ----- | -------------------------------------------------------------------------------------------------------------- |
| 1     | Up to 100 numbered member rows plus a heading and count for each other represented section                     |
| 2     | Bounded triage digests, such as one-line error and reply previews, variable values, and context-lane summaries |
| 3     | Full section bodies grouped by member for detailed investigation                                               |

Press `zz` to cycle levels 1 → 2 → 3 → 1. Press `zZ` below level 3 to open every fold to level 3, or press it at level 3
to close every fold to level 1. Use `z1`-`z3` to select an exact level. `za` cycles only the section at the top of the
metadata viewport; `zA` toggles that section between collapsed and fully expanded. A valid panel-level cycle, extreme
toggle, or direct selection clears these per-section overrides. The `Fold: N/3` field in the `CLAN` header always shows
the current panel level, while the `▸`/`▾`/`▼` heading glyph shows each section's effective level. Unknown disk-backed
sections stay hidden during enrichment behind one `scanning member data…` tail; represented sections appear when known,
and known-empty sections remain omitted. The compact roster and its numeric jumps remain available at every level.

The fold prefix is available only while the Agents tab is active. Press uppercase `Z` to zoom the largest panel; the
lowercase `z` key starts fold mode. Fold state is panel-wide and applies when a clan or multi-member family container is
selected. Using a fold chord on a regular agent updates the session state for the next container selection without
changing that agent's sections.

### Epic bead-work example

`sase bead work <epic-id>` puts every phase worker and the final land agent in clan `<epic-id>` and tribe `@epic`. For
an epic named `sase-6g`, the generated prompt has this shape:

```text
%id(!sase-6g.1, bead=sase-6g.1)
%clan(sase-6g, tribe=epic)
#bd/work_phase_bead:sase-6g.1
---
%id(!land, clan=sase-6g, bead=sase-6g)
%wait:sase-6g.1
%wait(bead=sase-6g.1)
#bd/land_epic:sase-6g
```

Phase dependency waits remain explicit and pair successful agent completion with phase-bead closure; the clan container
itself is not a land agent or other executable process. The `bead=` association lets each runner claim its phase or epic
only after those waits and workspace preparation. If the epic clan already exists during a re-work, every phase and land
segment uses the `clan=` join form.

## Sequential Agent Families

An agent family is a strictly sequential chain. A family is created only when `%i(suffix, family=parent)` attaches the
first follow-up to an existing agent. At that point SASE renames the original agent with its own `--<role>` suffix and
reserves the bare base name as a pure family container. Generic originals become `<family>--0`; plan proposers use
`<family>--plan`. Because creation requires an attachment, a family always has at least two members.

For example, attaching a reviewer to agent `foo` creates family `foo`, renames the original to `foo--0`, and names the
new member `foo--reviewer`:

```text
%i(reviewer, family=foo) Review the diff produced by this family.
%i(tester, family=foo) Run the focused tests and report any failures.
%i(@, family=planner) #with_feedback:: Add failure handling before coding.
```

The positional suffix is a bare token: write `%i(reviewer, family=foo)`, not `%i(--reviewer, family=foo)`.
`%i(@, family=foo)` allocates the next free numeric suffix.

Every family member has an `agent_family_role` derived from its suffix:

| Suffix                                         | Role                           | Display behavior                 |
| ---------------------------------------------- | ------------------------------ | -------------------------------- |
| `plan`, `q`, `code`, `epic`, `commit`          | Corresponding built-in role    | Built-in plan-chain status rules |
| Numeric (`@` allocates the next free number)   | Feedback or question round     | Built-in round status rules      |
| Any other word (`reviewer`, `tester`, `audit`) | The suffix itself, an open set | Ordinary RUNNING/DONE statuses   |

Arbitrary suffixes are ordinary family labels, not configured lifecycle hooks. SASE does not discover or execute custom
`kind: agent_family` definitions. Replace a stale definition with an explicit family attachment or an agent-requested
launch.

SASE resolves `parent` to the newest visible matching agent or family member in the current project. If the parent is
still running, the new member appears immediately as WAITING and starts only after that exact parent artifact completes
successfully. If the parent fails, stops, or is killed, the queued member becomes STOPPED and SASE sends a completion
notification.

If the parent is missing, ambiguous, or dismissed, or the composed member name already exists, launch preparation fails
before spawning the member. Collision errors suggest `%i(@, family=parent)`. `%wait:<family>` and `#fork` references to
the bare family name resolve through the family container; an exact `--<suffix>` name targets one member. A member
attached to an agent already inside a clan inherits that clan membership.

`#fork:<family>` contributes every readable transcript from a successful family member in chain order, oldest first. The
injected context labels each member and lists every omitted member: one that is still running or ended unsuccessfully,
or a successful member whose transcript is missing or unreadable. Shared inherited history is de-duplicated across the
included transcripts. At least one successful readable transcript is required. Use `#fork:<family>--<suffix>` when only
one member should be a parent. A family container can also be combined with independent agent, family, clan, or tribe
parents in one multi-parent fork.

### Family detail folding

Selecting a real multi-member family root in ACE adds a numbered `FAMILY MEMBERS` roster in stable chain order. The
original member and each follow-up are direct jump targets; synthetic planner projections and legacy parallel-family
scaffolding are not. The same `zz`, `zZ`, `za`, and `zA` chords used by clan summaries control the family roster and the
root's output variables, workflow variables, SASE context, slow calls, errors, xprompt, prompt, and consolidated reply.

Family summaries have two effective levels. Level 1 shows bounded activity, wait/retry, context, and prompt/reply
previews; level 2 adds full available content and member workspace, timestamp, and attempt annotations. Press `zZ` at
level 1 to open every fold to level 2, or at level 2 to close every fold to level 1. Press `z1` or `z2` to select either
level directly. `z3` and `z4` are invalid in a family context and leave both the panel level and section overrides
untouched. A member-specific override inherits from the `FAMILY MEMBERS` section, which in turn inherits the panel
level. The numbered roster and its digit jumps remain present at both effective levels. Absent xprompt and prompt
sections are omitted, while reply rows for members that have not responded yet remain visible with their pending state.

Two bundled xprompts help assemble common follow-up prompt bodies. They build text only; `%i` performs the attachment:

```text
%i(@, family=planner) #with_feedback:: Add failure handling before coding.
%i(@, family=planner) #with_q_and_a(qa_file=/tmp/qa_rounds.json):: Continue with the base prompt.
```

The full directive grammar is documented under [XPrompt directives](xprompt.md#supported-directives).

### Attaching within a multi-agent prompt

A later segment can attach to a statically named parent from an earlier segment:

```text
%i:foo Plan the change.
---
%i(reviewer, family=foo) Review foo's plan.
```

The attached member waits for the in-batch parent to complete successfully. This lookup supports earlier static names
such as `%i:foo` or `%i(foo)`; template-named and auto-named parents must already have an artifact before they can be
used as attachment targets.

## Agent Tribes

An agent tribe is a user-facing label for related agents across clans and families. Assign one at launch with the
`tribe=` keyword on `%id`, or use `#tribe` when the agent should be auto-named:

```text
%id(api-review, tribe=review) Review the API boundary.
---
#tribe:review Review another boundary with an automatic id.
```

ACE displays tribes with an `@` prefix and splits the Agents tab into panels such as `@review` and `@epic`. The clan's
single declaration assigns one effective tribe to the whole generation; joiner prompts omit `tribe=`. Older clan
generations without any `clan_tribe` value fall back to the distinct post-hoc member tribe assignments they carry.

Press `N` in ACE to set or clear the focused agent's tribe (or every marked agent). For the declaring clan member, ACE
rewrites the stored `%clan(<clan>, tribe=<tribe>)` and its `clan_tribe` metadata. For a joiner, ACE updates only the
metadata and never invents a second `%clan` declaration. The synthetic clan row itself is not an editable agent. The CLI
manages the per-agent assignment store for any named agent:

```bash
sase agent tribe set -n <agent> -t <tribe>
sase agent tribe unset -n <agent>
sase agent tribe list [-n <agent>]
```

Pass a bare tribe name to `set`, without the display-only `@` prefix. Names may contain letters, digits, underscores,
dots, and dashes. Per-agent assignments are stored canonically in `~/.sase/agent_tribes.json` with a `tribe` field. If
that file does not exist, SASE reads the legacy `~/.sase/agent_tags.json` scalar `tag` and list `tags` shapes. The first
mutation writes all imported assignments to the canonical store, which is authoritative from then on. Existing artifacts
and saved bundles can still be read when they use the legacy `tag` field, but rewritten metadata, new bundles, CLI
output, and editor projections use `tribe`. Clan-wide assignments use the separate per-member `clan_tribe` metadata and
are resolved across the generation. For ACE panel grouping, that explicit clan assignment takes precedence over
per-agent assignments.

ACE derives the reserved `@default` panel for agents whose outer presentation root has no effective tribe. This fallback
is display-only: SASE does not write `default` into agent metadata or the assignment store. An explicit stored `default`
assignment joins the same panel, and clearing any user-managed tribe returns the agent there.

### Tribe panel focus and folding

In the split layout, a tribe panel is also a selectable container. Repeated lowercase `h` follows the validated workflow
→ family → clan → tribe ladder and selects the whole expanded panel after the structural parent chain is exhausted; `h`
on the selected panel collapses it when another panel remains visible. Press `l` to expand a collapsed panel while
keeping container focus, then `l` again to return to the row ACE remembered for that panel. Uppercase `L` instead
expands the panel and enters its first selectable row. While an expanded whole panel is selected, `j` / `k` cycle across
panels without descending, and `l` or `Esc` returns to the remembered row. `J` / `K` always move to the first / last
selectable row of the next / previous panel. Whole-panel focus is unavailable in the merged layout. Apostrophe jump can
select any split-panel title, including a lone expanded panel, but a lone panel cannot be collapsed. With whole-panel
focus active, uppercase `H` isolates the selected panel by keeping it expanded and collapsing every sibling without
changing its remembered row. When isolation changes the layout, ACE remembers the prior collapsed-panel set for the
session: `↺` title markers and the `H restore panels` footer hint show that the next `H`, from any whole-panel focus,
will restore it. A separate sibling-panel or layout mutation invalidates that one-step restore.

Whole-panel focus replaces the ordinary agent detail with a `TRIBE` document. Its four `zz` metadata detail levels are:

| Level | Name      | Tribe summary content                                                                                         |
| ----- | --------- | ------------------------------------------------------------------------------------------------------------- |
| 1     | Glance    | Header, compact numbered top-level roster, attention previews, and headings/counts for non-empty sections     |
| 2     | Triage    | Bounded previews for every represented section                                                                |
| 3     | Inspect   | Nested roster detail and grouped full section bodies, still with protective bounds                            |
| 4     | Forensics | Unbounded bodies, tracebacks, the richest member annotations, and all-time runtime statistics and percentiles |

From levels 1-3, `zZ` opens every fold to level 4; at level 4, it closes every fold to level 1. `za` and `zA` adjust the
section or member at the top of the metadata viewport. Reply and slow-call presence enrichment is requested off-thread
at every tribe level so known-empty sections can remain absent; all-time runtime statistics remain level-4-only. Unknown
required disk-backed content produces one dim `⋯ scanning member data…` document tail rather than per-section
placeholders. The compact roster and its fixed numeric jump targets remain present at all four levels; the number keys
jump to top-level clans, families, workflows, or agents and expand only the required ancestors.

Use `z1`-`z3` to select the collapsed, expanded, or fully expanded view directly; `z4` selects the exhaustive view,
including unbounded roster annotations and runtime statistics. Direct numeric fold chords remain inside fold mode and do
not trigger numbered member jumps. Outside fold mode, these fixed metadata-member numbers are separate from ordinary
apostrophe entry hints, whose adaptive keys may use two characters in a large list.

The `,H` leader chord numbers every currently toggleable visible fold owner—eligible split-panel titles, grouping
banners, and agent-owned clan/family/workflow folds. Enter one or more whitespace-separated numbers or ascending ranges
such as `1 4-6` to toggle the selected mixed set in a single refresh. The ordinary apostrophe jump mode includes both
expanded and collapsed split-panel titles as destinations and preserves `Ctrl+O` jump-back history.

### Tribe wait and fork targets

Use an `@<tribe>` reference where `%wait` or `#fork` normally accepts an agent name:

```text
%wait:@review
#fork:@review
```

This is a next-entity target, not a request to wait for every historical member of the tribe. `%wait:@review` selects
the earliest successfully completed `@review` entity launched after the waiting agent: either one standalone agent or
one complete clan generation. Older entities, the waiting agent itself, failed agents, and incomplete clans do not
satisfy the dependency. A tribe-assigned member of a clan enrolls the whole generation, so that candidate becomes
eligible only after every member required by the normal clan wait succeeds.

`#fork:@review` implies the same wait, then resumes from the selected entity. A standalone match contributes its full
conversation. A clan match contributes one launch-ordered clan summary containing each member's sanitized prompts,
outcome/model metadata, reply size, and transcript path; full member replies are deliberately omitted so the child can
open only the transcripts it needs. Tribe targets can be mixed with explicit agent or clan parents in a multi-parent
fork, and ACE prompt completion offers visible `@tribe` values for both `%wait` and `#fork`. When no `%id` is supplied,
tribe waits and forks use neutral auto-names rather than derived `.w*` or `.f*` names because the eventual parent is
unknown at launch planning time.

ACE can insert these group references directly. Select a clan's synthetic container row and press `f` for
`#fork:<clan>`, or press `W` for `%wait:<clan>`. For a tribe, give its named panel whole-panel focus—expanded or
collapsed—and use the same keys for `#fork:@<tribe>` or `%wait:@<tribe>`. The reserved `@default` panel and grouping
banners are not group targets, and marked rows take precedence over the focused clan or tribe for `W`. For a selected
clan or tribe, ACE prefixes either prompt with a VCS tag only when every real agent currently in that scope resolves to
the same workflow and ref. Otherwise it omits the VCS tag so you can add the intended `#git`, `#gh`, or other workflow
reference yourself. Marked waits instead take VCS context from the selected marked row, or the first named mark when the
selection is elsewhere. The current rows determine only that optional VCS prefix; they do not pin the eventual clan or
tribe fork source. See [Forking Agents and Groups](ace.md#forking-agents-and-groups) for selection and revalidation
behavior.

## Agent-Initiated Family Launches

User-initiated launches are direct: prompts submitted through normal launch surfaces, including prompts containing
`%i(suffix, family=parent)`, do not require launch approval.

When a **running agent** requests another launch, SASE creates a typed `LaunchApproval` request and spawns nothing until
a human approves it. Agents use the generated `/sase_run` skill and submit a structured request:

```bash
sase launch request -f launch_request.json -o json
```

The request may contain `%i(suffix, family=parent)` in its prompt, so the approved launch joins an existing family with
any valid suffix. `launch_preview.md` shows the resolved launch plan before approval. Inside an agent, the request
command waits mechanically and returns one JSON outcome for approval, rejection, feedback, dispatch failure,
cancellation, or timeout; the agent does not poll response files.

Approve or reject from ACE, or use:

```bash
sase launch approve <selector>
sase launch reject <selector> [-f <feedback>]
```

The selector may be a request ID, notification ID, or unique notification prefix. Approval verifies the neutral request
bundle, revalidates and replans the stored prompt in its original working directory, and records host dispatch status in
the write-once response. A multi-slot launch is all-or-nothing. In-flight requests from the legacy launch-request layout
remain answerable during the compatibility window.

For the complete request schema, preview behavior, slot limits, and dispatch rules, see
[Launch Approval](ace.md#launch-approval) and `sase launch request --help`.
