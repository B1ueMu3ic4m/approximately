"""v323: the brief is browsable — `digest` as an MCP resource.

The operations state (grades, triage, prices) was already readable
from an MCP client; the shift brief was the missing one. The
resource serves the same page the CLI prints — text/markdown, one
read, no tool call.
"""

import json

from approximately.mcp_server import ServerContext, _resources, _resources_read
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(tmp_path):
    store = TraceStore(tmp_path)
    for i in range(4):
        with Recorder(f"run {i}", store=store) as rec:
            rec.tool("sh", {}, agent="bot", result="x")
            rec.respond("done", success=(i != 3))
    return store


def test_digest_resource_registered_and_readable(tmp_path):
    _seed(tmp_path)
    ctx = ServerContext(str(tmp_path))
    listed = [r["name"] for r in _resources(ctx)]
    assert "digest" in listed
    resp = _resources_read(
        {"params": {"uri": f"approximately://{tmp_path}/digest"}},
        ctx, 7)
    content = resp["result"]["contents"][0]
    assert content["mimeType"] == "text/markdown"
    assert content["text"].startswith(f"# ops digest — {tmp_path}")
    assert "## grades" in content["text"]
    assert "## today's arrivals" in content["text"]


def test_digest_resource_is_json_safe_and_bounded(tmp_path):
    _seed(tmp_path)
    ctx = ServerContext(str(tmp_path))
    resp = _resources_read(
        {"params": {"uri": f"approximately://{tmp_path}/digest"}},
        ctx, 8)
    text = resp["result"]["contents"][0]["text"]
    assert len(text) < 100_000, "the brief must stay a page"
    json.dumps({"len": len(text)})  # trivial serializability smoke
