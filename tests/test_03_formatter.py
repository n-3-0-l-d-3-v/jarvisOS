"""Feature 3: the six note templates + frontmatter builder."""

import pytest

from jarvis.formatter import (
    build_frontmatter,
    format_article,
    format_bug,
    format_concept,
    format_dsa,
    format_note,
    format_snippet,
    format_video,
)

TS = "2026-07-22T10:30:00"
CLS = {
    "title": "Redis Persistence",
    "domain": "databases",
    "subdomain": "redis",
    "type": "concept",
    "tags": ["redis", "persistence"],
    "summary": "How Redis persists data.",
    "creator": "",
}


def test_frontmatter_has_all_required_fields():
    fm = build_frontmatter(CLS, "cli", "", TS)
    for field in ("title:", "date:", "domain:", "subdomain:", "type:",
                  "tags:", "source:", "source_url:", "reviewed:"):
        assert field in fm, f"frontmatter missing {field}"
    assert fm.startswith("---")
    assert fm.count("---") >= 2
    assert "date: 2026-07-22" in fm


def test_frontmatter_renders_tags_as_yaml_list():
    fm = build_frontmatter(CLS, "cli", "", TS)
    assert '- "redis"' in fm and '- "persistence"' in fm


@pytest.mark.parametrize("func,required", [
    (format_concept, ["## Overview", "## Core Concept", "## Why It Matters",
                      "## How It Works", "## Key Points", "## Common Mistakes",
                      "## Examples", "## Interview Questions",
                      "## Related Topics", "## Resources"]),
    (format_dsa, ["## Problem Summary", "## Pattern", "## Approach",
                  "## Complexity", "## Solution", "## Key Insight",
                  "## Edge Cases", "## Similar Problems", "## Mistakes I Made"]),
    (format_bug, ["## The Bug", "## Error Message", "## Environment",
                  "## Root Cause", "## Fix Applied", "## Why It Works",
                  "## How To Prevent"]),
    (format_snippet, ["## What It Does", "## Code", "## Usage",
                      "## Dependencies", "## Parameters", "## Gotchas"]),
    (format_video, ["## Channel / Creator", "## Video Link", "## TLDR",
                    "## Key Concepts", "## Technologies Mentioned",
                    "## My Takeaways", "## Action Items"]),
    (format_article, ["## Source", "## TLDR", "## Key Points",
                      "## Important Details", "## Code Examples",
                      "## My Thoughts", "## How I Will Use This"]),
])
def test_every_template_has_its_required_sections(func, required):
    out = func("body text", CLS, "cli", "", TS)
    for section in required:
        assert section in out, f"{func.__name__} missing {section}"
    assert out.startswith("---"), "template must start with frontmatter"


@pytest.mark.parametrize("note_type,marker", [
    ("concept", "## Core Concept"),
    ("dsa", "## Problem Summary"),
    ("bug", "## The Bug"),
    ("snippet", "## What It Does"),
    ("video-summary", "## Channel / Creator"),
    ("article", "## Key Points"),
])
def test_format_note_full_mode_dispatches_to_correct_template(note_type, marker):
    cls = dict(CLS, type=note_type)
    assert marker in format_note("body", cls, "cli", "", TS, lean=False)


def test_format_note_defaults_to_concept_for_unknown_type():
    cls = dict(CLS, type="something-unknown")
    assert "## Core Concept" in format_note("body", cls, "cli", "", TS, lean=False)


# --- lean templates (the new default) -------------------------------------
@pytest.mark.parametrize("note_type", [
    "concept", "dsa", "bug", "snippet", "video-summary", "article",
])
def test_lean_notes_keep_content_and_wikilink_placeholder(note_type):
    cls = dict(CLS, type=note_type)
    out = format_note("MY ACTUAL CONTENT", cls, "cli", "", TS, lean=True)
    assert out.startswith("---"), "lean note must still have frontmatter"
    assert "MY ACTUAL CONTENT" in out, "lean note dropped the user's content"
    assert "<!-- [[wikilinks]] added automatically -->" in out, \
        "linker placeholder must survive in lean mode"
    assert f"# {CLS['title']}" in out


@pytest.mark.parametrize("note_type", [
    "concept", "dsa", "bug", "snippet", "video-summary", "article",
])
def test_lean_notes_are_substantially_smaller(note_type):
    cls = dict(CLS, type=note_type)
    lean = format_note("body", cls, "cli", "", TS, lean=True)
    full = format_note("body", cls, "cli", "", TS, lean=False)
    assert lean.count("## ") < full.count("## "), \
        f"{note_type}: lean should have fewer headings than full"


def test_lean_concept_drops_empty_scaffolding():
    out = format_note("body", CLS, "cli", "", TS, lean=True)
    for dropped in ("## Why It Matters", "## How It Works", "## Common Mistakes",
                    "## Interview Questions", "## Key Points"):
        assert dropped not in out, f"lean note still contains {dropped}"


def test_lean_placeholder_ratio_is_low():
    """The whole point: a lean note should be mostly content, not comments."""
    out = format_note("real content here", CLS, "cli", "", TS, lean=True)
    body = out.split("---", 2)[-1]
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    placeholders = [l for l in lines if l.startswith("<!--")]
    assert len(placeholders) <= 1, f"too many placeholders: {placeholders}"


def test_lean_dsa_keeps_useful_structure():
    cls = dict(CLS, type="dsa", subdomain="sliding-window")
    out = format_note("problem notes", cls, "cli", "", TS, lean=True)
    assert "## Pattern" in out and "## Complexity" in out
    assert "sliding-window" in out


def test_format_note_respects_config_default(monkeypatch):
    """With no explicit flag, format_note follows config.LEAN_NOTES."""
    import jarvis.config as cfg
    monkeypatch.setattr(cfg, "LEAN_NOTES", True, raising=False)
    assert "## Why It Matters" not in format_note("b", CLS, "cli", "", TS)
    monkeypatch.setattr(cfg, "LEAN_NOTES", False, raising=False)
    assert "## Why It Matters" in format_note("b", CLS, "cli", "", TS)


def test_templates_include_wikilink_placeholder_for_linker():
    """The linker relies on this exact placeholder existing."""
    for func in (format_concept, format_bug, format_snippet,
                 format_video, format_article):
        out = func("body", CLS, "cli", "", TS)
        assert "<!-- [[wikilinks]] added automatically -->" in out, func.__name__
    # DSA uses 'Related Patterns' but the same placeholder text.
    assert "<!-- [[wikilinks]] added automatically -->" in format_dsa(
        "body", CLS, "cli", "", TS)


def test_source_url_is_rendered_when_present():
    out = format_article("body", CLS, "article", "https://example.com/post", TS)
    assert "https://example.com/post" in out
