#gh:sase I want to test out our new sase_plan integration. Can you create a plan for creating a new `#reads` xprompt
YAML workflow (defined in the .xprompts/) that runs gemini, claude, and codex agents with same prompt: Find recent,
medium-to-long articles or research papers that will help me continue developing sase. These should run in parallel. A
final claude agent should consolidate and de-duplicate the list of articles/papers and provide a single "best next read"
recommendation. %model:gpt-5.3-codex #pr:reads_xprompt
