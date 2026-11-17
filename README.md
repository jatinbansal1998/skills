# skills

Agent skills for Claude Code, Codex and other agents that read `SKILL.md`.

| Skill | What it does |
|---|---|
| [`github-pr`](github-pr/SKILL.md) | File a concise, ready-for-review pull request, or a stack of them. |
| [`pr-review-guide`](pr-review-guide/SKILL.md) | Map a large PR for your own review: risk-ranked files, reading order, questions for the author. |
| [`sudo-handoff`](sudo-handoff/SKILL.md) | Run root-only commands without giving the agent sudo: it writes a script, you run one line, it reads the output. |
| [`agent-retrospective`](agent-retrospective/SKILL.md) | Review recent agent sessions for repeated mistakes and propose rule, skill or tool fixes. |

## Install

With the [`skills` CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add jatinbansal1998/skills            # pick from the list
npx skills add jatinbansal1998/skills -s github-pr  # one skill
```

## Develop

```bash
python -m pip install pyyaml==6.0.2
python -I evals/lint.py                                   # static checks over every skill
python -I -m unittest discover -s evals -p test_lint.py   # lint tests
python -I -m unittest discover -s agent-retrospective/tests
```

CI runs the same on every pull request.
