"""Agent registration tests use isolated homes, never live agent profiles."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/setup_agent.py"
RUNS = SCRIPT.parents[1] / ".local/test-runs"
RUNS.mkdir(parents=True, exist_ok=True)
SPEC = importlib.util.spec_from_file_location("mapwright_setup_agent", SCRIPT)
setup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = setup
SPEC.loader.exec_module(setup)


class AgentSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=RUNS)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.workspace = self.root / "maps with spaces"
        self.home.mkdir()
        self.workspace.mkdir()
        self.command = self.root / "Mapwright/.venv/Scripts/mapwright.exe"

    def native_config(self, checkout):
        config = {
            "game_dir": "legacy/csgo",
            "fgd": ["legacy/base.fgd", "legacy/kz.fgd"],
        }
        for key in ("hammer", "vbsp", "vvis", "vrad", "bspsrc_java"):
            config[key] = "legacy/bin/" + key + ".exe"
        for name in [
            "legacy/csgo/gameinfo.txt",
            *config["fgd"],
            *[config[k] for k in ("hammer", "vbsp", "vvis", "vrad", "bspsrc_java")],
            *[
                "legacy/bin/" + n
                for n in (
                    "tier0.dll",
                    "vstdlib.dll",
                    "filesystem_stdio.dll",
                    "materialsystem.dll",
                    "shaderapidx9.dll",
                )
            ],
        ]:
            path = checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        return config

    def test_jsonc_preserves_comments_other_servers_and_unknown_fields(self):
        original = """{
  // keep the user policy
  "permission": {"edit": "ask"},
  "mcp": {
    "other": {"type":"remote", "url":"https://example.com/a//b"},
    "mapwright": {"command":["old"], "custom": {"a": true},},
  },
}
"""
        values = setup.registration("opencode", self.command, self.workspace)
        updated = setup.merge_json(original, ["mcp", "mapwright"], values)
        self.assertIn("// keep the user policy", updated)
        self.assertIn(
            '"other": {"type":"remote", "url":"https://example.com/a//b"}', updated
        )
        parsed = json.loads(setup.jsonc_clean(updated))
        self.assertEqual(parsed["mcp"]["mapwright"]["custom"], {"a": True})
        self.assertEqual(parsed["permission"], {"edit": "ask"})
        self.assertEqual(parsed["mcp"]["mapwright"]["command"][0], str(self.command))
        self.assertEqual(
            setup.merge_json(updated, ["mcp", "mapwright"], values), updated
        )

    def test_json_missing_nested_sections_and_trailing_comments(self):
        for original in (
            "{}",
            "{/* preserve */}",
            '{"mcpServers": {}}',
            '{"mcpServers":{"other":{} /* keep */,},}',
        ):
            with self.subTest(original=original):
                values = setup.registration("pi", self.command, self.workspace)
                result = setup.merge_json(original, ["mcpServers", "mapwright"], values)
                self.assertEqual(
                    json.loads(setup.jsonc_clean(result))["mcpServers"]["mapwright"],
                    values,
                )

    def test_malformed_duplicate_and_wrong_sections_are_refused(self):
        for original in (
            '{"x":1,"x":2}',
            '{"mcpServers":[]}',
            '{"mcpServers":{"mapwright":false}}',
            "{/* unclosed",
            '{"bad":"unterminated}',
        ):
            with self.subTest(original=original):
                with self.assertRaises((ValueError, IndexError)):
                    setup.merge_json(
                        original, ["mcpServers", "mapwright"], {"command": "x"}
                    )

    def test_toml_preserves_settings_other_tables_and_registration_extensions(self):
        original = """model = "my-model" # keep
[mcp_servers.other]
command = "other.exe"

[mcp_servers.mapwright]
command = "old.exe"
args = ["old"]
enabled_tools = ["doctor"] # keep this

[projects.'D:/another-project']
trust_level = "trusted"
"""
        values = setup.registration("codex", self.command, self.workspace)
        updated = setup.merge_toml(original, "mapwright", values)
        self.assertIn('model = "my-model" # keep', updated)
        self.assertIn('enabled_tools = ["doctor"] # keep this', updated)
        parsed = tomllib.loads(updated)
        self.assertEqual(parsed["projects"], tomllib.loads(original)["projects"])
        self.assertEqual(parsed["mcp_servers"]["other"]["command"], "other.exe")
        self.assertEqual(parsed["mcp_servers"]["mapwright"]["args"], values["args"])
        self.assertEqual(setup.merge_toml(updated, "mapwright", values), updated)

    def test_toml_inline_and_multiline_replacement_fail_before_write(self):
        for text in (
            'mcp_servers = { mapwright = { command = "old" } }',
            '[mcp_servers.mapwright]\ncommand = "old"\nargs = [\n"old",\n]\n',
        ):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    setup.merge_toml(
                        text, "mapwright", {"command": "new", "args": ["mcp"]}
                    )

    @unittest.skipUnless(
        importlib.util.find_spec("yaml"), "PyYAML is a Hermes setup-only prerequisite"
    )
    def test_hermes_yaml_surgical_merge_and_flow_style(self):
        import yaml

        values = setup.registration("hermes", self.command, self.workspace)
        originals = (
            "# preserve comment\nmodel: chosen\nmcp_servers:\n  other:\n    command: other.exe\n  mapwright:\n    command: old\n    custom: keep\nnext: true\n",
            "mcp_servers: {mapwright: {}, other: {command: other}}\n",
            "model: selected\n",
            "",
        )
        for original in originals:
            with self.subTest(original=original):
                result = setup.merge_yaml(original, "mapwright", values)
                parsed = yaml.safe_load(result)
                self.assertEqual(
                    parsed["mcp_servers"]["mapwright"]["command"], str(self.command)
                )
                self.assertEqual(setup.merge_yaml(result, "mapwright", values), result)
                if "# preserve comment" in original:
                    self.assertIn("# preserve comment", result)
                    self.assertIn("    custom: keep", result)
                    self.assertEqual(parsed["next"], True)
                    self.assertEqual(
                        parsed["mcp_servers"]["other"], {"command": "other.exe"}
                    )
        with self.assertRaises(ValueError):
            setup.merge_yaml("model: &a chosen\nother: *a\n", "mapwright", values)

    def test_locations_match_explicit_scopes_and_profile_environment(self):
        expected = {
            "codex": ".codex/config.toml",
            "claude": ".mcp.json",
            "opencode": "opencode.json",
            "antigravity": ".agents/mcp_config.json",
            "pi": ".pi/mcp.json",
        }
        for client, relative in expected.items():
            config, _ = setup.locations(
                client, "project", self.workspace, self.home, {}
            )
            self.assertEqual(config, self.workspace / relative)
        profile = self.home / "custom hermes"
        config, skills = setup.locations(
            "hermes", "user", self.workspace, self.home, {"HERMES_HOME": str(profile)}
        )
        self.assertEqual(config, profile / "config.yaml")
        self.assertEqual(skills, profile / "skills")
        with self.assertRaises(ValueError):
            setup.locations("hermes", "project", self.workspace, self.home, {})

    def test_roundtrip_each_json_client_and_codex_with_backups(self):
        for client in setup.CLIENTS:
            if client == "hermes" and not importlib.util.find_spec("yaml"):
                continue
            scope = "user" if client == "hermes" else "project"
            config, _ = setup.locations(client, scope, self.workspace, self.home, {})
            before = setup.read(config)
            change = setup.plan_registration(
                client,
                config,
                "mapwright",
                setup.registration(client, self.command, self.workspace),
            )
            receipt = setup.apply_changes([change], self.workspace)
            self.assertIsNotNone(receipt)
            self.assertEqual(setup.read(config), change.after)
            self.assertEqual(setup.rollback(receipt)["status"], "planned")
            setup.rollback(receipt, True)
            self.assertEqual(setup.read(config), before)

    def test_apply_detects_concurrent_edit_and_rollback_retains_later_edits(self):
        path = self.home / "config.json"
        path.write_bytes(b"original")
        change = setup.Change(path, b"original", b"installed")
        path.write_bytes(b"concurrent")
        with self.assertRaises(ValueError):
            setup.apply_changes([change], self.workspace)
        self.assertEqual(path.read_bytes(), b"concurrent")
        path.write_bytes(b"original")
        receipt = setup.apply_changes([change], self.workspace)
        self.assertEqual(
            setup.apply_changes(
                [setup.Change(path, b"installed", b"installed")], self.workspace
            ),
            None,
        )
        path.write_bytes(b"later edit")
        with self.assertRaises(ValueError):
            setup.rollback(receipt, True)
        self.assertEqual(path.read_bytes(), b"later edit")

    def test_failed_apply_restores_prior_files(self):
        first, second = self.home / "first", self.home / "second"
        first.write_bytes(b"before")
        real_atomic = setup.atomic

        def failing_atomic(path, data):
            if path == second:
                raise OSError("simulated write failure")
            return real_atomic(path, data)

        with patch.object(setup, "atomic", side_effect=failing_atomic):
            with self.assertRaises(OSError):
                setup.apply_changes(
                    [
                        setup.Change(first, b"before", b"after"),
                        setup.Change(second, None, b"new"),
                    ],
                    self.workspace,
                )
        self.assertEqual(first.read_bytes(), b"before")
        self.assertFalse(second.exists())

    def test_installed_mapping_skill_bundles_guides_and_is_idempotent(self):
        skills = self.home / ".agents/skills"
        changes = setup.skill_changes(
            skills, setup.CHECKOUT, self.command, self.workspace
        )
        setup.apply_changes(changes, self.workspace)
        text = (skills / "mapwright/SKILL.md").read_text()
        self.assertNotIn("../../docs", text)
        for guide in setup.GUIDES:
            self.assertTrue((skills / "mapwright/references" / guide).is_file())
        setup_text = (skills / "mapwright-setup/SKILL.md").read_text()
        self.assertIn(str(SCRIPT).replace("\\", "/"), setup_text)
        import re

        for markdown in skills.rglob("*.md"):
            for link in re.findall(r"\]\(([^)]+)\)", markdown.read_text("utf-8")):
                if "://" not in link and not link.startswith("#"):
                    self.assertTrue(
                        (markdown.parent / link.split("#")[0]).exists(),
                        (markdown, link),
                    )
        self.assertEqual(
            setup.apply_changes(
                setup.skill_changes(
                    skills, setup.CHECKOUT, self.command, self.workspace
                ),
                self.workspace,
            ),
            None,
        )

    def test_unmanaged_skill_and_wrong_checkout_are_preserved(self):
        skills = self.home / "skills"
        (skills / "mapwright").mkdir(parents=True)
        (skills / "mapwright/SKILL.md").write_text("user skill")
        with self.assertRaises(ValueError):
            setup.skill_changes(skills, setup.CHECKOUT, self.command, self.workspace)
        self.assertEqual((skills / "mapwright/SKILL.md").read_text(), "user skill")

    def test_skill_install_can_be_reapplied_after_rollback_leaves_empty_folders(self):
        skills = self.home / "skills"
        changes = setup.skill_changes(
            skills, setup.CHECKOUT, self.command, self.workspace
        )
        receipt = setup.apply_changes(changes, self.workspace)
        setup.rollback(receipt, True)
        replacement = setup.skill_changes(
            skills, setup.CHECKOUT, self.command, self.workspace
        )
        self.assertEqual(len(replacement), len(changes))
        self.assertTrue(all(change.before is None for change in replacement))

    def test_native_configuration_reuse_resolves_original_relative_paths(self):
        checkout = self.root / "checkout"
        checkout.mkdir()
        (checkout / "mapwright.local.json").write_text(
            json.dumps(self.native_config(checkout))
        )
        changes, native = setup.native_plan(checkout, self.workspace, "auto", None, {})
        self.assertEqual(native["status"], "reuse")
        config = json.loads(changes[0].after)
        self.assertEqual(
            config["hammer"], str((checkout / "legacy/bin/hammer.exe").resolve())
        )
        self.assertEqual(len(config["fgd"]), 2)
        (self.workspace / "mapwright.local.json").write_text("{broken")
        with self.assertRaises(ValueError):
            setup.native_plan(checkout, self.workspace, "auto", None, {})

    def test_explicit_runtime_recovers_stale_config_and_partial_install(self):
        runtime = self.root / "owned runtime"
        self.native_config(self.root)
        (self.root / "legacy").rename(runtime)
        (runtime / "csgo/pak01_dir.vpk").write_bytes(b"content fixture")
        (self.workspace / "mapwright.local.json").write_text('{"hammer":"missing.exe"}')
        (self.workspace / ".local/csgo-editor/bin").mkdir(parents=True)
        with patch.object(setup, "os", SimpleNamespace(name="nt")):
            changes, native = setup.native_plan(
                self.root, self.workspace, "required", runtime, {}
            )
        self.assertEqual(changes, [])
        self.assertEqual(native["status"], "install")
        self.assertEqual(native["runtime"], str(runtime))
        self.assertNotEqual(native["install_dir"], ".local/csgo-editor")
        self.assertFalse((self.workspace / native["install_dir"]).exists())
        self.assertTrue(native["stale_configurations"])
        self.assertEqual(
            json.loads((self.workspace / "mapwright.local.json").read_text()),
            {"hammer": "missing.exe"},
        )

    def test_discovery_uses_original_content_instead_of_generated_shim(self):
        self.native_config(self.root)
        original = self.root / "legacy"
        (original / "csgo/pak01_dir.vpk").write_bytes(b"content fixture")
        generated = self.root / ".local/csgo-editor"
        generated.mkdir(parents=True)
        (generated / "installation.json").write_text(
            json.dumps({"runtime": str(original)})
        )
        self.assertIn(original, setup.runtime_candidates(self.root, {}))
        self.assertNotIn(generated, setup.runtime_candidates(self.root, {}))
        (original / "csgo/pak01_dir.vpk").unlink()
        self.assertNotIn(original, setup.runtime_candidates(self.root, {}))

    def test_moved_workspace_recovers_original_runtime_provenance(self):
        self.native_config(self.root)
        original = self.root / "legacy"
        (original / "csgo/pak01_dir.vpk").write_bytes(b"content fixture")
        generated = self.workspace / ".local/csgo-editor"
        generated.mkdir(parents=True)
        (generated / "installation.json").write_text(
            json.dumps({"runtime": str(original)})
        )
        (self.workspace / "mapwright.local.json").write_text(
            '{"hammer":"old-location/hammer.exe"}'
        )
        with patch.object(setup, "os", SimpleNamespace(name="nt")):
            _, native = setup.native_plan(
                self.root,
                self.workspace,
                "required",
                None,
                {"ProgramFiles(x86)": str(self.home)},
            )
        self.assertEqual(native["status"], "install")
        self.assertEqual(native["runtime"], str(original))

    def test_bootstrap_repairs_inheritance_without_replacing_active_python(self):
        checkout = self.root / "checkout"
        checkout.mkdir()
        (checkout / "pyproject.toml").write_text('[project]\nname="fixture"\n')
        python, command = setup.bootstrap(checkout)
        python.parent.mkdir(parents=True)
        python.write_bytes(b"running interpreter fixture")
        command.write_bytes(b"launcher fixture")
        cfg = checkout / ".venv/pyvenv.cfg"
        cfg.write_text("include-system-site-packages = true\nversion = 3.11\n")
        stamp = checkout / ".local/agent-setup/runtime.json"
        stamp.parent.mkdir(parents=True)
        stamp.write_text(
            json.dumps(
                {
                    "pyproject_sha256": setup.sha(
                        (checkout / "pyproject.toml").read_bytes()
                    )
                }
            )
        )
        import subprocess

        with patch.object(
            setup.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
        ) as run:
            setup.bootstrap(checkout, True)
        self.assertIn("include-system-site-packages = false", cfg.read_text())
        self.assertEqual(python.read_bytes(), b"running interpreter fixture")
        self.assertTrue(all("venv" not in call.args[0] for call in run.call_args_list))
        self.assertTrue(any("check" in call.args[0] for call in run.call_args_list))

    def test_required_native_rejects_non_windows_and_missing_prerequisites(self):
        with patch.object(setup, "os", SimpleNamespace(name="posix")):
            with self.assertRaisesRegex(ValueError, "requires Windows"):
                setup.native_plan(self.root, self.workspace, "required", None, {})
        (self.workspace / "mapwright.local.json").write_text('{"hammer":"missing.exe"}')
        with patch.object(setup, "runtime_candidates", return_value=[]):
            _, native = setup.native_plan(self.root, self.workspace, "auto", None, {})
        self.assertEqual(native["status"], "offline")
        self.assertTrue(native["stale_configurations"])

    def test_native_install_creates_workspace_and_preserves_config_until_success(self):
        from contextlib import redirect_stdout
        import io
        import subprocess

        workspace = self.root / "new workspace"
        config = workspace / "mapwright.local.json"
        plan = {
            "status": "install",
            "runtime": "owned-runtime",
            "install_dir": ".local/csgo-editor",
        }
        arguments = [
            "--client",
            "codex",
            "--home",
            str(self.home),
            "--workspace",
            str(workspace),
            "--native",
            "auto",
            "--yes",
        ]

        def install(command, **kwargs):
            self.assertTrue(workspace.is_dir())
            self.assertFalse((workspace / ".codex/config.toml").exists())
            self.assertFalse(config.exists())
            output = workspace / command[command.index("--output-config") + 1]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text('{"hammer":"installed.exe"}')
            return subprocess.CompletedProcess(command, 0)

        with (
            patch.object(
                setup, "bootstrap", return_value=(Path(sys.executable), self.command)
            ),
            patch.object(setup, "native_plan", return_value=([], dict(plan))),
            patch.object(setup, "verify_server", return_value={}),
            patch.object(setup.subprocess, "run", side_effect=install),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(setup.main(arguments), 0)
        self.assertEqual(json.loads(config.read_text()), {"hammer": "installed.exe"})

        config.write_text('{"hammer":"preserved.exe"}')
        with (
            patch.object(
                setup, "bootstrap", return_value=(Path(sys.executable), self.command)
            ),
            patch.object(setup, "native_plan", return_value=([], dict(plan))),
            patch.object(
                setup.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, "installer"),
            ),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(setup.main(arguments), 1)
        self.assertEqual(json.loads(config.read_text()), {"hammer": "preserved.exe"})

    def test_cli_dry_run_leaves_isolated_home_and_workspace_unchanged(self):
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--client",
                "pi",
                "--home",
                str(self.home),
                "--workspace",
                str(self.workspace),
                "--native",
                "off",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["data"]["status"], "planned")
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_hermes_dry_run_reports_missing_setup_parser_without_installing(self):
        from contextlib import redirect_stdout
        import io

        output = io.StringIO()
        with (
            patch.object(setup.importlib.util, "find_spec", return_value=None),
            redirect_stdout(output),
        ):
            code = setup.main(
                [
                    "--client",
                    "hermes",
                    "--scope",
                    "user",
                    "--home",
                    str(self.home),
                    "--workspace",
                    str(self.workspace),
                    "--native",
                    "off",
                ]
            )
        self.assertEqual(code, 0, output.getvalue())
        report = json.loads(output.getvalue())["data"]
        self.assertEqual(report["status"], "planned-with-prerequisites")
        self.assertTrue(report["prerequisites"])
        self.assertEqual(list(self.home.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
