import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from zerocoding.core.agent import Agent
from zerocoding.core.bootstrap import build_extensions, startup_warnings
from zerocoding.core.config import ConfigManager
from zerocoding.core.plugins import load_plugins
from zerocoding.core.subagent import EXPLORER_NAME, MAX_SUMMARY_CHARS, make_explorer_tool
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.base import ProviderTurn, ToolCall

SERVER = str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")


class Base(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name).resolve()
        self.root = self.tmp / "project"
        self.root.mkdir()
        (self.root / "a.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
        self.closers = []
        self.addCleanup(lambda: [c() for c in self.closers])

    def load_config(self, yaml_text):
        path = self.tmp / "config.yaml"
        path.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
        return ConfigManager(user_config_path=path, env_file=str(self.tmp / ".env")).load()

    def build(self, config, provider=None):
        agent = Agent(provider or type("P", (), {"chat": lambda self, messages, **k: ProviderTurn(content="x")})())
        agent.tools = ToolRegistry(self.root, approve=lambda a, p: True, policy=config.command_policy)
        skills = []
        extensions = build_extensions(config, agent, self.root, skills)
        if extensions.mcp:
            self.closers.append(extensions.mcp.close)
        return agent, extensions, skills


class TestExplorer(Base):
    def test_explorer_returns_a_summary_and_runs_read_only_with_own_context(self):
        sent = []
        turns = [
            ProviderTurn(tool_calls=[ToolCall("read_file", {"path": "a.py"}, "r")], usage={"prompt_tokens": 50, "completion_tokens": 5}),
            ProviderTurn(content="hello() is in a.py:1 and returns 1.", usage={"prompt_tokens": 70, "completion_tokens": 9}),
        ]
        provider = type("P", (), {})()
        provider.chat = lambda messages, **kw: (sent.append((messages, kw.get("tools"))), turns.pop(0))[1]
        agent = Agent(provider, tools=ToolRegistry(self.root, approve=lambda a, p: True))
        agent.context.add_message("user", "UNRELATED MAIN HISTORY")
        agent._stats = agent._new_stats()
        tool = make_explorer_tool(agent)
        summary = tool.handler({"task": "where is hello defined?"})
        self.assertIn("a.py:1", summary)
        offered = {t["function"]["name"] for t in sent[0][1]}
        self.assertEqual(offered, {"list_files", "search_files", "read_file"})  # read-only, no explore inside explore
        self.assertNotIn("UNRELATED MAIN HISTORY", str(sent[0][0]))
        self.assertEqual(agent.context.history[-1]["content"], "UNRELATED MAIN HISTORY")  # main context untouched
        self.assertEqual((agent._stats["prompt_tokens"], agent._stats["completion_tokens"], agent._stats["subagent_runs"]), (120, 14, 1))

    def test_explorer_cannot_write_even_if_the_model_tries(self):
        turns = [ProviderTurn(tool_calls=[ToolCall("write_file", {"path": "x.py", "content": "boom"}, "w")]),
                 ProviderTurn(content="could not write")]
        provider = type("P", (), {})()
        provider.chat = lambda messages, **kw: turns.pop(0)
        agent = Agent(provider, tools=ToolRegistry(self.root, approve=lambda a, p: True))
        make_explorer_tool(agent).handler({"task": "write something"})
        self.assertFalse((self.root / "x.py").exists())

    def test_empty_task_and_long_summary(self):
        provider = type("P", (), {"chat": lambda self, messages, **k: ProviderTurn(content="y" * 5000)})()
        agent = Agent(provider, tools=ToolRegistry(self.root))
        tool = make_explorer_tool(agent)
        with self.assertRaisesRegex(ValueError, "task must not be empty"):
            tool.handler({"task": "  "})
        self.assertLessEqual(len(tool.handler({"task": "go"})), MAX_SUMMARY_CHARS + 40)

    def test_explorer_tool_is_read_only_and_available_in_plan_mode(self):
        config = self.load_config("subagents:\n  enabled: true\n")
        agent, extensions, _ = self.build(config)
        self.assertTrue(agent.tools.is_read_only(EXPLORER_NAME))
        self.assertIn(EXPLORER_NAME, {s["function"]["name"] for s in agent.tools.read_only_schemas})
        self.assertTrue(extensions.subagents_enabled)


class TestPlugins(Base):
    def make_plugin(self, name="demo", skills=True, hooks="", mcp=""):
        folder = self.tmp / "plugins" / name
        (folder / "skills").mkdir(parents=True)
        if skills:
            (folder / "skills" / "style.md").write_text("---\ndescription: House style\n---\nUse tabs.", encoding="utf-8")
        (folder / "plugin.yaml").write_text("description: Demo plugin\nversion: 1.0\n", encoding="utf-8")
        if hooks:
            (folder / "hooks.yaml").write_text(hooks, encoding="utf-8")
        if mcp:
            (folder / "mcp.yaml").write_text(mcp, encoding="utf-8")
        return folder

    def test_discovered_but_not_enabled_does_nothing(self):
        self.make_plugin(hooks="hooks:\n  - {event: turn_end, command: 'true'}\n")
        loaded = load_plugins(self.tmp / "plugins", [])
        self.assertEqual((len(loaded.infos), loaded.infos[0].enabled, loaded.skills, loaded.hook_entries), (1, False, [], []))
        self.assertEqual((loaded.infos[0].skills, loaded.infos[0].hooks), (1, 1))

    def test_enabled_plugin_contributes_skills_hooks_and_mcp_with_plugin_dir_substitution(self):
        folder = self.make_plugin(
            hooks="hooks:\n  - {event: turn_end, command: '{plugin_dir}/notify.sh'}\n",
            mcp=f"servers:\n  fake:\n    command: ['{sys.executable}', '{SERVER}']\n    tools: {{echo: {{read_only: true}}}}\n",
        )
        loaded = load_plugins(self.tmp / "plugins", ["demo"])
        self.assertEqual([s.name for s in loaded.skills], ["demo:style"])
        self.assertEqual(loaded.hook_entries[0][0], "plugin:demo")
        self.assertEqual(loaded.hook_entries[0][1][0]["command"], f"{folder}/notify.sh")
        self.assertEqual(list(loaded.mcp_servers), ["demo_fake"])

    def test_bad_name_bad_yaml_and_missing_enabled_plugin_are_reported(self):
        self.make_plugin(name="Bad Name")
        bad = self.make_plugin(name="broken")
        (bad / "hooks.yaml").write_text("hooks: [unclosed", encoding="utf-8")
        loaded = load_plugins(self.tmp / "plugins", ["broken", "ghost"])
        errors = {i.name: i.errors for i in loaded.infos}
        self.assertTrue(errors["Bad Name"])
        self.assertTrue(errors["broken"])
        self.assertIn("not found", errors["ghost"][0])
        self.assertEqual(loaded.skills, [])  # a plugin with errors contributes nothing

    def test_plugin_never_executes_python(self):
        folder = self.make_plugin()
        marker = self.tmp / "marker"
        (folder / "plugin.py").write_text(f"open(r'{marker}', 'w').write('ran')", encoding="utf-8")
        (folder / "__init__.py").write_text(f"open(r'{marker}', 'w').write('ran')", encoding="utf-8")
        load_plugins(self.tmp / "plugins", ["demo"])
        self.assertFalse(marker.exists())


class TestBootstrapAndConfig(Base):
    def test_defaults_enable_nothing_and_expose_only_builtin_tools(self):
        agent, extensions, _ = self.build(self.load_config(""))
        self.assertIsNone(agent.hooks)
        self.assertEqual(len(agent.tools.schemas), 6)
        self.assertFalse(extensions.mcp.configured)
        self.assertEqual(startup_warnings(extensions), [])

    def test_full_yaml_wires_hooks_mcp_plugin_and_subagent(self):
        plugins = self.tmp / "plugins" / "demo"
        (plugins / "skills").mkdir(parents=True)
        (plugins / "skills" / "s.md").write_text("Plugin skill body", encoding="utf-8")
        config = self.load_config(f"""
            hooks:
              - {{name: h1, event: post_tool, match: edit_file, command: 'true'}}
              - {{event: bogus, command: x}}
            mcp:
              max_tools: 4
              servers:
                fake:
                  command: ['{sys.executable}', '{SERVER}']
                  tools: {{echo: {{read_only: true}}}}
            subagents: {{enabled: true}}
            plugins: {{path: '{self.tmp / "plugins"}', enabled: [demo]}}
        """)
        agent, extensions, skills = self.build(config)
        names = {s["function"]["name"] for s in agent.tools.schemas}
        self.assertTrue({"mcp__fake__echo", "explore"} <= names)
        self.assertEqual([h.name for h in agent.hooks.hooks], ["h1"])
        self.assertEqual([s.name for s in skills], ["demo:s"])
        warnings = startup_warnings(extensions)
        self.assertEqual(len(warnings), 1)
        self.assertIn("event must be one of", warnings[0])

    def test_failing_mcp_server_is_reported_but_agent_still_works(self):
        config = self.load_config("mcp:\n  servers:\n    ghost:\n      command: ['no-such-mcp-binary']\n      tools: [x]\n")
        agent, extensions, _ = self.build(config)
        self.assertEqual(len(agent.tools.schemas), 6)
        self.assertTrue(any("ghost" in w for w in startup_warnings(extensions)))
        self.assertEqual(agent.ask("hi"), "x")

    def test_config_roundtrip_keeps_extension_settings(self):
        config = self.load_config("subagents: {enabled: true}\nplugins: {enabled: [a, b]}\nhooks:\n  - {event: turn_end, command: 'true'}\n")
        data = config.to_dict()
        self.assertEqual(data["subagents"], {"enabled": True})
        self.assertEqual(data["plugins"]["enabled"], ["a", "b"])
        self.assertEqual(len(data["hooks"]), 1)


if __name__ == "__main__":
    unittest.main()
