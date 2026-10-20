"""Keep developer-machine paths and broken setup links out of shipped sources."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def test_sources_and_guides_have_no_personal_absolute_paths(self):
        paths = [
            ROOT / name
            for name in (
                "README.md",
                "AGENTS.md",
                "pyproject.toml",
                "mapwright.example.json",
            )
        ]
        for folder in ("cli", "scripts", "docs", "skills", "tests", ".github"):
            paths.extend(
                p
                for p in (ROOT / folder).rglob("*")
                if p.suffix in {".py", ".md", ".json", ".toml", ".yml"}
            )
        absolute = re.compile(r"\b[A-Za-z]:[\\/]|/(?:Users|home)/[^/\s]+/")
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text("utf-8")
                # Generic Windows fallback; actual detection honors ProgramFiles(x86).
                text = text.replace(r"C:\Program Files (x86)", "PROGRAM_FILES")
                self.assertIsNone(absolute.search(text), str(path))
                if path.suffix == ".md":
                    for link in re.findall(r"\]\(([^)]+)\)", text):
                        if "://" not in link and not link.startswith("#"):
                            self.assertTrue(
                                (path.parent / link.split("#")[0]).exists(),
                                (path, link),
                            )
