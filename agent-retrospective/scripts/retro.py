#!/usr/bin/env python3
"""List recent local agent sessions for an agent retrospective."""

from __future__ import annotations

import argparse
import collections
import json
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOTS = {
    "Claude Code": Path.home() / ".claude" / "projects",
    "Codex": Path.home() / ".codex" / "sessions",
    "Grok": Path.home() / ".grok" / "sessions",
    "Grok (T3)": Path.home() / ".t3" / "grok" / "sessions",
}
INJECTED_PROMPTS = ("# AGENTS.md instructions", "<skill>", "<environment_context>")
HELPER_PROMPTS = (
    "You generate concise git branch names",
    "Generate a title that will help the user",
)


@dataclass
class Session:
    path: Path
    source: str
    title: str | None = None
    turns: list[tuple[datetime, str, str]] = field(default_factory=list)
    cwd: str | None = None
    seen: set[tuple[datetime, str, str]] = field(default_factory=set)
    seen_messages: set[tuple[str, str]] = field(default_factory=set)

    @property
    def prompts(self) -> list[tuple[datetime, str]]:
        return [(when, text) for when, speaker, text in self.turns if speaker == "you"]

    @property
    def last_reply(self) -> str:
        return next((text for _, speaker, text in reversed(self.turns) if speaker == "agent"), "")

    def is_helper(self) -> bool:
        first = self.prompts[0][1] if self.prompts else ""
        return first.startswith(HELPER_PROMPTS) or (self.cwd or "").startswith("/tmp/t3code-")


def text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(item.get("text", "")) for item in value if isinstance(item, dict) and item.get("text")).strip()
    return ""


def when(value: object) -> datetime:
    if isinstance(value, (int, float)):
        if value > 10_000_000_000:
            value /= 1000
        return datetime.fromtimestamp(value, timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def add(session: Session, stamp: object, speaker: str, message: object, since: datetime) -> None:
    if not stamp:
        return
    moment = when(stamp)
    body = text(message)
    key = (moment, speaker, body)
    text_key = (speaker, body)
    if moment >= since and body and key not in session.seen and text_key not in session.seen_messages:
        session.seen.add(key)
        session.seen_messages.add(text_key)
        session.turns.append((moment, speaker, body))


def read(path: Path, source: str, since: datetime) -> Session:
    session = Session(path, source)
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = record.get("type")
            if kind == "session_meta":
                session.cwd = record.get("payload", {}).get("cwd")
            elif kind == "ai-title":
                session.title = record.get("aiTitle")
            elif source == "Claude Code" and kind in ("user", "assistant") and not record.get("isSidechain"):
                if kind == "user" and record.get("turnOrigin") not in ("human", "sdk"):
                    continue
                add(session, record.get("timestamp"), "you" if kind == "user" else "agent", record.get("message", {}).get("content"), since)
                session.cwd = record.get("cwd", session.cwd)
            elif source == "Codex":
                payload = record.get("payload", {})
                if kind == "response_item" and payload.get("type") == "message" and payload.get("role") in ("user", "assistant"):
                    add(session, record.get("timestamp"), "you" if payload["role"] == "user" else "agent", payload.get("content"), since)
                elif kind == "event_msg" and payload.get("type") == "item_completed":
                    item = payload.get("item", {})
                    if item.get("type") in ("UserMessage", "AgentMessage"):
                        add(session, record.get("timestamp"), "you" if item["type"] == "UserMessage" else "agent", item.get("content"), since)
                session.cwd = payload.get("cwd", session.cwd)
            elif source.startswith("Grok"):
                if kind in ("user", "assistant"):
                    add(session, record.get("timestamp"), "you" if kind == "user" else "agent", record.get("message", record.get("content")), since)
                elif "prompt" in record:
                    add(session, record.get("timestamp"), "you", record["prompt"], since)
    session.turns.sort()
    return session


def clip(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def sessions(hours: float) -> list[Session]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    found: list[Session] = []
    for source, root in ROOTS.items():
        if not root.exists():
            continue
        has_chat_history = any(root.rglob("chat_history.jsonl"))
        for path in root.rglob("*.jsonl"):
            if source.startswith("Grok") and path.name == "prompt_history.jsonl" and has_chat_history:
                continue
            if path.stat().st_mtime < since.timestamp():
                continue
            session = read(path, source, since)
            if session.turns and not session.is_helper():
                found.append(session)
    return sorted(found, key=lambda item: item.turns[0][0])


# Tool-call summary (--tools): what agents ran in their shells, what failed,
# and what they repeated. Only command names, counts and short redacted lines.
ERROR_KINDS = {
    "denied by user": re.compile(r"The user doesn't want to (?:proceed|take this action)"),
    "command not found": re.compile(r"command not found|not found: |Command `[^`]*` not found"),
    "no such file": re.compile(r"No such file or directory"),
    "permission denied": re.compile(r"Permission denied|Operation not permitted|a password is required"),
    "timeout": re.compile(r"timed out|deadline exceeded", re.I),
    "syntax error": re.compile(r"syntax error|parse error|unexpected token", re.I),
}
LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-+/=]{24,}")
SECRET_WORD = r"\w*(?:TOKEN|KEY|SECRET|PASS|AUTH)\w*"
SECRETS = (
    # NAME=value, NAME="a b", ?api_key=value
    (re.compile(rf"(?i)\b({SECRET_WORD})=(?:\"[^\"]*\"|'[^']*'|[^\s&]+)"), r"\1=<redacted>"),
    # "api_key": "value"
    (re.compile(rf'(?i)("{SECRET_WORD}"\s*:\s*)"[^"]*"'), r'\1"<redacted>"'),
    # Authorization: Bearer value, -H 'X-Api-Key: value'
    (re.compile(r"(?i)\b(authorization:\s*\w+|bearer|x-[\w-]*(?:key|token|secret)[\w-]*:)\s+[^\s'\"]+"), r"\1 <redacted>"),
)
CODEX_EXIT_CODE = re.compile(r'exit_code\W{0,4}:\s*(\d+)')
# zsh: "(eval):1: command not found: tmux"; bash: "tmux: command not found"; Nu: "Command `tmux` not found".
NAME = r"([A-Za-z_][\w.+-]*)"
MISSING_COMMAND = (re.compile(r"command not found: " + NAME), re.compile(NAME + r": command not found"),
                   re.compile(r"Command `" + NAME + "` not found"))
# Lines that only set up the real command, skipped when naming it.
SCAFFOLDING = {"cd", "export", "set", "echo", "printf", "true", "sleep", "source", ".", "{", "}", "(", ")"}
TWO_WORD_COMMANDS = {"git", "gh", "docker", "systemctl", "npm", "pnpm", "bun", "journalctl", "brew",
                     "apt", "sudo", "uv", "nu", "codex", "claude", "ssh", "t3", "go", "cargo"}
CODEX_COMMAND = re.compile(r'cmd:\s*"((?:[^"\\]|\\.)*)"')


@dataclass
class ToolCall:
    agent: str
    command: str
    error: str | None
    error_line: str


def redact(value: str) -> str:
    for pattern, replacement in SECRETS:
        value = pattern.sub(replacement, value)
    return LONG_TOKEN.sub("<long>", value)


def missing_command(line: str) -> str | None:
    found = next((match for pattern in MISSING_COMMAND if (match := pattern.search(line))), None)
    return found.group(1).rsplit("/", 1)[-1] if found else None


def segment_head(segment: str) -> str:
    words = [word for word in segment.split() if "=" not in word or word.startswith("-")]
    if not words:
        return ""
    first = words[0].rsplit("/", 1)[-1]
    if first in TWO_WORD_COMMANDS and len(words) > 1 and not words[1].startswith("-"):
        return f"{first} {words[1]}"
    return first


def command_head(command: str) -> str:
    """The first real command in a line such as `cd repo && export X=1; git status`."""
    heads = [segment_head(part) for part in re.split(r"&&|\|\||[;|\n]", command)]
    return next((head for head in heads if head and head not in SCAFFOLDING), heads[0] if heads else "")


def classify(output: str, failed: bool) -> tuple[str | None, str]:
    for kind, pattern in ERROR_KINDS.items():
        match = pattern.search(output)
        if match:
            line = next((line for line in output.splitlines() if pattern.search(line)), match.group(0))
            return kind, line
    return ("other error", output.splitlines()[0] if output else "") if failed else (None, "")


def in_window(record: dict, since: datetime) -> bool:
    """A session file can span weeks; keep only calls made inside the window."""
    stamp = record.get("timestamp")
    return not stamp or when(stamp) >= since


def tool_calls(hours: float) -> list[ToolCall]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    calls: list[ToolCall] = []
    claude_root, codex_root = ROOTS["Claude Code"], ROOTS["Codex"]
    for path in claude_root.rglob("*.jsonl") if claude_root.exists() else []:
        if path.stat().st_mtime < since.timestamp():
            continue
        pending: dict[str, str] = {}
        for record in records(path):
            content = record.get("message", {}).get("content") if isinstance(record.get("message"), dict) else None
            for part in content if isinstance(content, list) else []:
                if part.get("type") == "tool_use" and part.get("name") == "Bash":
                    pending[part.get("id", "")] = part.get("input", {}).get("command", "")
                elif part.get("type") == "tool_result" and part.get("tool_use_id") in pending:
                    command = pending.pop(part["tool_use_id"])
                    if in_window(record, since):
                        output = text(part.get("content")) or str(part.get("content", ""))
                        kind, line = classify(output[:4000], bool(part.get("is_error")))
                        calls.append(ToolCall("Claude Code", command, kind, line))
    for path in codex_root.rglob("*.jsonl") if codex_root.exists() else []:
        if path.stat().st_mtime < since.timestamp():
            continue
        # One exec call can run several commands; its output arrives under the same call_id.
        pending_codex: dict[str, list[str]] = {}
        for record in records(path):
            payload = record.get("payload", {})
            if payload.get("type") == "custom_tool_call":
                found = CODEX_COMMAND.findall(str(payload.get("input", "")))
                pending_codex[payload.get("call_id", "")] = [json.loads(f'"{command}"') for command in found]
            elif payload.get("type") == "custom_tool_call_output" and payload.get("call_id") in pending_codex:
                commands = pending_codex.pop(payload["call_id"])
                if commands and in_window(record, since):
                    output = payload.get("output", "")
                    body = (text(output) if isinstance(output, list) else str(output))[:4000]
                    failed = any(code != "0" for code in CODEX_EXIT_CODE.findall(body))
                    kind, line = classify(body, failed)
                    calls.extend(ToolCall("Codex", command, kind, line) for command in commands)
    return calls


def records(path: Path):
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def history_heads() -> dict[str, collections.Counter[str]]:
    files = {"zsh": Path.home() / ".zsh_history", "nu": Path.home() / ".config" / "nushell" / "history.txt"}
    heads: dict[str, collections.Counter[str]] = {}
    for shell, path in files.items():
        if path.exists():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            heads[shell] = collections.Counter(command_head(re.sub(r"^: \d+:\d+;", "", line)) for line in lines)
    return heads


def print_tools(calls: list[ToolCall], hours: float) -> None:
    print(f"Host: {socket.gethostname()} | window: last {hours:g} hours | shell tool calls: {len(calls)}")
    print("Error kinds are loose text matches: read the samples before trusting a count.")
    for agent in sorted({call.agent for call in calls}):
        mine = [call for call in calls if call.agent == agent]
        failed = [call for call in mine if call.error]
        print(f"\n== {agent}: {len(mine)} calls, {len(failed)} with an error")
        print("Top commands: " + ", ".join(f"{head} {count}" for head, count in collections.Counter(command_head(call.command) for call in mine).most_common(25)))
        print("Errors by kind: " + ", ".join(f"{kind} {count}" for kind, count in collections.Counter(call.error for call in failed).most_common()))
        missing = collections.Counter(name for call in failed if call.error == "command not found"
                                      and (name := missing_command(call.error_line)))
        if missing:
            print("Missing commands: " + ", ".join(f"{name} {count}" for name, count in missing.most_common(15)))
        print("Errors by command:")
        for (head, kind), count in collections.Counter((command_head(call.command), call.error) for call in failed).most_common(15):
            sample = next(call for call in failed if command_head(call.command) == head and call.error == kind)
            print(f"  {count:4} {head} | {kind} | {clip(redact(sample.command), 100)} -> {clip(redact(sample.error_line), 120)}")
        repeated = [(command, count) for command, count in collections.Counter(call.command.strip() for call in mine).most_common(15) if count >= 5]
        if repeated:
            print("Repeated commands:")
            for command, count in repeated:
                print(f"  {count:4}x {clip(redact(command), 140)}")
    for shell, heads in history_heads().items():
        print(f"\n== {shell} history (whole file): " + ", ".join(f"{head} {count}" for head, count in heads.most_common(30) if head))


def source_for(path: Path) -> str:
    return next((name for name, root in ROOTS.items() if path.is_relative_to(root)), "Unknown agent")


def print_session(item: Session) -> None:
    start = item.turns[0][0].astimezone().strftime("%Y-%m-%d %H:%M")
    end = item.turns[-1][0].astimezone().strftime("%H:%M")
    print(f"\n=== {item.title or '(untitled)'} [{item.source}] {start}-{end}")
    print(f"file {item.path} | cwd {item.cwd or '(unknown)'} | prompts {len(item.prompts)}")
    for moment, prompt in item.prompts:
        print(f"[{moment.astimezone():%H:%M}] you: {clip(prompt, 1200)}")
    print(f"Last reply: {clip(item.last_reply, 2000)}")


def print_inventory(item: Session) -> None:
    prompts = [prompt for _, prompt in item.prompts if not prompt.startswith(INJECTED_PROMPTS)]
    subject = prompts[0] if prompts else item.title or "(no user prompt)"
    start = item.turns[0][0].astimezone().strftime("%Y-%m-%d %H:%M")
    print(f"{start} [{item.source}] {clip(subject, 180)}")
    print(f"  {item.path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=168)
    parser.add_argument("--show", type=Path, help="show one session file")
    parser.add_argument("--limit", type=int, default=30, help="maximum inventory rows (default: 30)")
    parser.add_argument("--tools", action="store_true", help="summarise agents' shell tool calls and shell history")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.tools:
        print_tools(tool_calls(args.hours), args.hours)
        return
    if args.show:
        since = datetime.now(timezone.utc) - timedelta(hours=args.hours)
        item = read(args.show, source_for(args.show), since)
        if not item.turns:
            raise SystemExit("No readable turns in the selected window")
        print_session(item)
        return
    items = sessions(args.hours)
    shown = sorted(items, key=lambda item: item.turns[-1][0])[-args.limit:]
    print(f"Host: {socket.gethostname()} | window: last {args.hours:g} hours | sessions: {len(items)} | shown: {len(shown)}")
    print("Latest sessions; use --limit for more, --show <session-file> for prompts and final reply.")
    for item in reversed(shown):
        print_inventory(item)


if __name__ == "__main__":
    main()
