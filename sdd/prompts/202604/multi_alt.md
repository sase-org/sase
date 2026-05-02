---
plan: sdd/tales/202604/multi_alt.md
---
I just tried to use multiple `%(...)` alternation directives in the same prompt and got the error shown in the
~/tmp/mult_alt_error.txt file. Can you help me add support for multiple `alt` directives in the same prompt, which
should result in one agent being run for each combination of alternations (ex: 4 agents will be created if two `alt`
directives are found that each specified two chunks of text)? Think this through thoroughly and create a plan using your
`/sase_plan` skill before making any file changes.
