"""
Jarvis local API server (Task 3.4).

Exposes a small FastAPI app that powers:
  - a dark-themed web dashboard (GET /dashboard)
  - a browser bookmarklet that captures the current page from any browser
  - JSON capture endpoints used by the bookmarklet / mobile / scripts

Run it with:  jar serve   (or: python -m uvicorn jarvis.api_server:app)

Everything is local-first. The capture endpoints reuse the exact same
pipeline as the CLI (classify -> format -> save -> push -> link), so a note
captured from the browser is identical to `jar note`.
"""

import datetime
import html
import json
import threading
from collections import Counter
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from jarvis.config import INDEX_PATH, REPO_PATH

VERSION = "1.0"

app = FastAPI(title="Jarvis Knowledge OS", version=VERSION)

# The bookmarklet runs on arbitrary origins (youtube.com, blog posts, ...) and
# POSTs back to this local server, so cross-origin requests must be allowed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Captures mutate index.json and run git operations. Serialise them so two
# rapid captures (e.g. double bookmarklet click) can't corrupt the index.
_capture_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Data helpers
# --------------------------------------------------------------------------- #
def _load_index():
    try:
        if INDEX_PATH.exists():
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("notes", [])
                data.setdefault("total_notes", len(data["notes"]))
                return data
    except Exception:
        pass
    return {"notes": [], "total_notes": 0}


def _today_iso():
    return datetime.date.today().isoformat()


def compute_stats():
    """Aggregate everything the dashboard needs from index.json."""
    index = _load_index()
    notes = index.get("notes", [])
    today = _today_iso()

    def _count(pred):
        return sum(1 for n in notes if pred(n))

    domain_counts = Counter(
        (n.get("domain") or "unclassified") for n in notes
    )
    domain_breakdown = [
        {"domain": d, "count": c}
        for d, c in sorted(domain_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]

    # Recent = last 10 appended (index appends in capture order).
    recent = list(reversed(notes[-10:]))
    recent_clean = [
        {
            "title": n.get("title", "Untitled"),
            "type": n.get("type", "note"),
            "domain": n.get("domain", ""),
            "date": n.get("date", ""),
            "source": n.get("source", ""),
        }
        for n in recent
    ]

    return {
        "total_notes": len(notes),
        "today": _count(lambda n: n.get("date") == today),
        "dsa": _count(lambda n: n.get("type") == "dsa"),
        "videos": _count(lambda n: n.get("type") == "video-summary"),
        "articles": _count(lambda n: n.get("type") == "article"),
        "domains": domain_breakdown,
        "recent": recent_clean,
    }


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class NoteIn(BaseModel):
    text: str
    source: str = "bookmarklet"
    url: str = ""


class UrlIn(BaseModel):
    url: str
    note: str = ""


# --------------------------------------------------------------------------- #
# JSON / status endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "online", "repo": str(REPO_PATH), "version": VERSION}


@app.get("/status")
def status():
    stats = compute_stats()
    return {
        "total_notes": stats["total_notes"],
        "today": stats["today"],
        "repo": str(REPO_PATH),
        "version": VERSION,
    }


@app.get("/api/stats")
def api_stats():
    return compute_stats()


@app.get("/api/analytics")
def api_analytics(days: int = 30):
    from jarvis.analytics import build_analytics

    return build_analytics(days=days)


@app.get("/api/graph")
def api_graph(domain: str = "", max_nodes: int = 220):
    from jarvis.graph_view import build_graph

    return build_graph(domain=domain or None, max_nodes=max_nodes)


@app.get("/api/search")
def api_search(q: str = "", limit: int = 10):
    from jarvis.retrieval import search_notes

    return {"query": q, "results": search_notes(q, limit=limit)}


class AskIn(BaseModel):
    question: str


@app.post("/api/ask")
def api_ask(body: AskIn):
    question = (body.question or "").strip()
    if not question:
        return JSONResponse({"ok": False, "error": "empty question"}, status_code=400)
    from jarvis.retrieval import ask

    result = ask(question)
    return {"ok": True, **result}


# --------------------------------------------------------------------------- #
# Capture endpoints (reuse the CLI pipeline)
# --------------------------------------------------------------------------- #
@app.post("/capture/note")
def capture_note_endpoint(body: NoteIn):
    text = (body.text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "empty note"}, status_code=400)

    from jarvis.capture import capture_note
    from jarvis.orchestrator import process_inbox_orchestrated

    with _capture_lock:
        try:
            capture_note(text, source=body.source or "bookmarklet", source_url=body.url or "")
            result = process_inbox_orchestrated(force=False)
        except Exception as exc:  # pragma: no cover - defensive
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    ok = result.get("processed", 0) > 0
    title = ""
    for r in reversed(result.get("results", [])):
        if r.get("success") and r.get("classification"):
            title = r["classification"].get("title", "")
            break
    return {"ok": ok, "kind": "note", "title": title or text[:60], "detail": result}


@app.post("/capture/article")
def capture_article_endpoint(body: UrlIn):
    url = (body.url or "").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "missing url"}, status_code=400)

    from jarvis.article_fetcher import process_article_url
    from jarvis.git_sync import sync
    from jarvis.linker import run_linker_for_new_notes

    with _capture_lock:
        try:
            timestamp = datetime.datetime.now().isoformat()
            result = process_article_url(url, body.note or "", timestamp)
            if not result:
                return JSONResponse(
                    {"ok": False, "error": "could not fetch/parse article"},
                    status_code=502,
                )
            sync(f"feat: add article note — {result['title'][:50]} [knowledge-base]")
            _link_latest(run_linker_for_new_notes)
        except Exception as exc:  # pragma: no cover - defensive
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    return {
        "ok": True,
        "kind": "article",
        "title": result["title"],
        "site": result.get("site", ""),
        "saved": f"{result['folder_path']}/{result['filename']}",
    }


@app.post("/capture/youtube")
def capture_youtube_endpoint(body: UrlIn):
    url = (body.url or "").strip()
    if not url:
        return JSONResponse({"ok": False, "error": "missing url"}, status_code=400)

    from jarvis.git_sync import sync
    from jarvis.linker import run_linker_for_new_notes
    from jarvis.youtube_agent import process_youtube_url

    with _capture_lock:
        try:
            timestamp = datetime.datetime.now().isoformat()
            result = process_youtube_url(url, timestamp)
            if not result:
                return JSONResponse(
                    {"ok": False, "error": "could not process video"},
                    status_code=502,
                )
            sync(f"feat: add video-summary — {result['title'][:50]} [creator-content]")
            _link_latest(run_linker_for_new_notes)
        except Exception as exc:  # pragma: no cover - defensive
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    return {
        "ok": True,
        "kind": "youtube",
        "title": result["title"],
        "channel": result.get("channel", ""),
        "saved": f"{result['folder_path']}/{result['filename']}",
    }


def _link_latest(run_linker_for_new_notes):
    """Best-effort auto-link of the most recently indexed note."""
    try:
        index_data = _load_index()
        notes = index_data.get("notes", [])
        if notes:
            run_linker_for_new_notes([notes[-1]])
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Dashboard (HTML)
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    base = str(request.base_url).rstrip("/")
    return HTMLResponse(_render_dashboard(base))


def _build_bookmarklet(api_base):
    """Return the javascript: href for the capture bookmarklet."""
    js = _BOOKMARKLET_JS.replace("__API_BASE__", api_base)
    # Collapse to a single line and URL-encode so it is a valid javascript: URI
    # that survives being dragged into any browser's bookmarks bar.
    return "javascript:" + quote(js, safe="")


def _render_dashboard(base_url):
    stats = compute_stats()

    cards = [
        ("Total Notes", stats["total_notes"], "#00d4ff"),
        ("Today", stats["today"], "#3ddc84"),
        ("DSA", stats["dsa"], "#ffb703"),
        ("Videos", stats["videos"], "#ff6b6b"),
        ("Articles", stats["articles"], "#b388ff"),
    ]
    card_html = "".join(
        f'<div class="card"><div class="card-num" style="color:{color}">{value}</div>'
        f'<div class="card-label">{html.escape(label)}</div></div>'
        for label, value, color in cards
    )

    max_domain = max((d["count"] for d in stats["domains"]), default=1) or 1
    domain_rows = "".join(
        f'<div class="dom-row"><span class="dom-name">{html.escape(d["domain"])}</span>'
        f'<span class="dom-bar-wrap"><span class="dom-bar" style="width:{max(4, int(100 * d["count"] / max_domain))}%"></span></span>'
        f'<span class="dom-count">{d["count"]}</span></div>'
        for d in stats["domains"][:14]
    ) or '<div class="empty">No domains yet.</div>'

    if stats["recent"]:
        recent_rows = "".join(
            f"<tr><td>{html.escape(str(n['date']))}</td>"
            f"<td>{html.escape(n['title'][:60])}</td>"
            f'<td><span class="pill">{html.escape(n["type"])}</span></td>'
            f"<td>{html.escape(n['domain'])}</td></tr>"
            for n in stats["recent"]
        )
    else:
        recent_rows = '<tr><td colspan="4" class="empty">No captures yet — drag the bookmarklet and try it!</td></tr>'

    href = _build_bookmarklet(base_url)

    page = _DASHBOARD_HTML
    page = page.replace("__CARDS__", card_html)
    page = page.replace("__DOMAIN_ROWS__", domain_rows)
    page = page.replace("__RECENT_ROWS__", recent_rows)
    page = page.replace("__BOOKMARKLET_HREF__", html.escape(href, quote=True))
    page = page.replace("__API_BASE__", html.escape(base_url))
    page = page.replace("__REPO__", html.escape(str(REPO_PATH)))
    page = page.replace("__VERSION__", VERSION)
    return page


# --------------------------------------------------------------------------- #
# Server runner
# --------------------------------------------------------------------------- #
def run_server(host="127.0.0.1", port=7823):
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


# --------------------------------------------------------------------------- #
# Bookmarklet source (readable). __API_BASE__ is injected at render time.
# --------------------------------------------------------------------------- #
_BOOKMARKLET_JS = r"""
(function(){
  var API='__API_BASE__';
  var old=document.getElementById('jarvis-capture-overlay');
  if(old){old.remove();}
  var url=window.location.href;
  var title=document.title||url;
  var sel=(window.getSelection?String(window.getSelection()):'')||'';
  var isYT=/(?:youtube\.com\/watch|youtu\.be\/|youtube\.com\/shorts)/.test(url);
  var head=isYT?'\u{1F4FA} YouTube video':'\u{1F4C4} Web page / article';
  var o=document.createElement('div');
  o.id='jarvis-capture-overlay';
  o.style.cssText='position:fixed;top:18px;right:18px;z-index:2147483647;width:340px;background:#0f0f1a;color:#e6e6e6;border:1px solid #00d4ff;border-radius:12px;padding:16px;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;box-shadow:0 10px 44px rgba(0,0,0,.6);font-size:14px;line-height:1.4';
  o.innerHTML=''
    +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
    +'<strong style="color:#00d4ff;letter-spacing:.3px">Jarvis Capture</strong>'
    +'<span id="jv-x" style="cursor:pointer;color:#888;font-size:20px;line-height:1">×</span></div>'
    +'<div style="font-size:12px;color:#9aa2b2;margin-bottom:6px">'+head+'</div>'
    +'<div style="font-size:12px;color:#c8c8d4;margin-bottom:10px;max-height:34px;overflow:hidden">'+title.replace(/[<>]/g,'')+'</div>'
    +'<textarea id="jv-note" placeholder="Add a note or context (optional)" style="width:100%;box-sizing:border-box;height:70px;background:#161627;color:#e6e6e6;border:1px solid #2a2a40;border-radius:8px;padding:8px;resize:vertical;font-family:inherit;font-size:13px"></textarea>'
    +'<label style="display:flex;align-items:center;gap:6px;font-size:12px;color:#9aa2b2;margin:8px 0"><input type="checkbox" id="jv-asnote">Save my note as a standalone note (ignore the page)</label>'
    +'<div id="jv-msg" style="min-height:18px;font-size:12px;margin:4px 0 8px"></div>'
    +'<div style="display:flex;gap:8px">'
    +'<button id="jv-save" style="flex:1;background:#00d4ff;color:#001018;border:none;border-radius:8px;padding:10px;font-weight:600;cursor:pointer">Save to Jarvis</button>'
    +'<button id="jv-cancel" style="background:#1c1c2e;color:#ccc;border:1px solid #2a2a40;border-radius:8px;padding:10px 12px;cursor:pointer">Cancel</button></div>';
  document.body.appendChild(o);
  var ta=document.getElementById('jv-note');
  if(sel){ta.value=sel;}
  ta.focus();
  function close(){o.remove();}
  function msg(t,c){var m=document.getElementById('jv-msg');m.textContent=t;m.style.color=c;}
  document.getElementById('jv-x').onclick=close;
  document.getElementById('jv-cancel').onclick=close;
  document.getElementById('jv-save').onclick=function(){
    var note=ta.value||'';
    var asNote=document.getElementById('jv-asnote').checked;
    var ep,payload;
    if(asNote){
      if(!note.trim()){msg('⚠ Note is empty.','#ff6b6b');return;}
      ep='/capture/note';payload={text:note,source:'bookmarklet',url:url};
    }else if(isYT){
      ep='/capture/youtube';payload={url:url,note:note};
    }else{
      ep='/capture/article';payload={url:url,note:note};
    }
    msg('Saving… (this can take a few seconds)','#00d4ff');
    fetch(API+ep,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
      .then(function(r){return r.json();})
      .then(function(d){
        if(d&&d.ok){msg('✓ Saved: '+((d.title||'note').slice(0,40)),'#3ddc84');setTimeout(close,2000);}
        else{msg('⚠ '+((d&&d.error)||'Save failed'),'#ff6b6b');}
      })
      .catch(function(){msg('⚠ Cannot reach Jarvis. Is `jar serve` running?','#ff6b6b');});
  };
})();
"""


# --------------------------------------------------------------------------- #
# Dashboard HTML template (tokens replaced at render time).
# --------------------------------------------------------------------------- #
_DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jarvis — Knowledge OS</title>
<style>
  :root{--bg:#0f0f1a;--panel:#161627;--panel2:#1c1c2e;--border:#2a2a40;--accent:#00d4ff;--text:#e6e6e6;--muted:#9aa2b2;}
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(1200px 600px at 80% -10%,#15213a 0%,var(--bg) 55%);color:var(--text);font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1040px;margin:0 auto;padding:28px 20px 60px}
  header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:24px;flex-wrap:wrap}
  .brand{display:flex;align-items:center;gap:12px}
  .logo{width:40px;height:40px;border-radius:10px;background:linear-gradient(135deg,var(--accent),#7a5cff);display:flex;align-items:center;justify-content:center;font-weight:800;color:#001018;font-size:20px}
  h1{font-size:20px;margin:0;letter-spacing:.3px}
  .sub{color:var(--muted);font-size:12px;margin-top:2px}
  .btn{background:var(--panel2);border:1px solid var(--border);color:var(--text);border-radius:8px;padding:8px 14px;cursor:pointer;text-decoration:none;font-size:13px}
  .btn:hover{border-color:var(--accent)}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:26px}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:18px}
  .card-num{font-size:34px;font-weight:800;line-height:1}
  .card-label{color:var(--muted);font-size:12px;margin-top:8px;text-transform:uppercase;letter-spacing:.6px}
  .grid{display:grid;grid-template-columns:1fr 1.3fr;gap:20px}
  @media(max-width:820px){.grid{grid-template-columns:1fr}}
  .panel{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:18px}
  .panel h2{font-size:14px;margin:0 0 14px;color:var(--accent);text-transform:uppercase;letter-spacing:.6px}
  .dom-row{display:flex;align-items:center;gap:10px;margin:8px 0;font-size:13px}
  .dom-name{width:130px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .dom-bar-wrap{flex:1;height:8px;background:var(--panel2);border-radius:6px;overflow:hidden}
  .dom-bar{display:block;height:100%;background:linear-gradient(90deg,var(--accent),#7a5cff)}
  .dom-count{width:34px;text-align:right;color:var(--muted)}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:8px 8px;border-bottom:1px solid var(--border);vertical-align:top}
  th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
  .pill{background:var(--panel2);border:1px solid var(--border);border-radius:20px;padding:2px 9px;font-size:11px;color:var(--accent)}
  .empty{color:var(--muted);font-style:italic;padding:10px 0}
  .bm{margin-top:24px;background:linear-gradient(135deg,#141428,#181832);border:1px solid var(--border);border-radius:14px;padding:22px}
  .bm h2{color:var(--accent);margin-top:0}
  .bm-drag{display:inline-block;background:var(--accent);color:#001018;font-weight:700;padding:11px 20px;border-radius:10px;text-decoration:none;cursor:grab;box-shadow:0 4px 18px rgba(0,212,255,.35)}
  .bm-drag:active{cursor:grabbing}
  ol{color:var(--muted);font-size:13px;line-height:1.7;padding-left:20px}
  ol b{color:var(--text)}
  code{background:var(--panel2);border:1px solid var(--border);border-radius:5px;padding:1px 6px;color:var(--accent);font-size:12px}
  footer{margin-top:34px;color:var(--muted);font-size:12px;text-align:center}
  a{color:var(--accent)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <div class="logo">J</div>
      <div>
        <h1>Jarvis — Knowledge OS</h1>
        <div class="sub">__REPO__ · v__VERSION__</div>
      </div>
    </div>
    <a class="btn" href="/dashboard">↻ Refresh</a>
  </header>

  <div class="panel" style="margin-bottom:22px">
    <h2>🔎 Search your notes</h2>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <input id="q" type="search" placeholder="e.g. redis persistence, sliding window…"
             style="flex:1;min-width:220px;background:var(--panel2);border:1px solid var(--border);
                    color:var(--text);border-radius:8px;padding:10px 12px;font-size:14px">
      <button id="go" class="btn" style="background:var(--accent);color:#001018;border:none;font-weight:600">Search</button>
      <button id="askbtn" class="btn">Ask AI</button>
    </div>
    <div id="results" style="margin-top:14px"></div>
  </div>

  <div class="panel" style="margin-bottom:22px">
    <h2>📈 Learning Activity</h2>
    <div id="kpis" style="display:flex;gap:26px;flex-wrap:wrap;margin-bottom:16px"></div>
    <div style="color:var(--muted);font-size:12px;margin-bottom:4px">
      Notes captured per day &middot; last 30 days
    </div>
    <div id="timeline" style="position:relative;height:132px"></div>
    <div class="grid" style="margin-top:18px">
      <div>
        <div style="color:var(--muted);font-size:12px;margin-bottom:6px">Notes by domain</div>
        <div id="dombars"></div>
      </div>
      <div>
        <div style="color:var(--muted);font-size:12px;margin-bottom:6px">
          DSA pattern coverage <span id="patcov"></span>
        </div>
        <div id="patbars"></div>
      </div>
    </div>
  </div>

  <div class="panel" style="margin-bottom:22px">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
      <h2 style="margin:0">🕸 Knowledge Graph</h2>
      <div style="display:flex;gap:8px;align-items:center">
        <span id="gstat" style="color:var(--muted);font-size:12px"></span>
        <button id="greload" class="btn" style="padding:5px 10px;font-size:12px">Reload</button>
      </div>
    </div>
    <div id="glegend" style="display:flex;flex-wrap:wrap;gap:10px;margin:10px 0 6px"></div>
    <canvas id="graph" style="width:100%;height:420px;display:block;
            background:var(--panel2);border:1px solid var(--border);border-radius:10px;cursor:grab"></canvas>
    <div style="color:var(--muted);font-size:12px;margin-top:6px">
      Drag to pan · scroll to zoom · hover a node for its title · click to search it
    </div>
  </div>

  <div class="cards">__CARDS__</div>

  <div class="grid">
    <div class="panel">
      <h2>Domain Breakdown</h2>
      __DOMAIN_ROWS__
    </div>
    <div class="panel">
      <h2>Recent Captures</h2>
      <table>
        <thead><tr><th>Date</th><th>Title</th><th>Type</th><th>Domain</th></tr></thead>
        <tbody>__RECENT_ROWS__</tbody>
      </table>
    </div>
  </div>

  <div class="bm">
    <h2>📌 Capture Bookmarklet</h2>
    <p style="color:var(--muted);font-size:13px;margin-top:0">
      Drag this button to your bookmarks bar. Click it on <b>any</b> web page or
      YouTube video to save it straight into Jarvis — works in Zen, Firefox, Chrome, or mobile.
    </p>
    <p><a class="bm-drag" href="__BOOKMARKLET_HREF__" onclick="return false;">⚡ Save to Jarvis</a></p>
    <ol>
      <li>Make sure <code>jar serve</code> is running (this page proves it is).</li>
      <li>Show your browser's bookmarks bar (<b>Ctrl/Cmd + Shift + B</b>).</li>
      <li><b>Drag</b> the “⚡ Save to Jarvis” button up onto the bookmarks bar.</li>
      <li>On any page, click the bookmark → a dialog appears → add a note → <b>Save</b>.</li>
      <li>YouTube pages are auto-detected and saved as video summaries.</li>
    </ol>
    <p style="color:var(--muted);font-size:12px">
      API base: <code>__API_BASE__</code> ·
      Endpoints: <code>/capture/note</code> <code>/capture/article</code> <code>/capture/youtube</code>
    </p>
  </div>

  <footer>Jarvis Knowledge OS · dashboard served locally · nothing leaves your machine except your own GitHub pushes.</footer>
</div>
<script>
(function(){
  var q=document.getElementById('q'), out=document.getElementById('results');
  function esc(s){return String(s||'').replace(/[<>&]/g,function(c){return {'<':'&lt;','>':'&gt;','&':'&amp;'}[c];});}
  function render(items){
    if(!items || !items.length){ out.innerHTML='<div class="empty">No matches.</div>'; return; }
    out.innerHTML = items.map(function(r){
      return '<div style="padding:10px 0;border-bottom:1px solid var(--border)">'
        +'<div><b>'+esc(r.title)+'</b> <span class="pill">'+esc(r.domain)+'</span></div>'
        +'<div style="color:var(--muted);font-size:12px;margin-top:3px">'+esc(r.folder_path)+'/'+esc(r.filename)+'</div>'
        +'<div style="color:#c8c8d4;font-size:13px;margin-top:5px">'+esc(r.snippet)+'</div></div>';
    }).join('');
  }
  function search(){
    var v=q.value.trim(); if(!v){return;}
    out.innerHTML='<div class="empty">Searching…</div>';
    fetch('/api/search?q='+encodeURIComponent(v))
      .then(function(r){return r.json();})
      .then(function(d){render(d.results);})
      .catch(function(){out.innerHTML='<div class="empty">Search failed.</div>';});
  }
  function ask(){
    var v=q.value.trim(); if(!v){return;}
    out.innerHTML='<div class="empty">Thinking…</div>';
    fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},
                      body:JSON.stringify({question:v})})
      .then(function(r){return r.json();})
      .then(function(d){
        var src=(d.sources||[]).map(function(s){return esc(s.title);}).join(', ');
        out.innerHTML='<div style="background:var(--panel2);border:1px solid var(--border);'
          +'border-radius:10px;padding:14px;white-space:pre-wrap;font-size:14px">'+esc(d.answer)+'</div>'
          +(src?'<div style="color:var(--muted);font-size:12px;margin-top:8px">Sources: '+src+'</div>':'');
      })
      .catch(function(){out.innerHTML='<div class="empty">Ask failed.</div>';});
  }
  document.getElementById('go').onclick=search;
  document.getElementById('askbtn').onclick=ask;
  q.addEventListener('keydown',function(e){if(e.key==='Enter'){search();}});
  window.__jarvisSearch=function(v){q.value=v;search();};
})();

/* ---- Learning analytics -------------------------------------------------
   Every series here is single-series magnitude, so one hue (no categorical
   palette) and no legend — the section labels say what is plotted.
   Mark specs: bars capped at 24px with a 4px rounded data-end square at the
   baseline, 2px surface gaps between neighbours, hairline recessive gridlines,
   values in text tokens (never the data colour), hover tooltips throughout. */
(function(){
  var SERIES='#00d4ff', MUTED='#9aa2b2', GAP=2, MAXBAR=24;
  function esc(s){return String(s==null?'':s).replace(/[<>&]/g,function(c){
    return {'<':'&lt;','>':'&gt;','&':'&amp;'}[c];});}

  function tip(host){
    var el=document.createElement('div');
    el.style.cssText='position:absolute;pointer-events:none;opacity:0;transition:opacity .12s;'
      +'background:#0a0a14;color:#e6e6e6;border:1px solid var(--border);border-radius:6px;'
      +'padding:5px 9px;font-size:12px;white-space:nowrap;z-index:5';
    host.appendChild(el);
    return {
      show:function(html,x,y){el.innerHTML=html;el.style.opacity='1';
        el.style.left=Math.max(0,x-el.offsetWidth/2)+'px';el.style.top=(y-34)+'px';},
      hide:function(){el.style.opacity='0';}
    };
  }

  function timeline(host,rows){
    host.innerHTML='';
    var H=132, PAD_B=18, PAD_T=8, plot=H-PAD_B-PAD_T;
    var max=Math.max.apply(null,rows.map(function(r){return r.count;}).concat([1]));
    var t=tip(host);
    var wrap=document.createElement('div');
    wrap.style.cssText='display:flex;align-items:flex-end;gap:'+GAP+'px;height:'+H+'px;'
      +'border-bottom:1px solid var(--border);box-sizing:border-box;padding-bottom:'+PAD_B+'px';
    rows.forEach(function(r){
      var h=r.count?Math.max(3,Math.round(r.count/max*plot)):1;
      var b=document.createElement('div');
      b.style.cssText='flex:1;max-width:'+MAXBAR+'px;height:'+h+'px;'
        +'background:'+(r.count?SERIES:'var(--border)')+';'
        +'border-radius:4px 4px 0 0;cursor:default';
      b.addEventListener('mouseenter',function(){
        var rb=b.getBoundingClientRect(), rh=host.getBoundingClientRect();
        t.show('<b>'+r.count+'</b> note'+(r.count===1?'':'s')+' &middot; '+esc(r.label),
               rb.left-rh.left+rb.width/2, rb.top-rh.top);
      });
      b.addEventListener('mouseleave',t.hide);
      wrap.appendChild(b);
    });
    host.appendChild(wrap);
    /* Label only the ends — a date on every bar is unreadable. */
    var ax=document.createElement('div');
    ax.style.cssText='display:flex;justify-content:space-between;color:'+MUTED+';font-size:11px;margin-top:2px';
    ax.innerHTML='<span>'+esc(rows[0]?rows[0].label:'')+'</span>'
                +'<span>'+esc(rows.length?rows[rows.length-1].label:'')+'</span>';
    host.appendChild(ax);
  }

  function hbars(host,rows,unit){
    host.innerHTML='';
    var max=Math.max.apply(null,rows.map(function(r){return r.count;}).concat([1]));
    rows.forEach(function(r){
      var row=document.createElement('div');
      row.style.cssText='display:flex;align-items:center;gap:8px;margin:5px 0;font-size:12px';
      var pct=r.count?Math.max(2,Math.round(r.count/max*100)):0;
      row.innerHTML=
        '<span style="width:112px;color:var(--text);white-space:nowrap;overflow:hidden;'
        +'text-overflow:ellipsis" title="'+esc(r.name)+'">'+esc(r.name)+'</span>'
        +'<span style="flex:1;height:10px;background:var(--panel2);border-radius:3px;overflow:hidden">'
        +'<span style="display:block;height:100%;width:'+pct+'%;'
        +'background:'+(r.count?SERIES:'transparent')+';border-radius:0 4px 4px 0"></span></span>'
        +'<span style="width:26px;text-align:right;color:'+(r.count?'var(--text)':MUTED)+';'
        +'font-variant-numeric:tabular-nums">'+r.count+'</span>';
      row.title=r.name+': '+r.count+' '+(unit||'notes');
      host.appendChild(row);
    });
  }

  function kpis(host,t){
    host.innerHTML='';
    [['Total notes',t.notes],
     ['Day streak',t.streak],
     ['Active days /'+t.window_days,t.active_last_n],
     ['DSA patterns',t.patterns_covered+'/'+t.patterns_total]
    ].forEach(function(p){
      var d=document.createElement('div');
      d.innerHTML='<div style="font-size:26px;font-weight:700;color:var(--text);line-height:1">'
        +p[1]+'</div><div style="color:'+MUTED+';font-size:11px;text-transform:uppercase;'
        +'letter-spacing:.6px;margin-top:5px">'+esc(p[0])+'</div>';
      host.appendChild(d);
    });
  }

  fetch('/api/analytics').then(function(r){return r.json();}).then(function(d){
    kpis(document.getElementById('kpis'),d.totals);
    timeline(document.getElementById('timeline'),d.timeline);
    hbars(document.getElementById('dombars'),d.domains);
    hbars(document.getElementById('patbars'),d.patterns,'problems');
    document.getElementById('patcov').textContent=
      '('+d.totals.patterns_covered+' of '+d.totals.patterns_total+' covered)';
  }).catch(function(){
    document.getElementById('kpis').innerHTML='<span class="empty">Analytics unavailable.</span>';
  });
})();

/* ---- Knowledge graph: force-directed layout on canvas, no libraries ---- */
(function(){
  var cv=document.getElementById('graph'); if(!cv) return;
  var ctx=cv.getContext('2d'), N=[], E=[], raf=null, tick=0;
  var view={x:0,y:0,k:1}, drag=null, hover=null, W=0, H=0;

  function size(){
    /* getBoundingClientRect can be ~0 before layout settles or while the tab
       is hidden, which would render the graph into a 2px canvas. Fall back
       through offsetWidth/parent width and refuse to size below a sane floor. */
    var r=cv.getBoundingClientRect();
    var w=r.width||cv.offsetWidth||(cv.parentElement&&cv.parentElement.clientWidth)||0;
    var h=r.height||cv.offsetHeight||420;
    if(w<50){ return false; }
    var dpr=window.devicePixelRatio||1;
    W=w; H=h;
    cv.width=Math.round(W*dpr); cv.height=Math.round(H*dpr);
    ctx.setTransform(dpr,0,0,dpr,0,0);
    return true;
  }
  function sizeWhenReady(cb){
    /* Retry until the element has real width, then run cb once. */
    if(size()){ cb(); return; }
    var tries=0;
    var iv=setInterval(function(){
      if(size()||++tries>40){ clearInterval(iv); cb(); }
    },100);
  }
  function load(){
    fetch('/api/graph').then(function(r){return r.json();}).then(function(d){
      N=d.nodes.map(function(n){return Object.assign({},n,{
        x:W/2+(Math.random()-0.5)*W*0.7, y:H/2+(Math.random()-0.5)*H*0.7, vx:0, vy:0});});
      E=d.edges;
      document.getElementById('gstat').textContent=d.stats.node_count+' notes · '+d.stats.edge_count+' links';
      document.getElementById('glegend').innerHTML=d.domains.map(function(x){
        return '<span style="font-size:11px;color:var(--muted)">'
          +'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;'
          +'background:'+x.colour+';margin-right:4px"></span>'+x.domain+'</span>';}).join('');
      tick=0; if(raf) cancelAnimationFrame(raf); step();
    }).catch(function(){document.getElementById('gstat').textContent='graph unavailable';});
  }
  function step(){
    /* Simple Fruchterman-Reingold-ish relaxation; cools down and stops. */
    var k=Math.sqrt((W*H)/Math.max(N.length,1))*0.55;
    for(var i=0;i<N.length;i++){
      var a=N[i];
      for(var j=i+1;j<N.length;j++){
        var b=N[j], dx=a.x-b.x, dy=a.y-b.y, d2=dx*dx+dy*dy||0.01, d=Math.sqrt(d2);
        if(d>260) continue;
        var rep=(k*k)/d2*0.9;
        var ux=dx/d*rep, uy=dy/d*rep;
        a.vx+=ux; a.vy+=uy; b.vx-=ux; b.vy-=uy;
      }
    }
    for(var e=0;e<E.length;e++){
      var s=N[E[e].source], t=N[E[e].target]; if(!s||!t) continue;
      var dx=t.x-s.x, dy=t.y-s.y, d=Math.sqrt(dx*dx+dy*dy)||0.01;
      var att=(d*d)/k*0.0012*(E[e].weight||1);
      var ux=dx/d*att, uy=dy/d*att;
      s.vx+=ux; s.vy+=uy; t.vx-=ux; t.vy-=uy;
    }
    var damp=0.82, cx=W/2, cy=H/2;
    for(var n=0;n<N.length;n++){
      var p=N[n];
      p.vx+=(cx-p.x)*0.0016; p.vy+=(cy-p.y)*0.0016;   /* gentle centring */
      p.x+=Math.max(-18,Math.min(18,p.vx)); p.y+=Math.max(-18,Math.min(18,p.vy));
      p.vx*=damp; p.vy*=damp;
    }
    draw(); tick++;
    if(tick<300) raf=requestAnimationFrame(step);
  }
  function draw(){
    ctx.clearRect(0,0,W,H); ctx.save();
    ctx.translate(view.x,view.y); ctx.scale(view.k,view.k);
    ctx.strokeStyle='rgba(140,150,180,0.22)';
    for(var e=0;e<E.length;e++){
      var s=N[E[e].source], t=N[E[e].target]; if(!s||!t) continue;
      ctx.lineWidth=Math.min(2,0.4+(E[e].weight||1)*0.14);
      ctx.beginPath(); ctx.moveTo(s.x,s.y); ctx.lineTo(t.x,t.y); ctx.stroke();
    }
    for(var i=0;i<N.length;i++){
      var p=N[i], r=4+Math.min(p.degree,8)*1.3;
      ctx.beginPath(); ctx.arc(p.x,p.y,r,0,6.284);
      ctx.fillStyle=p.colour; ctx.globalAlpha=(hover&&hover!==p)?0.45:1;
      ctx.fill(); ctx.globalAlpha=1;
      if(hover===p){ ctx.strokeStyle='#fff'; ctx.lineWidth=1.5; ctx.stroke(); }
    }
    if(hover){
      var label=hover.title.slice(0,52), pad=6;
      ctx.font='12px -apple-system,Segoe UI,Roboto,Arial';
      var w=ctx.measureText(label).width;
      ctx.fillStyle='rgba(10,10,20,0.92)';
      ctx.fillRect(hover.x+10,hover.y-22,w+pad*2,20);
      ctx.fillStyle='#e6e6e6'; ctx.fillText(label,hover.x+10+pad,hover.y-8);
    }
    ctx.restore();
  }
  function at(mx,my){
    var x=(mx-view.x)/view.k, y=(my-view.y)/view.k, best=null, bd=1e9;
    for(var i=0;i<N.length;i++){
      var p=N[i], dx=p.x-x, dy=p.y-y, d=dx*dx+dy*dy;
      if(d<bd && d<400){ bd=d; best=p; }
    }
    return best;
  }
  cv.addEventListener('mousedown',function(ev){drag={x:ev.offsetX-view.x,y:ev.offsetY-view.y};cv.style.cursor='grabbing';});
  window.addEventListener('mouseup',function(){drag=null;cv.style.cursor='grab';});
  cv.addEventListener('mousemove',function(ev){
    if(drag){ view.x=ev.offsetX-drag.x; view.y=ev.offsetY-drag.y; draw(); return; }
    var h=at(ev.offsetX,ev.offsetY);
    if(h!==hover){ hover=h; draw(); }
  });
  cv.addEventListener('click',function(ev){
    var h=at(ev.offsetX,ev.offsetY);
    if(h && window.__jarvisSearch){ window.__jarvisSearch(h.title); }
  });
  cv.addEventListener('wheel',function(ev){
    ev.preventDefault();
    var f=ev.deltaY<0?1.12:0.89, mx=ev.offsetX, my=ev.offsetY;
    view.x=mx-(mx-view.x)*f; view.y=my-(my-view.y)*f; view.k*=f; draw();
  },{passive:false});
  document.getElementById('greload').onclick=function(){sizeWhenReady(load);};
  window.addEventListener('resize',function(){if(size())draw();});
  /* Re-lay out if the pane/tab becomes visible after first paint. */
  if(window.ResizeObserver){
    var seenWidth=0;
    new ResizeObserver(function(){
      var w=cv.getBoundingClientRect().width;
      if(w>50 && Math.abs(w-seenWidth)>20){ seenWidth=w; if(size()){ tick=0; step(); } }
    }).observe(cv);
  }
  sizeWhenReady(load);
})();
</script>
</body>
</html>
"""
