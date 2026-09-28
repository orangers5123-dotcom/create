"""Spawn the real stdio MCP server and talk to it with the MCP client.

There's no Resolve install here, so tool calls are expected to fail
cleanly (an error result) -- the point is that the server starts, lists
its tools, and keeps the protocol stream intact.
"""

import asyncio
import os
import sys

import pytest

mcp = pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _session_roundtrip():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "davinci_mcp"],
        cwd=REPO,
        # Point at a nonexistent install so the connection fails fast.
        env={**os.environ, "RESOLVE_SCRIPT_API": "/nonexistent", "RESOLVE_SCRIPT_LIB": "/nonexistent"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            result = await session.call_tool("get_status", {})
            return listed, result


def test_server_lists_tools_and_reports_missing_resolve():
    listed, result = asyncio.run(asyncio.wait_for(_session_roundtrip(), 30))
    names = {t.name for t in listed.tools}
    assert {"get_status", "add_marker", "auto_cut", "render"} <= names
    assert all(t.description for t in listed.tools)
    assert getattr(result, "is_error", None) or getattr(result, "isError", None)  # mcp 2.x / 1.x
    assert "DaVinciResolveScript" in result.content[0].text
