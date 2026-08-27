"""Feature 8: the RSS feed processor (Task 3.5)."""

import json

from jarvis import rss_processor as R

RSS_XML = b"""<?xml version='1.0'?><rss version='2.0'><channel>
<item><title>Rust async runtime deep dive</title><link>https://ex.com/rust</link>
<description>&lt;p&gt;tokio scheduler and performance&lt;/p&gt;</description>
<guid>g-rust</guid><pubDate>Tue, 22 Jul 2026 10:00:00 GMT</pubDate></item>
<item><title>Celebrity gossip roundup</title><link>https://ex.com/gossip</link>
<description>Non technical fluff.</description><guid>g-gossip</guid></item>
</channel></rss>"""

ATOM_XML = b"""<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'>
<entry><title>Postgres index internals</title>
<link href='https://ex.com/pg' rel='alternate'/><id>a-pg</id>
<summary>B-tree indexes speed up database queries in postgres.</summary>
<updated>2026-07-22T09:00:00Z</updated></entry></feed>"""


# --- parsing ---------------------------------------------------------------
def test_parses_rss_two_point_zero():
    items = R.parse_feed(RSS_XML)
    assert len(items) == 2
    assert items[0]["title"] == "Rust async runtime deep dive"
    assert items[0]["link"] == "https://ex.com/rust"
    assert items[0]["id"] == "g-rust"


def test_parses_atom_with_href_links():
    items = R.parse_feed(ATOM_XML)
    assert len(items) == 1
    assert items[0]["link"] == "https://ex.com/pg"
    assert items[0]["id"] == "a-pg"


def test_html_is_stripped_from_summaries():
    assert "<p>" not in R.parse_feed(RSS_XML)[0]["summary"]


def test_malformed_xml_returns_empty_not_crash():
    assert R.parse_feed(b"<rss><broken") == []


# --- relevance filtering ---------------------------------------------------
def test_keyword_filter_keeps_technical_drops_noise():
    items = R.parse_feed(RSS_XML) + R.parse_feed(ATOM_XML)
    for i in items:
        i["feed"] = "Test"
    kept_titles = [k["title"] for k in R._filter_with_keywords(items)]
    assert "Rust async runtime deep dive" in kept_titles
    assert "Postgres index internals" in kept_titles
    assert "Celebrity gossip roundup" not in kept_titles


def test_short_keywords_do_not_match_inside_words():
    """Regression: 'go' must not match 'gossip', 'ai' must not match 'email'."""
    items = [{"title": "Celebrity gossip and email drama", "summary": "",
              "link": "https://x.com/1", "id": "1", "feed": "T"}]
    assert R._filter_with_keywords(items) == []


def test_ai_filter_json_extraction():
    parsed = R._extract_json('```json\n[{"index":0,"domain":"backend"}]\n```')
    assert isinstance(parsed, list) and parsed[0]["index"] == 0


# --- saving + dedupe -------------------------------------------------------
def _stub_feeds(monkeypatch, xml=RSS_XML):
    monkeypatch.setattr(R, "GROQ_API_KEY", "", raising=False)
    monkeypatch.setattr(
        R, "fetch_feed",
        lambda feed: ([dict(i, feed=feed["name"]) for i in R.parse_feed(xml)]
                      if feed["name"] == "Hacker News" else []),
        raising=False)


def test_end_to_end_saves_note_and_updates_index(monkeypatch, sandbox, clean_index):
    (sandbox / "00-meta" / "rss_seen.json").unlink(missing_ok=True)
    _stub_feeds(monkeypatch)

    summary = R.process_feeds(sync_git=False, verbose=False)
    assert summary["saved"] >= 1

    files = list((sandbox / "22-knowledge-base" / "rss").glob("*.md"))
    assert files, "no RSS note written"
    content = files[0].read_text(encoding="utf-8")
    for section in ("## Source", "## Why It Matters", "## Summary",
                    "## Related Topics"):
        assert section in content
    assert "type: rss" in content

    index = json.loads(clean_index.read_text(encoding="utf-8"))
    assert index["total_notes"] >= 1
    assert index["notes"][0]["type"] == "rss"
    assert index["notes"][0]["source_url"] == "https://ex.com/rust"

    for f in files:
        f.unlink()


def test_seen_store_prevents_reprocessing(monkeypatch, sandbox, clean_index):
    (sandbox / "00-meta" / "rss_seen.json").unlink(missing_ok=True)
    _stub_feeds(monkeypatch)

    first = R.process_feeds(sync_git=False, verbose=False)
    assert first["saved"] >= 1
    second = R.process_feeds(sync_git=False, verbose=False)
    assert second["new"] == 0 and second["saved"] == 0

    for f in (sandbox / "22-knowledge-base" / "rss").glob("*.md"):
        f.unlink()


def test_source_url_in_index_blocks_resave(monkeypatch, sandbox, write_index):
    """Second dedupe layer: even with the seen-store wiped, an already
    indexed source_url must not be saved again."""
    (sandbox / "00-meta" / "rss_seen.json").unlink(missing_ok=True)
    write_index([{"id": "x", "title": "Rust", "source_url": "https://ex.com/rust",
                  "folder_path": "22-knowledge-base/rss", "filename": "old.md"}])
    _stub_feeds(monkeypatch)

    summary = R.process_feeds(sync_git=False, verbose=False)
    saved_urls = [f for f in summary["files"] if "rust" in f]
    assert not saved_urls, "re-saved an item already present in index.json"


def test_feed_fetch_failure_is_non_fatal(monkeypatch):
    monkeypatch.setattr(R, "fetch_feed", lambda feed: [], raising=False)
    summary = R.process_feeds(sync_git=False, verbose=False)
    assert summary["saved"] == 0  # no crash
