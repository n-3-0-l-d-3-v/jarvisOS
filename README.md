# Jarvis — Knowledge OS

A CLI + Discord daemon that turns scattered input (a Discord message, a YouTube link, an article URL, a raw LeetCode dump) into a structured, git-backed personal knowledge base — classified, enriched, cross-linked, and committed without manual filing.

Built to solve one problem: capture is easy, organization is not. Jarvis makes organization automatic.

## Pipeline

```
capture → classify → enrich → format → link → commit
```

1. **Capture** (`capture.py`) — any input (CLI arg, Discord message, YouTube/article URL) is written to `inbox/raw/` as a timestamped JSON record with a random id, source, and raw text. Nothing is lost even if a later stage fails.
2. **Classify** (`classifier.py`) — Gemini 2.0 Flash maps the raw text onto a fixed 25-domain taxonomy (`01-foundations` → `25-research`), extracting title, domain/subdomain, note type, tags, and complexity as strict JSON. `extract_json` is defensive by design: it tries a raw parse, strips markdown code fences, falls back to brace-slicing, and finally single-quote-to-double-quote repair — because LLM JSON output is not reliably well-formed and the pipeline can't afford to drop a note over a formatting slip.
3. **Enrich** — two source-specific agents run when applicable:
   - `dsa_agent.py` + `leetcode_fetcher.py`: detects `LC-###` / `leetcode-###` references, resolves the problem slug against LeetCode's public API, and asks Groq to extract pattern (sliding-window, two-pointers, DP, backtracking, graphs, …), complexity, and approach as structured JSON.
   - `youtube_agent.py`: resolves a video ID from any YouTube URL shape (watch/shorts/embed/youtu.be), then pulls metadata via the YouTube Data API v3 with an oEmbed fallback when no API key is configured.
   - `article_fetcher.py`: renders arbitrary URLs to markdown via Jina Reader (`r.jina.ai`) rather than shipping its own HTML/readability parser.
4. **Format** (`formatter.py`) — renders type-specific templates (concept / DSA / bug / project) with YAML frontmatter (title, domain, tags, complexity, source, reviewed flag) so every note is immediately Obsidian-compatible.
5. **Link** (`linker.py`) — after a note lands, `find_related_notes` scores every other note in the index: +3 same subdomain, +2 same domain, +2 same DSA pattern, +1 same type, +min(shared tags, 4), with a recency penalty applied once two notes drift more than 180 days apart. No embeddings, no vector store — a cheap, auditable, entirely local relevance score.
6. **Commit** (`git_sync.py`) — wraps GitPython to report dirty/ahead status and stage+commit+push the vault automatically, so the knowledge base is a real git history, not a folder of files.

An `index.json` tracks every note's metadata for linking and search; `index_cleaner.py` prunes entries whose backing file has been deleted or moved, keeping the index honest against the filesystem.

## Interfaces

- **CLI** (`jar`, via Click + Rich) — capture, list pending, process the inbox, force a reclassify pass, trigger linking, inspect git status, generate the daily/weekly log.
- **Discord bot** (`discord_bot.py`) — a channel-scoped bot that classifies YouTube/article URLs or raw text on message, reacts with progress emoji, and replies with a Discord embed summarizing what was filed and where.
- **Windows Task Scheduler** (`scheduler.py`) — registers a daily `schtasks` job that finalizes the day's log at 23:59 and, on Sundays, additionally rolls up a weekly summary.

## Daily log

`daily_log.py` maintains a per-day markdown file (`daily-logs/YYYY/MM/YYYY-MM-DD.md`) with a fixed template — summary, captured notes, technologies used, domains covered, DSA activity, bugs fixed, key learnings, tomorrow — appended to throughout the day and finalized (AI-summarized via Gemini) at day's end.

## Stack

Python · Click · Rich · GitPython · httpx · Gemini 2.0 Flash (classification, daily summaries) · Groq (DSA/pattern extraction) · Jina Reader (article extraction) · YouTube Data API v3 · discord.py

## Setup

```bash
pip install -e .
cp .env.example .env   # set JARVIS_REPO_PATH + API keys
jar --help
```

`JARVIS_REPO_PATH` points at a local git repository (an Obsidian vault in practice) — Jarvis creates `inbox/{raw,processed,failed}`, `00-meta/index.json`, and `daily-logs/` inside it on first run.

## Why it's built this way

Every external call (Gemini, Groq, YouTube, Jina) is wrapped with a fallback path rather than a hard failure — no API key still produces a usable note, just a less enriched one. The classify → enrich → link pipeline is intentionally stage-separated so a failure in one enrichment agent (say, LeetCode's API being down) never blocks capture or filing; failed notes move to `inbox/failed/` with the failure reason attached instead of vanishing.
