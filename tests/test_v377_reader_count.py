"""v377: the reader count is counted, not guessed.

The README said the log "reads back four ways" — a count that
rotted as the digest brief and the fleet dashboard joined the
reader (the same rot the "21-check CI matrix" banner suffered in
v3.66). The claim is now enumerated and pinned: every surface
the README names must exist in the code, and the count in the
sentence must equal the number of surfaces the pin knows. When
a seventh reader appears, the test says so and the README moves
with it.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

# every surface that reads the webhook archive back, and the
# code that proves it exists
READERS = {
    "/stats": ("receiver.py", "/stats"),
    "received": ("cli.py", "def cmd_received"),
    "inbox tool": ("mcp_server.py", '"inbox": _tool_inbox'),
    "status frame": ("cli.py", 'payload["webhook_inbox"]'),
    "digest brief": ("digest.py", "overnight arrivals"),
    "fleet dashboard": ("fleet.py", "webhook inbox: {inbox_rows}"),
}


def _readme_reader_sentence():
    text = (_ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"the log reads back (\S+) ways — ([^|]+)",
                      text)
    assert match, "the README lost the reader sentence"
    return match.group(1), match.group(2)


def test_the_named_count_matches_the_pinned_list():
    word, _rest = _readme_reader_sentence()
    number = {"two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7}[word]
    assert number == len(READERS), (
        f"the README says {word} ways; the pin knows "
        f"{len(READERS)} readers — move them together")


def test_every_named_surface_exists_in_the_code():
    _word, rest = _readme_reader_sentence()
    for name in READERS:
        short = name.split()[0].lstrip("/").replace("`", "")
        assert short in rest, \
            f"the README stopped naming {name}"
        src_name, marker = READERS[name]
        text = (_ROOT / "src" / "approximately"
                / src_name).read_text(encoding="utf-8")
        assert marker in text, \
            f"the pin's proof for {name} went stale"


def test_architecture_names_the_shared_filters():
    text = (_ROOT / "docs" / "ARCHITECTURE.md").read_text(
        encoding="utf-8")
    assert "kind/contains/since" in text, \
        "the one-reader paragraph names the shared filters"
    assert "nonce-scoped readback" in text, \
        "the ping's delivery proof is on the architecture page"
