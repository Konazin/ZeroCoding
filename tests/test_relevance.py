import tempfile
import unittest
from types import SimpleNamespace

from zerocoding.core.agent import Agent
from zerocoding.core.config import Config
from zerocoding.core.relevance import select_skills, select_tool_schemas
from zerocoding.core.tools import ToolRegistry
from zerocoding.providers.base import ProviderTurn


class DummyProvider:
    def __init__(self):
        self.requests = []

    def chat(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        return ProviderTurn(content="ok")


def tool_names(schemas):
    return {spec["function"]["name"] for spec in schemas}


class TestRelevance(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.registry = ToolRegistry(self.directory.name)

    def test_read_only_request_hides_write_and_command_tools(self):
        selected = select_tool_schemas("Explain how the router works", self.registry.schemas)
        self.assertEqual(tool_names(selected), {"list_files", "search_files", "read_file"})

    def test_edit_request_adds_write_tool_only(self):
        selected = select_tool_schemas("Corrija o bug no router", self.registry.schemas)
        self.assertEqual(tool_names(selected), {"list_files", "search_files", "read_file", "write_file", "edit_file"})

    def test_test_request_adds_command_tool(self):
        selected = select_tool_schemas("rode os testes", self.registry.schemas)
        self.assertIn("run_command", tool_names(selected))
        self.assertNotIn("write_file", tool_names(selected))

    def test_unknown_tools_are_never_hidden(self):
        extra = {"type": "function", "function": {"name": "custom_tool", "parameters": {}}}
        selected = select_tool_schemas("explain", self.registry.schemas + [extra])
        self.assertIn("custom_tool", tool_names(selected))

    def test_skill_selected_by_name_or_description(self):
        python = SimpleNamespace(name="python", description="Padroes para projetos Python")
        spring = SimpleNamespace(name="spring", description="Padroes para Java Spring Boot")
        self.assertEqual(select_skills("Escreva um script python", [python, spring]), [python])
        self.assertEqual(select_skills("configure Spring Boot", [python, spring]), [spring])
        self.assertEqual(select_skills("explique este arquivo", [python, spring]), [])

    def test_empty_request_selects_nothing_extra(self):
        self.assertEqual(select_skills("", [SimpleNamespace(name="python", description="Python")]), [])
        self.assertEqual(tool_names(select_tool_schemas("", self.registry.schemas)), {"list_files", "search_files", "read_file"})


class TestAgentDynamicContext(unittest.TestCase):
    def ask(self, dynamic, text, plan_mode=False):
        provider = DummyProvider()
        with tempfile.TemporaryDirectory() as directory:
            agent = Agent(provider, dynamic_context=dynamic, plan_mode=plan_mode)
            agent.tools = ToolRegistry(directory)
            agent.skills = [SimpleNamespace(name="python", description="Python style", content="Use type hints.")]
            agent.add_skill("python")
            agent.ask(text, use_tools=True)
        messages, kwargs = provider.requests[0]
        return messages, kwargs

    def test_disabled_by_default_sends_everything(self):
        self.assertFalse(Config.load().dynamic_context)
        messages, kwargs = self.ask(False, "Explain this")
        self.assertEqual(len(kwargs["tools"]), 6)
        self.assertIn("Use type hints.", messages[0]["content"])

    def test_enabled_filters_tools_and_skills(self):
        messages, kwargs = self.ask(True, "Explain this")
        self.assertEqual(tool_names(kwargs["tools"]), {"list_files", "search_files", "read_file"})
        self.assertNotIn("Use type hints.", messages[0]["content"])

    def test_enabled_keeps_relevant_skill_and_write_tool(self):
        messages, kwargs = self.ask(True, "Create a python module")
        self.assertIn("write_file", tool_names(kwargs["tools"]))
        self.assertIn("Use type hints.", messages[0]["content"])

    def test_plan_mode_stays_read_only(self):
        _, kwargs = self.ask(True, "Create a python module", plan_mode=True)
        self.assertEqual(tool_names(kwargs["tools"]), {"list_files", "search_files", "read_file"})


if __name__ == "__main__":
    unittest.main()
