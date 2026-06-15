---
plan: sdd/tales/202606/question_code_prompt_model.md
---
 When a "code" agent asks a question using the `/sase_questions` skill and the user answers. The new prompt we construct seems to currently use the "plan" agent (i.e. the original prompt), but it should use the same prompt that the "code" agent used for the base (i.e. before appending the questions and answers section to the bottom of the prompt). Also, we should use the model implied by `worker_models` (the same model used for the "code" agent) when launching this new agent (with the "code" prompt that has been enhanced with questions and answers).

Can you help me fix this? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.
