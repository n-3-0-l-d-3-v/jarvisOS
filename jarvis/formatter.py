from datetime import datetime


def _format_tags(tags):
    if not tags:
        return "[]"
    lines = [""]
    for tag in tags:
        lines.append(f'  - "{tag}"')
    return "\n".join(lines)


def _source_line(source_url, placeholder):
    return f"- [{source_url}]({source_url})" if source_url else placeholder


def build_frontmatter(classification, source, source_url, timestamp):
    try:
        date_value = datetime.fromisoformat(timestamp).date().isoformat() if timestamp else ""
    except Exception:
        date_value = (timestamp or "")[:10]

    title = classification.get("title", "Untitled Note")
    domain = classification.get("domain", "knowledge-base")
    subdomain = classification.get("subdomain", "unsorted")
    note_type = classification.get("type", "concept")
    tags = _format_tags(classification.get("tags", []))
    complexity = classification.get("complexity", "beginner")
    creator = classification.get("creator", "")

    return f'''---
title: "{title}"
date: {date_value}
domain: {domain}
subdomain: {subdomain}
type: {note_type}
tags:{tags}
source: {source}
source_url: "{source_url}"
complexity: {complexity}
creator: "{creator}"
reviewed: false
---
'''


def format_concept(text, classification, source, source_url, timestamp):
    frontmatter = build_frontmatter(classification, source, source_url, timestamp)
    title = classification.get("title", "Untitled Note")
    summary = classification.get("summary", "")
    resources = _source_line(source_url, "<!-- Add links here -->")
    return f"""{frontmatter}
# {title}

## Overview
{summary}

## Core Concept
{text}

## Why It Matters
<!-- Why developers need to know this -->

## How It Works
<!-- Internal mechanism or flow -->

## Key Points
<!-- Bullet list of important facts -->

## Common Mistakes
<!-- What people get wrong -->

## Examples

<!-- Code or real-world example -->

## Interview Questions
<!-- Common questions on this topic -->

## Related Topics
<!-- [[wikilinks]] added automatically -->

## Resources
{resources}

---
*Captured: {timestamp} | Source: {source} | Jarvis*
"""


def format_dsa(text, classification, source, source_url, timestamp):
    frontmatter = build_frontmatter(classification, source, source_url, timestamp)
    title = classification.get("title", "Untitled Note")
    subdomain = classification.get("subdomain", "")
    return f"""{frontmatter}
# {title}

## Problem Summary
{text}

## Pattern
{subdomain}

## Approach
<!-- Step by step solution approach -->

## Complexity
| | Value |
|---|---|
| Time | O( ) |
| Space | O( ) |

## Solution
```python
# Solution code here
```

## Key Insight
<!-- The core trick or observation that makes this work -->

## Edge Cases
<!-- List edge cases to watch for -->

## Similar Problems
<!-- Other problems using the same pattern -->

## Mistakes I Made
<!-- What went wrong, what to remember -->

## Related Patterns
<!-- [[wikilinks]] added automatically -->

---
*Captured: {timestamp} | Source: {source} | Jarvis*
"""


def format_bug(text, classification, source, source_url, timestamp):
    frontmatter = build_frontmatter(classification, source, source_url, timestamp)
    title = classification.get("title", "Untitled Note")
    return f"""{frontmatter}
# {title}

## The Bug
{text}

## Error Message

<!-- Paste exact error here -->

## Environment
<!-- OS, framework version, language version -->

## Root Cause
<!-- Why did this happen -->

## Fix Applied

<!-- Exact code or command that fixed it -->

## Why It Works
<!-- Explanation of why the fix resolved it -->

## How To Prevent
<!-- How to avoid this in the future -->

## Time Lost
<!-- How long did this take to debug -->

## Related Issues
<!-- [[wikilinks]] added automatically -->

---
*Captured: {timestamp} | Source: {source} | Jarvis*
"""


def format_snippet(text, classification, source, source_url, timestamp):
    frontmatter = build_frontmatter(classification, source, source_url, timestamp)
    title = classification.get("title", "Untitled Note")
    summary = classification.get("summary", "")
    source_line = _source_line(source_url, "<!-- Add source URL -->")
    return f"""{frontmatter}
# {title}

## What It Does
{summary}

## Code

{text}

## Usage

<!-- How to use this snippet -->

## Dependencies
<!-- Required imports or packages -->

## Parameters
<!-- Key inputs and what they do -->

## Gotchas
<!-- Edge cases or things to watch out for -->

## Related Snippets
<!-- [[wikilinks]] added automatically -->

## Source
{source_line}

---
*Captured: {timestamp} | Source: {source} | Jarvis*
"""


def format_video(text, classification, source, source_url, timestamp):
    frontmatter = build_frontmatter(classification, source, source_url, timestamp)
    title = classification.get("title", "Untitled Note")
    creator = classification.get("creator", "")
    summary = classification.get("summary", "")
    video_link = _source_line(source_url, "<!-- Add YouTube URL -->")
    return f"""{frontmatter}
# {title}

## Channel / Creator
{creator}

## Video Link
{video_link}

## TLDR
{summary}

## Raw Notes
{text}

## Key Concepts
<!-- Main ideas from the video -->

## Technologies Mentioned
<!-- List tools, languages, frameworks covered -->

## Timestamps of Important Moments
<!-- HH:MM — topic -->

## My Takeaways
<!-- What I personally found most useful -->

## Action Items
<!-- What to try or build based on this -->

## Related Topics
<!-- [[wikilinks]] added automatically -->

---
*Captured: {timestamp} | Source: {source} | Creator: {creator} | Jarvis*
"""


def format_article(text, classification, source, source_url, timestamp):
    frontmatter = build_frontmatter(classification, source, source_url, timestamp)
    title = classification.get("title", "Untitled Note")
    summary = classification.get("summary", "")
    source_line = _source_line(source_url, "<!-- Add article URL -->")
    return f"""{frontmatter}
# {title}

## Source
{source_line}

## TLDR
{summary}

## Key Points
{text}

## Important Details
<!-- Deeper notes on specific sections -->

## Code Examples

<!-- Any code from the article -->

## My Thoughts
<!-- Personal opinion or reflection -->

## How I Will Use This
<!-- Practical application -->

## Related Topics
<!-- [[wikilinks]] added automatically -->

---
*Captured: {timestamp} | Source: {source} | Jarvis*
"""


# --------------------------------------------------------------------------- #
# Lean templates
#
# The full templates above emit ~10 headings, most of which stay empty forever.
# A repo audit found the median note was 66% scaffolding, which makes opening
# your own notes feel like unfinished homework. Lean notes keep the content and
# at most a couple of genuinely useful prompts. The wikilink placeholder is
# always preserved because linker.py depends on that exact string.
# --------------------------------------------------------------------------- #

_WIKILINK_PLACEHOLDER = "<!-- [[wikilinks]] added automatically -->"


def _lean_note(body_sections, classification, source, source_url, timestamp,
               related_header="Related Topics"):
    frontmatter = build_frontmatter(classification, source, source_url, timestamp)
    title = classification.get("title", "Untitled Note")
    parts = [frontmatter, f"\n# {title}\n"]
    for heading, content in body_sections:
        content = (content or "").strip()
        if heading:
            parts.append(f"\n## {heading}\n{content}\n" if content else f"\n## {heading}\n")
        elif content:
            parts.append(f"\n{content}\n")
    parts.append(f"\n## {related_header}\n{_WIKILINK_PLACEHOLDER}\n")
    parts.append(f"\n---\n*Captured: {timestamp} | Source: {source} | Jarvis*\n")
    return "".join(parts)


def format_concept_lean(text, classification, source, source_url, timestamp):
    summary = classification.get("summary", "")
    sections = []
    if summary:
        sections.append((None, summary))
    sections.append((None, text))
    if source_url:
        sections.append(("Source", _source_line(source_url, "")))
    return _lean_note(sections, classification, source, source_url, timestamp)


def format_bug_lean(text, classification, source, source_url, timestamp):
    return _lean_note(
        [(None, text), ("Fix", "")],
        classification, source, source_url, timestamp,
        related_header="Related Issues",
    )


def format_snippet_lean(text, classification, source, source_url, timestamp):
    summary = classification.get("summary", "")
    sections = []
    if summary:
        sections.append((None, summary))
    sections.append(("Code", text))
    return _lean_note(sections, classification, source, source_url, timestamp,
                      related_header="Related Snippets")


def format_dsa_lean(text, classification, source, source_url, timestamp):
    # DSA keeps a little more structure — the fields are genuinely used.
    subdomain = classification.get("subdomain", "")
    return _lean_note(
        [
            (None, text),
            ("Pattern", subdomain),
            ("Approach", ""),
            ("Complexity", "| | Value |\n|---|---|\n| Time | O( ) |\n| Space | O( ) |"),
        ],
        classification, source, source_url, timestamp,
        related_header="Related Patterns",
    )


def format_video_lean(text, classification, source, source_url, timestamp):
    creator = classification.get("creator", "")
    summary = classification.get("summary", "")
    sections = []
    if creator:
        sections.append(("Channel", creator))
    if source_url:
        sections.append(("Video Link", _source_line(source_url, "")))
    if summary:
        sections.append(("TLDR", summary))
    sections.append((None, text))
    return _lean_note(sections, classification, source, source_url, timestamp)


def format_article_lean(text, classification, source, source_url, timestamp):
    summary = classification.get("summary", "")
    sections = []
    if source_url:
        sections.append(("Source", _source_line(source_url, "")))
    if summary:
        sections.append(("TLDR", summary))
    sections.append((None, text))
    return _lean_note(sections, classification, source, source_url, timestamp)


_FULL_DISPATCH = {
    "dsa": format_dsa,
    "bug": format_bug,
    "snippet": format_snippet,
    "video-summary": format_video,
    "article": format_article,
}

_LEAN_DISPATCH = {
    "dsa": format_dsa_lean,
    "bug": format_bug_lean,
    "snippet": format_snippet_lean,
    "video-summary": format_video_lean,
    "article": format_article_lean,
}


def format_note(text, classification, source, source_url, timestamp, lean=None):
    """Render a note. `lean` defaults to config.LEAN_NOTES."""
    if lean is None:
        try:
            from jarvis.config import LEAN_NOTES

            lean = LEAN_NOTES
        except Exception:
            lean = True

    note_type = classification.get("type", "concept")
    table = _LEAN_DISPATCH if lean else _FULL_DISPATCH
    default = format_concept_lean if lean else format_concept
    renderer = table.get(note_type, default)
    return renderer(text, classification, source, source_url, timestamp)
