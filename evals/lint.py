#!/usr/bin/env python3
"""Static checks for every skill in this repo: the mistakes past reviews found.

Errors fail the run; warnings are printed for a human to judge. Needs no
network and no claude login, so CI runs it on every pull request.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
DESCRIPTION_MAX = 300
BODY_BUDGET = 10_000
# Claude Code built-ins and repo-local skills a description or body may name.
KNOWN_ELSEWHERE = {"code-review", "simplify", "security-review", "schedule", "dataviz", "release"}

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.S)
NOT_FOR = re.compile(r"Not for (.*)$", re.S)
PAREN_NAME = re.compile(r"\(([a-z0-9][a-z0-9-]*)\)")
SKILL_MENTION = re.compile(r"`([a-z0-9][a-z0-9-]*)` skill|\(([a-z0-9][a-z0-9-]*) skill\)")
LOCAL_LINK = re.compile(r"\]\((?!https?:|#|mailto:|t3-thread:)([^)\s#]+)")
INSTALLED_PATH = re.compile(r"~/\.agents/skills/([a-z0-9-]+)/((?:scripts|references|templates|assets)/[\w./-]+)")
OWN_PATH = re.compile(r"`((?:scripts|references|templates|assets)/[\w./-]+)")
RELATIVE_RUN = re.compile(r"^\s*(?:python3?|node|bash|sh|uv run\S*)\s+(?:-\S+\s+)*(?:\./)?(?:[\w-]+/)?scripts/")
PLACEHOLDER_PATH = r"/(?:absolute/)?path/to/(?:skills?|{skills})\b"
USER_HOME = re.compile(r"/home/dell/")
LAST_VERIFIED = re.compile(r"^Last verified: \d{4}-\d{2}-\d{2}$", re.M)
# Each trap below was found in a skill; the message says why it breaks.
# Anywhere in a file, prose and table cells included:
TRAPS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\$\{?SKILL_DIR\b"), "$SKILL_DIR is set by nothing; use ~/.agents/skills/<name>"),
    (re.compile(r"pgrep[^`\n]*\\\\?\|"), "pgrep uses extended regex: \\| is a literal pipe, so the pattern never matches"),
    (re.compile(r"find -L[^`\n]*%l"), "with -L, find follows the link and %l prints nothing"),
]
# Only inside code blocks (prose says "under `bws-run infra`" as shorthand):
CODE_TRAPS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:^|[\s;|&(`'\"])(?:broker-run|bws-run) (?!<)"), "not on PATH; call ~/.agents/skills/<skill>/scripts/<tool>"),
]
BARE_PYTHON = re.compile(r"^\s*(?:\S+=\S+\s+)*python(?:\s|$)")


@dataclass(frozen=True)
class Finding:
    level: str
    where: str
    message: str


def known_skills() -> set[str]:
    ours = {p.parent.name for p in REPO.glob("*/SKILL.md")}
    return ours | KNOWN_ELSEWHERE


def code_lines(text: str) -> list[tuple[int, str]]:
    """Lines inside fenced code blocks, with 1-based line numbers."""
    inside, out = False, []
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            inside = not inside
        elif inside:
            out.append((number, line))
    return out


def check_frontmatter(skill: Path, text: str, known: set[str]) -> list[Finding]:
    where = f"{skill.name}/SKILL.md"
    match = FRONTMATTER.match(text)
    if not match:
        return [Finding("ERROR", where, "no YAML frontmatter")]
    try:
        front = yaml.safe_load(match.group(1))
    except yaml.YAMLError as err:
        return [Finding("ERROR", where, f"frontmatter is not valid YAML: {err}")]
    found: list[Finding] = []
    if front.get("name") != skill.name:
        found.append(Finding("ERROR", where, f"name {front.get('name')!r} differs from folder {skill.name!r}"))
    description = " ".join(str(front.get("description", "")).split())
    if not description:
        found.append(Finding("ERROR", where, "no description"))
    elif len(description) > DESCRIPTION_MAX:
        found.append(Finding("ERROR", where, f"description is {len(description)} chars, max {DESCRIPTION_MAX}"))
    if "description: >-" not in match.group(1):
        found.append(Finding("WARN", where, "description is not a `>-` folded block"))
    if "when_to_use" in front:
        found.append(Finding("ERROR", where, "`when_to_use` is read only by Claude Code; put triggers in description"))
    if not_for := NOT_FOR.search(description):
        for name in PAREN_NAME.findall(not_for.group(1)):
            if name not in known:
                found.append(Finding("ERROR", where, f"description points at unknown skill ({name})"))
    if front.get("disable-model-invocation"):
        policy = skill / "agents" / "openai.yaml"
        if not policy.exists() or "allow_implicit_invocation: false" not in policy.read_text():
            found.append(Finding("ERROR", where, "manual-only skill lacks agents/openai.yaml with allow_implicit_invocation: false"))
    elif "Use when" not in description:
        found.append(Finding("WARN", where, "description has no `Use when` trigger clause"))
    return found


def check_file(skill: Path, path: Path, known: set[str]) -> list[Finding]:
    text = path.read_text()
    rel = path.relative_to(REPO)
    placeholder = re.compile(PLACEHOLDER_PATH.format(skills="|".join(sorted(known))))
    found: list[Finding] = []
    example_lines = {number for number, _ in code_lines(text)}
    for number, line in enumerate(text.splitlines(), 1):
        where = f"{rel}:{number}"
        for target in LOCAL_LINK.findall(line) if number not in example_lines else []:
            if ("/" in target or "." in target) and not (path.parent / target).exists():
                found.append(Finding("ERROR", where, f"link to missing file {target}"))
        for owner, sub in INSTALLED_PATH.findall(line):
            if (REPO / owner).is_dir() and not (REPO / owner / sub.rstrip(".")).exists():
                found.append(Finding("ERROR", where, f"~/.agents/skills/{owner}/{sub} does not exist in the repo"))
        # In references a bare `scripts/x` often means another repo's script; only SKILL.md is checked.
        for sub in OWN_PATH.findall(line) if path.name == "SKILL.md" else []:
            if "<" not in sub and not (skill / sub.rstrip(".")).exists():
                # A bare scripts/ path may be another repo's (dash's scripts/index-reports.mjs).
                level = "WARN" if sub.startswith("scripts/") else "ERROR"
                found.append(Finding(level, where, f"`{sub}` does not exist in {skill.name}/"))
        for a, b in SKILL_MENTION.findall(line):
            if (name := a or b) not in known:
                found.append(Finding("ERROR", where, f"names unknown skill `{name}`"))
        if placeholder.search(line):
            found.append(Finding("ERROR", where, "placeholder path; give the real one"))
        if USER_HOME.search(line):
            found.append(Finding("WARN", where, "/home/dell/ breaks on the Mac; use ~/"))
    for number, line in enumerate(text.splitlines(), 1):
        for trap, why in TRAPS:
            if trap.search(line):
                found.append(Finding("ERROR", f"{rel}:{number}", why))
        if line.startswith("|") and re.search(r"`[^`]*\\\|[^`]*`", line):
            found.append(Finding("WARN", f"{rel}:{number}", "command with \\| in a table cell copies as a literal \\|; move it to a code block"))
    for number, line in code_lines(text):
        for trap, why in CODE_TRAPS:
            if trap.search(line):
                found.append(Finding("ERROR", f"{rel}:{number}", why))
        if BARE_PYTHON.search(line):
            found.append(Finding("ERROR", f"{rel}:{number}", "`python` is not installed on the Dell; use python3"))
        if RELATIVE_RUN.search(line):
            found.append(Finding("ERROR", f"{rel}:{number}",
                                 f"relative script path fails outside the skill; use ~/.agents/skills/{skill.name}/scripts/"))
    return found


def lint() -> list[Finding]:
    known = known_skills()
    found: list[Finding] = []
    for skill_md in sorted(REPO.glob("*/SKILL.md")):
        skill = skill_md.parent
        text = skill_md.read_text()
        found += check_frontmatter(skill, text, known)
        size = len(text.encode())
        if size > BODY_BUDGET:
            found.append(Finding("WARN", f"{skill.name}/SKILL.md",
                                 f"{size} bytes, budget {BODY_BUDGET}: move task-only detail to references/"))
        for doc in [skill_md, *sorted(skill.glob("*/*.md"))]:
            found += check_file(skill, doc, known)
        for ref in sorted(skill.glob("references/*.md")):
            if not LAST_VERIFIED.search("\n".join(ref.read_text().splitlines()[:5])):
                found.append(Finding("ERROR", str(ref.relative_to(REPO)),
                                     "no `Last verified: YYYY-MM-DD` in the first 5 lines"))
    return found


def main() -> int:
    found = lint()
    for f in found:
        print(f"{f.level:<5} {f.where}  {f.message}")
    errors = sum(f.level == "ERROR" for f in found)
    print(f"\n{errors} errors, {len(found) - errors} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
