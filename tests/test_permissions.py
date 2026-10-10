import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zerocoding.core.permissions import approval_route, requires_network_access, review_action
from zerocoding.tools.registry import ToolSpec
from zerocoding.tools.sandbox import _resolve_standard_command, _resolve_volta_command, _workspace_argv, build_bwrap_command


def tool(scope):
    return ToolSpec("write_file", "write", {}, lambda _: "ok", True, permission_scope=scope)


class ReviewProvider:
    def __init__(self, answer):
        self.answer = answer
        self.messages = None

    def chat(self, messages, **kwargs):
        self.messages = messages
        return self.answer


class TestPermissions(unittest.TestCase):
    def test_manual_always_routes_confirmed_tools_to_user(self):
        self.assertEqual(approval_route("manual", tool("project"), {}), "manual")

    def test_approve_for_me_reviews_only_local_actions(self):
        self.assertEqual(approval_route("approve_for_me", tool("project"), {}), "review")
        self.assertEqual(approval_route("approve_for_me", tool("external"), {}), "manual")

    def test_full_access_allows_only_local_actions_without_network(self):
        self.assertEqual(approval_route("full_access", tool("project"), {}), "allow")
        self.assertEqual(approval_route("full_access", tool("project"), {"network_access": True}), "manual")
        self.assertEqual(approval_route("full_access", tool("external"), {}), "manual")
        self.assertEqual(approval_route("full_access", tool("external"), {"network_access": True}), "manual")

    def test_reviewer_receives_action_and_requires_strict_json(self):
        provider = ReviewProvider('{"decision":"allow","reason":"Local project edit"}')
        allowed, reason = review_action(provider, "Add a greeting", tool("project"), {"path": "src/app.py"})
        self.assertTrue(allowed)
        self.assertEqual(reason, "Local project edit")
        self.assertIn('"tool": "write_file"', provider.messages[1]["content"])

    def test_reviewer_denies_malformed_output_and_provider_errors(self):
        self.assertFalse(review_action(ReviewProvider("approved"), "task", tool("project"), {})[0])

        class BrokenProvider:
            def chat(self, *_args, **_kwargs):
                raise RuntimeError("offline")

        allowed, reason = review_action(BrokenProvider(), "task", tool("project"), {})
        self.assertFalse(allowed)
        self.assertIn("offline", reason)

    def test_workspace_sandbox_hides_home_and_denies_network_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = build_bwrap_command(["python3", "-m", "pytest"], tmp)
        self.assertIn("--unshare-net", command)
        self.assertIn("--bind", command)
        self.assertNotIn("/home", [command[index + 1] for index, item in enumerate(command[:-1]) if item == "--bind"])
        self.assertEqual(command[-4:], ["--", "python3", "-m", "pytest"])

    def test_network_access_is_explicit_per_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = build_bwrap_command(["npm", "install"], tmp, network_access=True)
        self.assertNotIn("--unshare-net", command)

    def test_workspace_is_mounted_at_stable_path_and_readonly_runtime_is_exposed(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as runtime:
            command = build_bwrap_command(
                ["node", "--test"], tmp,
                readonly_paths=(Path(runtime),), extra_path=(Path(runtime) / "bin",),
            )
        self.assertEqual(command[-5:], ["--chdir", "/workspace", "--", "node", "--test"])
        self.assertIn("/workspace", command)
        self.assertIn(runtime, command)
        self.assertIn(str(Path(runtime) / "bin"), command[command.index("PATH") + 1])

    def test_volta_node_and_npm_use_readonly_installed_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            image = home / ".volta/tools/image/node/24.0.0"
            (image / "bin").mkdir(parents=True)
            (image / "bin/node").touch()
            npm = image / "lib/node_modules/npm/bin/npm-cli.js"
            npm.parent.mkdir(parents=True)
            npm.touch()
            shim = home / ".volta/bin/npm"
            with patch("zerocoding.tools.sandbox.Path.home", return_value=home), patch("zerocoding.tools.sandbox.shutil.which", return_value=str(shim)):
                argv, mounts, paths = _resolve_volta_command(["npm", "test"])

        self.assertEqual(argv, [str(image / "bin/node"), str(npm), "test"])
        self.assertEqual(mounts, (image,))
        self.assertEqual(paths, (image / "bin",))

    def test_absolute_project_arguments_and_pythonpath_map_into_workspace(self):
        root = Path("/tmp/project")
        self.assertEqual(_workspace_argv(["python", str(root / "tests")], root), ["python", "/workspace/tests"])

    def test_virtualenv_python_symlink_resolves_to_mounted_system_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            shim = Path(tmp) / "python"
            shim.symlink_to("/usr/bin/true")
            self.assertEqual(_resolve_standard_command([str(shim), "-V"]), ["/usr/bin/true", "-V"])

    def test_unconfirmed_external_tools_still_require_manual_approval(self):
        external = ToolSpec("mcp", "external", {}, lambda _: None)
        self.assertEqual(approval_route("full_access", external, {}), "manual")

    def test_dependency_install_commands_always_require_approval_and_network(self):
        install = ToolSpec("run_command", "run", {}, lambda _: None, True, permission_scope="command")
        test = ToolSpec("run_command", "run", {}, lambda _: None, True, permission_scope="command")
        self.assertTrue(requires_network_access(["npm", "install"]))
        self.assertTrue(requires_network_access(["python", "-m", "pip", "install", "-e", ".[dev]"]))
        self.assertEqual(approval_route("full_access", install, {"argv": ["npm", "install"]}), "manual")
        self.assertEqual(approval_route("full_access", test, {"argv": ["npm", "test"]}), "allow")


if __name__ == "__main__":
    unittest.main()
