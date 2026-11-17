---
name: github-pr
description: >-
  File a concise pull request, or a stack of them. Use whenever a PR is about to
  be opened: the user asks to raise, file, open, create a PR or says ship it,
  finished work is ready for review, or a change is too big for one PR. Not for
  reviewing or merging PRs.
---

# GitHub PR

## Hard rules

- **Never a draft.** Never pass `--draft`, override tools that default to it, and `gh pr ready` any draft that slipped through.
- Never PR from the base branch. Pick the base from the repo (`gh repo view --json defaultBranchRef`, or `development` if it uses one) and state it.
- Never `--no-verify`. A failing hook is a failing check.

## Title

Say why the change matters, ≤72 chars:
❌ `perf(server): negotiate permessage-deflate on the websocket`
✅ `perf(server): cut websocket frame size by 70%+ with gzipping`

## Body

```markdown
## Why
<1–3 sentences: the problem in the user's terms, from the session's first prompt and
corrections ("Reports were being committed to git and bloating the repo", not "This PR adds a
gitignore entry"). Linked issues or tickets: `Closes #<n>` (or the key) once per issue this PR
fully resolves, e.g. `Closes #12, closes #15`; `Part of #<n>` for one that a later PR finishes.>

## What changed
<short bullets, highest-impact first>

## Before and after
<per output that moved (screen, log line, metric with unit, command result, behaviour under a
condition): the input, the old output, the new. Quote real output from this session; label a
sketch illustrative. Screens: references/screenshots.md. Omit when output is unchanged.>

## Risk and rollout
<only when deploying needs more than a plain deploy (migration, config/env change, deploy order,
feature flag, breaking change): steps in order and rollback, in a `> [!WARNING]` alert.>

## Testing
<what was actually run and its result; "not run" if nothing was>
```

- A repo PR template is the structure when one exists: fill these sections into its headings, tick only true checklist items.
- Never paste customer data.
- End with `Created with <model> in <harness>.`, using the model names the harness reports (subagents included), or only the harness if unknown. This line replaces a `Co-Authored-By` trailer: never add one.

## References

| File | Read when | Holds |
|---|---|---|
| [references/screenshots.md](references/screenshots.md) | The user asks for screenshots, or the change visibly affects UI | Capture, native `--attach` upload, verification |
| [references/stacks.md](references/stacks.md) | Step 3's size check, or the user asks for a stack | Raising layers with `gh stack` |

## Steps

1. If the branch already has an open PR (`gh pr view --json url,state`), update it (below) instead of creating one. Dirty tree: ask what to include.
2. Rebase on the freshly fetched base and run what CI runs (`.github/workflows/`). Red stops the PR: fix it or tell the user.
3. Check the diff against `origin/<base>`:
   - Secrets: `git diff --name-only -G '(api[_-]?key|secret|token|passw|BEGIN .*PRIVATE KEY)' origin/<base>...HEAD` prints only file names. Confirm each match is a name, not a value. No `.env`, build output or reports.
   - Self-review: read the whole diff once as its reviewer. Remove debug output, commented-out code, stray TODOs, unrelated reformatting and files committed by accident.
   - Size: over about 400 changed lines (not counting lockfiles and generated code), raise a stack per [references/stacks.md](references/stacks.md) instead of steps 4–5. One PR only when the user says so.
4. Push, then `gh pr create --assignee @me --title "..." --body-file <file>`.
   - Reviewers: none by hand when the repo has `CODEOWNERS`; otherwise only ones the user names.
   - Labels: only when recent merged PRs carry them, and only from `gh label list`.
5. On lines a reviewer would question (a deliberate retry, an odd ordering, a workaround), leave a PR review comment saying why.
6. `gh pr checks <pr-url> --watch --fail-fast`; fix and push until green. Report the URL with the result.

## Updating an open PR

The body describes the branch as it is now. After pushes that change what the PR does or how it was tested, rewrite the stale sections with `gh pr edit <pr-url> --body-file <file>`.
