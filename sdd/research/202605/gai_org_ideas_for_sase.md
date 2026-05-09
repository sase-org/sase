# GAI Org Ideas for SASE

## Corpus Map

Generated for bead `sase-2h.1` on 2026-05-09. This is a phase-1 inventory, not the final synthesis.

Search command:

```bash
rg -il --hidden --glob '!**/.git/**' '(^|[^A-Za-z])gai([^A-Za-z]|$)|now_gai|gai_' /home/bryan/org
```

The search currently returns 463 files. Match counts below use the same case-insensitive pattern and count matched terms, not lines.

### Priority Rules

- `P0`: direct backlog/design sources that should be read first.
- `P1`: prompt/workflow sources and high-signal reference files.
- `P2`: dated execution history with at least three matches; useful for recurrence and pain-point mining.
- `P3`: low-count dated logs, background references, and likely incidental matches; sample as needed after higher priorities.

### Summary

| Bucket | Files |
| --- | ---: |
| P0 | 6 |
| P1 | 50 |
| P2 | 146 |
| P3 | 261 |

| Category | Files |
| --- | ---: |
| Core backlog/design notes | 6 |
| Prompt/workflow sources | 48 |
| Dated execution history | 391 |
| External/lit/reference notes | 4 |
| Incidental/background references | 14 |

### Review Routing

- Agent A should start with every `P0` row, then inspect any `P1` row that is not clearly prompt-specific.
- Agent B should cover all `Prompt/workflow sources` rows, especially `P1` prompt and chat files.
- Agent C should cover `P2` dated execution history first, then sample `P3` dated logs only when they cluster around repeated dates or terms.
- Agent D should cover `External/lit/reference notes`, then skim high-count incidental files such as `inbox.zo` only for explicit SASE or agent-workflow design material.

### Complete Inventory

| Priority | Category | Matches | Path |
| --- | --- | ---: | --- |
| P0 | Core backlog/design notes | 298 | `/home/bryan/org/now_gai.zo` |
| P0 | Core backlog/design notes | 83 | `/home/bryan/org/gai_ideas.zo` |
| P0 | Core backlog/design notes | 10 | `/home/bryan/org/plans/gai_xprompt_jinja.md` |
| P0 | Core backlog/design notes | 2 | `/home/bryan/org/text/gai_expand_agent_bug.txt` |
| P0 | Core backlog/design notes | 2 | `/home/bryan/org/text/gai_hidden_bug_snapshot.txt` |
| P0 | Core backlog/design notes | 1 | `/home/bryan/org/text/gai_split_syntax.txt` |
| P1 | External/lit/reference notes | 11 | `/home/bryan/org/agent_ref.zo` |
| P1 | External/lit/reference notes | 4 | `/home/bryan/org/claude_code_ref.zo` |
| P1 | Prompt/workflow sources | 22 | `/home/bryan/org/prompts/gai_xpl.md` |
| P1 | Prompt/workflow sources | 21 | `/home/bryan/org/prompts/gai_suffices.md` |
| P1 | Prompt/workflow sources | 16 | `/home/bryan/org/prompts/gai_loop.md` |
| P1 | Prompt/workflow sources | 16 | `/home/bryan/org/prompts/gai_monitor.md` |
| P1 | Prompt/workflow sources | 14 | `/home/bryan/org/prompts/gai_comments.md` |
| P1 | Prompt/workflow sources | 13 | `/home/bryan/org/prompts/gai_mentors.md` |
| P1 | Prompt/workflow sources | 11 | `/home/bryan/org/prompts/gai_history.md` |
| P1 | Prompt/workflow sources | 11 | `/home/bryan/org/prompts/gai_split.md` |
| P1 | Prompt/workflow sources | 10 | `/home/bryan/org/prompts/gai_work_filter_opts.md` |
| P1 | Prompt/workflow sources | 9 | `/home/bryan/org/prompts/gai_accept.md` |
| P1 | Prompt/workflow sources | 9 | `/home/bryan/org/prompts/gai_rerun.md` |
| P1 | Prompt/workflow sources | 8 | `/home/bryan/org/chat/gai_fix_tests_prompt.md` |
| P1 | Prompt/workflow sources | 8 | `/home/bryan/org/prompts/gai_attn_suffix.md` |
| P1 | Prompt/workflow sources | 6 | `/home/bryan/org/prompts/gai_new_tdd_feature.md` |
| P1 | Prompt/workflow sources | 6 | `/home/bryan/org/prompts/gai_output_types.md` |
| P1 | Prompt/workflow sources | 6 | `/home/bryan/org/prompts/gai_running.md` |
| P1 | Prompt/workflow sources | 5 | `/home/bryan/org/prompts/gai_ace_agents_tab.md` |
| P1 | Prompt/workflow sources | 5 | `/home/bryan/org/prompts/gai_hooks.md` |
| P1 | Prompt/workflow sources | 5 | `/home/bryan/org/prompts/gai_reverted.md` |
| P1 | Prompt/workflow sources | 4 | `/home/bryan/org/prompts/gai_rewind.md` |
| P1 | Prompt/workflow sources | 4 | `/home/bryan/org/prompts/gai_work_project.md` |
| P1 | Prompt/workflow sources | 4 | `/home/bryan/org/prompts/gai_work_run.md` |
| P1 | Prompt/workflow sources | 3 | `/home/bryan/org/prompts/gai_create_cl.md` |
| P1 | Prompt/workflow sources | 3 | `/home/bryan/org/prompts/gai_diff_option.md` |
| P1 | Prompt/workflow sources | 3 | `/home/bryan/org/prompts/gai_mult_test_targets.md` |
| P1 | Prompt/workflow sources | 3 | `/home/bryan/org/prompts/gai_review.md` |
| P1 | Prompt/workflow sources | 3 | `/home/bryan/org/prompts/gai_run.md` |
| P1 | Prompt/workflow sources | 3 | `/home/bryan/org/prompts/gai_work_projects_v2.md` |
| P1 | Prompt/workflow sources | 2 | `/home/bryan/org/prompts/gai_fig_shares.md` |
| P1 | Prompt/workflow sources | 2 | `/home/bryan/org/prompts/gai_fix_state_trans.md` |
| P1 | Prompt/workflow sources | 2 | `/home/bryan/org/prompts/gai_gemi.md` |
| P1 | Prompt/workflow sources | 2 | `/home/bryan/org/prompts/gai_new_ynx.md` |
| P1 | Prompt/workflow sources | 2 | `/home/bryan/org/prompts/gai_periodic.md` |
| P1 | Prompt/workflow sources | 2 | `/home/bryan/org/prompts/gai_presubmit.md` |
| P1 | Prompt/workflow sources | 2 | `/home/bryan/org/prompts/gai_work.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_failing_tests.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_fix_hg_update.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_fix_tdd_feature_test_cmd.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_hooks_v2.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_new_ez_feature.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_new_feature.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_no_failed_test_research.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_review_2.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_snippets.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_super_fix_tests.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_tag_archive.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_test_cmd.md` |
| P1 | Prompt/workflow sources | 1 | `/home/bryan/org/prompts/gai_urls.md` |
| P2 | Dated execution history | 36 | `/home/bryan/org/2026/20260101_done.zo` |
| P2 | Dated execution history | 33 | `/home/bryan/org/2025/20251114_done.zo` |
| P2 | Dated execution history | 25 | `/home/bryan/org/2026/20260115_poms.zo` |
| P2 | Dated execution history | 23 | `/home/bryan/org/2025/20251220_done.zo` |
| P2 | Dated execution history | 23 | `/home/bryan/org/2025/20251221_done.zo` |
| P2 | Dated execution history | 22 | `/home/bryan/org/2025/20251223_poms.zo` |
| P2 | Dated execution history | 22 | `/home/bryan/org/2026/20260204_poms.zo` |
| P2 | Dated execution history | 20 | `/home/bryan/org/2025/20251221_poms.zo` |
| P2 | Dated execution history | 19 | `/home/bryan/org/2025/20251106_done.zo` |
| P2 | Dated execution history | 19 | `/home/bryan/org/2025/20251106_poms.zo` |
| P2 | Dated execution history | 19 | `/home/bryan/org/2025/20251227_poms.zo` |
| P2 | Dated execution history | 19 | `/home/bryan/org/2025/20251229_done.zo` |
| P2 | Dated execution history | 19 | `/home/bryan/org/2025/20251229_poms.zo` |
| P2 | Dated execution history | 19 | `/home/bryan/org/2026/20260108_poms.zo` |
| P2 | Dated execution history | 18 | `/home/bryan/org/2025/20251226_poms.zo` |
| P2 | Dated execution history | 18 | `/home/bryan/org/2026/20260114_poms.zo` |
| P2 | Dated execution history | 17 | `/home/bryan/org/2026/20260115_done.zo` |
| P2 | Dated execution history | 17 | `/home/bryan/org/2026/20260117_done.zo` |
| P2 | Dated execution history | 16 | `/home/bryan/org/2025/20251109_done.zo` |
| P2 | Dated execution history | 16 | `/home/bryan/org/2025/20251226_done.zo` |
| P2 | Dated execution history | 16 | `/home/bryan/org/2026/20260107_poms.zo` |
| P2 | Dated execution history | 15 | `/home/bryan/org/2026/20260104_done.zo` |
| P2 | Dated execution history | 14 | `/home/bryan/org/2025/20251101_done.zo` |
| P2 | Dated execution history | 14 | `/home/bryan/org/2025/20251107_poms.zo` |
| P2 | Dated execution history | 14 | `/home/bryan/org/2025/20251228_day.zo` |
| P2 | Dated execution history | 14 | `/home/bryan/org/2025/20251228_poms.zo` |
| P2 | Dated execution history | 14 | `/home/bryan/org/2026/20260102_poms.zo` |
| P2 | Dated execution history | 14 | `/home/bryan/org/2026/20260112_poms.zo` |
| P2 | Dated execution history | 14 | `/home/bryan/org/2026/20260113_done.zo` |
| P2 | Dated execution history | 14 | `/home/bryan/org/2026/20260117_poms.zo` |
| P2 | Dated execution history | 13 | `/home/bryan/org/2025/20251107_done.zo` |
| P2 | Dated execution history | 13 | `/home/bryan/org/2026/20260106_poms.zo` |
| P2 | Dated execution history | 13 | `/home/bryan/org/2026/20260118_done.zo` |
| P2 | Dated execution history | 13 | `/home/bryan/org/2026/20260202_poms.zo` |
| P2 | Dated execution history | 12 | `/home/bryan/org/2025/20251113_done.zo` |
| P2 | Dated execution history | 12 | `/home/bryan/org/2025/20251222_done.zo` |
| P2 | Dated execution history | 12 | `/home/bryan/org/2025/20251228_done.zo` |
| P2 | Dated execution history | 12 | `/home/bryan/org/2025/20251230_poms.zo` |
| P2 | Dated execution history | 12 | `/home/bryan/org/2026/20260109_poms.zo` |
| P2 | Dated execution history | 12 | `/home/bryan/org/2026/20260112_done.zo` |
| P2 | Dated execution history | 12 | `/home/bryan/org/2026/20260120_done.zo` |
| P2 | Dated execution history | 12 | `/home/bryan/org/2026/20260131_poms.zo` |
| P2 | Dated execution history | 11 | `/home/bryan/org/2025/20251220_poms.zo` |
| P2 | Dated execution history | 11 | `/home/bryan/org/2025/20251222_poms.zo` |
| P2 | Dated execution history | 11 | `/home/bryan/org/2026/20260105_poms.zo` |
| P2 | Dated execution history | 11 | `/home/bryan/org/2026/20260107_done.zo` |
| P2 | Dated execution history | 11 | `/home/bryan/org/2026/20260114_done.zo` |
| P2 | Dated execution history | 11 | `/home/bryan/org/2026/20260120_poms.zo` |
| P2 | Dated execution history | 11 | `/home/bryan/org/2026/20260211_poms.zo` |
| P2 | Dated execution history | 11 | `/home/bryan/org/2026/20260222_done.zo` |
| P2 | Dated execution history | 10 | `/home/bryan/org/2026/20260108_done.zo` |
| P2 | Dated execution history | 10 | `/home/bryan/org/2026/20260109_done.zo` |
| P2 | Dated execution history | 10 | `/home/bryan/org/2026/20260118_poms.zo` |
| P2 | Dated execution history | 10 | `/home/bryan/org/2026/20260119_done.zo` |
| P2 | Dated execution history | 10 | `/home/bryan/org/2026/20260119_poms.zo` |
| P2 | Dated execution history | 10 | `/home/bryan/org/2026/20260203_poms.zo` |
| P2 | Dated execution history | 10 | `/home/bryan/org/2026/20260206_poms.zo` |
| P2 | Dated execution history | 9 | `/home/bryan/org/2025/20251111_done.zo` |
| P2 | Dated execution history | 9 | `/home/bryan/org/2025/20251120_poms.zo` |
| P2 | Dated execution history | 9 | `/home/bryan/org/2026/20260313_poms.zo` |
| P2 | Dated execution history | 8 | `/home/bryan/org/2026/20260101_poms.zo` |
| P2 | Dated execution history | 8 | `/home/bryan/org/2026/20260105_done.zo` |
| P2 | Dated execution history | 8 | `/home/bryan/org/2026/20260113_poms.zo` |
| P2 | Dated execution history | 8 | `/home/bryan/org/2026/20260122_done.zo` |
| P2 | Dated execution history | 8 | `/home/bryan/org/2026/20260205_done.zo` |
| P2 | Dated execution history | 8 | `/home/bryan/org/2026/20260211_done.zo` |
| P2 | Dated execution history | 8 | `/home/bryan/org/2026/20260325_poms.zo` |
| P2 | Dated execution history | 7 | `/home/bryan/org/2025/20251030_poms.zo` |
| P2 | Dated execution history | 7 | `/home/bryan/org/2025/20251104_done.zo` |
| P2 | Dated execution history | 7 | `/home/bryan/org/2025/20251105_poms.zo` |
| P2 | Dated execution history | 7 | `/home/bryan/org/2025/20251114_poms.zo` |
| P2 | Dated execution history | 7 | `/home/bryan/org/2025/20251224_poms.zo` |
| P2 | Dated execution history | 7 | `/home/bryan/org/2026/20260106_done.zo` |
| P2 | Dated execution history | 7 | `/home/bryan/org/2026/20260116_done.zo` |
| P2 | Dated execution history | 7 | `/home/bryan/org/2026/20260121_poms.zo` |
| P2 | Dated execution history | 7 | `/home/bryan/org/2026/20260124_poms.zo` |
| P2 | Dated execution history | 7 | `/home/bryan/org/2026/20260126_poms.zo` |
| P2 | Dated execution history | 7 | `/home/bryan/org/2026/20260129_poms.zo` |
| P2 | Dated execution history | 7 | `/home/bryan/org/2026/20260203_done.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2025/20251024_poms.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2025/20251029_done.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2025/20251030_day.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2025/20251105_day.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2025/20251108_poms.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2025/20251111_poms.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2025/20251119_poms.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2025/20251207_poms.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2026/20260121_done.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2026/20260128_done.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2026/20260129_done.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2026/20260208_poms.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2026/20260214_day.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2026/20260215_poms.zo` |
| P2 | Dated execution history | 6 | `/home/bryan/org/2026/20260324_poms.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2025/20251024_done.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2025/20251026_done.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2025/20251104_poms.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2025/20251223_done.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2025/20251231_poms.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2026/20260104_poms.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2026/20260111_poms.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2026/20260122_poms.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2026/20260124_done.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2026/20260127_poms.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2026/20260210_poms.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2026/20260217_poms.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2026/20260318_poms.zo` |
| P2 | Dated execution history | 5 | `/home/bryan/org/2026/20260319_poms.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2025/20251025_poms.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2025/20251026_poms.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2025/20251029_poms.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2025/20251102_poms.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2025/20251103_poms.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2025/20251110_done.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2025/20251113_poms.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2025/20251126_poms.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2025/20251207_done.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2025/20251227_done.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2026/20260102_done.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2026/20260103_poms.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2026/20260213_done.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2026/20260217_done.zo` |
| P2 | Dated execution history | 4 | `/home/bryan/org/2026/20260401_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2025/20251023_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2025/20251028_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2025/20251030_done.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2025/20251031_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2025/20251101_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2025/20251105_done.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2025/20251110_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2025/20251121_done.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2025/20251128_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2025/20251129_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2025/20251201_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2025/20251218_done.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2026/20260102_day.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2026/20260122_day.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2026/20260205_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2026/20260206_day.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2026/20260214_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2026/20260223_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2026/20260224_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2026/20260311_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2026/20260317_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2026/20260322_poms.zo` |
| P2 | Dated execution history | 3 | `/home/bryan/org/2026/20260326_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251025_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251027_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251028_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251112_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251112_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251115_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251116_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251116_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251128_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251208_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251219_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251219_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251224_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2025/20251225_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260110_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260111_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260130_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260201_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260214_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260215_day.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260216_day.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260217_day.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260218_day.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260221_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260225_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260306_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260312_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260313_done.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260314_day.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260315_day.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260316_day.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260319_day.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260321_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260423_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260427_poms.zo` |
| P3 | Dated execution history | 2 | `/home/bryan/org/2026/20260429_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20250615_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251022_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251022_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251023_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251027_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251031_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251101_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251102_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251103_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251103_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251104_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251106_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251107_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251108_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251109_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251109_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251110_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251111_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251112_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251113_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251114_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251115_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251116_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251117_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251117_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251117_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251118_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251118_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251119_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251119_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251120_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251121_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251121_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251122_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251123_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251124_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251124_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251125_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251126_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251126_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251127_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251128_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251129_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251129_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251130_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251130_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251130_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251201_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251202_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251203_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251204_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251205_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251206_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251206_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251207_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251208_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251209_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251210_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251211_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251211_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251212_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251213_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251214_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251215_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251216_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251217_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251218_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251219_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251220_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251221_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251222_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251223_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251224_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251225_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251226_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251227_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251229_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251230_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2025/20251231_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260101_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260103_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260103_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260104_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260105_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260106_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260107_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260108_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260109_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260110_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260111_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260112_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260113_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260114_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260115_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260116_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260116_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260117_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260118_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260119_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260120_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260121_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260123_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260123_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260124_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260125_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260126_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260126_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260127_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260128_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260129_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260130_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260131_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260201_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260202_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260202_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260203_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260204_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260205_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260207_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260207_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260208_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260208_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260209_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260209_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260210_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260210_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260211_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260212_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260213_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260213_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260219_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260220_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260221_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260222_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260222_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260223_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260223_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260224_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260225_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260226_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260226_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260227_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260227_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260301_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260301_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260302_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260303_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260303_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260304_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260305_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260306_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260310_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260311_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260312_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260313_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260316_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260317_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260318_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260319_done.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260320_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260320_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260321_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260322_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260323_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260324_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260325_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260326_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260327_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260327_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260328_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260329_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260329_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260330_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260330_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260331_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260331_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260401_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260402_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260403_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260404_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260405_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260406_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260407_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260408_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260409_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260410_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260411_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260412_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260413_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260414_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260415_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260416_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260417_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260418_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260419_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260420_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260421_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260422_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260423_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260424_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260425_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260425_poms.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260427_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260428_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260429_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260430_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260503_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260504_day.zo` |
| P3 | Dated execution history | 1 | `/home/bryan/org/2026/20260504_poms.zo` |
| P3 | External/lit/reference notes | 2 | `/home/bryan/org/ai_ref.zo` |
| P3 | External/lit/reference notes | 2 | `/home/bryan/org/gemini_cli_ref.zo` |
| P3 | Incidental/background references | 102 | `/home/bryan/org/inbox.zo` |
| P3 | Incidental/background references | 31 | `/home/bryan/org/zoq/needs_attn.zoq` |
| P3 | Incidental/background references | 5 | `/home/bryan/org/work_ref.zo` |
| P3 | Incidental/background references | 4 | `/home/bryan/org/work_ideas.zo` |
| P3 | Incidental/background references | 3 | `/home/bryan/org/goog_tools.zo` |
| P3 | Incidental/background references | 2 | `/home/bryan/org/h2_role.zo` |
| P3 | Incidental/background references | 1 | `/home/bryan/org/dev_ideas.zo` |
| P3 | Incidental/background references | 1 | `/home/bryan/org/fscarpel_meet_2025Q4.zo` |
| P3 | Incidental/background references | 1 | `/home/bryan/org/now_dev.zo` |
| P3 | Incidental/background references | 1 | `/home/bryan/org/now_prjs.zo` |
| P3 | Incidental/background references | 1 | `/home/bryan/org/now_work.zo` |
| P3 | Incidental/background references | 1 | `/home/bryan/org/text/sase_notify.md` |
| P3 | Incidental/background references | 1 | `/home/bryan/org/text/sase_periodic_zorg.txt` |
| P3 | Incidental/background references | 1 | `/home/bryan/org/zot/day_log.zot` |
