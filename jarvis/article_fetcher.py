import httpx
import json
import re
from datetime import datetime
from pathlib import Path
import uuid

from jarvis.config import REPO_PATH, INDEX_PATH, GROQ_API_KEY


def extract_json(text):
    if not text:
        return None

    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass

    try:
        fixed = text[start : end + 1] if start != -1 else text
        fixed = fixed.replace("'", '"')
        return json.loads(fixed)
    except Exception:
        pass

    return None


def fetch_article(url):
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        "Accept": "text/markdown",
        "X-Return-Format": "markdown",
        "User-Agent": "Jarvis-Knowledge-OS/1.0",
    }

    print(f"  [Article] Fetching via Jina Reader: {url[:60]}...")

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(jina_url, headers=headers)

        if response.status_code != 200:
            print(f"  [Article] Jina fetch failed: {response.status_code}")
            return None

        content = response.text
        lines = content.split("\n")

        content_start = 0
        for i, line in enumerate(lines):
            if line.startswith("# ") or (i > 5 and line.strip()):
                content_start = i
                break

        clean_content = "\n".join(lines[content_start:])

        if len(clean_content) > 6000:
            clean_content = clean_content[:6000] + "\n\n[Content truncated]"

        print(f"  [Article] Content fetched: {len(clean_content)} chars")
        return clean_content
    except Exception as e:
        print(f"  [Article] Jina fetch failed: {e}")
        return None


def extract_article_metadata(url, content):
    metadata = {
        "url": url,
        "title": "",
        "site": "",
        "estimated_read_time": "",
    }

    h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if h1_match:
        metadata["title"] = h1_match.group(1).strip()

    if not metadata["title"]:
        path = url.split("/")[-1].replace("-", " ").replace("_", " ")
        metadata["title"] = path.title()[:80]

    domain_match = re.search(r"https?://(?:www\.)?([^/]+)", url)
    if domain_match:
        metadata["site"] = domain_match.group(1)

    word_count = len(content.split())
    read_minutes = max(1, word_count // 200)
    metadata["estimated_read_time"] = f"{read_minutes} min read"

    return metadata


def classify_article_with_ai(url, content, metadata):
    if not GROQ_API_KEY:
        print("  [Article] No Groq API key — skipping AI classification")
        return None

    prompt = f"""
You are Jarvis, analyzing a technical article for a developer knowledge base.
Return ONLY valid JSON. Start with {{ end with }}. No explanation.

Article URL: {url}
Site: {metadata['site']}
Title: {metadata['title']}
Content excerpt: {content[:3000]}

Return this exact JSON:
{{
  "domain": "exactly one of: dsa, frontend, backend, devops, cloud, ai-ml, system-design, databases, security, programming, tools, career, research, open-source",
  "subdomain": "specific technology or topic like redis docker react etc",
  "type": "article",
  "title": "clean article title max 10 words",
  "tags": ["4-6", "specific", "lowercase", "tags"],
  "folder_path": "path in repo like 08-databases/redis or 06-backend/authentication or 09-system-design/scalability",
  "complexity": "beginner|intermediate|advanced",
  "tldr": "2-3 sentence summary of the article's main point",
  "key_points": [
      "most important point from the article",
      "second most important point",
      "third most important point",
      "fourth most important point"
  ],
  "technologies": ["technologies", "tools", "mentioned"],
  "practical_value": "one sentence on how a developer can apply this",
  "confidence": 0.9
}}
"""

    try:
        from jarvis.ai import complete_json, last_error

        result = complete_json(prompt, max_tokens=1000, temperature=0.1)
        if result is None:
            print(f"  [Article] AI classification unavailable ({last_error()})")
            return None

        # Guard against the model echoing prompt text into the domain value.
        from jarvis.classifier import normalize_domain, normalize_subdomain

        result["domain"] = normalize_domain(result.get("domain"))
        result["subdomain"] = normalize_subdomain(result.get("subdomain"))
        return result
    except Exception as exception:
        print(f"  [Article] AI classification error: {exception}")
        return None


def build_article_note(url, content, metadata, classification, timestamp):
    title = classification["title"] if classification else metadata["title"]
    domain = classification["domain"] if classification else "knowledge-base"
    subdomain = classification["subdomain"] if classification else ""
    tags = json.dumps(classification["tags"] if classification else [])
    complexity = classification["complexity"] if classification else "intermediate"
    tldr = classification["tldr"] if classification else "<!-- Add summary -->"
    key_points = (
        "\n".join(f"- {p}" for p in classification["key_points"])
        if classification
        else "<!-- Add key points -->"
    )
    technologies = (
        "\n".join(f"- {t}" for t in classification["technologies"])
        if classification
        else "<!-- Add technologies -->"
    )
    practical_value = (
        classification["practical_value"]
        if classification
        else "<!-- Add practical application -->"
    )

    return f"""---
title: "{title}"
date: {timestamp[:10]}
domain: {domain}
subdomain: {subdomain}
type: article
tags: {tags}
source: article
source_url: "{url}"
site: "{metadata['site']}"
read_time: "{metadata['estimated_read_time']}"
complexity: "{complexity}"
reviewed: false
---

# {title}

## Source
- Site: {metadata['site']}
- URL: [{url}]({url})
- Read time: {metadata['estimated_read_time']}

## TLDR
{tldr}

## Key Points
{key_points}

## Technologies Mentioned
{technologies}

## How I Can Apply This
{practical_value}

## Detailed Notes
{content[:2000] if content else '<!-- Add detailed notes -->'}

## My Thoughts
<!-- Personal opinion or reflection -->

## Related Topics
<!-- [[wikilinks]] added automatically -->

---
*Captured: {timestamp} | Source: {metadata['site']} | Jarvis*
"""


def process_article_url(url, manual_note="", timestamp=None):
    try:
        if timestamp is None:
            timestamp = datetime.now().isoformat()

        print(f"  [Article] Processing: {url[:70]}")

        content = fetch_article(url)
        if content is None:
            print("  [Article] Could not fetch article content")
            return None

        metadata = extract_article_metadata(url, content)

        if manual_note:
            content = f"{content}\n\nUser notes: {manual_note}"

        classification = classify_article_with_ai(url, content, metadata)
        if classification is None:
            print("  [Article] AI classification failed, using basic template")

        note_markdown = build_article_note(url, content, metadata, classification, timestamp)

        if classification and classification.get("folder_path"):
            folder_path = classification["folder_path"]
        else:
            folder_path = "22-knowledge-base/articles"

        title = classification["title"] if classification else metadata["title"]
        slug = title.lower()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = slug.strip().replace(" ", "-")
        slug = re.sub(r"-+", "-", slug)
        slug = slug[:60] + ".md"
        filename = slug

        folder = REPO_PATH / folder_path
        folder.mkdir(parents=True, exist_ok=True)

        filepath = folder / filename
        if filepath.exists():
            print(f"  [Article] Note already exists — overwriting: {folder_path}/{filename}")

        filepath.write_text(note_markdown, encoding="utf-8")

        from jarvis.index_store import upsert_note

        upsert_note({
            "id": str(uuid.uuid4())[:8],
            "title": title,
            "domain": classification["domain"] if classification else "knowledge-base",
            "subdomain": classification["subdomain"] if classification else "",
            "folder_path": folder_path,
            "filename": filename,
            "date": timestamp[:10],
            "tags": classification["tags"] if classification else [],
            "type": "article",
            "source": "article",
            "source_url": url,
            "site": metadata["site"],
            "confidence": classification["confidence"] if classification else 0.5,
            "classifier_used": "article-agent",
        })

        return {
            "success": True,
            "title": title,
            "site": metadata["site"],
            "folder_path": folder_path,
            "filename": filename,
        }
    except Exception as e:
        print(f"  [Article] Unexpected error: {e}")
        return None
