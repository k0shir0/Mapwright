"""Keep developer-machine paths and broken setup links out of shipped sources."""

from pathlib import Path
import importlib.util
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    @unittest.skipUnless(
        importlib.util.find_spec("yaml"), "Install the dev extra for skill YAML lint"
    )
    def test_skill_frontmatter_is_discoverable(self):
        import yaml

        skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
        self.assertTrue(skills)
        for path in skills:
            with self.subTest(skill=path.parent.name):
                text = path.read_text("utf-8")
                self.assertTrue(text.startswith("---\n"), str(path))
                metadata, body = text[4:].split("\n---\n", 1)
                fields = yaml.safe_load(metadata)
                self.assertIsInstance(fields, dict)
                self.assertEqual(fields["name"], path.parent.name)
                self.assertRegex(fields["name"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                self.assertLessEqual(len(fields["name"]), 64)
                self.assertIsInstance(fields["description"], str)
                self.assertTrue(fields["description"].strip())
                self.assertLessEqual(len(fields["description"]), 1024)
                self.assertTrue(body.strip())

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
