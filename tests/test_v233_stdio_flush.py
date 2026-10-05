"""v233: the stdio smoke — a real pipe, a real process.

`approximately mcp` drives Claude Desktop/Zed over piped stdio, and
piped stdout block-buffers: without a flush per response the server
answers into a buffer no client ever reads.  Every prior test drove
`handle_request` in-process, so the flagship entry point's transport
was never exercised until this subprocess smoke.
"""

import json
import subprocess

TOOLS_REQUEST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list",
                 "params": {}}
DOCTOR_CALL = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
               "params": {"name": "doctor", "arguments": {}}}
INITIALIZE = {"jsonrpc": "2.0", "id": 3, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05",
                         "capabilities": {},
                         "clientInfo": {"name": "smoke", "version": "0"}}}


def _rpc(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def test_stdio_server_answers_over_a_real_pipe(tmp_path):
    proc = subprocess.Popen(
        ["approximately", "mcp", "--store", str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True)
    try:
        tools = _rpc(proc, TOOLS_REQUEST)["result"]["tools"]
        assert len(tools) == 47

        doctor = _rpc(proc, DOCTOR_CALL)["result"]["content"][0]["text"]
        payload = json.loads(doctor)
        assert payload["healthy"] is True

        init = _rpc(proc, INITIALIZE)["result"]
        assert "serverInfo" in init
    finally:
        proc.terminate()
