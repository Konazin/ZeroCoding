import asyncio
import os
import re
import threading
from contextlib import AsyncExitStack

from .registry import ToolRegistry, ToolSpec


class MCPClientManager:
    """Optional, long-lived stdio MCP connections; importing this module needs no SDK."""

    def __init__(self, servers: dict):
        self.servers = servers
        self.clients = {}
        self._loop = None
        self._thread = None
        self._stack = None
        self.tool_names = []

    def start(self):
        if not self.servers or self._loop:
            return
        try:
            from mcp import Client, StdioServerParameters
        except ImportError as exc:
            raise RuntimeError("MCP is configured. Install it with: pip install 'zerocoding[mcp]'") from exc
        self._Client, self._StdioServerParameters = Client, StdioServerParameters
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        try:
            self._submit(self._connect()).result(timeout=60)
        except Exception:
            self.close()
            raise

    async def _connect(self):
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        for name, config in self.servers.items():
            if config.get("transport", "stdio") != "stdio":
                raise ValueError(f"Unsupported MCP transport for {name}; only stdio is supported.")
            params = self._StdioServerParameters(
                command=config["command"],
                args=list(config.get("args") or []),
                env={key: re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda match: os.getenv(match.group(1), ""), str(value)) for key, value in (config.get("env") or {}).items()},
            )
            self.clients[name] = await self._stack.enter_async_context(self._Client(params))

    def register_tools(self, registry: ToolRegistry):
        self.start()
        for server, client in self.clients.items():
            result = self._call(client.list_tools()).result(timeout=30)
            for item in result.tools:
                safe_server = re.sub("[^A-Za-z0-9_-]", "_", server)
                safe_tool = re.sub("[^A-Za-z0-9_-]", "_", item.name)
                tool_name = f"mcp__{safe_server}__{safe_tool}"
                self.tool_names.append(tool_name)
                registry.register(ToolSpec(
                    name=tool_name,
                    description=f"MCP server {server}: {item.description or item.name}",
                    input_schema=getattr(item, "input_schema", getattr(item, "inputSchema", {"type": "object", "properties": {}})),
                    handler=lambda args, server=server, name=item.name: self.call_tool(server, name, args),
                    confirmation=True,
                ))

    def call_tool(self, server: str, name: str, arguments: dict):
        result = self._call(self.clients[server].call_tool(name, arguments)).result(timeout=120)
        if getattr(result, "is_error", getattr(result, "isError", False)):
            raise RuntimeError(self._content(result))
        return self._content(result)

    def list_resources(self, server: str):
        return self._call(self.clients[server].list_resources()).result(timeout=30).resources

    def read_resource(self, server: str, uri: str):
        return self._content(self._call(self.clients[server].read_resource(uri)).result(timeout=60))

    def list_prompts(self, server: str):
        return self._call(self.clients[server].list_prompts()).result(timeout=30).prompts

    def get_prompt(self, server: str, name: str):
        return self._content(self._call(self.clients[server].get_prompt(name)).result(timeout=60))

    def close(self):
        if not self._loop:
            return
        try:
            self._submit(self._stack.aclose()).result(timeout=10)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=10)
            self._loop.close()
            self._loop = None

    def _submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    def _call(self, awaitable):
        async def wait():
            return await awaitable
        return self._submit(wait())

    @staticmethod
    def _content(result):
        items = getattr(result, "content", None) or getattr(result, "contents", None) or getattr(result, "messages", None) or []
        texts = []
        for item in items:
            content = getattr(item, "content", item)
            text = getattr(content, "text", None)
            if text is not None:
                texts.append(text)
            elif hasattr(content, "data"):
                texts.append("[non-text MCP content omitted]")
            else:
                texts.append(str(content))
        return ("\n".join(texts) or str(result))[:6000]
