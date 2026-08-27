# Jarvis — Complete Documentation

Two passes over the same system: **Part 1** in plain English, **Part 2** in full
technical detail.

Status: Phases 1, 2 and 3 complete. 22 CLI commands, 20 modules, 192 passing tests.

---
---

# PART 1 — THE SIMPLE EXPLANATION

## What Jarvis actually is

You learn things all day — a LeetCode problem, a bug you fixed, a YouTube video,
a blog post. Normally that knowledge evaporates.

Jarvis is a robot librarian. You throw a scrap of text or a link at it, and it:

1. **Catches it instantly** so you never lose your train of thought
2. **Figures out what it is** (a DSA problem? a bug? an article?)
3. **Files it in the right folder** in your notes repo
4. **Writes it up properly** using a template with all the right sections
5. **Connects it to related notes** you already had
6. **Backs it up to GitHub** automatically
7. **Writes it into today's diary** so you can see what you learned

You do one thing (`jar note "..."`). It does seven.

## The mental model

Think of three boxes:

- **The Inbox** — anything you capture lands here instantly as a raw file. This is
  deliberately dumb and fast so capturing never blocks you.
- **The Brain** — reads the inbox, decides what each thing is, and writes it up.
- **The Library** — your `devNote` folder: 27 topic folders of clean Markdown,
  plus a daily diary, all synced to a private GitHub repo.

## What you can actually do

### Save something you learned
```
jar note "redis keeps data safe using RDB snapshots and AOF logs"
```
It works out this is a databases/Redis concept, writes a full note with Overview /
Why It Matters / Common Mistakes / Interview Questions sections, files it under
`08-databases/redis/`, links it to your other Redis notes, pushes to GitHub, and
adds a line to today's diary.

### Save a LeetCode problem
```
jar note "LC-76 minimum window substring using sliding window"
```
It recognises the LeetCode number, **fetches the official problem** from LeetCode
(title, difficulty, tags, which companies ask it), asks an AI to explain the
approach, time/space complexity, edge cases and common mistakes, then saves it as
`lc-76-minimum-window-substring.md`. The filename is deterministic, so saving the
same problem twice updates one file instead of making duplicates.

### Save a YouTube video
```
jar youtube https://youtube.com/watch?v=...
```
Pulls the title, channel and **auto-generated subtitles**, gets an AI to summarise
it into key concepts and action items, recognises the creator (Fireship,
Primeagen, ByteByteGo, NeetCode and ~20 others) and files it under that creator.

### Save an article
```
jar article https://someblog.com/post
```
Uses a free service that turns any webpage into clean text (no browser needed),
summarises it, and saves it with TLDR and key points.

### Save from your phone
```
jar discord
```
Starts a Discord bot. Message your private Discord channel from your phone and it
saves into the same system. Links and text both work.

### Save from your browser with one click
```
jar serve
```
Opens a dashboard at `http://localhost:7823/dashboard`. Drag the
**"⚡ Save to Jarvis"** button onto your bookmarks bar. Now on *any* webpage,
click that bookmark → a small dark dialog appears → type a note → Save.
It knows if you're on YouTube and handles it differently. Works in Zen, Firefox,
Chrome, and on mobile.

### Read the tech news for you
```
jar rss
```
Checks Hacker News, TLDR Tech and JavaScript Weekly, uses AI to throw away
everything irrelevant, and saves brief notes only on things that matter to a
developer. Won't ever save the same story twice.

### See what you did
```
jar today        what you learned today
jar finalize     AI writes a paragraph summarising your day
jar weekly       AI writes a full week review
jar status       how many notes you have
jar dsa          all your LeetCode problems grouped by pattern
jar graph "redis"   which notes relate to Redis
```

### Set it and forget it
```
jar schedule --rss
```
Windows then runs the day's summary at 23:59 and the news check at 08:00,
automatically, forever.

## Why it never breaks

For understanding your notes it tries **Google Gemini** first. If that's down or
out of quota it tries **Groq**. If both fail it falls back to plain keyword
matching that needs no internet and cannot fail. So capturing always works — worst
case the filing is a bit less clever.

## What it costs

Nothing. Every service is a free tier: Gemini, Groq, YouTube API, LeetCode,
Jina Reader, Discord, GitHub. No paid APIs and no AI models running on your laptop.

---
---

# PART 2 — THE TECHNICAL EXPLANATION

## Architecture

```
                        jar <command>  (Click CLI)
                                │
        ┌───────────────────────┼────────────────────────┐
        │                       │                        │
   capture.py             direct agents            api_server.py
   (inbox/raw/*.json)   youtube / article        (FastAPI :7823)
        │                 rss / leetcode          dashboard+bookmarklet
        │                       │                        │
        └───────────► orchestrator.py ◄──────────────────┘
                     process_single_note()
                                │
   ┌──────────┬─────────────────┼──────────────┬───────────────┐
classifier  formatter/      index.json     daily_log.py    git_sync.py
(3-tier)    dsa_agent       (00-meta)      (journal)       (commit+push)
                                │
                            linker.py  ([[wikilinks]])
```

Design principle: **capture is decoupled from processing.** `capture_note()` only
writes a JSON file (<50 ms, no network). Everything expensive happens afterwards,
so a slow API can never block you mid-thought.

## Module reference

| Module | Responsibility |
|---|---|
| `config.py` | Single source of truth. Loads `.env`, derives all paths, creates required dirs at import. |
| `capture.py` | `capture_note()` writes `inbox/raw/<ts>_<id>.json`; `mark_processed()` / `mark_failed()` move files between inbox states. |
| `classifier.py` | 3-tier classification chain + helpers: `clean_json_response`, `extract_json`, `validate_folder_path`, `detect_dsa_pattern` (12 patterns), `detect_note_type`, `normalize_domain`, `classify_with_groq`, `classify_with_keywords`, `classify_note`. |
| `formatter.py` | Six templates (`concept`, `dsa`, `bug`, `snippet`, `video`, `article`) + `build_frontmatter()` + `format_note()` dispatcher. |
| `orchestrator.py` | `process_single_note()` runs the 10-step pipeline; `process_inbox_orchestrated()` loops the inbox; `run_parallel_dsa_enrichment()` uses `ThreadPoolExecutor`. |
| `processor.py` | Thin delegate kept for API stability. |
| `dsa_agent.py` | Groq DSA specialist → approach, complexity, key insight, edge cases, similar problems, companies, mistakes. `build_dsa_note()` renders the enriched template. |
| `leetcode_fetcher.py` | LeetCode GraphQL, no API key. `extract_lc_number`, `get_problem_slug` (cached), `fetch_problem`, `enrich_note_with_leetcode`. |
| `youtube_agent.py` | YouTube Data API v3 → oEmbed fallback, `youtube-transcript-api` for captions, Groq summary, `detect_creator()` over a 24-channel map. |
| `article_fetcher.py` | Jina Reader (`r.jina.ai`) → Markdown, Groq classification, article note builder. |
| `rss_processor.py` | Stdlib RSS/Atom parser, Groq relevance filter with keyword fallback, two-layer dedupe, note writer. |
| `linker.py` | Relevance scoring + `[[wikilink]]` injection into Related Topics / Related Patterns. |
| `daily_log.py` | Journal: `get_log_path`, `ensure_log_exists`, `append_to_log`, `update_technologies`, `finalize_log`, `generate_weekly_summary`. |
| `git_sync.py` | GitPython: `get_status`, `stage_and_commit`, `push_to_remote`, `sync`, `build_commit_message`. |
| `index_cleaner.py` | `clean_index()` prunes entries whose file vanished; `fix_domains()` repairs LLM-corrupted domain values. |
| `api_server.py` | FastAPI app, dashboard renderer, bookmarklet generator, capture endpoints. |
| `discord_bot.py` | Routes Discord messages into the same pipeline. `!help !status !today !dsa`. |
| `scheduler.py` / `tasks.py` | `schtasks` registration + the entry point those tasks call. |
| `cli.py` | All 22 commands. |

## The classification chain

`classify_note(text, source, source_url)`:

1. `detect_note_type()` pre-classifies from the raw text — checks `--source`, then
   an LC-number regex, then `detect_dsa_pattern()`, then bug / snippet / video /
   article markers. **DSA is checked before the snippet check**, otherwise a DSA
   note containing its solution code gets misfiled as a snippet.
2. `detect_dsa_pattern()` matches strict multi-word phrases (`"sliding window"`,
   `"two pointer"`) across 12 patterns — deliberately strict to avoid false hits.
3. **Tier 1 Gemini 2.0 Flash** → **Tier 2 Groq llama-3.3-70b** → **Tier 3 keywords**.
   Tier 3 is pure Python and cannot fail, guaranteeing a classification always exists.
4. `extract_json()` tolerates raw JSON, ``` fences, prose-wrapped JSON, and
   single-quoted JSON.
5. `validate_folder_path()` corrects wrong numeric prefixes (`99-dsa` → `04-dsa`).
6. `normalize_domain()` strips echoed prompt scaffolding.

## The pipeline (`process_single_note`)

1. Read inbox JSON
2. `classify_note()`
3. If DSA → `run_parallel_dsa_enrichment()`: LeetCode fetch **and** DSA agent run
   concurrently in a `ThreadPoolExecutor` (~5-8 s vs ~15 s sequential), then the
   DSA agent re-runs with LeetCode context for a better answer
4. Render via `build_dsa_note()` or `format_note()`
5. Filename: DSA → deterministic `lc-<n>-<slug>.md`; else `slugify(title).md`
6. Duplicate check (skip unless `--force`)
7. Write Markdown
8. Append to daily log + update technologies
9. Update `index.json`
10. Commit + push, then `run_linker_for_new_notes()`; a full re-link runs every
    10th note (`should_run_full_link()`)

## Data structures

**Inbox item** (`inbox/raw/*.json`)
```json
{"id":"a1b2c3d4","timestamp":"2026-07-22T10:30:00","date":"2026-07-22",
 "time":"10:30:00","source":"cli","source_url":"","text":"...","status":"pending"}
```

**Index entry** (`00-meta/index.json`)
```json
{"total_notes": 112, "notes": [{
  "id","title","domain","subdomain","folder_path","filename","date","tags",
  "type","source","confidence","classifier_used","dsa_pattern",
  "problem_number","difficulty","companies","lc_difficulty","lc_companies"}]}
```

**Note frontmatter** — every note carries YAML: `title, date, domain, subdomain,
type, tags, source, source_url, complexity, reviewed`, plus type-specific fields
(DSA adds `problem_number, pattern, difficulty, time_complexity,
space_complexity, companies`).

## Linker scoring

`+3` same subdomain · `+2` same domain · `+2` same DSA pattern · `+1` per shared
tag (max 4) · `+1` same type · `−1` if >180 days older. Threshold `>= 2`, top 5,
rendered as `- [[filename|Title]]`.

## HTTP API (`jar serve`, port 7823)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | — | `{status, repo, version}` |
| GET | `/status` | — | `{total_notes, today, repo, version}` |
| GET | `/api/stats` | — | totals, per-type counts, domain breakdown, recent 10 |
| GET | `/dashboard`, `/` | — | server-rendered dark HTML |
| POST | `/capture/note` | `{text, source?, url?}` | `{ok, kind, title}` |
| POST | `/capture/article` | `{url, note?}` | `{ok, title, site, saved}` |
| POST | `/capture/youtube` | `{url, note?}` | `{ok, title, channel, saved}` |

- CORS `*` — the bookmarklet POSTs from arbitrary origins.
- A `threading.Lock` serialises captures so concurrent writes can't corrupt
  `index.json` or collide in git.
- Capture handlers are sync `def`, so FastAPI runs the blocking git/HTTP work in
  its threadpool rather than stalling the event loop.
- The dashboard is server-rendered by token replacement (not f-strings) so the
  CSS/JS braces need no escaping. All interpolated note data is `html.escape`d —
  a note titled `<script>alert(1)</script>` renders inert (covered by a test).

## The bookmarklet

Generated per-request from the server's own base URL, URL-encoded, HTML-escaped
into the anchor `href`. Validated as syntactically valid JS via `node --check`.
On click it captures `location.href`, `document.title` and any selection, detects
YouTube via regex, injects a fixed-position dark dialog at
`z-index:2147483647`, and POSTs to the right endpoint — showing `✓ Saved`
(auto-closing after 2 s), a red error, or a "Is `jar serve` running?" hint if the
fetch fails. A checkbox switches to saving your note standalone instead of the page.

> Browsers treat `http://localhost` as a secure context, so this works from HTTPS
> pages without mixed-content errors.

## RSS processor

Feeds: Hacker News, TLDR Tech, JavaScript Weekly.

> **Bytes.dev was specified but has no public RSS feed** — every candidate path
> (`/rss`, `/rss.xml`, `/feed`, `/feed.xml`, `/rss/feed.xml`) returns 404, as it's
> an email-first newsletter. JavaScript Weekly replaces it as the JS source.

- Parsed with stdlib `xml.etree` handling both RSS 2.0 `<item>` and Atom
  `<entry>` (including `<link href>`), so **no `feedparser` dependency** — this
  keeps the install light, matching the project's lightweight constraint.
- Relevance: one batched Groq call for up to 40 new items returning at most 8 keeps.
- Fallback filter uses **word-boundary regex**, not substring matching — otherwise
  `"go"` matches `"gossip"` and `"ai"` matches `"email"`.
- **Two dedupe layers**: `00-meta/rss_seen.json` (fast path, bounded to 800 keys)
  *and* a `source_url` check against `index.json`, so a lost seen-store still
  can't cause re-saves.
- Unreachable feeds are skipped, never fatal.

## Testing

`pytest` — **192 tests, 13 files, ~25 s, fully offline.**

`tests/conftest.py` sets `JARVIS_REPO_PATH` to a temp dir **before any jarvis
import** (module-level constants bind at import), then builds a devNote skeleton
and `git init`s it with **no `origin` remote** — so commits are exercised for real
while pushes fail gracefully exactly as the code expects. Your real repo is never
touched and nothing is ever pushed.

| File | Tests | Covers |
|---|---|---|
| `test_01_config_capture.py` | 6 | path resolution, inbox lifecycle, unique IDs |
| `test_02_classifier.py` | 21 | JSON extraction, folder validation, DSA/type detection, offline tier |
| `test_03_formatter.py` | 17 | all 6 templates, frontmatter, dispatcher, linker placeholder |
| `test_04_daily_log.py` | 11 | path building, section routing, dedupe (ISSUE 1 regression) |
| `test_05_linker.py` | 10 | scoring, wikilink format, injection |
| `test_06_index_git.py` | 7 | stale pruning, commit messages, graceful missing remote |
| `test_07_agents.py` | 25 | YouTube/article/LeetCode/DSA pure functions |
| `test_08_rss.py` | 11 | RSS+Atom parsing, filtering, both dedupe layers |
| `test_09_api_server.py` | 19 | all endpoints, dashboard, XSS escaping, CORS, bookmarklet |
| `test_10_pipeline_e2e.py` | 7 | full pipeline, duplicates, `--force`, DSA filenames, failure capture |
| `test_11_cli.py` | 34 | every command registered + help + behaviour |
| `test_12_scheduler.py` | 8 | schtasks wiring, task routing, failure handling |
| `test_13_domain_normalization.py` | 9 | LLM artifact scrubbing + index repair |

## Bugs found and fixed during this work

1. **Daily log** — `get_log_path()` didn't create `YYYY/MM`; config was bound
   stale. Fixed with lazy `get_config()` + `mkdir(parents=True)`.
2. **Double logging** — `cli.py` had a dead second `append_to_log()` call that
   would have duplicated every diary entry had its guard ever matched. Removed;
   the orchestrator is now the single writer.
3. **DSA misdetection** — `detect_note_type()` only returned `dsa` for
   `--source leetcode`, so `jar note "LC-1 ... def twoSum()"` was filed as a
   *snippet*. Now detects LC numbers and DSA patterns from the text, before the
   snippet check.
4. **RSS false positives** — substring keyword matching kept "Celebrity **go**ssip".
   Replaced with word-boundary patterns.
5. **Domain corruption** — agent prompts put the instruction inside the value
   (`"domain": "primary domain: dsa|frontend|..."`), so the model echoed it into
   `index.json` (2 live entries affected). Prompts reworded, `normalize_domain()`
   added to all three agents, and `jar index-clean --fix-domains` added to repair
   existing data.
6. **Bytes.dev** — specified feed doesn't exist; replaced.

## Known limitations

- `schtasks` scheduling is Windows-only.
- Transcripts need captions to exist on the video.
- Jina Reader can struggle with heavy JS or paywalled pages.
- Free-tier rate limits apply (Gemini 1M tokens/day, Groq 14.4k req/day).
- `index.json` is rewritten whole on each save — fine at this scale, but it is
  the component to revisit at tens of thousands of notes.

## Not yet built (Phases 4-5)

Semantic search over your own notes (`jar ask`), quiz mode, revision scheduling,
Obsidian graph export, and the analytics dashboard (streaks, velocity,
interview-readiness scoring).
