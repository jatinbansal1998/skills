# Raising a stack of PRs

Last verified: 2026-11-05

Uses the `gh stack` extension (`gh extension install github/gh-stack`, checked on v0.1.0).
Never push or open a PR for the big branch itself.

1. Plan layers bottom to top, split by whole file, each passing checks on its own. Tell the
   user the layers.
2. One branch per layer. `gh stack init --base` branches from the *local* base, so update it:

   ```bash
   base=main; big=my-big-branch
   git fetch origin && git switch "$base" && git pull --ff-only
   gh stack init --base "$base" "$big-1"
   git restore --source "$big" --staged --worktree -- <layer 1 paths> && git commit -m "<title>"
   gh stack add "$big-2"
   git restore --source "$big" --staged --worktree -- <layer 2 paths> && git commit -m "<title>"
   git diff "$big" HEAD --stat       # after the top layer: empty means nothing was left behind
   ```

   `git restore --source` carries deletions; `git checkout "$big" -- <paths>` fails on them.
3. Run the secret scan and checks on each layer against the layer below. Never `git rebase` a
   layer by hand.
4. `gh stack submit --auto --open`. A non-interactive shell forces `--auto`, which alone
   opens drafts.
5. Give each PR (`gh stack view --json`) a real title and body with
   `gh pr edit <pr-url> --title "<title>" --body-file <file>`, opening with its place, e.g.
   `Part 2 of 3: builds on #171, followed by #173.` Watch each PR's checks.
6. Base moved or a layer changed or merged: `gh stack sync` (`--prune` after a merge).
   Conflict: `gh stack rebase`, then `gh stack sync`.

If `gh stack` is unavailable or `submit` fails, tell the user and raise the same layers with
`gh pr create --base <branch below>`, bottom first.
