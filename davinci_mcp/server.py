"""MCP server (stdio) exposing DaVinci Resolve to Claude Code.

Registered for this repo in ``.mcp.json``; see ``davinci_mcp/README.md``.
The tool implementations live in ``tools.py``.
"""

import functools
import sys

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError as _McpToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp.exceptions import ToolError as _McpToolError

from davinci_mcp import tools

INSTRUCTIONS = """\
Controls the DaVinci Resolve instance running on this machine (Resolve must
be open with a project loaded, and external scripting enabled in
Preferences > System > General).
Times are seconds from the start of the current timeline unless a field says
frames. auto_cut is a dry run unless apply=true: run it without apply first,
show the user the planned cuts/markers, and only apply after they agree.
"""

server = _Server("davinci-resolve", instructions=INSTRUCTIONS)


def _register(fn):
    """Register ``fn`` as a tool, keeping stray prints off the stdio
    protocol stream (stdout) by sending them to stderr instead, and
    reporting failures as MCP tool errors whose message reaches the model
    (the SDK otherwise hides unexpected exceptions behind a generic one).
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            raise _McpToolError(f"{type(exc).__name__}: {exc}") from exc
        finally:
            sys.stdout = stdout

    server.tool()(wrapper)
    return fn


for _fn in (
    tools.get_status,
    tools.open_page,
    tools.list_timelines,
    tools.set_current_timeline,
    tools.create_timeline,
    tools.get_timeline_items,
    tools.add_marker,
    tools.get_markers,
    tools.delete_markers,
    tools.list_media_pool,
    tools.import_media,
    tools.append_to_timeline,
    tools.auto_cut,
    tools.list_render_presets,
    tools.render,
    tools.render_status,
):
    _register(_fn)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
