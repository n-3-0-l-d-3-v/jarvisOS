# Jarvis — Personal Engineering Knowledge OS

Jarvis is a CLI tool (`jar`) that captures, classifies, and stores engineering
knowledge automatically into a private GitHub repo, using **free cloud AI APIs
only** (no local LLMs). Notes are plain Markdown, cross-linked with `[[wikilinks]]`,
and every capture is auto-committed and pushed.

```
capture ──▶ classify ──▶ format ──▶ save ──▶ push ──▶ link
           (Gemini →     (6 note      (Markdown  (git)   (wikilinks)
            Groq →        templates)   in devNote)
            keywords)
```

## Install

```bash
pip install -e .          # or: pip install -r requirements.txt
```

Then copy `.env.example` to `.env` and fill in your values:

| Variable | Purpose |
|----------|---------|
| `JARVIS_REPO_PATH` | Absolute path to your `devNote` knowledge repo |
| `GEMINI_API_KEY` | Primary classifier (Gemini 2.0 Flash) |
| `GROQ_API_KEY` | Fallback classifier + DSA/YouTube/article/RSS agents |
| `YOUTUBE_API_KEY` | Richer YouTube metadata (optional; falls back to oEmbed) |
| `DISCORD_BOT_TOKEN` / `DISCORD_GUILD_ID` / `DISCORD_CHANNEL_ID` | Mobile capture via Discord (optional) |

The classifier degrades gracefully: **Gemini → Groq → offline keywords**, so
Jarvis still works with no keys (lower quality classification).

## Commands

### Capture
| Command | Description |
|---------|-------------|
| `jar note "..."` | Capture → classify → format → save → push → link |
| `jar note "..." --source leetcode` | Activate the DSA pipeline |
| `jar note "..." --force` | Overwrite an existing note |
| `jar note "..." --no-push` | Instant capture — commit locally, skip the GitHub push |
| `jar youtube URL` | Capture a YouTube video as a structured note |
| `jar article URL` | Fetch an article (Jina Reader) and save as a note |
| `jar rss` | Fetch dev RSS feeds and save relevant items as notes |
| `jar push` | Push any locally-committed notes to GitHub (after `--no-push`) |

## Talk to your knowledge base (MCP)

The most capable way to use Jarvis is **not the CLI** — register it as an MCP
server and talk to Claude, which can then search, read, write and reason over
your whole vault:

```bash
claude mcp add --transport stdio -s user jarvis -- python -m jarvis.mcp_server
```

Then: *"What do I know about Redis persistence?"* · *"Save this: Postgres MVCC
keeps old row versions for concurrent reads"* · *"Build me a DSA handbook."*

Twelve tools are exposed: `search_notes`, `read_note`, `ask_knowledge_base`,
`find_related`, `capture_note`, `capture_url`, `knowledge_stats`, `list_recent`,
`get_daily_log`, `notes_due_for_review`, `knowledge_health`, `export_document`.

Because the Claude mobile app does speech-to-text, this also gives you voice
capture on your phone for free.

### Voice
| Command | Description |
|---------|-------------|
| `jar listen` | Speak a note — records, transcribes (Groq Whisper), captures |
| `jar listen --ask` | Speak a question, get an answer from your own notes |
| `jar listen --file memo.m4a` | Transcribe a phone voice memo |

### Synthesis — make knowledge compound
| Command | Description |
|---------|-------------|
| `jar wiki` | List note clusters worth synthesizing |
| `jar wiki "redis"` | Merge every scattered Redis note into ONE authoritative page |
| `jar wiki --all` | Synthesize every suggested cluster |

Implements the [LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
raw captures stay immutable, and the AI maintains a separate `wiki/topics/`
layer that gets richer as related notes arrive. On the live repo this merged 13
overlapping Redis notes into one page — and flagged a dead doc link in the
process.

### Recall — get knowledge back out
| Command | Description |
|---------|-------------|
| `jar search "term"` | Instant offline full-text search across note contents, ranked with snippets |
| `jar ask "question"` | Answer synthesized from your own notes, with cited sources (Gemini→Groq; degrades to search offline) |
| `jar open "term"` | Open the best-matching note in your editor |

### Retention — actually remember what you captured
| Command | Description |
|---------|-------------|
| `jar review` | Spaced-repetition session over notes that are due (1→3→7→16→35→75 day ladder) |
| `jar review --list` | Just show what's due, don't run the session |
| `jar quiz` | Quiz yourself on your own notes; `--domain dsa` to focus. Great before interviews |

### Documentation — turn notes into a document
| Command | Description |
|---------|-------------|
| `jar export --domain databases` | Compile a domain into ONE Markdown handbook with a table of contents |
| `jar export --tag redis --title "Redis Notes"` | Export by tag, type (`--type dsa`), or search (`--query "..."`) |

### Maintenance
| Command | Description |
|---------|-------------|
| `jar doctor` | Health-check the repo: empty notes, broken links, duplicates, stale notes, untracked files. Gives a 0-100 score |
| `jar doctor --details` | List the actual offending files |
| `jar reindex` | Re-add notes that exist on disk but fell out of `index.json` (they're invisible to search until you do) |

`jar note` auto-detects YouTube and article URLs and routes them accordingly.

### Daily logs & reviews
| Command | Description |
|---------|-------------|
| `jar today` | Show today's daily log |
| `jar log [--date YYYY-MM-DD]` | Show a specific daily log |
| `jar finalize` | AI-generate the day's narrative summary |
| `jar weekly` | AI-generate a weekly review from the last 7 logs |
| `jar logs` | List all logs grouped by month |
| `jar schedule [--rss]` | Set up Windows midnight finalize (and optional daily RSS) |

### Knowledge base
| Command | Description |
|---------|-------------|
| `jar status` | Repo stats and git info |
| `jar inbox` | Show pending notes |
| `jar process` | Manually process the inbox |
| `jar dsa [--pattern X]` | DSA notes grouped by pattern |
| `jar lc NUMBER` | Preview a LeetCode problem |
| `jar link [--domain X]` | Run the cross-linker over notes |
| `jar graph "term"` | Show related notes with match scores |
| `jar cleanup` | Reclassify unsorted notes |
| `jar index-clean` | Remove stale index.json entries |
| `jar index-clean --fix-domains` | Also repair domains containing leaked AI prompt text |
| `jar sync` | Manual git push |

### Web dashboard & bookmarklet
| Command | Description |
|---------|-------------|
| `jar serve [--host H] [--port P]` | Start the local dashboard + capture API (default `127.0.0.1:7823`) |
| `jar discord` | Start the Discord bot for mobile capture |

Open `http://localhost:7823/dashboard`, then **drag the “⚡ Save to Jarvis”
button to your bookmarks bar**. Click it on any web page or YouTube video to
capture straight into Jarvis — works in Zen, Firefox, Chrome, and mobile.

Use `jar serve --host 0.0.0.0` to reach the dashboard/bookmarklet from your
phone on the same network.

#### API endpoints
| Method | Path | Body | Purpose |
|--------|------|------|---------|
| GET | `/health` | — | Liveness + repo/version |
| GET | `/status` | — | `total_notes`, `today` |
| GET | `/api/stats` | — | Full dashboard stats (JSON) |
| GET | `/dashboard` | — | Dark-themed HTML dashboard |
| POST | `/capture/note` | `{text, source?, url?}` | Capture a quick note |
| POST | `/capture/article` | `{url, note?}` | Capture an article |
| POST | `/capture/youtube` | `{url, note?}` | Capture a YouTube video |

## Package layout (`jarvis/`)

| Module | Responsibility |
|--------|----------------|
| `config.py` | Paths + API keys from `.env` |
| `capture.py` | Write raw capture JSON to the inbox |
| `classifier.py` | 3-tier classifier: Gemini → Groq → keywords |
| `formatter.py` | 6 note templates (concept, dsa, bug, snippet, video, article) |
| `orchestrator.py` | Parallel processing engine (single source of truth for daily-log writes) |
| `processor.py` | Thin delegate to the orchestrator |
| `dsa_agent.py` / `leetcode_fetcher.py` | DSA specialist + LeetCode GraphQL data |
| `youtube_agent.py` / `article_fetcher.py` | Content capture agents |
| `rss_processor.py` | RSS feed processor (stdlib parser, Groq/keyword filter) |
| `index_store.py` | Single source of truth for `index.json` — upsert-by-file so re-captures never duplicate rows |
| `retrieval.py` | Full-text search + AI answers over your own notes (`jar search` / `jar ask`) |
| `health.py` | Repo health checks + `reindex` recovery of unindexed notes |
| `review.py` | Spaced repetition + quiz generation |
| `exporter.py` | Compiles notes into a single shareable document |
| `daily_log.py` | Daily journal + AI summaries |
| `linker.py` | `[[wikilink]]` cross-linker |
| `git_sync.py` | Stage / commit / push |
| `scheduler.py` / `tasks.py` | Windows Task Scheduler jobs (finalize, rss) |
| `api_server.py` | FastAPI dashboard + capture API + bookmarklet |
| `index_cleaner.py` | Prune stale `index.json` entries |
| `cli.py` | All `jar` commands |

## Tests

```bash
pip install pytest
pytest
```

192 tests cover every module. The suite is **fully sandboxed**: `tests/conftest.py`
points `JARVIS_REPO_PATH` at a throwaway temp git repo *before* any jarvis module
is imported, so the complete pipeline (capture → classify → format → save → index
→ daily log → git commit) runs end to end without ever touching your real devNote
repo or pushing to GitHub. AI calls are stubbed, so the suite is deterministic and
runs offline in ~25s.

## Notes
- Everything is local-first; the only outbound traffic is your own GitHub
  pushes and the free AI/feed APIs.
- `00-meta/index.json` in the knowledge repo tracks every note ever saved.
