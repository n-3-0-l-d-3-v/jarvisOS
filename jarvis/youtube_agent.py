import httpx
import json
import re
from uuid import uuid4
from datetime import datetime

from jarvis.config import REPO_PATH, YOUTUBE_API_KEY, GROQ_API_KEY, INDEX_PATH


def _fetch_oembed_metadata(video_id):
    try:
        url = "https://www.youtube.com/oembed"
        params = {"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"}
        resp = httpx.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "video_id": video_id,
            "title": data.get("title", "Unknown"),
            "channel": data.get("author_name", "Unknown"),
            "description": "See video for details",
            "published_at": "Unknown",
            "tags": [],
            "duration": "Unknown",
            "view_count": "Unknown",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail": data.get("thumbnail_url", ""),
        }
    except Exception:
        return None


def extract_video_id(url):
    """Extract YouTube video ID from any YouTube URL format."""
    patterns = [
        r'(?:v=)([a-zA-Z0-9_-]{11})',
        r'(?:youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
        r'(?:shorts/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def fetch_video_metadata(video_id):
    """Fetch video metadata using YouTube Data API v3."""
    if not YOUTUBE_API_KEY:
        # Fallback: use oEmbed endpoint for basic metadata
        print("  [YouTube] No API key — fetching basic metadata only")
        metadata = _fetch_oembed_metadata(video_id)
        if metadata:
            return metadata
        print("  [YouTube] oEmbed fetch failed")
        return None

    try:
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet,contentDetails,statistics",
            "id": video_id,
            "key": YOUTUBE_API_KEY,
        }
        resp = httpx.get(url, params=params, timeout=10)
        data = resp.json()

        if "items" not in data or not data["items"]:
            print("  [YouTube] Video not found via Data API — trying oEmbed...")
            metadata = _fetch_oembed_metadata(video_id)
            if metadata:
                return metadata
            print("  [YouTube] Video not found")
            return None

        item = data["items"][0]
        snippet = item["snippet"]

        return {
            "video_id": video_id,
            "title": snippet["title"],
            "channel": snippet["channelTitle"],
            "description": snippet["description"][:500] if snippet.get("description") else "",
            "published_at": snippet["publishedAt"][:10] if snippet.get("publishedAt") else "Unknown",
            "tags": snippet.get("tags", [])[:10],
            "duration": item["contentDetails"]["duration"],
            "view_count": item["statistics"].get("viewCount", "0"),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail": snippet["thumbnails"]["high"]["url"] if "high" in snippet.get("thumbnails", {}) else "",
        }
    except Exception as e:
        print(f"  [YouTube] API fetch failed: {e}")
        return None


def fetch_transcript(video_id):
    """Fetch transcript from YouTube using youtube-transcript-api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api import TranscriptsDisabled, NoTranscriptFound

        try:
            api = YouTubeTranscriptApi()
            transcript = api.fetch(video_id, languages=["en", "en-US", "en-GB"])

            # Combine all text segments across snippet objects
            parts = []
            for snippet in transcript:
                text = getattr(snippet, "text", "")
                if text:
                    parts.append(text)
            full_text = " ".join(parts)

            # Clean up formatting artifacts
            full_text = re.sub(r"\[.*?\]", "", full_text)  # remove [Music] etc
            full_text = re.sub(r"\s+", " ", full_text).strip()

            if not full_text:
                print("  [YouTube] Transcript returned empty content")
                return None

            # Truncate to 8000 chars
            if len(full_text) > 8000:
                full_text = full_text[:8000] + "..."

            print(f"  [YouTube] Transcript fetched: {len(full_text)} chars")
            return full_text

        except TranscriptsDisabled:
            print("  [YouTube] Transcripts disabled for this video")
            return None
        except NoTranscriptFound:
            print("  [YouTube] No transcript available")
            return None

    except ImportError:
        print("  [YouTube] youtube-transcript-api not installed")
        return None
    except Exception as e:
        print(f"  [YouTube] Transcript fetch failed: {e}")
        return None


CREATOR_MAP = {
    "Fireship": "fireship",
    "ThePrimeagen": "primeagen",
    "The Primeagen": "primeagen",
    "ByteByteGo": "bytebytego",
    "Theo - t3.gg": "theo",
    "t3dotgg": "theo",
    "Theo Browne": "theo",
    "Harkirat Singh": "harkirat",
    "NetworkChuck": "networkchuck",
    "Traversy Media": "traversy-media",
    "Web Dev Simplified": "web-dev-simplified",
    "Andrej Karpathy": "andrej-karpathy",
    "Lex Fridman": "lex-fridman",
    "freeCodeCamp.org": "freecodecamp",
    "AI Explained": "ai-explained",
    "Coding with John": "coding-with-john",
    "TechWorld with Nana": "techworld-with-nana",
    "Computerphile": "computerphile",
    "3Blue1Brown": "3blue1brown",
    "CS Dojo": "cs-dojo",
    "NeetCode": "neetcode",
    "Abdul Bari": "abdul-bari",
    "Coderized": "coderized",
    "CodeAesthetic": "code-aesthetic",
    "Hussein Nasser": "hussein-nasser",
    "Tech With Tim": "tech-with-tim",
}


def detect_creator(channel_name):
    """Map YouTube channel name to creator folder."""
    # Exact match first
    if channel_name in CREATOR_MAP:
        return CREATOR_MAP[channel_name]

    # Case-insensitive partial match
    channel_lower = channel_name.lower()
    for key, value in CREATOR_MAP.items():
        if key.lower() in channel_lower:
            return value

    # Slugify channel name
    slug = channel_name.lower().replace(" ", "-").replace(".", "").replace("_", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def extract_json(text):
    """Extract JSON from text, handling edge cases."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def summarize_with_ai(metadata, transcript):
    """Summarize video with AI using Groq."""
    if not GROQ_API_KEY:
        print("  [YouTube] No Groq API key — skipping AI summary")
        return None

    context = transcript[:4000] if transcript else metadata.get("description", "")

    prompt = f"""You are Jarvis, analyzing a YouTube video for a developer's knowledge base.
Return ONLY valid JSON. Start with {{ end with }}. No explanation.

Video: {metadata['title']}
Channel: {metadata['channel']}
URL: {metadata['url']}
Transcript excerpt: {context}

Return this exact JSON:
{{
  "tldr": "2-3 sentence summary of what this video covers",
  "domain": "primary domain: dsa|frontend|backend|devops|cloud|ai-ml|system-design|databases|security|programming|tools|career",
  "topics": ["list", "of", "4-6", "main", "topics", "covered"],
  "technologies": ["technologies", "frameworks", "tools", "mentioned"],
  "key_concepts": [
    {{"concept": "name", "explanation": "one sentence"}},
    {{"concept": "name", "explanation": "one sentence"}},
    {{"concept": "name", "explanation": "one sentence"}}
  ],
  "difficulty": "beginner|intermediate|advanced",
  "folder_path": "path under 21-creators/[creator]/[domain]",
  "tags": ["4-6", "specific", "lowercase", "tags"],
  "action_items": ["things", "to", "try", "or", "build"]
}}"""

    try:
        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 1000,
            },
            timeout=20,
        )

        if resp.status_code != 200:
            print(f"  [YouTube] Groq error {resp.status_code}")
            return None

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        result = extract_json(content)

        if result:
            print("  [YouTube] AI summary generated")
            return result
        else:
            print("  [YouTube] Failed to parse AI response")
            return None

    except Exception as e:
        print(f"  [YouTube] AI summary failed: {e}")
        return None


def build_concepts_section(summary):
    """Build Key Concepts section from summary."""
    lines = []
    for kc in summary.get("key_concepts", []):
        lines.append(f"### {kc.get('concept', 'Concept')}")
        lines.append(kc.get("explanation", ""))
        lines.append("")
    return "\n".join(lines)


def build_video_note(metadata, transcript, summary, timestamp):
    """Build complete markdown note for video."""
    creator = detect_creator(metadata["channel"])

    frontmatter = f"""---
title: "{metadata['title']}"
date: {timestamp[:10]}
domain: {summary.get('domain', 'creator-content') if summary else 'creator-content'}
type: video-summary
tags: {json.dumps(summary.get('tags', []) if summary else [])}
source: youtube
source_url: "{metadata['url']}"
channel: "{metadata['channel']}"
creator: "{creator}"
difficulty: "{summary.get('difficulty', 'intermediate') if summary else 'intermediate'}"
reviewed: false
---"""

    concepts_section = (
        build_concepts_section(summary)
        if summary
        else "<!-- Add key concepts -->"
    )

    technologies = (
        "\n".join(f"- {t}" for t in summary.get("technologies", []))
        if summary
        else "<!-- Add technologies -->"
    )

    topics = (
        "\n".join(f"- {t}" for t in summary.get("topics", []))
        if summary else "<!-- Add topics -->"
    )

    action_items = (
        "\n".join(f"- [ ] {a}" for a in summary.get("action_items", []))
        if summary
        else "<!-- Add action items -->"
    )

    tldr = summary.get("tldr", metadata.get("description", "No summary")) if summary else metadata.get("description", "")

    body = f"""
# {metadata['title']}

## Channel
{metadata['channel']}

## Video Link
{metadata['url']}

## Published
{metadata.get('published_at', 'Unknown')}

## TLDR
{tldr}

## Key Concepts
{concepts_section}

## Technologies Mentioned
{technologies}

## Main Topics
{topics}

## My Notes
{transcript[:1000] if transcript else '<!-- Add your notes here -->'}

## Action Items
{action_items}

## Takeaways
<!-- What I personally found most useful -->

## Related Topics
<!-- [[wikilinks]] added automatically -->

## Resources
- [Watch Video]({metadata['url']})

---
*Captured: {timestamp} | Channel: {metadata['channel']} | Jarvis*"""

    return frontmatter + body


def process_youtube_url(url, timestamp=None):
    """Main entry point: process YouTube URL and save as note."""
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    # Extract video ID
    video_id = extract_video_id(url)
    if not video_id:
        print("  [YouTube] Invalid URL — could not extract video ID")
        return None

    print(f"  [YouTube] Processing: {url}")

    # Fetch metadata
    metadata = fetch_video_metadata(video_id)
    if not metadata:
        print("  [YouTube] Could not fetch metadata — using minimal fallback")
        metadata = {
            "video_id": video_id,
            "title": f"YouTube Video {video_id}",
            "channel": "unknown-channel",
            "description": "Video metadata unavailable; captured from URL only.",
            "published_at": "Unknown",
            "tags": [],
            "duration": "Unknown",
            "view_count": "Unknown",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail": "",
        }

    print(f"  [YouTube] Video: {metadata['title']}")
    print(f"  [YouTube] Channel: {metadata['channel']}")

    # Fetch transcript
    transcript = fetch_transcript(video_id)

    # Detect creator
    creator_folder = detect_creator(metadata["channel"])
    print(f"  [YouTube] Creator: {creator_folder}")

    # Summarize with AI
    summary = summarize_with_ai(metadata, transcript)
    if not summary:
        print("  [YouTube] AI summary failed, using basic template")

    # Build markdown
    markdown = build_video_note(metadata, transcript, summary, timestamp)

    # Determine folder path
    if summary and summary.get("folder_path"):
        folder_path = summary["folder_path"]
    else:
        domain = summary.get("domain", "general") if summary else "general"
        folder_path = f"21-creators/{creator_folder}/{domain}"

    # Build filename
    slug = metadata["title"].lower()
    slug = re.sub(r"[^a-z0-9\s\-]", "", slug)
    slug = slug.strip().replace(" ", "-")
    slug = re.sub(r"-+", "-", slug)
    slug = slug[:60]
    filename = f"{slug}.md"

    # Create folder
    folder = REPO_PATH / folder_path
    folder.mkdir(parents=True, exist_ok=True)

    # Write file
    filepath = folder / filename
    filepath.write_text(markdown, encoding="utf-8")

    # Update index
    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            index_data = json.load(f)
    except Exception:
        index_data = {"notes": [], "total_notes": 0}

    new_entry = {
        "id": str(uuid4())[:8],
        "title": metadata["title"],
        "domain": summary.get("domain", "creator-content") if summary else "creator-content",
        "subdomain": creator_folder,
        "folder_path": folder_path,
        "filename": filename,
        "date": timestamp[:10],
        "tags": summary.get("tags", []) if summary else [],
        "type": "video-summary",
        "source": "youtube",
        "creator": creator_folder,
        "confidence": 0.9 if summary else 0.5,
        "classifier_used": "youtube-agent",
    }

    index_data["notes"].append(new_entry)
    index_data["total_notes"] = len(index_data["notes"])

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)

    return {
        "success": True,
        "title": metadata["title"],
        "channel": metadata["channel"],
        "folder_path": folder_path,
        "filename": filename,
    }
