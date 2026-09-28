"""v140: ARCHITECTURE keeps the interop pair documented."""


def test_architecture_documents_interop():
    from pathlib import Path

    text = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "## Interop" in text
    assert "importer.py" in text and "exporter.py" in text
    assert "import_transcripts" in text
    assert "export_transcripts" in text
    assert "--judge-cache" in text
    assert "stats.json" in text
    assert "--watch" in text
