import sys
import types
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from zerocoding.tools.mcp_client import MCPClientManager
from zerocoding.tools.registry import ToolRegistry


class FakeClient:
    def __init__(self, _params):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def list_tools(self):
        tool = SimpleNamespace(name="echo", description="echo text", input_schema={"type": "object", "properties": {"text": {"type": "string"}}})
        return SimpleNamespace(tools=[tool])

    async def call_tool(self, _name, arguments):
        return SimpleNamespace(is_error=False, content=[SimpleNamespace(text=arguments["text"])])

    async def list_resources(self):
        return SimpleNamespace(resources=[SimpleNamespace(uri="file:///a", name="a")])

    async def read_resource(self, _uri):
        return SimpleNamespace(contents=[SimpleNamespace(text="resource text")])

    async def list_prompts(self):
        return SimpleNamespace(prompts=[SimpleNamespace(name="review", description="Review")])

    async def get_prompt(self, _name):
        return SimpleNamespace(messages=[SimpleNamespace(content=SimpleNamespace(text="prompt text"))])


class TestMCPClient(unittest.TestCase):
    def test_stdio_tools_resources_prompts_and_shutdown(self):
        fake = types.ModuleType("mcp")
        fake.Client = FakeClient
        fake.StdioServerParameters = lambda **kwargs: kwargs
        config = {"local": {"command": "fake", "args": []}}
        manager = MCPClientManager(config)
        registry = ToolRegistry()
        with patch.dict(sys.modules, {"mcp": fake}):
            manager.register_tools(registry)
            self.assertEqual(registry.get("mcp__local__echo").handler({"text": "ok"}), "ok")
            self.assertEqual(manager.read_resource("local", "file:///a"), "resource text")
            self.assertEqual(manager.get_prompt("local", "review"), "prompt text")
            self.assertEqual(manager.tool_names, ["mcp__local__echo"])
            manager.close()

    def test_disabled_mcp_does_not_import_sdk(self):
        MCPClientManager({}).start()


if __name__ == "__main__":
    unittest.main()
