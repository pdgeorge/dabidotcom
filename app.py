import os
import re
import sqlite3
from datetime import datetime
from typing import Optional
from enum import Enum
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import markdown as md
import bleach
from bleach.css_sanitizer import CSSSanitizer

# --------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------
API_KEY = os.getenv("PAGES_API_KEY", "abc123")
DB_PATH = os.getenv("DB_PATH", "pages.db")
SITE_NAME = os.getenv("SITE_NAME", "Dabby")
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = Path(os.getenv("STATIC_DIR", str(BASE_DIR / "static")))

# --------------------------------------------------------------------
# Markdown Sanitization (used only in markdown mode)
# --------------------------------------------------------------------
ALLOWED_TAGS = bleach.sanitizer.ALLOWED_TAGS.union({
    "div","span","p","pre","code","h1","h2","h3","h4","h5","h6",
    "ul","ol","li","blockquote","hr","br","strong","em","a","img",
    "table","thead","tbody","tr","th","td"
})

ALLOWED_ATTRS = {
    "a": ["href","title","rel","target"],
    "img": ["src","alt","title"],
    "*": ["style"]
}

css_sanitizer = CSSSanitizer(
    allowed_css_properties=[
        "background","background-color","color","padding","margin",
        "border","border-radius","text-align","font-weight","font-style",
        "height","width","min-height"
    ]
)

def render_markdown(markdown_text: str) -> str:
    raw_html = md.markdown(markdown_text, extensions=["fenced_code", "tables"])
    clean_html = bleach.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        css_sanitizer=css_sanitizer,
        strip=True
    )
    return clean_html

# --------------------------------------------------------------------
# FastAPI + Database setup
# --------------------------------------------------------------------
app = FastAPI()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY,
        slug TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        markdown TEXT NOT NULL,
        html TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        mode TEXT DEFAULT 'markdown'
    )
    """)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(pages)")}
    if "mode" not in cols:
        conn.execute("ALTER TABLE pages ADD COLUMN mode TEXT DEFAULT 'markdown'")
    conn.commit()
    conn.close()

init_db()

# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def valid_slug(s: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9-]{1,80}", s))

def static_conflict(slug: str) -> bool:
    base = STATIC_DIR / "dabi" / slug
    return any([
        base.with_suffix(".html").is_file(),
        (base / "index.html").is_file(),
        base.is_file(),
    ])

def require_api_key(request: Request):
    key = request.headers.get("X-API-Key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

# --------------------------------------------------------------------
# Data Models
# --------------------------------------------------------------------
class ContentMode(str, Enum):
    markdown = "markdown"
    html = "html"

class CreatePage(BaseModel):
    slug: str = Field(..., description="URL slug like 'first-page'")
    title: Optional[str] = None
    markdown: Optional[str] = None
    html: Optional[str] = None
    mode: ContentMode = ContentMode.markdown

class UpdatePage(BaseModel):
    title: Optional[str] = None
    markdown: Optional[str] = None
    html: Optional[str] = None
    mode: Optional[ContentMode] = None

# --------------------------------------------------------------------
# API Endpoints
# --------------------------------------------------------------------
@app.post("/api/pages")
def create_page(payload: CreatePage, _: None = Depends(require_api_key)):
    if not valid_slug(payload.slug):
        raise HTTPException(400, "Slug must be [a-z0-9-], 1..80 chars")
    if static_conflict(payload.slug):
        raise HTTPException(409, "Slug conflicts with a static page")

    now = datetime.utcnow().isoformat()

    if payload.mode == ContentMode.html:
        if not payload.html:
            raise HTTPException(400, "html required when mode=html")
        html = payload.html
        title = payload.title or SITE_NAME
        markdown_src = payload.html
        mode_str = "html"
    else:
        if not payload.markdown:
            raise HTTPException(400, "markdown required when mode=markdown")
        html = render_markdown(payload.markdown)
        title = payload.title or "Untitled"
        markdown_src = payload.markdown
        mode_str = "markdown"

    conn = db()
    try:
        conn.execute(
            "INSERT INTO pages (slug,title,markdown,html,created_at,updated_at,mode) VALUES (?,?,?,?,?,?,?)",
            (payload.slug, title, markdown_src, html, now, now, mode_str),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Slug already exists")
    finally:
        conn.close()

    return {"ok": True, "slug": payload.slug}

@app.put("/api/pages/{slug}")
def update_page(slug: str, payload: UpdatePage, _: None = Depends(require_api_key)):
    if not valid_slug(slug):
        raise HTTPException(400, "Bad slug")

    conn = db()
    row = conn.execute("SELECT * FROM pages WHERE slug=?", (slug,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Not found")

    mode_cur = row["mode"]
    mode_new = payload.mode.value if payload.mode else mode_cur

    if mode_new == "html":
        new_html = payload.html if payload.html is not None else row["html"]
        if not new_html:
            conn.close()
            raise HTTPException(400, "html required when mode=html")
        new_title = payload.title or row["title"]
        new_md = new_html
    else:
        new_md = payload.markdown if payload.markdown is not None else row["markdown"]
        if not new_md:
            conn.close()
            raise HTTPException(400, "markdown required when mode=markdown")
        new_html = render_markdown(new_md)
        new_title = payload.title or row["title"]

    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE pages SET title=?, markdown=?, html=?, updated_at=?, mode=? WHERE slug=?",
        (new_title, new_md, new_html, now, mode_new, slug),
    )
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/pages/{slug}")
def delete_page(slug: str, _: None = Depends(require_api_key)):
    if not valid_slug(slug):
        raise HTTPException(400, "Bad slug")

    conn = db()
    cur = conn.execute("DELETE FROM pages WHERE slug=?", (slug,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()

    if deleted == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True, "deleted": slug}

@app.get("/api/pages")
def list_pages(limit: int = 50, offset: int = 0):
    conn = db()
    cur = conn.execute(
        "SELECT slug, title, created_at, updated_at, mode FROM pages ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    items = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"items": items}

# --------------------------------------------------------------------
# HTML Rendering
# --------------------------------------------------------------------
def page_shell(title: str, body_html: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title} · {SITE_NAME}</title>
<link rel="stylesheet" href="/style.css"/>
<body>
<main class="layout">
  <section class="window">
    <div class="window__titlebar">
      <div class="window__title">{title}</div>
      <div class="window__controls" aria-hidden="true">
        <span class="winbtn winbtn--min" title="Minimize"></span>
        <span class="winbtn winbtn--max" title="Maximize"></span>
        <span class="winbtn winbtn--close" title="Close"></span>
      </div>
    </div>
    <div class="window__body">
      {body_html}
    </div>
  </section>
</main>
</body></html>"""

@app.get("/dabi", response_class=HTMLResponse)
def dabi_index():
    conn = db()
    cur = conn.execute("SELECT slug, title, created_at FROM pages ORDER BY created_at DESC LIMIT 100")
    rows = cur.fetchall()
    conn.close()

    list_html = "<h1>Dabi Pages</h1><ul>" + "".join(
        f'<li><a class="link" href=\"/dabi/{r["slug"]}\">{r["title"]}</a> <small>({r["slug"]})</small></li>'
        for r in rows
    ) + "</ul>"
    return HTMLResponse(page_shell(f"{SITE_NAME} Dabi Pages", list_html))

@app.get("/dabi/{slug}", response_class=HTMLResponse)
def get_page(slug: str):
    if not valid_slug(slug):
        return PlainTextResponse("Not found", status_code=404)
    conn = db()
    row = conn.execute("SELECT * FROM pages WHERE slug=?", (slug,)).fetchone()
    conn.close()
    if not row:
        return PlainTextResponse("Not found", status_code=404)

    is_html = (row["mode"] == "html")
    html = row["html"]

    full_doc = "<html" in html.lower() or "<!doctype" in html.lower()
    if is_html and full_doc:
        return HTMLResponse(html)

    body = f"<h1>{row['title']}</h1>\n{html}"
    return HTMLResponse(page_shell(row["title"], body))

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
