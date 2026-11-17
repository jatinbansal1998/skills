---
name: sudo-handoff
description: >-
  Run root-only commands without agent sudo: hand the user one sudo line,
  then read its output file. Use when the next command needs root (apt,
  system units, /etc), or on "sudo: a password is required", "Permission
  denied" or "Operation not permitted". Not for API keys or tokens.
---

# Sudo handoff

The agent cannot type a sudo password. Do not ask the user to run commands and
paste output back. Write a script, hand over one line, read the result yourself.

```bash
sudo -n true 2>/dev/null && echo SUDO_OK || echo NO_SUDO
```

If it prints `SUDO_OK`, sudo works without a password (a recent `sudo` in the same
terminal, or a passwordless rule): run the commands yourself. If it prints
`NO_SUDO`, use this flow.

## 1. Write the script

Do everything that needs no root first: check preconditions (for example
`/sys/kernel/security/lockdown` before an MSR write), validate configs
(`systemd-analyze verify`, `--dry-run`), read what is world-readable. The script
holds only the root part, so a failure in it is about root, not a typo.

One script per step: read-only diagnostics first, then a separate script for a
change, so the user can run the safe one without committing to the other.

One directory per task, created by the agent: `/tmp/<task>/` (for example
`/tmp/cpu-diag/`). Never write root output straight into `/tmp`: with
`fs.protected_regular=2` (Ubuntu's default), root cannot reopen a file there that
another user owns, so a re-run can fail. Use the directory on macOS too. A directory the agent owns avoids
that, and root's output (umask 022) stays readable by the agent.

Script shape, written to `/tmp/<task>/<step>.sh` and made executable with
`chmod +x`:

```bash
#!/bin/bash
# <One line: what this does, and "Read-only, changes nothing." or what it changes.>
exec > /tmp/<task>/<step>-output.txt 2>&1
set -x
<commands, absolute paths only>
```

- `exec >` sends everything, errors included, to the file. `set -x` prints each
  command before its output, so every line in the file traces to its command.
- Diagnostics: no `set -e`. One failed probe should not hide the rest.
- Changes: `set -euo pipefail` after `set -x`. Capture the state before, apply,
  capture the state after, in the same script. Prefer temporary changes (undone
  by reboot) and write a `revert-<step>.sh` next to it.
- Proving an install: undo the change first, then let the installed thing redo
  it, so the output shows it working on its own.
- No prompts. Output goes to a file, so a question would hang unseen. Pass `-y`
  (`apt-get install -y`) and give every command its input.
- The output file is read back into the transcript: keep secrets out of the
  script and its output.

## 2. Hand it over

Give the user exactly one command, then stop and wait:

```
sudo /tmp/<task>/<step>.sh
```

On another machine, write the script there over SSH and tell the user to run
the line on that machine. Read the output back over SSH.

Say in one line what it does, whether it changes anything, how to undo it, and
that its output goes to `/tmp/<task>/<step>-output.txt`. Do not poll for the
file. The user says when it has run.

## 3. Read the output yourself

```bash
date -r /tmp/<task>/<step>-output.txt   # written after the handoff? (works on Linux and macOS)
cat /tmp/<task>/<step>-output.txt
```

- A missing file or an old timestamp means it did not run. Say so; do not reuse
  an earlier result.
- Walk it command by command using the `+` lines. A failed command can still
  print a harmless-looking number. With `set -e`, check that the last command
  shown is the last one in the script.
- Report what the output proves, quoting the lines that matter.

## 4. Clean up

`/tmp` clears on reboot. Keep the revert script until the user is done with the
change. Anything that must survive goes into a repo (a systemd unit, a setup
step), not `/tmp`.
