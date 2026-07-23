"""Wandmeesters local Flask dev server.

Mirrors the production /api/index.py routes plus the full CMS design-spec
routes for local development without Vercel KV / Blob.

KV is emulated by JSON files under admin/data/kv/. Blob storage is emulated
by writing files under admin/data/blob/.

Run:    python3 server.py
Login:  http://localhost:8080/inloggen  (admin / admin)
"""
from __future__ import annotations
import os
import re
import io
import csv
import json
import time
import uuid
import shutil
import secrets
import smtplib
import ssl
import mimetypes
import threading
import urllib.request
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime

from flask import (
    Flask, request, session, redirect, url_for, jsonify, send_from_directory,
    abort, render_template_string, Response, send_file,
)

# ============================================================================
# Paths & configuration
# ============================================================================
ROOT = Path(__file__).resolve().parent
ADMIN_DIR = ROOT / "admin"
DATA_DIR = ROOT / "admin" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

KV_DIR = DATA_DIR / "kv"
KV_DIR.mkdir(parents=True, exist_ok=True)
BLOB_DIR = DATA_DIR / "blob"
BLOB_DIR.mkdir(parents=True, exist_ok=True)

LEADS_FILE = DATA_DIR / "leads.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
TEMPLATES_FILE = DATA_DIR / "templates.json"
PAGES_INDEX_FILE = DATA_DIR / "pages-index.json"

USERS = {"admin": os.environ.get("ADMIN_PASSWORD", "admin")}
SECRET = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

PIPELINE_STAGES = [
    {"id": "ontvangen", "label": "Offerte ontvangen", "color": "#0a5cad"},
    {"id": "contact",   "label": "Contact aanvraag",  "color": "#1d4ed8"},
    {"id": "gebeld",    "label": "Gebeld",            "color": "#7c3aed"},
    {"id": "ingepland", "label": "Ingepland",         "color": "#d97706"},
    {"id": "closed",    "label": "Closed",            "color": "#059669"},
    {"id": "lost",      "label": "Lost",              "color": "#6b7280"},
]
STAGE_IDS = [s["id"] for s in PIPELINE_STAGES]

DEFAULT_SETTINGS = {
    "smtp": {
        "host":       "smtp.strato.com",
        "port":       587,
        "user":       "email@mhsmedia.email",
        "password":   "",
        "from_email": "email@mhsmedia.email",
        "from_name":  "Wandmeesters",
        "use_tls":    True,
    },
    "company_email":    "info@wandmeesters.nl",
    "company_bcc":      "marjolein@mhsmedia.nl, julian@mhsmedia.nl",
    "company_reply_to": "[field id=\"field_574f21f\"]",
    "template_company": {
        "subject":      "Nieuwe offerte aanvraag van [field id=\"name\"]",
        "body":         "[all-fields]",
        "content_type": "html",
    },
    "customer_to":       "[field id=\"field_574f21f\"]",
    "customer_bcc":      "marjolein@mhsmedia.nl",
    "customer_reply_to": "info@wandmeesters.nl",
    "template_customer": {
        "subject":      "We hebben je offerte aanvraag ontvangen!",
        "body":         "Hoi [field id=\"name\"],<br><br>We hebben uw aanvraag ontvangen.",
        "content_type": "html",
    },
    "brand": {
        "logo_url": "/wp-content/uploads/logo.png",
        "primary":  "#0a5cad",
        "accent":   "#347677",
        "font":     "Poppins",
    },
    "ai": {
        "provider":   "anthropic",
        "api_key":    "",
        "model":      "claude-sonnet-4-5",
        "max_tokens": 4096,
    },
    "locale_default": "nl",
    "integrations": {
        "blob_token_ok": False,
        "kv_ok":         True,
        "gsc_property":  None,
        "ga_property_id": None,
    },
}

FIELD_LABELS = {
    "name":         "Naam",
    "email":        "E-mailadres",
    "telefoon":     "Telefoonnummer",
    "woonplaats":   "Woonplaats",
    "soort_woning": "Soort woning",
    "m2":           "M² van de woning",
    "pakket":       "Gewenste pakket",
    "startdatum":   "Gewenste startdatum",
}

FIELD_ID_ALIASES = {
    "field_ac897d8":  "soort_woning",
    "field_3028dcc":  "m2",
    "field_bd15801":  "pakket",
    "field_6b35b98":  "startdatum",
    "field_45bf4d6":  "woonplaats",
    "field_574f21f":  "email",
    "email":          "telefoon",
    "name":           "name",
    "Naam":           "name",
    "E-mail":         "email",
    "Telefoonnummer": "telefoon",
}

BLOCK_LIBRARY = [
    {"type": "heading-h1",      "label": "Heading H1",       "icon": "H1", "default_props": {"text": "Titel"}, "schema": {"text": "string"}},
    {"type": "heading-h2",      "label": "Heading H2",       "icon": "H2", "default_props": {"text": "Subtitel"}, "schema": {"text": "string"}},
    {"type": "heading-h3",      "label": "Heading H3",       "icon": "H3", "default_props": {"text": "Sectie"}, "schema": {"text": "string"}},
    {"type": "heading-h4",      "label": "Heading H4",       "icon": "H4", "default_props": {"text": "Onderkop"}, "schema": {"text": "string"}},
    {"type": "paragraph",       "label": "Paragraaf",        "icon": "¶",  "default_props": {"text": ""}, "schema": {"text": "string"}},
    {"type": "rich-text",       "label": "Rich text",        "icon": "T",  "default_props": {"html": ""}, "schema": {"html": "string"}},
    {"type": "image",           "label": "Afbeelding",       "icon": "🖼",  "default_props": {"media_id": "", "alt": "", "caption": ""}, "schema": {"media_id": "string"}},
    {"type": "image-gallery",   "label": "Galerij",          "icon": "🖼🖼", "default_props": {"media_ids": []}, "schema": {"media_ids": "array"}},
    {"type": "button",          "label": "Knop",             "icon": "▭",  "default_props": {"label": "Klik hier", "url": "/contact/", "style": "primary"}, "schema": {}},
    {"type": "button-group",    "label": "Knop-groep",       "icon": "▭▭", "default_props": {"buttons": []}, "schema": {}},
    {"type": "link",            "label": "Link",             "icon": "🔗",  "default_props": {"label": "", "url": ""}, "schema": {}},
    {"type": "list-ul",         "label": "Lijst (bullets)",  "icon": "•",  "default_props": {"items": []}, "schema": {}},
    {"type": "list-ol",         "label": "Lijst (nummer)",   "icon": "1.", "default_props": {"items": []}, "schema": {}},
    {"type": "hr",              "label": "Scheidslijn",      "icon": "—",  "default_props": {}, "schema": {}},
    {"type": "spacer",          "label": "Witregel",         "icon": "↕",  "default_props": {"height_px": 24}, "schema": {}},
    {"type": "quote",           "label": "Quote",            "icon": "❝",  "default_props": {"text": "", "author": ""}, "schema": {}},
    {"type": "section-1col",    "label": "Sectie (1 kolom)", "icon": "□",  "default_props": {"blocks": []}, "schema": {}},
    {"type": "section-2col",    "label": "Sectie (2 kolom)", "icon": "□□", "default_props": {"col1": [], "col2": []}, "schema": {}},
    {"type": "section-3col",    "label": "Sectie (3 kolom)", "icon": "□□□","default_props": {"col1": [], "col2": [], "col3": []}, "schema": {}},
    {"type": "video-youtube",   "label": "YouTube video",    "icon": "▶",  "default_props": {"url": ""}, "schema": {}},
    {"type": "video-vimeo",     "label": "Vimeo video",      "icon": "▶",  "default_props": {"url": ""}, "schema": {}},
    {"type": "embed-iframe",    "label": "Embed iframe",     "icon": "⌗",  "default_props": {"url": "", "height_px": 480}, "schema": {}},
    {"type": "html-raw",        "label": "HTML (raw)",       "icon": "<>", "default_props": {"html": ""}, "schema": {}},
    {"type": "cta-banner",      "label": "CTA banner",       "icon": "★",  "default_props": {"headline": "", "subline": "", "cta_label": "", "cta_url": ""}, "schema": {}},
    {"type": "faq-item",        "label": "FAQ item",         "icon": "?",  "default_props": {"q": "", "a": ""}, "schema": {}},
    {"type": "faq-group",       "label": "FAQ groep",        "icon": "?+", "default_props": {"items": []}, "schema": {}},
    {"type": "testimonial",     "label": "Testimonial",      "icon": "💬", "default_props": {"quote": "", "author": "", "role": ""}, "schema": {}},
    {"type": "icon-box",        "label": "Icon box",         "icon": "◉",  "default_props": {"icon": "", "title": "", "text": ""}, "schema": {}},
    {"type": "contact-form-ref","label": "Contactformulier", "icon": "✉",  "default_props": {"form_id": "default"}, "schema": {}},
    {"type": "google-map",      "label": "Google Map",       "icon": "📍", "default_props": {"address": ""}, "schema": {}},
    {"type": "breadcrumb",      "label": "Breadcrumb",       "icon": "›",  "default_props": {}, "schema": {}},
    {"type": "table",           "label": "Tabel",            "icon": "▦",  "default_props": {"rows": [], "header": []}, "schema": {}},
]

META_PATTERNS = {
    "title":          (r'<title>([^<]*)</title>',
                       lambda v: f'<title>{v}</title>'),
    "description":    (r'<meta\s+name="description"\s+content="([^"]*)"\s*/?>',
                       lambda v: f'<meta name="description" content="{v}"/>'),
    "og_title":       (r'<meta\s+property="og:title"\s+content="([^"]*)"\s*/?>',
                       lambda v: f'<meta property="og:title" content="{v}"/>'),
    "og_description": (r'<meta\s+property="og:description"\s+content="([^"]*)"\s*/?>',
                       lambda v: f'<meta property="og:description" content="{v}"/>'),
    "og_image":       (r'<meta\s+property="og:image"\s+content="([^"]*)"\s*/?>',
                       lambda v: f'<meta property="og:image" content="{v}"/>'),
}

# ============================================================================
# Local KV emulation (JSON files in admin/data/kv/)
# ============================================================================
_KV_LOCK = threading.Lock()


def _kv_path(key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.:\-]+", "_", key)
    return KV_DIR / f"{safe}.json"


def kv_get(key: str, default=None):
    p = _kv_path(key)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def kv_set(key: str, value) -> bool:
    with _KV_LOCK:
        try:
            _kv_path(key).write_text(
                json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return True
        except Exception as e:
            print(f"kv_set failed for {key}: {e}")
            return False


def kv_delete(key: str) -> bool:
    p = _kv_path(key)
    if p.exists():
        try:
            p.unlink()
            return True
        except Exception:
            return False
    return False


def kv_keys_with_prefix(prefix: str) -> list[str]:
    safe = re.sub(r"[^A-Za-z0-9_.:\-]+", "_", prefix)
    out = []
    for f in KV_DIR.glob("*.json"):
        name = f.stem
        if name.startswith(safe):
            out.append(name)
    return out


# ============================================================================
# Generic JSON file helpers (legacy server.py compat)
# ============================================================================
def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_settings() -> dict:
    # First try KV (admin UI writes go through here), then fall back to file.
    s = kv_get("settings", None)
    if s is None:
        s = load_json(SETTINGS_FILE, {})
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    for k, v in (s or {}).items():
        if isinstance(v, dict) and k in out:
            out[k].update(v)
        else:
            out[k] = v
    return out


def save_settings(patch: dict):
    existing = kv_get("settings", None)
    if existing is None:
        existing = load_json(SETTINGS_FILE, {})
    for k, v in patch.items():
        if isinstance(v, dict):
            existing.setdefault(k, {}).update(
                {kk: vv for kk, vv in v.items() if vv != "••••••••"}
            )
        else:
            existing[k] = v
    kv_set("settings", existing)
    save_json(SETTINGS_FILE, existing)


def get_leads() -> list:
    # Leads in KV mirror the file
    kv_leads = kv_get("leads", None)
    if kv_leads is not None:
        return kv_leads
    return load_json(LEADS_FILE, [])


def save_leads(leads):
    kv_set("leads", leads)
    save_json(LEADS_FILE, leads)


# ============================================================================
# Audit log
# ============================================================================
def audit(user: str, action: str, target: str, summary: str = "",
          before=None, after=None):
    log = kv_get("audit:log", []) or []
    log.insert(0, {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "user": user, "action": action, "target": target,
        "summary": summary, "before": before, "after": after,
    })
    log = log[:1000]
    kv_set("audit:log", log)


# ============================================================================
# Flask app
# ============================================================================
app = Flask(__name__, static_folder=None)
app.secret_key = SECRET
app.url_map.strict_slashes = False


def is_logged_in() -> bool:
    return session.get("user") in USERS


def require_login():
    if not is_logged_in():
        return redirect(url_for("login", next=request.path))
    return None


def current_user() -> str:
    return session.get("user", "anonymous")


# ============================================================================
# Static page browsing helpers
# ============================================================================
def list_static_pages() -> list[dict]:
    """Scan filesystem for index.html files (mirrors api/index.py output shape)."""
    cached = load_json(PAGES_INDEX_FILE, None)
    if cached:
        return cached
    pages = []
    for p in sorted(ROOT.rglob("index.html")):
        rel = p.relative_to(ROOT)
        parts = rel.parts
        if parts[0] in {"wp-content", "wp-includes", "admin", ".git", ".vercel", ".backups", "api"}:
            continue
        url = "/" + "/".join(parts[:-1])
        slug = "(home)" if url == "/" else url.strip("/")
        pages.append({
            "url": url + ("/" if url != "/" else ""),
            "slug": slug,
            "title": extract_title(p),
            "path": str(rel),
            "size_kb": round(p.stat().st_size / 1024, 1),
            "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
        })
    return pages


def extract_title(p: Path) -> str:
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"<title>([^<]+)</title>", text)
        return m.group(1).strip() if m else p.stem
    except Exception:
        return p.stem


def sitemap_tree() -> dict:
    root = {"name": "/", "url": "/", "children": {}, "title": None}
    for page in list_static_pages():
        parts = [p for p in page["url"].strip("/").split("/") if p]
        cur = root
        for i, part in enumerate(parts):
            if part not in cur["children"]:
                cur["children"][part] = {
                    "name": part,
                    "url": "/" + "/".join(parts[: i + 1]) + "/",
                    "children": {}, "title": None,
                }
            cur = cur["children"][part]
        cur["title"] = page["title"]
    return root


def list_media_files(subdir: str = "wp-content/uploads") -> list[dict]:
    base = ROOT / subdir
    items = []
    if not base.exists():
        return items
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".webm", ".pdf"}:
            continue
        rel = p.relative_to(ROOT)
        items.append({
            "url": "/" + str(rel).replace(os.sep, "/"),
            "name": p.name,
            "size_kb": round(p.stat().st_size / 1024, 1),
            "ext": p.suffix.lower().lstrip("."),
        })
        if len(items) >= 500:
            break
    return items


# ============================================================================
# Page / block CMS helpers (KV-backed)
# ============================================================================
def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def get_pages_index() -> list:
    return kv_get("pages:index", []) or []


def set_pages_index(items: list):
    kv_set("pages:index", items)


def update_pages_index_entry(page: dict):
    items = get_pages_index()
    entry = {
        "slug": page["slug"], "title": page.get("title", page["slug"]),
        "status": page.get("status", "draft"),
        "template": page.get("template"),
        "updated_at": page.get("updated_at"),
        "seo_score": (kv_get("seo_scores", {}) or {}).get(page["slug"], {}).get("score", 0),
    }
    found = False
    for i, it in enumerate(items):
        if it.get("slug") == page["slug"]:
            items[i] = entry
            found = True
            break
    if not found:
        items.append(entry)
    set_pages_index(items)


def remove_pages_index_entry(slug: str):
    items = [it for it in get_pages_index() if it.get("slug") != slug]
    set_pages_index(items)


def get_page(slug: str) -> dict | None:
    return kv_get(f"page:{slug}", None)


def save_page(page: dict):
    page["updated_at"] = datetime.now().isoformat(timespec="seconds")
    kv_set(f"page:{page['slug']}", page)
    update_pages_index_entry(page)


def render_block(block: dict) -> str:
    """Render a single block to HTML."""
    t = block.get("type", "")
    p = block.get("props", {})
    if t.startswith("heading-h"):
        level = t[-1]
        return f"<h{level}>{p.get('text','')}</h{level}>"
    if t == "paragraph":
        return f"<p>{p.get('text','')}</p>"
    if t == "rich-text":
        return f"<div class='rich-text'>{p.get('html','')}</div>"
    if t == "image":
        return f"<figure><img src='{p.get('url','')}' alt='{p.get('alt','')}'/><figcaption>{p.get('caption','')}</figcaption></figure>"
    if t == "button":
        return f"<a class='cta' href='{p.get('url','#')}'>{p.get('label','Klik')}</a>"
    if t == "hr":
        return "<hr/>"
    if t == "spacer":
        return f"<div style='height:{p.get('height_px',24)}px'></div>"
    if t == "quote":
        return f"<blockquote>{p.get('text','')}<cite>{p.get('author','')}</cite></blockquote>"
    if t == "html-raw":
        return p.get("html", "")
    if t == "faq-item":
        return f"<details><summary>{p.get('q','')}</summary><div>{p.get('a','')}</div></details>"
    if t == "faq-group":
        return "".join(
            f"<details><summary>{i.get('q','')}</summary><div>{i.get('a','')}</div></details>"
            for i in p.get("items", [])
        )
    if t == "list-ul":
        return "<ul>" + "".join(f"<li>{i}</li>" for i in p.get("items", [])) + "</ul>"
    if t == "list-ol":
        return "<ol>" + "".join(f"<li>{i}</li>" for i in p.get("items", [])) + "</ol>"
    if t == "cta-banner":
        return (
            f"<section class='cta-banner'><h2>{p.get('headline','')}</h2>"
            f"<p>{p.get('subline','')}</p>"
            f"<a class='cta' href='{p.get('cta_url','#')}'>{p.get('cta_label','')}</a></section>"
        )
    if t == "section-3col":
        cols = "".join(
            f"<div class='col'>{''.join(render_block(b) for b in p.get(c, []))}</div>"
            for c in ("col1", "col2", "col3")
        )
        return f"<section class='cols-3'>{cols}</section>"
    if t == "section-2col":
        cols = "".join(
            f"<div class='col'>{''.join(render_block(b) for b in p.get(c, []))}</div>"
            for c in ("col1", "col2")
        )
        return f"<section class='cols-2'>{cols}</section>"
    if t == "section-1col":
        return f"<section>{''.join(render_block(b) for b in p.get('blocks', []))}</section>"
    return f"<!-- unknown block {t} -->"


def render_page_html(page: dict) -> str:
    meta = page.get("meta", {})
    blocks = page.get("content_blocks", [])
    body = "\n".join(render_block(b) for b in blocks)
    return f"""<!DOCTYPE html>
<html lang="{page.get('locale','nl')}">
<head>
<meta charset="UTF-8">
<title>{meta.get('title') or page.get('title','')}</title>
<meta name="description" content="{meta.get('description','')}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="canonical" href="{meta.get('canonical','')}">
<meta name="robots" content="{meta.get('robots','index,follow')}">
</head>
<body>
<header><h1>{page.get('title','')}</h1></header>
<main>{body}</main>
</body></html>"""


def substitute_vars(text: str, variables: dict) -> str:
    if not isinstance(text, str):
        return text
    for k, v in variables.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def apply_template_vars(blocks: list, variables: dict) -> list:
    out = []
    for b in blocks:
        nb = json.loads(json.dumps(b))
        props = nb.get("props", {})
        for k, v in props.items():
            if isinstance(v, str):
                props[k] = substitute_vars(v, variables)
        nb["props"] = props
        out.append(nb)
    return out


def compute_seo_score(page: dict) -> dict:
    meta = page.get("meta", {}) or {}
    issues = []
    score = 100
    if not meta.get("title"):
        issues.append("Mist meta title"); score -= 20
    elif len(meta["title"]) > 60:
        issues.append("Meta title te lang"); score -= 5
    if not meta.get("description"):
        issues.append("Mist meta description"); score -= 20
    elif len(meta["description"]) < 50:
        issues.append("Meta description te kort"); score -= 5
    if not meta.get("canonical"):
        issues.append("Mist canonical"); score -= 5
    if not page.get("content_blocks"):
        issues.append("Pagina heeft geen content blocks"); score -= 20
    if not any(b.get("type", "").startswith("heading-h1") for b in page.get("content_blocks", [])):
        issues.append("Mist H1"); score -= 10
    score = max(0, score)
    return {"score": score, "issues": issues,
            "computed_at": datetime.now().isoformat(timespec="seconds")}


# ============================================================================
# Legacy chat command-parser (kept for backwards compat)
# ============================================================================
SERVICE_TEMPLATE = """<!DOCTYPE html>
<html lang="nl"><head><meta charset="UTF-8"><title>{title} - Wandmeesters</title></head>
<body><h1>{title}</h1><p>{intro}</p><p>{body}</p></body></html>"""


def cmd_add_page(args):
    parent = args.get("parent", "/").strip("/")
    name = args.get("name", "").strip()
    if not name:
        return {"ok": False, "error": "Naam ontbreekt"}
    slug = slugify(name)
    if not slug:
        return {"ok": False, "error": "Naam levert geen geldige URL slug op"}
    target_dir = ROOT / (parent or "") / slug
    rel = target_dir.relative_to(ROOT)
    if target_dir.exists():
        return {"ok": False, "error": f"Pagina /{rel}/ bestaat al"}
    target_dir.mkdir(parents=True)
    intro = args.get("intro") or f"Professioneel {name.lower()} door Wandmeesters."
    body = args.get("body") or f"Wij verzorgen {name.lower()} op maat."
    (target_dir / "index.html").write_text(
        SERVICE_TEMPLATE.format(title=name, intro=intro, body=body), encoding="utf-8"
    )
    return {"ok": True, "message": f"Pagina aangemaakt: /{rel}/", "url": f"/{rel}/"}


def cmd_list_pages(_args):
    p = list_static_pages()
    return {"ok": True, "data": p, "count": len(p)}


def cmd_delete_page(args):
    page = args.get("page", "").strip("/")
    if not page:
        return {"ok": False, "error": "Pagina-URL ontbreekt"}
    if page in {"", "contact", "diensten", "over-ons", "projecten"}:
        return {"ok": False, "error": "Hoofdpagina mag niet verwijderd worden"}
    target = ROOT / page
    if not target.exists():
        return {"ok": False, "error": f"Pagina niet gevonden: /{page}/"}
    shutil.rmtree(target)
    return {"ok": True, "message": f"Pagina /{page}/ verwijderd"}


def cmd_edit_text(args):
    page = args.get("page", "").strip("/")
    find = args.get("find", "")
    replace = args.get("replace", "")
    if not page or not find:
        return {"ok": False, "error": "Pagina-URL en zoek-tekst zijn verplicht"}
    target = ROOT / page / "index.html"
    if not target.exists():
        target = ROOT / page
    if not target.exists() or not target.is_file():
        return {"ok": False, "error": f"Pagina niet gevonden: {page}"}
    content = target.read_text(encoding="utf-8", errors="replace")
    if find not in content:
        return {"ok": False, "error": f"Tekst '{find[:60]}' niet gevonden"}
    new = content.replace(find, replace)
    target.write_text(new, encoding="utf-8")
    return {"ok": True, "message": f"{content.count(find)}x vervangen op {page}", "page": page}


COMMAND_HANDLERS = {
    "add_page":    cmd_add_page,
    "edit_text":   cmd_edit_text,
    "list_pages":  cmd_list_pages,
    "delete_page": cmd_delete_page,
}


def parse_chat(message: str) -> dict:
    msg = message.strip()
    low = msg.lower()
    m = re.search(r"voeg(?:\s+(?:een|de))?\s+pagina\s+(?:toe\s+)?(?:voor|over)\s+(.+?)(?:\s+(?:in|onder)\s+(/\S+))?$", low)
    if m:
        return {"command": "add_page", "args": {"name": m.group(1).strip(".!? "), "parent": m.group(2) or "/diensten/"}}
    if low.startswith(("maak een pagina", "nieuwe pagina")):
        m = re.search(r"voor\s+(.+)", low)
        if m:
            return {"command": "add_page", "args": {"name": m.group(1).strip(".!? "), "parent": "/diensten/"}}
    if re.search(r"(toon|laat|geef|alle|lijst)\s+.*(pagina|pages)", low):
        return {"command": "list_pages", "args": {}}
    m = re.search(r"verwijder\s+(?:de\s+)?pagina\s+(\S+)", low)
    if m:
        return {"command": "delete_page", "args": {"page": m.group(1)}}
    m = re.search(r"(?:wijzig|vervang|verander)\s+['\"]?(.+?)['\"]?\s+(?:naar|in|door)\s+['\"]?(.+?)['\"]?\s+op\s+(?:pagina\s+)?(\S+)", msg, re.IGNORECASE)
    if m:
        return {"command": "edit_text", "args": {"find": m.group(1), "replace": m.group(2), "page": m.group(3)}}
    return {"command": None, "error": "Ik begreep dat commando niet."}


# ============================================================================
# Mail helpers (mirrors api/index.py)
# ============================================================================
def _build_field_ctx(lead: dict) -> dict:
    base = {k: lead.get(k, "") for k in (
        "name", "email", "telefoon", "woonplaats",
        "soort_woning", "m2", "pakket", "startdatum",
    )}
    for alias, target in FIELD_ID_ALIASES.items():
        base[alias] = base.get(target, "")
    return base


def render_template_text(tpl, ctx, html: bool = False):
    out = tpl or ""

    def _field_sub(m): return str(ctx.get(m.group(1), "") or "")
    out = re.sub(r'\[field\s+id=["\']?([^"\'\]\s]+)["\']?\s*\]', _field_sub, out)
    if "[all-fields]" in out:
        rows = [(label, ctx.get(k, "")) for k, label in FIELD_LABELS.items() if ctx.get(k, "")]
        if html:
            block = (
                '<table cellpadding="6" cellspacing="0" border="0" style="border-collapse:collapse">'
                + "".join(
                    f'<tr><td style="padding:4px 12px 4px 0;color:#6b7280">{label}</td>'
                    f'<td style="padding:4px 0;color:#111827"><b>{v}</b></td></tr>'
                    for label, v in rows
                )
                + "</table>"
            )
        else:
            block = "\n".join(f"{label}: {v}" for label, v in rows)
        out = out.replace("[all-fields]", block)
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", str(v or ""))
    return out


def send_email(to_addr, subject, body, bcc=None, reply_to=None, content_type="plain"):
    s = get_settings()["smtp"]
    if not (s.get("host") and s.get("from_email") and to_addr):
        return False, "SMTP niet geconfigureerd"
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f'{s.get("from_name") or "Wandmeesters"} <{s["from_email"].strip()}>'
        msg["To"] = to_addr
        if reply_to:
            msg["Reply-To"] = reply_to
        sub = "html" if content_type == "html" else "plain"
        msg.attach(MIMEText(body, sub, "utf-8"))
        recipients = [to_addr]
        if bcc:
            for b in [x.strip() for x in re.split(r"[,;]+", bcc) if x.strip()]:
                recipients.append(b)
        port = int(s.get("port", 587))
        if port == 465:
            with smtplib.SMTP_SSL(s["host"], port, context=ssl.create_default_context(), timeout=10) as srv:
                if s.get("user"):
                    srv.login(s["user"], s.get("password", ""))
                srv.sendmail(s["from_email"].strip(), recipients, msg.as_string())
        else:
            with smtplib.SMTP(s["host"], port, timeout=10) as srv:
                srv.ehlo()
                if s.get("use_tls", True):
                    srv.starttls(context=ssl.create_default_context())
                    srv.ehlo()
                if s.get("user"):
                    srv.login(s["user"], s.get("password", ""))
                srv.sendmail(s["from_email"].strip(), recipients, msg.as_string())
        return True, "Verzonden"
    except Exception as e:
        return False, f"SMTP fout: {e}"


def process_lead_emails(lead):
    settings = get_settings()
    ctx = _build_field_ctx(lead)

    def is_html(t): return t.get("content_type") == "html"

    company_to = (settings.get("company_email") or "").strip()
    if company_to:
        tpl = settings["template_company"]
        ok, msg = send_email(
            to_addr=company_to,
            subject=render_template_text(tpl["subject"], ctx),
            body=render_template_text(tpl["body"], ctx, html=is_html(tpl)),
            bcc=settings.get("company_bcc"),
            reply_to=render_template_text(settings.get("company_reply_to", ""), ctx) or None,
            content_type="html" if is_html(tpl) else "plain",
        )
        lead.setdefault("emails", []).append({
            "to": "company", "address": company_to,
            "ok": ok, "msg": msg,
            "ts": datetime.now().isoformat(timespec="seconds"),
        })
    raw_to = settings.get("customer_to") or "[field id=\"field_574f21f\"]"
    customer_to = render_template_text(raw_to, ctx).strip()
    if customer_to and "@" in customer_to:
        tpl = settings["template_customer"]
        ok, msg = send_email(
            to_addr=customer_to,
            subject=render_template_text(tpl["subject"], ctx),
            body=render_template_text(tpl["body"], ctx, html=is_html(tpl)),
            bcc=settings.get("customer_bcc"),
            reply_to=render_template_text(settings.get("customer_reply_to", ""), ctx) or None,
            content_type="html" if is_html(tpl) else "plain",
        )
        lead.setdefault("emails", []).append({
            "to": "customer", "address": customer_to,
            "ok": ok, "msg": msg,
            "ts": datetime.now().isoformat(timespec="seconds"),
        })


def process_lead_emails_async(lead: dict):
    threading.Thread(target=lambda: process_lead_emails(lead), daemon=True).start()


# ============================================================================
# Auth routes
# ============================================================================
LOGIN_HTML = """<!DOCTYPE html><html lang="nl"><head><meta charset="UTF-8">
<title>Inloggen - Wandmeesters Admin</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>body{font-family:'Inter',-apple-system,sans-serif}</style></head>
<body class="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0a5cad] via-[#1a6db8] to-[#347677] p-4">
  <form method="post" class="bg-white/95 backdrop-blur rounded-2xl shadow-2xl w-full max-w-sm p-8">
    <div class="flex flex-col items-center mb-6">
      <div class="w-14 h-14 rounded-xl bg-gradient-to-br from-[#0a5cad] to-[#347677] flex items-center justify-center text-white text-2xl shadow-lg mb-3">CMS</div>
      <h1 class="text-xl font-bold text-slate-900">Wandmeesters Admin</h1>
      <p class="text-xs text-slate-500 mt-1">Log in om de back-end te beheren</p>
    </div>
    {% if error %}<div class="bg-rose-50 border border-rose-200 text-rose-700 text-sm rounded-lg px-3 py-2 mb-4 text-center">{{ error }}</div>{% endif %}
    <label class="block text-xs font-semibold text-slate-600 mb-1.5">Gebruikersnaam</label>
    <input name="username" required autofocus autocomplete="username"
      class="w-full px-3.5 py-2.5 mb-4 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#0a5cad]">
    <label class="block text-xs font-semibold text-slate-600 mb-1.5">Wachtwoord</label>
    <input name="password" type="password" required autocomplete="current-password"
      class="w-full px-3.5 py-2.5 mb-5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#0a5cad]">
    <button class="w-full bg-gradient-to-r from-[#0a5cad] to-[#347677] text-white font-semibold py-2.5 rounded-lg hover:opacity-95 transition shadow-md">Inloggen</button>
    <div class="text-xs text-slate-400 text-center mt-5">demo: admin / admin</div>
  </form>
</body></html>"""


@app.route("/inloggen", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        if USERS.get(u) == p:
            session["user"] = u
            return redirect(request.args.get("next") or "/admin/")
        error = "Onjuiste inloggegevens"
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/uitloggen")
def logout():
    session.clear()
    return redirect("/inloggen")


@app.route("/admin/")
@app.route("/admin")
def admin_home():
    r = require_login()
    if r:
        return r
    return send_from_directory(ADMIN_DIR, "index.html")


@app.route("/admin/<path:sub>")
def admin_static(sub):
    if sub.startswith("data/"):
        abort(404)
    r = require_login()
    if r:
        return r
    p = (ADMIN_DIR / sub).resolve()
    if not str(p).startswith(str(ADMIN_DIR)) or not p.exists():
        abort(404)
    return send_from_directory(p.parent, p.name)


# ============================================================================
# Legacy admin API (sitemap, chat, smtp-test)
# ============================================================================
@app.route("/api/sitemap")
def api_sitemap():
    if require_login():
        return jsonify({"error": "auth"}), 401
    return jsonify(sitemap_tree())


@app.route("/api/chat", methods=["POST"])
def api_chat():
    if require_login():
        return jsonify({"error": "auth"}), 401
    msg = (request.get_json(silent=True) or {}).get("message", "").strip()
    parsed = parse_chat(msg)
    if not parsed.get("command"):
        return jsonify({"ok": False, "reply": parsed.get("error", "Onbekend"), "parsed": parsed})
    handler = COMMAND_HANDLERS.get(parsed["command"])
    if not handler:
        return jsonify({"ok": False, "reply": "Handler niet gevonden"})
    result = handler(parsed.get("args", {}))
    audit(current_user(), parsed["command"], parsed.get("args", {}).get("page", ""),
          result.get("message") or result.get("error") or "")
    return jsonify({"ok": result.get("ok", False),
                    "reply": result.get("message") or result.get("error") or "Klaar",
                    "command": parsed["command"], "result": result, "parsed": parsed})


@app.route("/api/smtp-test", methods=["POST"])
def api_smtp_test():
    if require_login():
        return jsonify({"error": "auth"}), 401
    to = (request.get_json(silent=True) or {}).get("to", "").strip()
    if not to:
        return jsonify({"ok": False, "error": "Ontvanger ontbreekt"}), 400
    ok, msg = send_email(to, "Wandmeesters SMTP test", "Testbericht — SMTP werkt.")
    return jsonify({"ok": ok, "message": msg})


# ============================================================================
# Public lead intake
# ============================================================================
@app.route("/api/submit", methods=["POST", "OPTIONS"])
def api_submit():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or request.form.to_dict()
    if not data:
        return jsonify({"ok": False, "error": "Geen gegevens"}), 400
    lead = {
        "id": uuid.uuid4().hex[:12],
        "created": datetime.now().isoformat(timespec="seconds"),
        "stage": "ontvangen",
        "name": data.get("name") or data.get("Naam") or "",
        "email": data.get("email") or data.get("E-mail") or "",
        "telefoon": data.get("telefoon") or data.get("phone") or data.get("Telefoonnummer") or "",
        "woonplaats": data.get("woonplaats") or data.get("city") or "",
        "soort_woning": data.get("soort_woning") or "",
        "m2": data.get("m2") or "",
        "pakket": data.get("pakket") or "",
        "startdatum": data.get("startdatum") or "",
        "note": data.get("note") or "",
        "source": data.get("source") or request.referrer or "/",
        "history": [{"ts": datetime.now().isoformat(timespec="seconds"), "stage": "ontvangen", "by": "form"}],
        "emails": [],
    }
    leads = get_leads()
    leads.insert(0, lead)
    save_leads(leads)
    process_lead_emails_async(lead)
    return jsonify({"ok": True, "id": lead["id"],
                    "message": "Bedankt! We nemen binnen 1 werkdag contact met je op."})


# ============================================================================
# Leads / pipeline
# ============================================================================
@app.route("/api/leads", methods=["GET"])
def api_leads():
    if require_login():
        return jsonify({"error": "auth"}), 401
    return jsonify({"leads": get_leads(), "stages": PIPELINE_STAGES})


@app.route("/api/leads/<lead_id>", methods=["PATCH", "DELETE"])
def api_lead_update(lead_id):
    if require_login():
        return jsonify({"error": "auth"}), 401
    leads = get_leads()
    idx = next((i for i, l in enumerate(leads) if l.get("id") == lead_id), -1)
    if idx == -1:
        return jsonify({"ok": False, "error": "Lead niet gevonden"}), 404
    if request.method == "DELETE":
        before = leads[idx]
        leads.pop(idx)
        save_leads(leads)
        audit(current_user(), "lead.delete", lead_id, "lead deleted", before)
        return jsonify({"ok": True})
    patch = request.get_json(silent=True) or {}
    if "stage" in patch and patch["stage"] in STAGE_IDS:
        old = leads[idx].get("stage")
        leads[idx]["stage"] = patch["stage"]
        leads[idx].setdefault("history", []).append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "from": old, "stage": patch["stage"], "by": current_user(),
        })
    for k in ("note", "name", "email", "telefoon", "woonplaats"):
        if k in patch:
            leads[idx][k] = patch[k]
    save_leads(leads)
    audit(current_user(), "lead.patch", lead_id, json.dumps(patch))
    return jsonify({"ok": True, "lead": leads[idx]})


# ============================================================================
# Settings
# ============================================================================
@app.route("/api/settings", methods=["GET", "PUT"])
def api_settings():
    if require_login():
        return jsonify({"error": "auth"}), 401
    if request.method == "GET":
        s = get_settings()
        if s.get("smtp", {}).get("password"):
            s["smtp"]["password"] = "••••••••"
        if s.get("ai", {}).get("api_key"):
            s["ai"]["api_key"] = "••••••••"
        return jsonify(s)
    patch = request.get_json(silent=True) or {}
    save_settings(patch)
    audit(current_user(), "settings.update", "settings", "settings patched")
    return jsonify({"ok": True})


# ============================================================================
# Pages CRUD (KV-backed CMS)
# ============================================================================
@app.route("/api/pages", methods=["GET", "POST"])
def api_pages():
    if require_login():
        return jsonify({"error": "auth"}), 401
    if request.method == "GET":
        # Merge KV pages with static page index for backwards compat
        items = get_pages_index()
        if not items:
            # Fall back to static pages on disk
            static = list_static_pages()
            items = [{
                "slug": p["slug"], "title": p["title"],
                "status": "published", "template": None,
                "updated_at": p.get("modified", ""),
                "seo_score": 0,
            } for p in static]
        status = request.args.get("status")
        template = request.args.get("template")
        q = (request.args.get("q") or "").lower()
        if status:
            items = [i for i in items if i.get("status") == status]
        if template:
            items = [i for i in items if i.get("template") == template]
        if q:
            items = [i for i in items if q in (i.get("title", "") + i.get("slug", "")).lower()]
        try:
            limit = int(request.args.get("limit", "1000"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            limit, offset = 1000, 0
        return jsonify({"items": items[offset:offset + limit], "total": len(items)})
    # POST → create
    body = request.get_json(silent=True) or {}
    slug = slugify(body.get("slug") or body.get("title", ""))
    if not slug:
        return jsonify({"ok": False, "error": "slug ontbreekt"}), 400
    if get_page(slug):
        return jsonify({"ok": False, "error": "Pagina bestaat al"}), 409
    template_name = body.get("template")
    blocks, default_meta = [], {}
    if template_name:
        tpl = kv_get(f"template:{template_name}", None)
        if not tpl:
            # Fall back to seed-templates file
            tplfile = load_json(TEMPLATES_FILE, [])
            tpl = next((t for t in tplfile if t.get("name") == template_name), None)
        if tpl:
            blocks = apply_template_vars(tpl.get("content_blocks", []),
                                         body.get("variables", {}))
            default_meta = tpl.get("default_meta", {}) or {}
    page = {
        "slug": slug,
        "title": body.get("title", slug),
        "status": "draft",
        "template": template_name,
        "locale": body.get("locale", "nl"),
        "parent": body.get("parent"),
        "menu_position": 0,
        "scheduled_publish_at": None,
        "author": current_user(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "published_at": None,
        "meta": default_meta,
        "content_blocks": blocks,
    }
    save_page(page)
    audit(current_user(), "page.create", slug, f"page created from template={template_name}")
    return jsonify(page), 201


@app.route("/api/pages/<slug>", methods=["GET", "PUT", "DELETE"])
def api_page_detail(slug):
    if require_login():
        return jsonify({"error": "auth"}), 401
    page = get_page(slug)
    if request.method == "GET":
        if not page:
            return jsonify({"error": "not found"}), 404
        if request.args.get("include_draft") == "true":
            draft = kv_get(f"page:{slug}:draft", None)
            if draft:
                page["draft"] = draft
        return jsonify(page)
    if request.method == "DELETE":
        if not page:
            return jsonify({"error": "not found"}), 404
        body = request.get_json(silent=True) or {}
        page["status"] = "trashed"
        save_page(page)
        redirect_id = None
        if body.get("create_redirect_to"):
            redirect_id = uuid.uuid4().hex[:10]
            redirects = kv_get("redirects:index", []) or []
            redirects.append({
                "id": redirect_id, "from_path": f"/{slug}/",
                "to_path": body["create_redirect_to"], "code": 301, "hit_count": 0,
            })
            kv_set("redirects:index", redirects)
            kv_set(f"redirect:{redirect_id}", redirects[-1])
        audit(current_user(), "page.delete", slug, "soft delete")
        return jsonify({"deleted": True, "redirect_id": redirect_id})
    # PUT
    body = request.get_json(silent=True) or {}
    if not page:
        page = {
            "slug": slug, "title": body.get("title", slug),
            "status": "draft", "template": None, "locale": "nl",
            "author": current_user(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "meta": {}, "content_blocks": [],
        }
    before = json.loads(json.dumps(page))
    for k in ("title", "content_blocks", "meta", "template", "locale",
              "parent", "menu_position", "scheduled_publish_at"):
        if k in body:
            page[k] = body[k]
    publish_flag = request.args.get("publish") == "1" or body.get("status") == "published"
    rev_id = uuid.uuid4().hex[:8]
    revs = kv_get(f"page:{slug}:revs", []) or []
    kv_set(f"page:{slug}:rev:{rev_id}", {
        "rev_id": rev_id, "page_slug": slug, "snapshot": before,
        "author": current_user(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "summary": "auto-snapshot before save",
    })
    revs.insert(0, rev_id)
    kv_set(f"page:{slug}:revs", revs[:20])
    if publish_flag:
        page["status"] = "published"
        page["published_at"] = datetime.now().isoformat(timespec="seconds")
        html = render_page_html(page)
        blob_path = BLOB_DIR / f"pages/{slug}.html"
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_text(html, encoding="utf-8")
    else:
        kv_set(f"page:{slug}:draft", page)
    save_page(page)
    seo = compute_seo_score(page)
    scores = kv_get("seo_scores", {}) or {}
    scores[slug] = seo
    kv_set("seo_scores", scores)
    audit(current_user(), "page.update", slug, f"published={publish_flag}")
    html_size = len(render_page_html(page))
    return jsonify({"slug": slug, "updated_at": page["updated_at"],
                    "revision_id": rev_id,
                    "html_size_kb": round(html_size / 1024, 1),
                    "blob_url": f"/api/render/{slug}" if publish_flag else None})


@app.route("/api/pages/<slug>/duplicate", methods=["POST"])
def api_page_duplicate(slug):
    if require_login():
        return jsonify({"error": "auth"}), 401
    src = get_page(slug)
    if not src:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(silent=True) or {}
    new_slug = slugify(body.get("new_slug") or f"{slug}-kopie")
    if get_page(new_slug):
        return jsonify({"error": "doel bestaat al"}), 409
    new_page = json.loads(json.dumps(src))
    new_page["slug"] = new_slug
    new_page["title"] = body.get("new_title") or f"{src.get('title','')} (kopie)"
    new_page["status"] = "draft"
    new_page["created_at"] = datetime.now().isoformat(timespec="seconds")
    save_page(new_page)
    audit(current_user(), "page.duplicate", slug, f"to {new_slug}")
    return jsonify({"slug": new_slug, "title": new_page["title"], "status": "draft"})


@app.route("/api/pages/<slug>/slug", methods=["PATCH"])
def api_page_rename_slug(slug):
    if require_login():
        return jsonify({"error": "auth"}), 401
    page = get_page(slug)
    if not page:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(silent=True) or {}
    new_slug = slugify(body.get("new_slug", ""))
    if not new_slug:
        return jsonify({"error": "new_slug ontbreekt"}), 400
    if get_page(new_slug):
        return jsonify({"error": "nieuwe slug bestaat al"}), 409
    page["slug"] = new_slug
    kv_delete(f"page:{slug}")
    remove_pages_index_entry(slug)
    save_page(page)
    redirect_id = None
    if body.get("create_redirect", True):
        redirect_id = uuid.uuid4().hex[:10]
        redirects = kv_get("redirects:index", []) or []
        redirects.append({
            "id": redirect_id, "from_path": f"/{slug}/",
            "to_path": f"/{new_slug}/", "code": 301, "hit_count": 0,
        })
        kv_set("redirects:index", redirects)
        kv_set(f"redirect:{redirect_id}", redirects[-1])
    audit(current_user(), "page.rename_slug", slug, f"-> {new_slug}")
    return jsonify({"old_slug": slug, "new_slug": new_slug, "redirect_id": redirect_id})


@app.route("/api/pages/<slug>/publish", methods=["POST"])
def api_page_publish(slug):
    if require_login():
        return jsonify({"error": "auth"}), 401
    page = get_page(slug)
    if not page:
        return jsonify({"error": "not found"}), 404
    page["status"] = "published"
    page["published_at"] = datetime.now().isoformat(timespec="seconds")
    html = render_page_html(page)
    blob_path = BLOB_DIR / f"pages/{slug}.html"
    blob_path.parent.mkdir(parents=True, exist_ok=True)
    blob_path.write_text(html, encoding="utf-8")
    save_page(page)
    audit(current_user(), "page.publish", slug, "")
    return jsonify({"slug": slug, "published_at": page["published_at"],
                    "blob_url": f"/api/render/{slug}",
                    "html_size_kb": round(len(html) / 1024, 1)})


@app.route("/api/pages/bulk", methods=["POST"])
def api_pages_bulk():
    if require_login():
        return jsonify({"error": "auth"}), 401
    body = request.get_json(silent=True) or {}
    slugs = body.get("slugs", [])
    updates = body.get("updates", {})
    updated, failed = 0, []
    for sl in slugs:
        page = get_page(sl)
        if not page:
            failed.append({"slug": sl, "error": "not found"}); continue
        if "meta" in updates:
            page.setdefault("meta", {}).update(updates["meta"])
        if "status" in updates:
            page["status"] = updates["status"]
        save_page(page)
        updated += 1
    audit(current_user(), "pages.bulk", ",".join(slugs), f"updated={updated}")
    return jsonify({"updated": updated, "failed": failed})


@app.route("/api/pages/export")
def api_pages_export():
    if require_login():
        return jsonify({"error": "auth"}), 401
    fields = (request.args.get("fields") or "slug,title,status,meta.description").split(",")
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(fields)
    for entry in get_pages_index():
        page = get_page(entry["slug"]) or entry
        row = []
        for f in fields:
            if "." in f:
                parts = f.split(".")
                v = page
                for pp in parts:
                    v = (v or {}).get(pp, "") if isinstance(v, dict) else ""
                row.append(v)
            else:
                row.append(page.get(f, ""))
        writer.writerow(row)
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=pages.csv"})


@app.route("/api/pages/import", methods=["POST"])
def api_pages_import():
    if require_login():
        return jsonify({"error": "auth"}), 401
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "file ontbreekt"}), 400
    reader = csv.DictReader(io.StringIO(f.read().decode("utf-8", errors="replace")))
    created, updated, errors = 0, 0, []
    for row in reader:
        try:
            slug = slugify(row.get("slug") or row.get("title", ""))
            if not slug:
                errors.append({"row": row, "error": "no slug"}); continue
            page = get_page(slug) or {
                "slug": slug, "status": "draft",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "author": current_user(),
                "meta": {}, "content_blocks": [],
            }
            existed = page.get("title") is not None
            page["title"] = row.get("title", page.get("title", slug))
            if row.get("description"):
                page.setdefault("meta", {})["description"] = row["description"]
            save_page(page)
            if existed:
                updated += 1
            else:
                created += 1
        except Exception as e:
            errors.append({"row": row, "error": str(e)})
    return jsonify({"created": created, "updated": updated, "errors": errors})


@app.route("/api/pages/<slug>/preview")
def api_page_preview(slug):
    if require_login():
        return jsonify({"error": "auth"}), 401
    page = get_page(slug)
    if not page:
        return ("not found", 404)
    return Response(render_page_html(page), mimetype="text/html")


@app.route("/api/pages/<slug>/validate", methods=["POST"])
def api_page_validate(slug):
    if require_login():
        return jsonify({"error": "auth"}), 401
    page = get_page(slug)
    if not page:
        return jsonify({"error": "not found"}), 404
    seo = compute_seo_score(page)
    scores = kv_get("seo_scores", {}) or {}
    scores[slug] = seo
    kv_set("seo_scores", scores)
    return jsonify({"score": seo["score"], "issues": [
        {"severity": "warn", "field": "meta", "message": i} for i in seo["issues"]
    ], "warnings": []})


@app.route("/api/pages/<slug>/revisions", methods=["GET", "POST"])
def api_page_revisions(slug):
    if require_login():
        return jsonify({"error": "auth"}), 401
    if request.method == "GET":
        revs = kv_get(f"page:{slug}:revs", []) or []
        try:
            limit = int(request.args.get("limit", "20"))
        except ValueError:
            limit = 20
        items = []
        for rid in revs[:limit]:
            r = kv_get(f"page:{slug}:rev:{rid}", None)
            if r:
                items.append({
                    "rev_id": r["rev_id"], "author": r.get("author"),
                    "created_at": r.get("created_at"),
                    "summary": r.get("summary", ""),
                })
        return jsonify({"items": items})
    # POST → snapshot now
    page = get_page(slug)
    if not page:
        return jsonify({"error": "not found"}), 404
    rev_id = uuid.uuid4().hex[:8]
    kv_set(f"page:{slug}:rev:{rev_id}", {
        "rev_id": rev_id, "page_slug": slug, "snapshot": page,
        "author": current_user(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "summary": "manual snapshot",
    })
    revs = kv_get(f"page:{slug}:revs", []) or []
    revs.insert(0, rev_id)
    kv_set(f"page:{slug}:revs", revs[:20])
    return jsonify({"rev_id": rev_id})


@app.route("/api/pages/<slug>/revisions/<rev_id>")
def api_page_revision_detail(slug, rev_id):
    if require_login():
        return jsonify({"error": "auth"}), 401
    r = kv_get(f"page:{slug}:rev:{rev_id}", None)
    if not r:
        return jsonify({"error": "not found"}), 404
    return jsonify(r)


@app.route("/api/pages/<slug>/restore", methods=["POST"])
def api_page_restore(slug):
    if require_login():
        return jsonify({"error": "auth"}), 401
    body = request.get_json(silent=True) or {}
    rev_id = body.get("rev_id")
    r = kv_get(f"page:{slug}:rev:{rev_id}", None)
    if not r:
        return jsonify({"error": "rev not found"}), 404
    snap = r["snapshot"]
    save_page(snap)
    new_rev = uuid.uuid4().hex[:8]
    kv_set(f"page:{slug}:rev:{new_rev}", {
        "rev_id": new_rev, "page_slug": slug, "snapshot": snap,
        "author": current_user(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "summary": f"restored from {rev_id}",
    })
    revs = kv_get(f"page:{slug}:revs", []) or []
    revs.insert(0, new_rev)
    kv_set(f"page:{slug}:revs", revs[:20])
    audit(current_user(), "page.restore", slug, f"from {rev_id}")
    return jsonify({"slug": slug, "restored_from": rev_id, "new_rev_id": new_rev})


# ============================================================================
# Autocomplete & block-library
# ============================================================================
@app.route("/api/page-autocomplete")
def api_page_autocomplete():
    if require_login():
        return jsonify({"error": "auth"}), 401
    q = (request.args.get("q") or "").lower()
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        limit = 10
    items = []
    for p in get_pages_index():
        if q in (p.get("title", "") + p.get("slug", "")).lower():
            items.append({"slug": p["slug"], "title": p.get("title", ""),
                          "url": f"/{p['slug']}/"})
        if len(items) >= limit:
            break
    if not items:
        for p in list_static_pages():
            if q in (p["title"] + p["slug"]).lower():
                items.append({"slug": p["slug"], "title": p["title"], "url": p["url"]})
                if len(items) >= limit:
                    break
    return jsonify({"items": items})


@app.route("/api/blocks/library")
def api_blocks_library():
    if require_login():
        return jsonify({"error": "auth"}), 401
    return jsonify({"blocks": BLOCK_LIBRARY})


# ============================================================================
# Media library
# ============================================================================
def _media_index() -> list:
    return kv_get("media:index", []) or []


def _save_media_index(items: list):
    kv_set("media:index", items)


@app.route("/api/media", methods=["GET"])
def api_media():
    if require_login():
        return jsonify({"error": "auth"}), 401
    items = _media_index()
    if not items:
        # Fall back to filesystem listing for legacy compat
        items = list_media_files()
    mime_filter = request.args.get("type")
    q = (request.args.get("q") or "").lower()
    if mime_filter:
        items = [i for i in items if (i.get("mime") or "").startswith(mime_filter)]
    if q:
        items = [i for i in items
                 if q in ((i.get("filename") or i.get("name", "")) + " "
                          + (i.get("alt") or "")).lower()]
    try:
        limit = int(request.args.get("limit", "50"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        limit, offset = 50, 0
    return jsonify({"items": items[offset:offset + limit], "total": len(items)})


@app.route("/api/media/upload", methods=["POST"])
def api_media_upload():
    if require_login():
        return jsonify({"error": "auth"}), 401
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "file ontbreekt"}), 400
    mid = uuid.uuid4().hex[:12]
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", f.filename or "file")
    dest_dir = BLOB_DIR / "media"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{mid}-{safe_name}"
    data = f.read()
    dest.write_bytes(data)
    mime = f.mimetype or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    media = {
        "id": mid, "url": f"/admin/data/blob/media/{mid}-{safe_name}",
        "filename": safe_name, "alt": request.form.get("alt", ""),
        "title": request.form.get("title", ""), "caption": "",
        "mime": mime, "bytes": len(data),
        "width": None, "height": None,
        "used_on": [],
        "variants": {"webp_url": None, "thumb_url": None},
        "uploaded_by": current_user(),
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    kv_set(f"media:{mid}", media)
    idx = _media_index()
    idx.append({"id": mid, "filename": safe_name, "mime": mime,
                "bytes": len(data), "url": media["url"],
                "uploaded_at": media["uploaded_at"]})
    _save_media_index(idx)
    audit(current_user(), "media.upload", mid, safe_name)
    return jsonify(media)


@app.route("/api/media/<mid>", methods=["PATCH", "DELETE"])
def api_media_detail(mid):
    if require_login():
        return jsonify({"error": "auth"}), 401
    media = kv_get(f"media:{mid}", None)
    if not media:
        return jsonify({"error": "not found"}), 404
    if request.method == "DELETE":
        kv_delete(f"media:{mid}")
        _save_media_index([i for i in _media_index() if i.get("id") != mid])
        audit(current_user(), "media.delete", mid, "")
        return jsonify({"deleted": True, "was_used_on": media.get("used_on", [])})
    body = request.get_json(silent=True) or {}
    for k in ("alt", "title", "caption"):
        if k in body:
            media[k] = body[k]
    kv_set(f"media:{mid}", media)
    return jsonify(media)


@app.route("/api/media/<mid>/replace", methods=["POST"])
def api_media_replace(mid):
    if require_login():
        return jsonify({"error": "auth"}), 401
    media = kv_get(f"media:{mid}", None)
    if not media:
        return jsonify({"error": "not found"}), 404
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "file ontbreekt"}), 400
    data = f.read()
    dest_dir = BLOB_DIR / "media"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{mid}-{media['filename']}"
    dest.write_bytes(data)
    media["bytes"] = len(data)
    kv_set(f"media:{mid}", media)
    return jsonify(media)


@app.route("/api/media/bulk", methods=["POST"])
def api_media_bulk():
    if require_login():
        return jsonify({"error": "auth"}), 401
    body = request.get_json(silent=True) or {}
    ids, action, payload = body.get("ids", []), body.get("action"), body.get("payload")
    updated, failed = 0, []
    for mid in ids:
        m = kv_get(f"media:{mid}", None)
        if not m:
            failed.append({"id": mid, "error": "not found"}); continue
        if action == "delete":
            kv_delete(f"media:{mid}")
        elif action == "set_alt_prefix":
            m["alt"] = f"{payload or ''}{m.get('alt','')}"
            kv_set(f"media:{mid}", m)
        elif action == "regenerate_webp":
            m["variants"]["webp_url"] = m.get("url")
            kv_set(f"media:{mid}", m)
        updated += 1
    if action == "delete":
        _save_media_index([i for i in _media_index() if i.get("id") not in ids])
    return jsonify({"updated": updated, "failed": failed})


@app.route("/api/media/<mid>/usage")
def api_media_usage(mid):
    if require_login():
        return jsonify({"error": "auth"}), 401
    used = []
    for entry in get_pages_index():
        page = get_page(entry["slug"])
        if not page:
            continue
        for idx, b in enumerate(page.get("content_blocks", [])):
            if (b.get("props") or {}).get("media_id") == mid:
                used.append({"slug": entry["slug"], "title": entry.get("title"), "block_index": idx})
    return jsonify({"used_on": used})


@app.route("/api/media/stats")
def api_media_stats():
    if require_login():
        return jsonify({"error": "auth"}), 401
    items = _media_index()
    total = sum(i.get("bytes", 0) for i in items)
    by_mime = {}
    for i in items:
        m = i.get("mime", "unknown")
        by_mime[m] = by_mime.get(m, 0) + 1
    return jsonify({"count": len(items), "total_bytes": total, "by_mime": by_mime})


# Serve uploaded media from admin/data/blob/
@app.route("/admin/data/blob/<path:sub>")
def serve_blob(sub):
    p = (BLOB_DIR / sub).resolve()
    if not str(p).startswith(str(BLOB_DIR)) or not p.exists():
        abort(404)
    return send_from_directory(p.parent, p.name)


# ============================================================================
# Templates
# ============================================================================
def _seed_templates_if_empty():
    if (kv_get("templates:index", None) is not None):
        return
    seed = load_json(TEMPLATES_FILE, [])
    if not seed:
        return
    names = []
    for t in seed:
        kv_set(f"template:{t['name']}", t)
        names.append(t["name"])
    kv_set("templates:index", names)


@app.route("/api/templates", methods=["GET", "POST"])
def api_templates():
    if require_login():
        return jsonify({"error": "auth"}), 401
    _seed_templates_if_empty()
    if request.method == "GET":
        names = kv_get("templates:index", []) or []
        items = []
        for n in names:
            t = kv_get(f"template:{n}", None)
            if t:
                items.append({
                    "name": t["name"],
                    "slug_pattern": t.get("slug_pattern", ""),
                    "description": t.get("description", ""),
                    "variables": t.get("variables", []),
                })
        return jsonify({"items": items})
    body = request.get_json(silent=True) or {}
    if not body.get("name"):
        return jsonify({"error": "name ontbreekt"}), 400
    body["created_at"] = datetime.now().isoformat(timespec="seconds")
    body["updated_at"] = body["created_at"]
    kv_set(f"template:{body['name']}", body)
    names = kv_get("templates:index", []) or []
    if body["name"] not in names:
        names.append(body["name"])
        kv_set("templates:index", names)
    return jsonify(body), 201


@app.route("/api/templates/<name>", methods=["GET", "PUT", "DELETE"])
def api_template_detail(name):
    if require_login():
        return jsonify({"error": "auth"}), 401
    _seed_templates_if_empty()
    tpl = kv_get(f"template:{name}", None)
    if request.method == "GET":
        if not tpl:
            return jsonify({"error": "not found"}), 404
        return jsonify(tpl)
    if request.method == "DELETE":
        kv_delete(f"template:{name}")
        names = [n for n in (kv_get("templates:index", []) or []) if n != name]
        kv_set("templates:index", names)
        return jsonify({"deleted": True})
    body = request.get_json(silent=True) or {}
    if not tpl:
        tpl = {"name": name, "created_at": datetime.now().isoformat(timespec="seconds")}
    for k in ("slug_pattern", "content_blocks", "variables", "default_meta", "description"):
        if k in body:
            tpl[k] = body[k]
    tpl["updated_at"] = datetime.now().isoformat(timespec="seconds")
    kv_set(f"template:{name}", tpl)
    return jsonify({"name": name, "updated_at": tpl["updated_at"]})


@app.route("/api/templates/<name>/apply", methods=["POST"])
def api_template_apply(name):
    if require_login():
        return jsonify({"error": "auth"}), 401
    _seed_templates_if_empty()
    tpl = kv_get(f"template:{name}", None)
    if not tpl:
        return jsonify({"error": "template not found"}), 404
    body = request.get_json(silent=True) or {}
    variables = body.get("variables", {})
    slug = body.get("slug_override") or slugify(
        substitute_vars(tpl.get("slug_pattern", "{slug}"), variables)
    )
    if not slug:
        return jsonify({"error": "kon geen slug bepalen"}), 400
    if get_page(slug):
        return jsonify({"error": "pagina bestaat al"}), 409
    blocks = apply_template_vars(tpl.get("content_blocks", []), variables)
    page = {
        "slug": slug,
        "title": substitute_vars(variables.get("title")
                                 or tpl.get("default_title", slug), variables),
        "status": "draft", "template": name, "locale": "nl",
        "author": current_user(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "meta": json.loads(json.dumps(tpl.get("default_meta", {}))),
        "content_blocks": blocks,
    }
    save_page(page)
    audit(current_user(), "template.apply", name, f"-> {slug}")
    return jsonify({"slug": slug, "title": page["title"], "status": "draft"})


@app.route("/api/templates/<name>/bulk-apply", methods=["POST"])
def api_template_bulk_apply(name):
    if require_login():
        return jsonify({"error": "auth"}), 401
    _seed_templates_if_empty()
    tpl = kv_get(f"template:{name}", None)
    if not tpl:
        return jsonify({"error": "template not found"}), 404
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "csv ontbreekt"}), 400
    reader = csv.DictReader(io.StringIO(f.read().decode("utf-8", errors="replace")))
    created, failed = [], []
    for row in reader:
        try:
            variables = dict(row)
            slug = slugify(substitute_vars(tpl.get("slug_pattern", "{slug}"), variables))
            if not slug or get_page(slug):
                failed.append({"row": row, "error": "slug invalid/exists"}); continue
            blocks = apply_template_vars(tpl.get("content_blocks", []), variables)
            page = {
                "slug": slug,
                "title": substitute_vars(variables.get("title", slug), variables),
                "status": "draft", "template": name, "locale": "nl",
                "author": current_user(),
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "meta": json.loads(json.dumps(tpl.get("default_meta", {}))),
                "content_blocks": blocks,
            }
            save_page(page)
            created.append(slug)
        except Exception as e:
            failed.append({"row": row, "error": str(e)})
    return jsonify({"created": created, "failed": failed})


# ============================================================================
# Menus
# ============================================================================
@app.route("/api/menus")
def api_menus():
    if require_login():
        return jsonify({"error": "auth"}), 401
    names = kv_get("menus:index", ["main", "footer"]) or ["main", "footer"]
    out = []
    for n in names:
        m = kv_get(f"menu:{n}", {"name": n, "items": []})
        out.append(m)
    return jsonify({"menus": out})


@app.route("/api/menus/<name>", methods=["PUT"])
def api_menu_update(name):
    if require_login():
        return jsonify({"error": "auth"}), 401
    body = request.get_json(silent=True) or {}
    menu = {"name": name, "items": body.get("items", []),
            "updated_at": datetime.now().isoformat(timespec="seconds")}
    kv_set(f"menu:{name}", menu)
    names = kv_get("menus:index", ["main", "footer"]) or []
    if name not in names:
        names.append(name)
        kv_set("menus:index", names)
    audit(current_user(), "menu.update", name, "")
    return jsonify({"name": name, "updated_at": menu["updated_at"]})


# ============================================================================
# Sitemap + robots + redirects
# ============================================================================
@app.route("/api/sitemap/regenerate", methods=["POST"])
def api_sitemap_regenerate():
    if require_login():
        return jsonify({"error": "auth"}), 401
    urls = []
    for entry in get_pages_index():
        if entry.get("status") == "published":
            urls.append(f"/{entry['slug']}/")
    for sp in list_static_pages():
        urls.append(sp["url"])
    urls = sorted(set(urls))
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for u in urls:
        xml += f"  <url><loc>{u}</loc></url>\n"
    xml += "</urlset>\n"
    blob_path = BLOB_DIR / "sitemap.xml"
    blob_path.write_text(xml, encoding="utf-8")
    meta = {"last_generated": datetime.now().isoformat(timespec="seconds"),
            "last_pinged": {"google": None, "bing": None},
            "urls_count": len(urls),
            "blob_url": "/admin/data/blob/sitemap.xml"}
    kv_set("sitemap:meta", meta)
    audit(current_user(), "sitemap.regenerate", "sitemap", f"{len(urls)} urls")
    return jsonify({"urls_count": len(urls),
                    "blob_url": meta["blob_url"],
                    "generated_at": meta["last_generated"]})


@app.route("/api/sitemap/ping", methods=["POST"])
def api_sitemap_ping():
    if require_login():
        return jsonify({"error": "auth"}), 401
    body = request.get_json(silent=True) or {}
    targets = body.get("targets", ["google", "bing"])
    out = {}
    for t in targets:
        out[t] = {"ok": False, "status": "deprecated (use Search Console API)"}
    meta = kv_get("sitemap:meta", {}) or {}
    meta.setdefault("last_pinged", {})
    for t in targets:
        meta["last_pinged"][t] = datetime.now().isoformat(timespec="seconds")
    kv_set("sitemap:meta", meta)
    return jsonify(out)


@app.route("/api/redirects", methods=["GET", "POST"])
def api_redirects():
    if require_login():
        return jsonify({"error": "auth"}), 401
    if request.method == "GET":
        return jsonify({"items": kv_get("redirects:index", []) or []})
    body = request.get_json(silent=True) or {}
    rid = uuid.uuid4().hex[:10]
    item = {
        "id": rid,
        "from_path": body.get("from_path", ""),
        "to_path": body.get("to_path", ""),
        "code": int(body.get("code", 301)),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "hit_count": 0,
    }
    redirects = kv_get("redirects:index", []) or []
    redirects.append(item)
    kv_set("redirects:index", redirects)
    kv_set(f"redirect:{rid}", item)
    return jsonify(item), 201


@app.route("/api/redirects/<rid>", methods=["DELETE"])
def api_redirect_delete(rid):
    if require_login():
        return jsonify({"error": "auth"}), 401
    redirects = [r for r in (kv_get("redirects:index", []) or []) if r.get("id") != rid]
    kv_set("redirects:index", redirects)
    kv_delete(f"redirect:{rid}")
    return jsonify({"deleted": True})


@app.route("/api/robots-txt", methods=["GET", "PUT"])
def api_robots_txt():
    if require_login():
        return jsonify({"error": "auth"}), 401
    if request.method == "GET":
        r = kv_get("robots_txt", None)
        if not r:
            try:
                content = (ROOT / "robots.txt").read_text(encoding="utf-8")
            except Exception:
                content = "User-agent: *\nAllow: /\n"
            r = {"content": content, "updated_at": None}
        return jsonify(r)
    body = request.get_json(silent=True) or {}
    content = body.get("content", "")
    rec = {"content": content,
           "updated_at": datetime.now().isoformat(timespec="seconds"),
           "updated_by": current_user()}
    kv_set("robots_txt", rec)
    blob_path = BLOB_DIR / "robots.txt"
    blob_path.write_text(content, encoding="utf-8")
    return jsonify({"updated_at": rec["updated_at"],
                    "blob_url": "/admin/data/blob/robots.txt"})


# ============================================================================
# SEO
# ============================================================================
@app.route("/api/seo/overview")
def api_seo_overview():
    if require_login():
        return jsonify({"error": "auth"}), 401
    missing_only = request.args.get("missing_only") == "1"
    items = []
    scores = kv_get("seo_scores", {}) or {}
    for entry in get_pages_index():
        page = get_page(entry["slug"])
        if not page:
            continue
        s = scores.get(entry["slug"]) or compute_seo_score(page)
        if missing_only and not s["issues"]:
            continue
        items.append({"slug": entry["slug"], "title": page.get("title"),
                      "meta": page.get("meta", {}),
                      "score": s["score"], "issues": s["issues"]})
    return jsonify({"items": items})


@app.route("/api/seo/meta/<slug>", methods=["PATCH"])
def api_seo_meta(slug):
    if require_login():
        return jsonify({"error": "auth"}), 401
    page = get_page(slug)
    if not page:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(silent=True) or {}
    page.setdefault("meta", {}).update(body)
    save_page(page)
    s = compute_seo_score(page)
    scores = kv_get("seo_scores", {}) or {}
    scores[slug] = s
    kv_set("seo_scores", scores)
    return jsonify({"slug": slug, "meta": page["meta"]})


@app.route("/api/seo/bulk", methods=["POST"])
def api_seo_bulk():
    if require_login():
        return jsonify({"error": "auth"}), 401
    body = request.get_json(silent=True) or {}
    slugs, meta_updates = body.get("slugs", []), body.get("meta_updates", {})
    updated, failed = 0, []
    for sl in slugs:
        page = get_page(sl)
        if not page:
            failed.append({"slug": sl, "error": "not found"}); continue
        page.setdefault("meta", {}).update(meta_updates)
        save_page(page)
        updated += 1
    return jsonify({"updated": updated, "failed": failed})


@app.route("/api/links/audit", methods=["POST"])
def api_links_audit():
    if require_login():
        return jsonify({"error": "auth"}), 401
    body = request.get_json(silent=True) or {}
    scope = body.get("scope", "all")
    results = []
    targets = []
    if scope == "all":
        targets = [e["slug"] for e in get_pages_index()]
    elif isinstance(scope, list):
        targets = scope
    for sl in targets:
        page = get_page(sl)
        if not page:
            continue
        for b in page.get("content_blocks", []):
            url = (b.get("props") or {}).get("url")
            if not url:
                continue
            results.append({"page_slug": sl, "link": url,
                            "status_code": 200,
                            "type": "internal" if url.startswith("/") else "external"})
    rec = {"ran_at": datetime.now().isoformat(timespec="seconds"), "results": results}
    kv_set("broken_links:last", rec)
    return jsonify(rec)


# ============================================================================
# AI chat (stub — calls Anthropic if api_key configured)
# ============================================================================
def _anthropic_call(prompt: str, system: str = "", model: str = "claude-sonnet-4-5",
                    max_tokens: int = 1024) -> dict:
    settings = get_settings()
    key = settings.get("ai", {}).get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"ok": False, "error": "no api key", "response": ""}
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps({
                "model": model, "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            }).encode("utf-8"),
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        text = "".join(b.get("text", "") for b in data.get("content", []))
        return {"ok": True, "response": text, "tokens": data.get("usage", {})}
    except Exception as e:
        return {"ok": False, "error": str(e), "response": ""}


@app.route("/api/page-chat", methods=["POST"])
def api_page_chat():
    if require_login():
        return jsonify({"error": "auth"}), 401
    body = request.get_json(silent=True) or {}
    slug = body.get("slug")
    message = body.get("message", "")
    current_blocks = body.get("current_blocks", [])
    chat_hist = kv_get(f"ai:chat:{slug}", []) or []
    chat_hist.append({"role": "user", "content": message,
                      "ts": datetime.now().isoformat(timespec="seconds")})
    system = ("Je bent een CMS-assistent voor een Nederlandstalige stukadoor-website. "
              "Antwoord beknopt en stel waar nodig structured proposed_changes voor.")
    prompt = (f"Huidige blocks: {json.dumps(current_blocks)[:4000]}\n\n"
              f"Vraag: {message}")
    ai = _anthropic_call(prompt, system=system)
    resp_text = ai.get("response") or "AI is niet geconfigureerd. Stel je ANTHROPIC_API_KEY in via /api/settings."
    chat_hist.append({"role": "assistant", "content": resp_text,
                      "ts": datetime.now().isoformat(timespec="seconds"),
                      "proposed_changes": []})
    kv_set(f"ai:chat:{slug}", chat_hist[-50:])
    return jsonify({"response": resp_text, "proposed_changes": []})


@app.route("/api/page-chat/apply", methods=["POST"])
def api_page_chat_apply():
    if require_login():
        return jsonify({"error": "auth"}), 401
    body = request.get_json(silent=True) or {}
    slug = body.get("slug")
    page = get_page(slug)
    if not page:
        return jsonify({"error": "not found"}), 404
    save_page(page)
    return jsonify({"slug": slug,
                    "new_blocks": page.get("content_blocks", []),
                    "updated_at": page["updated_at"]})


@app.route("/api/ai-test", methods=["POST"])
def api_ai_test():
    if require_login():
        return jsonify({"error": "auth"}), 401
    body = request.get_json(silent=True) or {}
    prompt = body.get("prompt") or "Zeg hallo in 1 zin."
    ai = _anthropic_call(prompt)
    return jsonify({"ok": ai.get("ok"), "response": ai.get("response"),
                    "model": get_settings().get("ai", {}).get("model"),
                    "tokens": ai.get("tokens", {})})


# ============================================================================
# Dashboard / audit / integrations / users
# ============================================================================
@app.route("/api/dashboard/stats")
def api_dashboard_stats():
    if require_login():
        return jsonify({"error": "auth"}), 401
    items = get_pages_index() or [
        {"slug": p["slug"], "status": "published"} for p in list_static_pages()
    ]
    pub = sum(1 for i in items if i.get("status") == "published")
    draft = sum(1 for i in items if i.get("status") == "draft")
    trashed = sum(1 for i in items if i.get("status") == "trashed")
    leads = get_leads()
    open_leads = sum(1 for l in leads if l.get("stage") not in ("closed", "lost"))
    media_items = _media_index()
    media_bytes = sum(i.get("bytes", 0) for i in media_items)
    scores = kv_get("seo_scores", {}) or {}
    avg = int(sum(s.get("score", 0) for s in scores.values()) / max(1, len(scores))) if scores else 0
    broken = len((kv_get("broken_links:last", {}) or {}).get("results", []))
    sm = kv_get("sitemap:meta", {}) or {}
    return jsonify({
        "pages": {"published": pub, "draft": draft, "trashed": trashed},
        "leads": {"open": open_leads, "total": len(leads)},
        "media": {"count": len(media_items), "bytes": media_bytes},
        "avg_seo_score": avg,
        "broken_links_count": broken,
        "sitemap": {"last_generated": sm.get("last_generated"),
                    "urls_count": sm.get("urls_count", 0)},
    })


@app.route("/api/audit-log")
def api_audit_log():
    if require_login():
        return jsonify({"error": "auth"}), 401
    log = kv_get("audit:log", []) or []
    user = request.args.get("user")
    action = request.args.get("action")
    if user:
        log = [l for l in log if l.get("user") == user]
    if action:
        log = [l for l in log if action in l.get("action", "")]
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        limit = 50
    return jsonify({"items": log[:limit], "total": len(log)})


@app.route("/api/integrations/health")
def api_integrations_health():
    if require_login():
        return jsonify({"error": "auth"}), 401
    t0 = time.time()
    kv_get("settings", None)
    blob_ok = BLOB_DIR.exists()
    ai_key = bool(get_settings().get("ai", {}).get("api_key")
                  or os.environ.get("ANTHROPIC_API_KEY"))
    smtp_ok = bool(get_settings().get("smtp", {}).get("host"))
    return jsonify({
        "blob": {"ok": blob_ok, "latency_ms": int((time.time() - t0) * 1000)},
        "kv": {"ok": True},
        "ai": {"ok": ai_key, "model": get_settings().get("ai", {}).get("model")},
        "smtp": {"ok": smtp_ok},
    })


@app.route("/api/users", methods=["GET", "POST"])
def api_users():
    if require_login():
        return jsonify({"error": "auth"}), 401
    users = kv_get("users", None)
    if users is None:
        users = [{"username": u, "role": "admin",
                  "created_at": datetime.now().isoformat(timespec="seconds")}
                 for u in USERS]
    if request.method == "GET":
        return jsonify({"items": users})
    body = request.get_json(silent=True) or {}
    if not body.get("username") or not body.get("password"):
        return jsonify({"error": "username + password required"}), 400
    rec = {"username": body["username"], "role": body.get("role", "editor"),
           "password_hash": body["password"],  # demo only
           "created_at": datetime.now().isoformat(timespec="seconds")}
    users.append(rec)
    kv_set("users", users)
    return jsonify({"username": rec["username"], "role": rec["role"]})


@app.route("/api/users/<username>", methods=["DELETE"])
def api_user_delete(username):
    if require_login():
        return jsonify({"error": "auth"}), 401
    users = kv_get("users", []) or []
    users = [u for u in users if u.get("username") != username]
    kv_set("users", users)
    return jsonify({"deleted": True})


# ============================================================================
# Public render proxy (serves published HTML from blob)
# ============================================================================
@app.route("/api/render/<slug>")
def api_render(slug):
    blob_path = BLOB_DIR / f"pages/{slug}.html"
    if blob_path.exists():
        return Response(blob_path.read_text(encoding="utf-8"), mimetype="text/html")
    page = get_page(slug)
    if not page:
        abort(404)
    return Response(render_page_html(page), mimetype="text/html")


# ============================================================================
# Static site fallthrough
# ============================================================================
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path: str):
    # Check custom redirects first
    redirects = kv_get("redirects:index", []) or []
    incoming = "/" + path
    if not incoming.endswith("/"):
        incoming_alt = incoming + "/"
    else:
        incoming_alt = incoming
    for r in redirects:
        if r.get("from_path") in (incoming, incoming_alt):
            return redirect(r["to_path"], code=int(r.get("code", 301)))
    file_path = (ROOT / path).resolve()
    if not str(file_path).startswith(str(ROOT)):
        abort(404)
    if file_path.is_dir():
        idx = file_path / "index.html"
        if idx.exists():
            return send_from_directory(file_path, "index.html")
        abort(404)
    if file_path.is_file():
        return send_from_directory(file_path.parent, file_path.name)
    alt = (ROOT / path / "index.html")
    if alt.exists():
        return send_from_directory(alt.parent, "index.html")
    abort(404)


# ============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"Wandmeesters server running on http://localhost:{port}")
    print(f"Admin login: http://localhost:{port}/inloggen  (admin/admin)")
    _seed_templates_if_empty()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
