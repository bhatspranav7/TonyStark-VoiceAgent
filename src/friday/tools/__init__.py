"""MCP tools. Each module exposes register(mcp); add new modules to the list below."""

from . import news, system, web

MODULES = [news, web, system]


def register_all(mcp) -> None:
    for module in MODULES:
        module.register(mcp)
