## What does this PR add or change?

<!-- One or two sentences. Link the issue if there is one. -->

## Category

- [ ] New skill
- [ ] Fix to an existing skill (a rule, number or source was wrong)
- [ ] New script or tests
- [ ] Docs / README
- [ ] Other

## If this PR states a rule, rate, threshold or legal requirement

<!-- This is the important one. A wrong claim here generates wrong code for
     everyone who installs the skill. -->

- Source (official docs / government site preferred):
- Date you verified it:
- Is it likely to go stale? Should the skill tell the agent to re-check it?

## Checklist

- [ ] `python -m pytest -q` passes locally
- [ ] SKILL.md has valid frontmatter (`name` matches the folder name, `description` says what it does **and when to use it**)
- [ ] Any new script is **Python 3.9+ stdlib only** — no third-party imports
- [ ] No API keys, no real personal data, no promotional content
- [ ] I have not fabricated any number or rule I could not source
