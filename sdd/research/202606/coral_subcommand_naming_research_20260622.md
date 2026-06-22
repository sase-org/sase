# Coral Rename — Subcommand & Axe-Internal Naming Research

Date: 2026-06-22

## Question

If `sase` is renamed to **`coral`**, what should the `ace` and `axe` subcommands be called, and what should the
axe-internal concepts currently named **lumberjacks** and **chops** become? The goal is names that are *related to the
coral brand, easy to understand, and not too distant from what each command actually does*.

This note is scoped to the subcommand/metaphor layer only. The top-level name itself is researched separately in
[`sase_rename_research_consolidated.md`](./sase_rename_research_consolidated.md) (which evaluated `Corral` — a different
word from `coral` — and rejected it on npm/crates collisions). Registry/domain/trademark clearance for the literal word
"coral" is **out of scope here** but flagged under [Scope & caveats](#scope--caveats).

## What each name actually denotes today

A rename should track function, so the recap below is the yardstick for every candidate.

| Term | Kind | What it is | User-facing string |
| --- | --- | --- | --- |
| `ace` | subcommand (interactive) | "Agentic ChangeSpec Explorer." The TUI / human-driven **control surface**: browse ChangeSpecs, watch live agents, drive automation. Tabs: PRs, Agents, Axe. | "Interactively navigate through ChangeSpecs matching a query" |
| `axe` | subcommand (background) | The **automation daemon**: a long-running, schedule-driven background system that keeps ChangeSpec state fresh (hooks, mentors, comment polling, cleanup, digests). | "Schedule-based daemon for continuous ChangeSpec status updates" |
| `lumberjack` | axe internal | A **worker process / scheduler loop**. Each one owns a subset of jobs and runs them on a fixed interval (hooks 5s, waits 10s, checks 5m, comments 1m, housekeeping 1h). | "Individual scheduler loop that runs a subset of jobs on a fixed interval" |
| `chop` | axe internal | A **single job unit** executed by a lumberjack. Either a script or an agent. The smallest unit of work. | "A single job unit executed by a lumberjack. Can be a script or an agent" |
| `Orchestrator` | axe internal | Parent process that spawns and supervises the lumberjacks. | — |
| `tick` | axe internal | One iteration of a lumberjack's scheduler loop. | — |

### Three structural properties worth preserving

The current names are not arbitrary; they encode a deliberate design that any rename should try to keep:

1. **`ace` / `axe` are 3-letter near-twins** — same length, differ by one middle letter, both pronounceable, both
   evocative. `ace` reads as skillful/interactive; `axe` reads as work/cutting. This twinning makes the pair memorable
   and visually balanced in help output.
2. **The axe family is one coherent sub-metaphor**: *tool → worker → repeated single action* (`axe` → `lumberjack` →
   `chop`). The worker is named for the trade; the unit is named for the worker's one repeated motion (a swing = a
   chop). A good replacement family should come from a **single** domain so the three names reinforce each other, exactly
   as logging does today.
3. **Flavor with clarity** — the names are playful but immediately legible to a new user. Pure-literal names (`worker`,
   `job`, `daemon`) would lose the brand character the tool clearly values.

## Naming criteria (for this layer)

1. Sits inside the **coral / reef / ocean** semantic field so it reinforces the new brand instead of fighting it.
2. **Self-explanatory** — a new user can guess roughly what it does before reading docs.
3. **Faithful to function** — interactive-explorer for `ace`; continuous-scheduled-background for `axe`; worker for
   `lumberjack`; single-work-unit for `chop`.
4. **Family coherence** — the `axe`-replacement, worker, and unit names should come from one ocean sub-metaphor, the way
   logging unifies axe/lumberjack/chop today.
5. Short and CLI-friendly; ideally preserves the **near-twin** feel of `ace`/`axe`.
6. Avoids obvious second meanings that collide with the tool's own domain (e.g. avoid `helm` → Kubernetes Helm).

## The coral semantic field

"Coral" opens a rich, instantly understood ocean vocabulary, and one detail is brand gold:

> A coral **reef** is built by countless tiny **polyps**, each laying down a small skeleton that accretes, over time,
> into a vast living structure. That is the product's thesis in one image: many small agents, each making a small,
> durable, reviewable change, accreting into a large software system.

That origin story makes **`reef`** the natural word for the place you explore, and gives the whole rename a coherent
center. Usable nearby words: reef, tide, current, swell, surge, wave, dive, diver, deep, drift, reel, trawl, cast,
haul, net, angler, crew, skipper, harbor, helm, bridge, deck, buoy, shoal, school, polyp.

## Candidate naming sets (themed, internally coherent)

Each row is a complete, self-consistent set. Pick a row, not a grab-bag.

| Theme | `ace` → | `axe` → | `lumberjack` → | `chop` → | Character |
| --- | --- | --- | --- | --- | --- |
| **Reef & Reel** *(recommended)* | `reef` | `reel` | `angler` | `cast` | Tightest structural mirror of axe/lumberjack/chop; `reef`/`reel` echo the `ace`/`axe` twins. |
| **Reef & Trawl** | `reef` | `trawl` | `crew` | `haul` | Max clarity; "trawler runs continuously" is the most obviously *daemon-like* of the options. |
| **Reef & Tide** | `reef` | `tide` | `current` | `swell` | `tide` is the single most *semantically accurate* daemon word (periodic, automatic, scheduled), but its worker/unit are the softest. |
| **Dive & Drift** | `dive` | `drift` | `diver` | `dive`* | Verb-forward and energetic; *collides (`dive` used twice) — avoid unless you split it. |
| **Plain / low-flavor** | `deck` / `console` | `daemon` / `pulse` | `worker` | `job` / `task` | Maximum legibility, zero brand flavor. Fallback only. |

## Recommendation: **Reef & Reel**

```
sase ace            →   coral reef          # the interactive control surface
sase axe            →   coral reel          # the background automation daemon
  lumberjack        →   angler              # a scheduler-loop worker
  chop              →   cast                # one job unit
  Orchestrator      →   skipper             # supervises the anglers
  tick              →   tick (keep) / cast-cycle
```

Why this set wins on the stated goals:

- **It mirrors the existing structure almost exactly.** The current family is *tool → worker-named-for-trade →
  single-repeated-action* (`axe` → `lumberjack` → `chop`). Reel/angler/cast is the same shape: a `reel` is the iconic
  tool, an `angler` is the worker named for the trade, and a `cast` is the one repeated motion that produces a unit of
  work — the precise analog of a "swing"/"chop." Anyone who understood lumberjack/chop will understand angler/cast on
  first read.
- **`reef` is the most on-brand, most intuitive word for the explorer.** `coral reef` is *the* canonical coral phrase.
  The reef is the living place where your ChangeSpecs (coral colonies) and agents (fish) live and you swim through them
  — a perfect fit for an interactive *explorer / control surface*, which is literally what ACE ("Agentic ChangeSpec
  Explorer") is.
- **`reef` / `reel` preserve the `ace` / `axe` near-twin aesthetic** — 4 letters, differ by one letter, one interactive
  and one work-flavored. The visual balance in help output survives the rename.
- **One coherent sub-metaphor.** Reef → reel → angler → cast all live in the same ocean/fishing world, so the family
  reinforces itself the way logging does today.

Example transcripts under this naming:

```
$ coral reef                      # open the interactive TUI (today: sase ace)
$ coral reel start                # start the automation daemon (today: sase axe start)
$ coral reel angler list          # list scheduler-loop workers (today: axe lumberjack list)
$ coral reel angler run hooks     # run one worker once
$ coral reel cast list            # list job units (today: axe chop list)
$ coral reel cast run hook_checks # run one job unit (today: axe chop run ...)
```

Reads cleanly, and "the hooks **angler** runs every 5s, making its **casts** (the hook-check cast, the mentor-check
cast…)" is as legible as the lumberjack/chop sentence it replaces.

### The one weak spot (and the alternative that fixes it)

`reel` is slightly less obviously *continuous/scheduled* than the daemon ideal — a reel is a discrete spool. It is
defensible (a reel spins in a loop, and "reeling work in" connotes steady retrieval), but if the **standalone accuracy
of the daemon word** matters most to you, two swaps are available:

- **Swap the daemon to `trawl`** (keep the family fishing-themed): a trawler drags nets *continuously* and hauls
  *periodically* — the most daemon-like image available. Pairs naturally with `crew` (worker) and `haul` (unit). This is
  the **Reef & Trawl** row, and it is the strongest pick if "easy to understand" is the dominant criterion. It loses the
  `reef`/`reel` twin echo and makes the worker plural (`crew`) rather than a single repeated actor.
- **Swap the daemon to `tide`** (best *word*, weakest *family*): tides are automatic, periodic, scheduled (tide tables!),
  and relentless — semantically the closest match to a cron-like daemon, and `coral tide` is lovely. The cost is that
  "tide" has no native worker/unit, so `current`/`swell` are grafted on and read softer than angler/cast. Choose this
  only if you'd rather have the best daemon noun than the most coherent trio.

## À la carte menu (mix & match)

If you don't want a pre-built set, pick one cell per row. Top pick is **bolded**.

**`ace` → interactive explorer / control surface**

| Candidate | Note |
| --- | --- |
| **`reef`** | Most on-brand; the place you explore. The reef *is* where the work lives. |
| `dive` | Verb; "dive into your changes." Energetic but less of a "place." |
| `deck` | A ship's control deck; reads as a command surface. Generic. |
| `bridge` | A ship's command center — apt for "control surface," but heavily overloaded in software. |
| `helm` | Steering/control — great fit, but collides with Kubernetes Helm. Avoid. |

**`axe` → background automation daemon**

| Candidate | Note |
| --- | --- |
| **`reel`** | Preserves `reef`/`reel` twin; anchors angler/cast. Slightly less "continuous." |
| `trawl` | Most obviously continuous-background; anchors crew/haul. Best for pure clarity. |
| `tide` | Best *semantic* match (periodic/scheduled/automatic); weak worker/unit. |
| `current` | Continuous flow; better as a worker than a daemon. |
| `drift` | Continuous, passive; a bit too "aimless" for scheduled work. |

**`lumberjack` → worker / scheduler loop**

| Candidate | Note |
| --- | --- |
| **`angler`** | Single worker named for the trade who repeats one action — exact lumberjack analog. |
| `crew` | Very clear; but plural, so loses the single-repeated-actor mirror. |
| `diver` | A diver descends, works, resurfaces, repeats — good loop image. |
| `current` | Fits `tide`; reads more like a flow than a worker. |
| `tender` | A tender boat services a larger vessel — apt but less intuitive. |

**`chop` → single job unit**

| Candidate | Note |
| --- | --- |
| **`cast`** | One throw of the line = one job; tightest parallel to a single "chop"/swing. |
| `haul` | "The day's haul" = a batch pulled in; very intuitive as a unit of work. Pairs with `crew`/`trawl`. |
| `dive` | One dive = one job (if the worker is `diver`). |
| `swell` / `surge` | Fit `tide`; read softer/less concrete as a discrete unit. |

**`Orchestrator` → supervisor of the workers** (bonus — same family)

| Candidate | Note |
| --- | --- |
| **`skipper`** | Directs the crew/anglers; short, clear, on-theme. |
| `harbormaster` | Coordinates all traffic; vivid but long. |
| `bosun` | Directs the deck crew. (Note: rejected as a *top-level* name elsewhere for collisions, but fine as an internal concept.) |

## CORAL as a (optional) backronym

`SASE` expanded to "Structured Agentic Software Engineering." You can keep that phrase as the **methodology** under the
new brand and let `coral` simply be a name — or mint a fresh backronym. Options if you want one:

- **C**oordinated **O**rchestration of **R**epeatable **A**gentic **L**abor
- **C**ollaborative **O**rchestration of **R**eviewable **A**gentic **L**abor
- **C**ontrolled **O**rchestration of **R**epeatable **A**gentic **L**oops

Recommendation: don't force it. The polyp-builds-the-reef story (above) is a stronger brand narrative than any
backronym, and prior naming criteria already call for keeping "structured agentic software engineering" as a descriptor.

## Scope & caveats

- **"Coral" is a very common English word.** That helps memorability/pronunciation but hurts searchability and raises
  collision risk — the same trade-off the top-level rename note weighs for other candidates. Before committing, re-run
  that note's clearance method (exact PyPI/npm/crates queries, GitHub repo-name search, the `<name>-core` /
  `<name>-github` / `<name>-nvim` family check) against `coral` specifically. Not done here.
- **Blast radius of the subcommand rename** (out of scope to enumerate fully, but flag for planning): help text and
  parser definitions, the ACE "Axe" tab label, `~/.sase/axe/lumberjacks/<name>/chops/...` state paths, `sase_chop_*`
  console scripts, `ChopConfig`/lumberjack class names, docs (`docs/ace.md`, `docs/axe.md`), the glossary, generated
  skills, and any `chop` plugin entry points. A rename here is a real migration, not just a string swap.
- These are **naming candidates, not a decision.** The intent is to give you a coherent shortlist with honest
  trade-offs to choose from.

## Open questions for you

1. Which criterion dominates — **family coherence + twin aesthetic** (→ Reef & Reel) or **standalone clarity of the
   daemon word** (→ Reef & Trawl, or Reef & Tide)?
2. Do you want to keep the worker as a *single repeated actor* (angler/diver) to mirror `lumberjack`, or is a plural
   `crew` acceptable?
3. Should `coral` carry a backronym, or stand alone with "structured agentic software engineering" as the methodology?
4. Want me to draft the matching renames for `Orchestrator` and `tick`, and sketch the migration surface, as a follow-up
   `/sase_plan`?
