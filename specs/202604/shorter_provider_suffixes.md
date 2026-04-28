 We currently append ".<llm>" to agent names when multiple models / LLM providers are given to the `%m` directive (either as multiple args or via multiple `%m` directives). Can you help me start using shorter strings for
`<llm>`? Namely, let's use "gem" instead of "gemini", "cld" instead of "claude", and "cdx" instead of "codex". Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.


### Additional Requirements

- We should also use "jet" instead of "jetski/jetski-default" for the jetski provider, defined in the ../sase-google repo.