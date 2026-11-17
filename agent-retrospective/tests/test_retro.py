"""Collector output regressions from the first retrospective."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "retro.py"
spec = importlib.util.spec_from_file_location("retro", SCRIPT)
retro = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = retro
spec.loader.exec_module(retro)


class InventoryTests(unittest.TestCase):
    def session(self, name: str) -> retro.Session:
        moment = datetime(2026, 10, 31, tzinfo=timezone.utc)
        return retro.Session(Path(name), "Codex", turns=[
            (moment, "you", "# AGENTS.md instructions\nInjected rules"),
            (moment, "you", "<skill>Injected skill</skill>"),
            (moment, "you", "<environment_context>Injected environment</environment_context>"),
            (moment, "you", "Fix missing broker health checks"),
            (moment, "agent", "Detailed final reply"),
        ])

    def run_cli(self, *args: str, sessions: list[retro.Session] | None = None) -> str:
        output = io.StringIO()
        with patch.object(sys, "argv", [str(SCRIPT), *args]), patch.object(
            retro, "sessions", return_value=sessions if sessions is not None else [self.session("older.jsonl"), self.session("newer.jsonl")]
        ), contextlib.redirect_stdout(output):
            retro.main()
        return output.getvalue()

    def test_inventory_uses_actual_prompt_without_transcript(self) -> None:
        output = self.run_cli()
        self.assertIn("Fix missing broker health checks", output)
        self.assertIn("newer.jsonl", output)
        self.assertNotIn("Injected", output)
        self.assertNotIn("Detailed final reply", output)

    def test_default_inventory_is_capped(self) -> None:
        sessions = [self.session(f"session-{i}.jsonl") for i in range(31)]
        output = self.run_cli(sessions=sessions)
        self.assertEqual(30, sum(line.startswith("  session-") for line in output.splitlines()))
        self.assertIn("sessions: 31 | shown: 30", output)

    def test_limit_selects_latest_activity_not_start(self) -> None:
        older = self.session("older-active.jsonl")
        newer = self.session("newer-idle.jsonl")
        moment = older.turns[-1][0]
        newer.turns = [(time + timedelta(hours=1), role, text) for time, role, text in newer.turns]
        older.turns.append((moment + timedelta(hours=2), "agent", "Recent activity"))
        output = self.run_cli("--limit", "1", sessions=[older, newer])
        self.assertIn("older-active.jsonl", output)
        self.assertNotIn("newer-idle.jsonl", output)
        self.assertIn("shown: 1", output)

    def test_show_preserves_injected_context_and_reply(self) -> None:
        output = io.StringIO()
        with patch.object(sys, "argv", [str(SCRIPT), "--show", "selected.jsonl"]), patch.object(
            retro, "read", return_value=self.session("selected.jsonl")
        ), contextlib.redirect_stdout(output):
            retro.main()
        self.assertIn("Injected rules", output.getvalue())
        self.assertIn("Detailed final reply", output.getvalue())


if __name__ == "__main__":
    unittest.main()


class ToolCallTests(unittest.TestCase):
    """--tools reads Bash calls from Claude Code and exec calls from Codex."""

    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        self.claude = self.tmp / "claude"
        self.codex = self.tmp / "codex"
        self.claude.mkdir()
        self.codex.mkdir()
        self.enterContext(patch.dict(retro.ROOTS, {"Claude Code": self.claude, "Codex": self.codex}))

    def write_claude(self, *calls: tuple[str, str, bool]) -> None:
        lines = []
        for number, (command, output, failed) in enumerate(calls):
            lines.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": f"t{number}", "name": "Bash", "input": {"command": command}}]}})
            lines.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": f"t{number}", "content": output, "is_error": failed}]}})
        (self.claude / "session.jsonl").write_text("\n".join(json.dumps(line) for line in lines))

    def run_tools(self) -> str:
        output = io.StringIO()
        with patch.object(sys, "argv", [str(SCRIPT), "--tools"]), patch.object(
            retro, "history_heads", return_value={}
        ), contextlib.redirect_stdout(output):
            retro.main()
        return output.getvalue()

    def test_missing_commands_are_named_and_scaffolding_skipped(self) -> None:
        self.write_claude(
            ("cd ~/repo && export X=1; tmux ls", "(eval):1: command not found: tmux", True),
            ("cd ~/repo && git status", "On branch main", False),
        )
        output = self.run_tools()
        self.assertIn("Missing commands: tmux 1", output)
        self.assertIn("tmux 1", output.split("Top commands: ")[1].splitlines()[0])
        self.assertNotIn("cd 2", output)

    def test_refused_calls_are_not_counted_as_failures(self) -> None:
        self.write_claude(("rm -rf build", "The user doesn't want to take this action right now.", True))
        output = self.run_tools()
        self.assertIn("denied by user 1", output)
        self.assertNotIn("other error", output)

    def test_codex_exec_calls_are_read(self) -> None:
        def call(call_id: str, command: str) -> dict:
            return {"type": "response_item", "payload": {"type": "custom_tool_call", "call_id": call_id,
                                                         "input": f'tools.exec_command({{cmd:"{command}"}})'}}

        def result(call_id: str, body: str) -> dict:
            return {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": call_id,
                                                         "output": [{"type": "input_text", "text": body}]}}

        # Two calls in flight: each output must go to its own call.
        lines = [call("a", "python -V"), call("b", "make build"),
                 result("a", "zsh:1: command not found: python"),
                 result("b", '{"exit_code":2} make: *** No rule to make target')]
        (self.codex / "rollout.jsonl").write_text("\n".join(json.dumps(line) for line in lines))
        output = self.run_tools()
        self.assertIn("== Codex: 2 calls, 2 with an error", output)
        self.assertIn("Missing commands: python 1", output)
        self.assertIn("make | other error | make build", output)

    def test_secret_values_are_redacted(self) -> None:
        self.write_claude(*[("API_TOKEN=hunter2value curl https://x", "curl: (6) not resolved: No such file or directory", True)] * 5)
        output = self.run_tools()
        self.assertIn("API_TOKEN=<redacted>", output)
        self.assertNotIn("hunter2value", output)

    def test_short_secrets_in_headers_json_and_quotes_are_redacted(self) -> None:
        for line in ['curl -H "Authorization: Bearer s3cret" x', '{"api_key": "s3cret"}',
                     'PASSWORD="s3 cret" run', "curl 'https://x/?token=s3cret&q=1'"]:
            self.assertNotIn("s3", retro.redact(line), line)

    def test_calls_before_the_window_are_left_out(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        lines = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "old", "name": "Bash", "input": {"command": "vim notes"}}]}},
            {"type": "user", "timestamp": old, "message": {"content": [
                {"type": "tool_result", "tool_use_id": "old", "content": "command not found: vim", "is_error": True}]}},
        ]
        (self.claude / "session.jsonl").write_text("\n".join(json.dumps(line) for line in lines))
        self.assertIn("shell tool calls: 0", self.run_tools())
