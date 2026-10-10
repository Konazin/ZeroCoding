import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from zerocoding.cli import handle_command, run_project_init
from zerocoding.core.agent import Agent
from zerocoding.core.config import Config, ModeConfig, ProviderConfig


class FakeConsole:
    def __init__(self):
        self.lines = []

    def print(self, value="", *args, **kwargs):
        self.lines.append(str(value))


class FakeManager:
    def __init__(self):
        self.saved = 0

    def save(self, config):
        self.saved += 1


class FakeTUI:
    def __init__(self):
        self.permission_mode = "manual"
        self.messages = []

    def show_info(self, message):
        self.messages.append(message)

    def show_success(self, message):
        self.messages.append(message)

    def show_error(self, message):
        self.messages.append(message)


class FakeProvider:
    supports_tools = True

    def __init__(self, models, path="src/todo/cli.py"):
        self.models = models
        self.path = path
        self.model = "deepseek-coder-v2"
        self.seen_tool_names = []
        self.seen_messages = []

    def list_models(self):
        return self.models

    def chat(self, *_args, **_kwargs):
        return '{"decision":"allow","reason":"Ação local necessária"}'

    def chat_stream_with_tools(self, messages, tools, max_output_tokens=512):
        self.seen_messages.extend(messages)
        self.seen_tool_names = [item["function"]["name"] for item in tools]
        if not any(message.get("role") == "tool" for message in messages):
            arguments = {"path": self.path, "content": "def main(argv=None):\n    return 0\n"}
            yield {"tool_calls": [{"id": "write-1", "type": "function", "function": {"name": "write_file", "arguments": json.dumps(arguments)}}]}
        else:
            yield {"content": "The CLI project is ready."}
            yield {"tool_calls": []}


class JavaScriptProvider(FakeProvider):
    def chat_stream_with_tools(self, messages, tools, max_output_tokens=512):
        self.seen_messages.extend(messages)
        self.seen_tool_names = [item["function"]["name"] for item in tools]
        if not any(message.get("role") == "tool" for message in messages):
            arguments = {"path": "src/index.js", "content": "export function main(argv = []) { return argv.length; }\n"}
            yield {"tool_calls": [{"id": "write-js", "type": "function", "function": {"name": "write_file", "arguments": json.dumps(arguments)}}]}
        else:
            yield {"content": "The JavaScript CLI project is ready."}
            yield {"tool_calls": []}


def make_config(model="qwen2.5-coder:7b"):
    config = Config(
        provider="local",
        providers={"local": ProviderConfig(name="local", type="ollama", model=model)},
        mode="code",
        modes={"project": ModeConfig.from_dict("project", {"provider": "local", "model": "qwen2.5-coder:7b", "input_budget_tokens": 2048, "max_tool_steps": 8, "output_budget_tokens": 1024})},
    )
    return config


class TestCliProjectInit(unittest.TestCase):
    def test_init_scaffolds_and_generates_without_command_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = FakeProvider(["qwen2.5-coder:7b"])
            answers = iter(["python", "cli", "A tiny todo command-line app", "s", "n"])
            console = FakeConsole()

            result = run_project_init("todo", make_config(), FakeManager(), provider, console=console, input_fn=lambda _: next(answers), cwd=root)

            self.assertEqual(result, 0)
            self.assertIn("def main", (root / "todo/src/todo/cli.py").read_text())
            self.assertIn("write_file", provider.seen_tool_names)
            self.assertNotIn("run_command", provider.seen_tool_names)
            self.assertIn("-m unittest", " ".join(console.lines))
            prompt = " ".join(str(message.get("content") or "") for message in provider.seen_messages)
            self.assertIn("from todo.cli import name", prompt)
            self.assertIn("separate sequential tool calls", prompt)
            self.assertIn("ordinary scalar parameters", prompt)
            self.assertIn("Only test behavior explicitly requested", prompt)
            self.assertIn("--- src/todo/cli.py ---", prompt)
            self.assertIn("--- tests/test_cli.py ---", prompt)

    def test_javascript_cli_init_uses_node_scaffold_and_keeps_install_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = JavaScriptProvider(["qwen2.5-coder:7b"])
            answers = iter(["javascript", "cli", "A small command", "s", "n"])
            console = FakeConsole()

            result = run_project_init("js-tool", make_config(), FakeManager(), provider, console=console, input_fn=lambda _: next(answers), cwd=root)

            self.assertEqual(result, 0)
            self.assertTrue((root / "js-tool/src/index.js").is_file())
            self.assertIn("node:test", (root / "js-tool/tests/index.test.js").read_text())
            self.assertIn('"node": ">=24"', (root / "js-tool/package.json").read_text())
            prompt = " ".join(str(message.get("content") or "") for message in provider.seen_messages)
            self.assertIn("node:util parseArgs", prompt)
            self.assertIn("src/index.js", prompt)
            self.assertNotIn("run_command", provider.seen_tool_names)

    def test_approve_for_me_reviews_scaffold_and_file_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = make_config()
            config.permission_mode = "approve_for_me"
            provider = FakeProvider(["qwen2.5-coder:7b"], path="src/reviewed/cli.py")
            answers = iter(["python", "cli", "A tiny app", "n"])
            with patch("zerocoding.cli.workspace_sandbox_available", return_value=False):
                result = run_project_init("reviewed", config, FakeManager(), provider, console=FakeConsole(), input_fn=lambda _: next(answers), cwd=root)

            self.assertEqual(result, 0)
            self.assertIn("def main", (root / "reviewed/src/reviewed/cli.py").read_text())
            self.assertEqual(config.permission_mode, "approve_for_me")

    def test_permissions_command_persists_modes_and_rejects_unsafe_full_access(self):
        config = make_config()
        manager = FakeManager()
        tui = FakeTUI()
        agent = Agent(FakeProvider(["qwen2.5-coder:7b"]))
        args = (tui, agent, config, manager, None, None, None, None)

        with patch("zerocoding.core.agent.workspace_sandbox_available", return_value=False):
            handle_command("/permissions approve-for-me", *args)
            self.assertEqual(config.permission_mode, "approve_for_me")
            self.assertEqual(tui.permission_mode, "approve_for_me")
            handle_command("/permissions full-access", *args)
            self.assertEqual(config.permission_mode, "approve_for_me")
            self.assertIn("bubblewrap", tui.messages[-1])
            handle_command("/permissions manual", *args)

        self.assertEqual(config.permission_mode, "manual")
        self.assertEqual(manager.saved, 2)

    def test_missing_model_can_be_switched_to_an_installed_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = FakeProvider(["qwen2.5-coder:7b"])
            config = make_config("deepseek-coder-v2")
            answers = iter(["1", "python", "cli", "A tiny app", "n"])
            manager = FakeManager()

            result = run_project_init("todo", config, manager, provider, console=FakeConsole(), input_fn=lambda _: next(answers), cwd=root, provider_override=True)

            self.assertEqual(result, 0)
            self.assertEqual(config.model, "qwen2.5-coder:7b")
            self.assertEqual(provider.model, "qwen2.5-coder:7b")
            self.assertEqual(manager.saved, 1)
            self.assertFalse((root / "todo").exists())

    def test_selected_model_persists_on_project_profile_without_changing_active_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = make_config("user-model")
            config.modes["project"].model = "missing-project-model"
            provider = FakeProvider(["qwen2.5-coder:7b"])
            answers = iter(["1", "python", "cli", "A tiny app", "n"])
            manager = FakeManager()

            result = run_project_init("todo", config, manager, provider, console=FakeConsole(), input_fn=lambda _: next(answers), cwd=root)

            self.assertEqual(result, 0)
            self.assertEqual(provider.model, "qwen2.5-coder:7b")
            self.assertEqual(config.modes["project"].model, "qwen2.5-coder:7b")
            self.assertEqual(config.provider, "local")
            self.assertEqual(config.model, "user-model")
            self.assertEqual(manager.saved, 1)

    def test_offline_provider_explains_next_step_without_prompting_or_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = FakeProvider([])
            provider.list_models = lambda: (_ for _ in ()).throw(ConnectionError("connection refused"))
            console = FakeConsole()

            result = run_project_init("todo", make_config(), FakeManager(), provider, console=console, input_fn=lambda _: self.fail("must not prompt"), cwd=root)

            self.assertEqual(result, 1)
            self.assertIn("ollama serve", " ".join(console.lines))
            self.assertFalse((root / "todo").exists())

    def test_empty_model_list_explains_how_to_install_without_prompting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            console = FakeConsole()

            result = run_project_init("todo", make_config(), FakeManager(), FakeProvider([]), console=console, input_fn=lambda _: self.fail("must not prompt"), cwd=root)

            self.assertEqual(result, 1)
            self.assertIn("ollama pull qwen2.5-coder:7b", " ".join(console.lines))
            self.assertFalse((root / "todo").exists())

    def test_api_missing_dependencies_are_not_installed_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            class PlainProvider:
                model = "qwen2.5-coder:7b"
                supports_tools = False

                def list_models(self):
                    return [self.model]

                def chat_stream(self, messages, max_output_tokens=512):
                    yield "The API scaffold is ready."

            provider = PlainProvider()
            answers = iter(["python", "api", "A tiny JSON API", "s", "n"])
            console = FakeConsole()
            with patch("zerocoding.cli.importlib.util.find_spec", return_value=None), \
                    patch("zerocoding.cli.venv.EnvBuilder") as env_builder, \
                    patch("zerocoding.cli.subprocess.run") as run:
                result = run_project_init("api-sample", make_config(), FakeManager(), provider, console=console, input_fn=lambda _: next(answers), cwd=root)

            self.assertEqual(result, 0)
            self.assertIn("Não verificado", " ".join(console.lines))
            self.assertIn("instalação", " ".join(console.lines).lower())
            env_builder.assert_not_called()
            run.assert_not_called()

    def test_agent_cannot_overwrite_project_metadata(self):
        class MetadataProvider(FakeProvider):
            def chat_stream_with_tools(self, messages, tools, max_output_tokens=512):
                if not any(message.get("role") == "tool" for message in messages):
                    args = {"path": "pyproject.toml", "content": "[broken]\n"}
                    yield {"tool_calls": [{"id": "write-meta", "type": "function", "function": {"name": "write_file", "arguments": json.dumps(args)}}]}
                else:
                    yield {"content": "Finished."}
                    yield {"tool_calls": []}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            answers = iter(["python", "cli", "A tiny app", "s", "n"])

            result = run_project_init("safe-app", make_config(), FakeManager(), MetadataProvider(["qwen2.5-coder:7b"]), console=FakeConsole(), input_fn=lambda _: next(answers), cwd=root)

            self.assertEqual(result, 0)
            metadata = (root / "safe-app/pyproject.toml").read_text()
            self.assertIn("setuptools>=68", metadata)
            self.assertIn("[project.scripts]", metadata)

    def test_agent_cannot_write_outside_new_project_directory(self):
        class TraversalProvider(FakeProvider):
            def chat_stream_with_tools(self, messages, tools, max_output_tokens=512):
                if not any(message.get("role") == "tool" for message in messages):
                    args = {"path": "../outside.py", "content": "unexpected = True\n"}
                    yield {"tool_calls": [{"id": "write-outside", "type": "function", "function": {"name": "write_file", "arguments": json.dumps(args)}}]}
                else:
                    yield {"content": "Finished."}
                    yield {"tool_calls": []}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            answers = iter(["python", "cli", "A tiny app", "s", "n"])

            result = run_project_init("safe-app", make_config(), FakeManager(), TraversalProvider(["qwen2.5-coder:7b"]), console=FakeConsole(), input_fn=lambda _: next(answers), cwd=root)

            self.assertEqual(result, 0)
            self.assertFalse((root / "outside.py").exists())

    def test_cli_verification_adds_src_to_pythonpath(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "sample"
            target.mkdir()
            answers = iter(["s"])
            with patch("zerocoding.cli.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="OK", stderr="")) as run:
                from zerocoding.cli import _verify_new_project
                _verify_new_project("cli", target, FakeConsole(), lambda _: next(answers))

            env = run.call_args.kwargs["env"]
            self.assertIn(str(target / "src"), env["PYTHONPATH"].split(os.pathsep))

    def test_noop_generation_gets_one_direct_retry(self):
        class RetryProvider:
            supports_tools = True
            model = "qwen2.5-coder:7b"

            def __init__(self):
                self.requests = 0

            def list_models(self):
                return [self.model]

            def chat_stream_with_tools(self, messages, tools, max_output_tokens=512):
                self.requests += 1
                if self.requests == 1:
                    yield {"content": "I will build the project."}
                    yield {"tool_calls": []}
                elif self.requests == 2:
                    yield {"tool_calls": [
                        {"id": "source", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "src/todo/cli.py", "content": "def main(argv=None):\n    return 0\n"})}},
                        {"id": "tests", "type": "function", "function": {"name": "write_file", "arguments": json.dumps({"path": "tests/test_cli.py", "content": "import unittest\n\nclass TestTodo(unittest.TestCase):\n    def test_placeholder(self):\n        self.assertTrue(True)\n"})}},
                    ]}
                else:
                    yield {"content": "Implemented the project."}
                    yield {"tool_calls": []}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = RetryProvider()
            answers = iter(["python", "cli", "A todo command", "s", "n"])
            console = FakeConsole()

            result = run_project_init("todo", make_config(), FakeManager(), provider, console=console, input_fn=lambda _: next(answers), cwd=root)

            self.assertEqual(result, 0)
            self.assertEqual(provider.requests, 3)
            self.assertIn("def main", (root / "todo/src/todo/cli.py").read_text())
            self.assertIn("TestTodo", (root / "todo/tests/test_cli.py").read_text())
            self.assertIn("uma vez", " ".join(console.lines).lower())

    def test_failed_verification_repairs_and_requires_a_second_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sample"
            target.mkdir()
            answers = iter(["s", "s"])
            console = FakeConsole()
            repair = lambda output: self.assertIn("SyntaxError", output)
            failure = SimpleNamespace(returncode=1, stdout="", stderr="SyntaxError: invalid syntax")
            success = SimpleNamespace(returncode=0, stdout="OK", stderr="")
            with patch("zerocoding.cli.subprocess.run", side_effect=[failure, success]) as run:
                from zerocoding.cli import _verify_new_project
                _verify_new_project("cli", target, console, lambda _: next(answers), repair=repair)

            self.assertEqual(run.call_count, 2)
            self.assertTrue(any("após correção" in line for line in console.lines))

    def test_nonempty_target_is_refused_before_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "existing"
            target.mkdir()
            (target / "keep.txt").write_text("keep")

            result = run_project_init("existing", make_config(), FakeManager(), FakeProvider(["qwen2.5-coder:7b"]), console=FakeConsole(), input_fn=lambda _: self.fail("must not ask"), cwd=root)

            self.assertEqual(result, 1)
            self.assertEqual((target / "keep.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
