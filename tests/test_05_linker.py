"""Feature 5: the [[wikilink]] cross-reference engine."""

from jarvis import linker as L

BASE = {
    "id": "a1", "title": "Sliding Window Basics", "domain": "dsa",
    "subdomain": "sliding-window", "dsa_pattern": "sliding-window",
    "type": "dsa", "tags": ["arrays", "window"], "date": "2026-07-01",
    "folder_path": "04-dsa", "filename": "sliding-window-basics.md",
}


def _note(**over):
    """Build a related-note fixture.

    Each note gets its own filename unless one is given explicitly: a note's
    identity is its file, so two distinct notes sharing a filename is not a
    real-world state (the linker now treats that as the same note).
    """
    note = dict(BASE, **over)
    if "filename" not in over:
        note["filename"] = f"{note.get('id', 'note')}-{_slugish(note['title'])}.md"
    return note


def _slugish(text):
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def test_same_subdomain_scores_highest():
    other = _note(id="b1", title="Longest Substring")
    related = L.find_related_notes(BASE, [other])
    assert related and related[0]["score"] >= 3


def test_note_never_links_to_itself():
    assert L.find_related_notes(BASE, [BASE]) == []


def test_duplicate_index_rows_do_not_produce_duplicate_links():
    """Regression: a note indexed twice must appear once in related results."""
    row = _note(id="dupe", title="Duplicated Note", filename="duplicated-note.md")
    related = L.find_related_notes(BASE, [row, dict(row), dict(row)])
    assert len(related) == 1


def test_a_duplicate_row_of_self_is_not_related_to_self():
    """A second index row pointing at the same file is still 'self'."""
    self_dupe = dict(BASE, id="different-id")
    assert L.find_related_notes(BASE, [self_dupe]) == []


def test_unrelated_note_is_filtered_out():
    unrelated = _note(id="c1", title="CSS Grid", domain="frontend",
                      subdomain="css", dsa_pattern="", type="concept",
                      tags=["css"])
    assert L.find_related_notes(BASE, [unrelated]) == []


def test_shared_tags_contribute_score():
    other = _note(id="d1", title="Array Tricks", domain="dsa",
                  subdomain="arrays", dsa_pattern="", tags=["arrays", "window"])
    related = L.find_related_notes(BASE, [other])
    assert related, "shared tags + same domain should pass the threshold"


def test_results_are_sorted_by_score_desc():
    strong = _note(id="s1", title="Strong Match")
    weak = _note(id="w1", title="Weak Match", subdomain="arrays",
                 dsa_pattern="", tags=[])
    related = L.find_related_notes(BASE, [weak, strong])
    scores = [r["score"] for r in related]
    assert scores == sorted(scores, reverse=True)


def test_max_results_is_respected():
    others = [_note(id=f"x{i}", title=f"Note {i}") for i in range(10)]
    assert len(L.find_related_notes(BASE, others, max_results=3)) == 3


def test_build_wikilinks_format():
    links = L.build_wikilinks([
        {"filename": "two-sum.md", "title": "Two Sum"},
    ])
    assert links == "- [[two-sum|Two Sum]]"


def test_inject_wikilinks_replaces_placeholder(tmp_path):
    note = tmp_path / "n.md"
    note.write_text(
        "# T\n\n## Related Topics\n<!-- [[wikilinks]] added automatically -->\n",
        encoding="utf-8")
    assert L.inject_wikilinks(note, "- [[a|A]]") is True
    content = note.read_text(encoding="utf-8")
    assert "- [[a|A]]" in content
    assert "added automatically" not in content


def test_inject_wikilinks_handles_related_patterns_section(tmp_path):
    note = tmp_path / "n2.md"
    note.write_text("# T\n\n## Related Patterns\nnothing yet\n", encoding="utf-8")
    assert L.inject_wikilinks(note, "- [[b|B]]") is True
    assert "- [[b|B]]" in note.read_text(encoding="utf-8")


def test_should_run_full_link_on_multiples_of_ten(write_index):
    write_index([{"id": str(i)} for i in range(10)])
    assert L.should_run_full_link() is True
    write_index([{"id": str(i)} for i in range(7)])
    assert L.should_run_full_link() is False
