"""Regression checks for Markdown examples in skill references."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import lint


class MarkdownLinksTest(unittest.TestCase):
    def test_example_links_are_not_treated_as_shipped_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "example"
            skill.mkdir()
            document = skill / "SKILL.md"
            document.write_text(
                "```markdown\n![Example](./example.png)\n```\n"
                "[Missing reference](./missing.md)\n"
            )
            with patch.object(lint, "REPO", root):
                findings = lint.check_file(skill, document, {"example"})
            self.assertEqual(
                [finding.message for finding in findings],
                ["link to missing file ./missing.md"],
            )


if __name__ == "__main__":
    unittest.main()
