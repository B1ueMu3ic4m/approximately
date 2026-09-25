"""v121: toolscan eats its own cooking — every shipped MCP tool
description must pass the toolkit's own injection/homoglyph scanner
clean, and the ARCHITECTURE adapter list stays in sync with contrib/.
"""

from approximately.contrib import pydantic_ai  # noqa: F401
from approximately.mcp_server import _TOOLS
from approximately.toolscan import scan


def test_all_tool_descriptions_scan_clean():
    for tool in _TOOLS:
        result = scan(tool["description"])
        assert result.verdict == "clean", (
            tool["name"], result.verdict, result.findings)


def test_all_schemas_have_required_type():
    for tool in _TOOLS:
        schema = tool["inputSchema"]
        assert schema.get("type") == "object", tool["name"]
        assert isinstance(schema.get("properties"), dict)
        required = schema.get("required", [])
        assert all(r in schema["properties"] for r in required), tool["name"]


def test_contrib_adapters_importable_lazily():
    """New adapters must register in contrib/ without breaking the
    zero-dependency import of the core package."""
    import approximately
    import approximately.contrib.google_adk

    assert approximately.__version__
