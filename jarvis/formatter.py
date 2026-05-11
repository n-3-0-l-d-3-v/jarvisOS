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


def format_note(text, classification, source, source_url, timestamp):
    note_type = classification.get("type", "concept")

    if note_type == "dsa":
        return format_dsa(text, classification, source, source_url, timestamp)
    elif note_type == "bug":
        return format_bug(text, classification, source, source_url, timestamp)
    elif note_type == "snippet":
        return format_snippet(text, classification, source, source_url, timestamp)
    elif note_type == "video-summary":
        return format_video(text, classification, source, source_url, timestamp)
    elif note_type == "article":
        return format_article(text, classification, source, source_url, timestamp)
    else:
        return format_concept(text, classification, source, source_url, timestamp)
