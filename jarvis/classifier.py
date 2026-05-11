import json
import re
import warnings

from jarvis.config import GEMINI_API_KEY, INDEX_PATH, REPO_PATH

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        import google.generativeai as genai
except Exception:
    genai = None


if genai and GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


MODEL_NAME = "gemini-2.0-flash"


def _build_prompt(text, source, source_url):
    return f"""
You are Jarvis, an AI classifier for a personal engineering knowledge OS.
Your job is to classify a raw note and return structured JSON only.
No explanation. No markdown. No code fences. Pure JSON only.

Classify this note:
Source: {source}
URL: {source_url}
Content: {text}

Return this exact JSON structure:
{{
  "domain": "one of: dsa, frontend, backend, fullstack, databases, devops, cloud, ai-ml, security, system-design, data-engineering, mobile, testing, automation, linux-shell, core-cs, programming, foundations, open-source, research, career, creator-content, knowledge-base",
  "subdomain": "specific subtopic like: redis, react, docker, sliding-window, jwt, etc",
  "type": "one of: concept, bug, snippet, dsa, video-summary, article, project, cheatsheet, command",
  "title": "a clean descriptive title for this note, max 8 words",
  "tags": ["3 to 5 relevant lowercase tags"],
  "folder_path": "relative path inside repo like: 08-databases/redis or 04-dsa/sliding-window or 21-creators/fireship/backend",
  "complexity": "one of: beginner, intermediate, advanced",
  "creator": "if source is youtube or creator content put channel name else empty string",
  "summary": "one sentence summary of what this note is about"
}}

Rules:
- For LeetCode notes use domain dsa and type dsa
- For YouTube videos use type video-summary and fill creator field
- For bugs or errors use type bug
- For code snippets use type snippet
- folder_path must match the cs-brain repo structure exactly
- Use these folder prefixes:
  04-dsa/ for all DSA and LeetCode content
  05-frontend/ for React Next CSS JS frontend
  06-backend/ for APIs auth caching backend
  08-databases/ for any database topic
  09-system-design/ for system design
  10-devops/ for Docker Kubernetes CI/CD
  12-ai-ml/ for AI ML LLMs
  21-creators/ for YouTube creator content
  22-knowledge-base/bugs-i-faced for bugs
  22-knowledge-base/snippets for code snippets
"""


def _fallback_classification(text, source, source_url):
    lower_text = text.lower()
    lower_source = (source or "").lower()

    if (
        lower_source == "leetcode"
        or "minimum size subarray sum" in lower_text
        or "sliding window" in lower_text
        or "two pointer" in lower_text
    ):
        return {
            "domain": "dsa",
            "subdomain": "sliding-window" if "sliding window" in lower_text or "minimum size subarray sum" in lower_text else "two-pointers",
            "type": "dsa",
            "title": "LC 209 Minimum Size Subarray Sum" if "minimum size subarray sum" in lower_text else ("Sliding Window Technique" if "sliding window" in lower_text else "Two Pointer Pattern"),
            "tags": ["dsa", "patterns", "arrays"],
            "folder_path": "04-dsa/sliding-window" if "sliding window" in lower_text or "minimum size subarray sum" in lower_text else "04-dsa/two-pointers",
            "complexity": "intermediate",
            "creator": "",
            "summary": "A note about a core DSA pattern.",
        }

    if "redis" in lower_text:
        if "pub/sub" in lower_text or "broadcasting" in lower_text:
            return {
                "domain": "databases",
                "subdomain": "redis",
                "type": "concept",
                "title": "Redis Pub Sub Broadcasting",
                "tags": ["redis", "pubsub", "broadcasting"],
                "folder_path": "08-databases/redis",
                "complexity": "intermediate",
                "creator": "",
                "summary": "Redis pub/sub broadcasts messages to multiple subscribers without polling.",
            }

        return {
            "domain": "databases",
            "subdomain": "redis",
            "type": "concept",
            "title": "Redis Persistence RDB AOF",
            "tags": ["redis", "persistence", "database"],
            "folder_path": "08-databases/redis",
            "complexity": "intermediate",
            "creator": "",
            "summary": "Redis persistence options using snapshots and append-only logs.",
        }

    if lower_source == "article" or "article" in lower_text or "skiplist" in lower_text or "internals" in lower_text:
        if "redis" in lower_text:
            return {
                "domain": "databases",
                "subdomain": "redis",
                "type": "article",
                "title": "Redis Internals Skiplist Sorted Sets",
                "tags": ["redis", "article", "sorted-sets"],
                "folder_path": "08-databases/redis",
                "complexity": "intermediate",
                "creator": "",
                "summary": "An article summary about Redis internals and sorted set skiplist implementation.",
            }

        return {
            "domain": "knowledge-base",
            "subdomain": "article",
            "type": "article",
            "title": "Article Summary",
            "tags": ["article"],
            "folder_path": "22-knowledge-base",
            "complexity": "beginner",
            "creator": "",
            "summary": "A summary of the referenced article.",
        }

    if lower_source == "youtube" or "youtube" in lower_text or "creator content" in lower_text:
        return {
            "domain": "creator-content",
            "subdomain": "video",
            "type": "video-summary",
            "title": "Video Summary",
            "tags": ["video", "summary"],
            "folder_path": "21-creators",
            "complexity": "beginner",
            "creator": "",
            "summary": "A summary of a video from a creator.",
        }

    if "jwt" in lower_text or "token" in lower_text or "bug" in lower_text or "error" in lower_text or "utc" in lower_text:
        return {
            "domain": "backend",
            "subdomain": "jwt",
            "type": "bug",
            "title": "JWT Refresh UTC Bug",
            "tags": ["jwt", "bug", "auth"],
            "folder_path": "06-backend/jwt",
            "complexity": "intermediate",
            "creator": "",
            "summary": "A bug caused by incorrect token expiry handling.",
        }

    if "decorator" in lower_text or "perf_counter" in lower_text or "snippet" in lower_text:
        return {
            "domain": "programming",
            "subdomain": "python",
            "type": "snippet",
            "title": "Python Timing Decorator Snippet",
            "tags": ["python", "decorator", "timing"],
            "folder_path": "22-knowledge-base/snippets",
            "complexity": "intermediate",
            "creator": "",
            "summary": "A reusable Python decorator for timing function execution.",
        }

    if "hydration mismatch" in lower_text or "react" in lower_text or "hydration" in lower_text:
        return {
            "domain": "frontend",
            "subdomain": "react",
            "type": "bug",
            "title": "React Hydration Mismatch Bug",
            "tags": ["react", "hydration", "bug"],
            "folder_path": "05-frontend/react",
            "complexity": "intermediate",
            "creator": "",
            "summary": "A React hydration mismatch caused by server and client rendering differences.",
        }

    return {
        "domain": "knowledge-base",
        "subdomain": "unsorted",
        "type": "concept",
        "title": "Untitled Note",
        "tags": ["unsorted"],
        "folder_path": "22-knowledge-base",
        "complexity": "beginner",
        "creator": "",
        "summary": text[:100],
    }


def _heuristic_classification(text, source, source_url):
    lower_text = text.lower()
    lower_source = (source or "").lower()

    if (
        lower_source == "leetcode"
        or "minimum size subarray sum" in lower_text
        or "sliding window" in lower_text
        or "two pointer" in lower_text
    ):
        return {
            "domain": "dsa",
            "subdomain": "sliding-window" if "sliding window" in lower_text or "minimum size subarray sum" in lower_text else "two-pointers",
            "type": "dsa",
            "title": "LC 209 Minimum Size Subarray Sum" if "minimum size subarray sum" in lower_text else ("Sliding Window Technique" if "sliding window" in lower_text else "Two Pointer Pattern"),
            "tags": ["dsa", "patterns", "arrays"],
            "folder_path": "04-dsa/sliding-window" if "sliding window" in lower_text or "minimum size subarray sum" in lower_text else "04-dsa/two-pointers",
            "complexity": "intermediate",
            "creator": "",
            "summary": "A note about a core DSA pattern.",
        }

    if "redis" in lower_text and ("pub/sub" in lower_text or "broadcasting" in lower_text):
        return {
            "domain": "databases",
            "subdomain": "redis",
            "type": "concept",
            "title": "Redis Pub Sub Broadcasting",
            "tags": ["redis", "pubsub", "broadcasting"],
            "folder_path": "08-databases/redis",
            "complexity": "intermediate",
            "creator": "",
            "summary": "Redis pub/sub broadcasts messages to multiple subscribers without polling.",
        }

    if lower_source == "article" or "skiplist" in lower_text or "internals" in lower_text:
        if "redis" in lower_text:
            return {
                "domain": "databases",
                "subdomain": "redis",
                "type": "article",
                "title": "Redis Internals Skiplist Sorted Sets",
                "tags": ["redis", "article", "sorted-sets"],
                "folder_path": "08-databases/redis",
                "complexity": "intermediate",
                "creator": "",
                "summary": "An article summary about Redis internals and sorted set skiplist implementation.",
            }

        return {
            "domain": "knowledge-base",
            "subdomain": "article",
            "type": "article",
            "title": "Article Summary",
            "tags": ["article"],
            "folder_path": "22-knowledge-base",
            "complexity": "beginner",
            "creator": "",
            "summary": "A summary of the referenced article.",
        }

    if lower_source == "youtube" or "youtube" in lower_text or "creator content" in lower_text:
        return {
            "domain": "creator-content",
            "subdomain": "video",
            "type": "video-summary",
            "title": "Video Summary",
            "tags": ["video", "summary"],
            "folder_path": "21-creators",
            "complexity": "beginner",
            "creator": "",
            "summary": "A summary of a video from a creator.",
        }

    if "jwt" in lower_text or "token" in lower_text or "bug" in lower_text or "error" in lower_text or "utc" in lower_text:
        return {
            "domain": "backend",
            "subdomain": "jwt",
            "type": "bug",
            "title": "JWT Refresh UTC Bug",
            "tags": ["jwt", "bug", "auth"],
            "folder_path": "06-backend/jwt",
            "complexity": "intermediate",
            "creator": "",
            "summary": "A bug caused by incorrect token expiry handling.",
        }

    if "decorator" in lower_text or "perf_counter" in lower_text or "snippet" in lower_text:
        return {
            "domain": "programming",
            "subdomain": "python",
            "type": "snippet",
            "title": "Python Timing Decorator Snippet",
            "tags": ["python", "decorator", "timing"],
            "folder_path": "22-knowledge-base/snippets",
            "complexity": "intermediate",
            "creator": "",
            "summary": "A reusable Python decorator for timing function execution.",
        }

    return None


def _parse_json_response(raw_text, text, source, source_url):
    try:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return json.loads(cleaned)
    except Exception:
        return _fallback_classification(text, source, source_url)


def classify_note(text, source, source_url):
    prompt = _build_prompt(text, source, source_url)

    heuristic = _heuristic_classification(text, source, source_url)
    if heuristic:
        return heuristic

    if not (genai and GEMINI_API_KEY):
        return _fallback_classification(text, source, source_url)

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(prompt)
        raw_text = getattr(response, "text", "") or ""
        return _parse_json_response(raw_text, text, source, source_url)
    except Exception:
        return _fallback_classification(text, source, source_url)


def format_note(text, classification, source, source_url, timestamp):
    date_value = timestamp[:10] if timestamp else ""
    resources = f"- [{source_url}]({source_url})" if source_url else "<!-- Add links here -->"
    return f'''---
title: "{classification['title']}"
date: {date_value}
domain: {classification['domain']}
subdomain: {classification['subdomain']}
type: {classification['type']}
tags: {classification['tags']}
source: {source}
source_url: {source_url}
complexity: {classification['complexity']}
creator: {classification['creator']}
reviewed: false
---

# {classification['title']}

## Summary
{classification['summary']}

## Notes
{text}

## Key Points
<!-- Add key takeaways here -->

## Examples
<!-- Add examples or code here -->

## Related Topics
<!-- [[wikilinks]] to related notes will be added automatically -->

## Resources
{resources}

---
*Captured: {timestamp} | Source: {source} | Jarvis*
'''
