---
name: agent-retrospective
description: >-
  Review local Claude Code and Codex agent sessions for repeated
  mistakes, rediscovery, decision loops, and workflow improvements. Use when the
  user asks for an agent retro or wants rules, skills, tools, or process improved.
  Not for daily productivity or time tracking.
---

# Agent retrospective

Use this on demand. It is a short improvement conversation, not a daily report
and not a stateful service.

## Run

Collect recent sessions with the standalone collector:

```sh
python3 -I ~/.agents/skills/agent-retrospective/scripts/retro.py --hours 168
```

Use the user's window when supplied. The command's default is seven days. It
reads local Claude Code and Codex session directories (T3 threads included) and
prints a compact inventory of the latest 30 sessions, newest first. Inventory
subjects use actual user prompts, excluding injected AGENTS.md, skill and
environment blocks; prompts and final replies are shown only with `--show`.
Use `--limit 100` to include more sessions. It does not save a ledger or report.
If a provider is absent or unsupported, say so.

The roots are `~/.claude/projects` and `~/.codex/sessions`.

To inspect one selected session without dumping the raw log:

```sh
python3 -I ~/.agents/skills/agent-retrospective/scripts/retro.py --show <session-file> --hours 168
```

To see what agents ran in their shells across all sessions, and what failed:

```sh
python3 -I ~/.agents/skills/agent-retrospective/scripts/retro.py --tools --hours 168
```

It summarises Claude Code Bash calls and Codex `exec_command` calls
per agent: top commands (skipping `cd`/`export` set-up), errors by kind and by command with
one redacted sample each, missing command names, and commands repeated five or more times,
then the top commands in zsh and Nu history (whole files, not the window). Error kinds are
loose text matches; read the samples before trusting a count. Run it on the machine where
the sessions ran: it reads only local session files.

Read only the sessions relevant to the review. Do not quote secrets or copy raw
transcripts into the skill directory. Keep temporary output out of the repo.

## Reader and judgement

Use a cheap reader to extract facts when there are several sessions:

- Claude parent thread: use Haiku.
- GPT or Codex parent thread: use GPT-6.1 Terra.

Give the reader the collector command and selected session paths. Ask for facts
only: goal, outcome, user correction, agent error, detour, blocker, repeated
decision, missing tool or fact, and evidence. The parent thread judges patterns,
verifies important claims, and writes the answer. If the reader is unavailable,
read the sessions yourself.

## Tool-call signals

Map each signal in the `--tools` summary to the place that owns the fix:

| Signal | Usual cause | Owner |
|---|---|---|
| `Missing commands` for a tool that is installed | PATH gap in agents' non-interactive shell | the shell's env file (`.zshenv`, `.bash_profile`) in the dotfiles repo |
| `Missing commands` for a tool that is not installed (`python`, `go`, `jq`) | missing package | the machine's setup or install script |
| `pkill` errors, exit 143 or 144 | `pkill -f` matched its own shell | a bracket-pattern rule (`pkill -f '[p]attern'`) in the global `CLAUDE.md`/`AGENTS.md` |
| The same multi-step line repeated across sessions | no script or skill for it | a script in the owning repo's `bin/`, or a skill |
| Paths, ports or unit names looked up in many sessions | fact not written down | the owning skill or project `CLAUDE.md`/`AGENTS.md` |
| `denied by user` | agent asked for something the user refused | the rule or skill that led there |
| Long `sleep`/`until` loops, `timeout` | waiting without a signal | the skill that runs the wait |

## What to report

Keep the answer concise:

1. What worked and why.
2. Repeated friction, with session paths or timestamps as evidence.
3. Likely root causes: project rule, shared skill, tool, process, or isolated
   incident.
4. Up to three proposed improvements. Name the owning repository or file and
   the exact behavior to change.

Verify a proposed lesson against the current repository or installed skill
before recommending it. A single unusual incident is not a durable rule.

Never edit `~/.claude/CLAUDE.md`, any `AGENTS.md`, a skill, a tool, or a
project during the retro. Ask which proposed improvements to implement in a later
change. Save a Markdown copy only when the user asks for one; otherwise leave
no state behind.
