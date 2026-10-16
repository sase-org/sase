---
title: Reader testing
description: How to run an observed reader round and turn the results into doc changes.
---

# Reader testing

This page describes the observed reader round that checks whether the homepage doors
send newcomers to the right place. Bryan runs the round; its results become follow-up
work.

## Running a round

Recruit three to five people who have not used SASE. Sit with each reader individually,
share the homepage, and watch — do not guide. For each task below, note which door the
reader picks first and whether they finish the task. A round takes about 30 minutes per
reader.

## The six tasks

Give each task as a plain goal, one at a time:

1. **Is SASE for me?** — Decide whether SASE fits how you work. (Expect: Learn.)
2. **Run a first agent.** — Launch one agent and find its result. (Expect: Learn.)
3. **Run two agents in parallel.** — Start two runs without them clashing. (Expect: Do.)
4. **What is a bead?** — Explain what a bead tracks. (Expect: Understand.)
5. **Find a config key.** — Look up what one configuration value does. (Expect: Look
   up.)
6. **Recover an interrupted agent.** — Restart or revive a broken run. (Expect: Do.)

## Success measure

At least 4 of 5 readers pick the right door first on each task. A door that readers
consistently miss needs a better label, not a better explanation elsewhere.

## Results template

Copy one row per reader per task:

| Reader | Task | First door picked | Expected door | Match? | Finished? | Notes |
| ------ | ---- | ----------------- | ------------- | ------ | --------- | ----- |
| R1     | 1    |                   | Learn         |        |           |       |

End with the tally: tasks where fewer than 4 of 5 readers picked the right door first,
and the exact labels that confused them.

## Proposing label changes

Door labels are an interface decision, so changes stay human-reviewed:

- File the results as follow-up work noting which labels failed and what readers
  expected instead.
- Propose replacement labels against the failed tasks, not in the abstract — each new
  label must plausibly fix a recorded miss.
- Never move pages between tabs to fix a label; the label changes, the structure stays.
  See [Writing docs](writing-docs.md).

## Related

- [Contribute](index.md) — The contributor hub this page belongs to.
- [Writing docs](writing-docs.md) — The documentation contract for humans and agents.
