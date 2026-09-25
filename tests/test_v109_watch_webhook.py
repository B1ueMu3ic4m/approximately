"""v109: fleet watch webhook — every digest cycle POSTs the summary.

`fleet --watch --webhook URL` now notifies per cycle, not just on
one-shot surveys. Delivery failure is a stderr warning and the loop
continues: an ops watch must survive its notification endpoint being
down (that is exactly when you need it to keep watching). The poster
is injectable, so tests run against a fake — the one-shot path's
transport contract (scheme check, HMAC signature, bounded retries)
is covered by earlier rounds and reused here.
"""


from approximately.cli import build_parser
from approximately.fleet import watch_fleet
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path, name="s"):
    store = TraceStore(str(tmp_path / name))
    rec = Recorder("watch fixture", save=False)
    rec.tool("search", {"q": 1}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def _digest_dir(tmp_path):
    d = tmp_path / "digests"
    d.mkdir()
    return d


def test_watch_posts_each_cycle(tmp_path):
    calls = []

    def fake_poster(summaries, url):
        calls.append((url, [s.name for s in summaries],
                      round(summaries[0].failure_rate, 4)))
        return "200"

    store = _store(tmp_path)
    written = watch_fleet([store.directory], _digest_dir(tmp_path),
                          interval=0, iterations=3,
                          webhook_url="https://hooks.example/x",
                          notify=fake_poster)
    assert written == 3
    assert len(calls) == 3
    assert all(url == "https://hooks.example/x" for url, _, _ in calls)
    assert calls[0][2] == 0.0  # the fixture store is all-green


def test_watch_survives_poster_failure(tmp_path, capsys):
    def broken_poster(summaries, url):
        raise RuntimeError("endpoint down (as on a bad night)")

    store = _store(tmp_path)
    written = watch_fleet([store.directory], _digest_dir(tmp_path),
                          interval=0, iterations=2,
                          webhook_url="https://hooks.example/x",
                          notify=broken_poster)
    assert written == 2  # the watch loop lived on
    err = capsys.readouterr().err
    assert "webhook delivery failed" in err
    assert "hooks.example" not in err  # the URL never leaks into logs


def test_watch_without_webhook_is_unchanged(tmp_path):
    store = _store(tmp_path)
    digest_dir = _digest_dir(tmp_path)
    written = watch_fleet([store.directory], digest_dir,
                          interval=0, iterations=2)
    assert written == 2
    assert list(digest_dir.glob("digest-*.jsonl"))


def test_cli_passes_webhook_through(tmp_path):
    parser = build_parser()
    args = parser.parse_args([
        "fleet", str(_store(tmp_path).directory),
        "--watch", "60", "--digest-dir", str(tmp_path / "d"),
        "--webhook", "https://hooks.example/x",
        "--iterations", "1",
    ])
    assert args.webhook == "https://hooks.example/x"
