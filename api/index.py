"""Wandmeesters serverless backend (Vercel @vercel/python).

Routes:
  /inloggen            login form (POST/GET)
  /uitloggen           logout
  /admin/              admin SPA (auth-required, serves admin/index.html)
  /admin/<sub>         admin static assets (auth-required)
  /api/submit          public lead-intake (called from site forms)
  /api/pages           pages list (auth)
  /api/sitemap         site tree (auth)
  /api/media           media listing (auth)
  /api/leads           list/patch/delete leads (auth)
  /api/settings        SMTP + email templates (auth)
  /api/smtp-test       send a test e-mail (auth)
  /api/chat            chatbot command parser (auth)

Storage:
  Vercel KV via REST API.  Env vars expected:
    KV_REST_API_URL, KV_REST_API_TOKEN
  When unset (e.g. local dev), the code falls back to file storage under /tmp.
"""
from __future__ import annotations
import os, re, json, secrets, smtplib, ssl, uuid, urllib.request, urllib.parse, base64, io, csv, hashlib, time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, request, session, redirect, jsonify, send_from_directory, abort, render_template_string, Response, make_response

# Locate the project root (one level above /api)
ROOT = Path(__file__).resolve().parent.parent
ADMIN_DIR = ROOT / "admin"

# Auth ----------------------------------------------------------------------
USERS = {"admin": os.environ.get("ADMIN_PASSWORD", "admin")}
SECRET = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

# KV REST -------------------------------------------------------------------
KV_URL = os.environ.get("KV_REST_API_URL", "").rstrip("/")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN", "")
# Local fallback: prefer admin/data/kv (writable on dev), fall back to /tmp (writable on Vercel runtime)
_LOCAL_KV_DIR = Path(__file__).resolve().parent.parent / "admin" / "data" / "kv"
try:
    _LOCAL_KV_DIR.mkdir(parents=True, exist_ok=True)
    FALLBACK_DIR = _LOCAL_KV_DIR
except OSError:
    FALLBACK_DIR = Path("/tmp/wandmeesters")
    FALLBACK_DIR.mkdir(parents=True, exist_ok=True)

# Read-only bootstrap (bundled met de lambda). Bevat alle gemigreerde pages
# uit de statische HTML. Gebruikt als KV én FALLBACK_DIR niets opleveren.
_BOOTSTRAP_PATH = Path(__file__).resolve().parent / "data" / "pages-bootstrap.json"
_BOOTSTRAP_PAGES: dict = {}
_BOOTSTRAP_PAGES_INDEX: list = []
try:
    if _BOOTSTRAP_PATH.exists():
        _bdata = json.loads(_BOOTSTRAP_PATH.read_text("utf-8"))
        _BOOTSTRAP_PAGES = _bdata.get("pages", {}) or {}
        _BOOTSTRAP_PAGES_INDEX = _bdata.get("pages_index", []) or []
except Exception:
    pass


def _bootstrap_lookup(key: str):
    """Read-only fallback voor pages-bootstrap. Returns None als niet gevonden."""
    if key == "pages:index" and _BOOTSTRAP_PAGES_INDEX:
        return _BOOTSTRAP_PAGES_INDEX
    if key in _BOOTSTRAP_PAGES:
        return _BOOTSTRAP_PAGES[key]
    return None


def _safe_kv_filename(key: str) -> str:
    """Make a KV key safe for use as a filename."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", key)


def _kv_request(path: str, body: dict | None = None) -> dict:
    url = f"{KV_URL}/{path}"
    headers = {"Authorization": f"Bearer {KV_TOKEN}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


def kv_get(key: str, default=None):
    if not KV_URL:
        f = FALLBACK_DIR / f"{_safe_kv_filename(key)}.json"
        if f.exists():
            return json.loads(f.read_text("utf-8"))
        # Bootstrap fallback (read-only) — voor productie zonder KV
        boot = _bootstrap_lookup(key)
        return boot if boot is not None else default
    try:
        r = _kv_request(f"get/{urllib.parse.quote(key, safe='')}")
        v = r.get("result")
        if v is None:
            # KV is empty for this key → fall back to bootstrap
            boot = _bootstrap_lookup(key)
            return boot if boot is not None else default
        try: return json.loads(v)
        except (TypeError, ValueError): return v
    except Exception:
        boot = _bootstrap_lookup(key)
        return boot if boot is not None else default


def kv_set(key: str, value) -> bool:
    if not KV_URL:
        f = FALLBACK_DIR / f"{_safe_kv_filename(key)}.json"
        f.write_text(json.dumps(value, ensure_ascii=False), "utf-8")
        return True
    try:
        body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        url = f"{KV_URL}/set/{urllib.parse.quote(key, safe='')}"
        req = urllib.request.Request(
            url, data=body.encode("utf-8"),
            headers={"Authorization": f"Bearer {KV_TOKEN}", "Content-Type": "text/plain"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            json.loads(r.read())
        return True
    except Exception as e:
        print(f"KV set failed: {e}")
        return False


def kv_delete(key: str) -> bool:
    """Delete a KV key. Returns True on success."""
    if not KV_URL:
        f = FALLBACK_DIR / f"{_safe_kv_filename(key)}.json"
        try:
            if f.exists(): f.unlink()
            return True
        except OSError:
            return False
    try:
        url = f"{KV_URL}/del/{urllib.parse.quote(key, safe='')}"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {KV_TOKEN}"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            json.loads(r.read())
        return True
    except Exception as e:
        print(f"KV delete failed: {e}")
        return False


def kv_list(prefix: str) -> list[str]:
    """List all keys with a given prefix. Uses Upstash SCAN in prod, local listing in dev.
    Augmenteert met bootstrap-keys zodat gemigreerde pages zichtbaar zijn ook als KV leeg is."""
    boot_keys = [k for k in _BOOTSTRAP_PAGES.keys() if k.startswith(prefix)]
    if not KV_URL:
        out = []
        safe_prefix = _safe_kv_filename(prefix)
        for f in FALLBACK_DIR.glob("*.json"):
            name = f.stem
            if name.startswith(safe_prefix):
                out.append(name)
        # Union met bootstrap (safe-decoded vorm zou anders zijn — caller resolved via kv_get)
        # We returnen original keys uit bootstrap, NIET safe-names — callers gebruiken die voor kv_get
        for bk in boot_keys:
            safe = _safe_kv_filename(bk)
            if safe not in out:
                out.append(safe)
        return out
    try:
        cursor = "0"
        keys: list[str] = []
        for _ in range(20):
            path = (
                f"scan/{cursor}/match/{urllib.parse.quote(prefix + '*', safe='')}/count/100"
            )
            r = _kv_request(path)
            res = r.get("result") or []
            if isinstance(res, list) and len(res) == 2:
                cursor, batch = res[0], res[1]
                keys.extend(batch)
                if str(cursor) == "0":
                    break
            else:
                break
        # Voeg bootstrap-keys toe die nog niet in KV staan
        seen = set(keys)
        for bk in boot_keys:
            if bk not in seen:
                keys.append(bk)
        return keys
    except Exception as e:
        print(f"KV list failed: {e}")
        return []


# Config --------------------------------------------------------------------
PIPELINE_STAGES = [
    {"id": "ontvangen",  "label": "Offerte ontvangen", "color": "#0a5cad"},
    {"id": "contact",    "label": "Contact aanvraag",  "color": "#1d4ed8"},
    {"id": "gebeld",     "label": "Gebeld",            "color": "#7c3aed"},
    {"id": "ingepland",  "label": "Ingepland",         "color": "#d97706"},
    {"id": "closed",     "label": "Closed",            "color": "#059669"},
    {"id": "lost",       "label": "Lost",              "color": "#6b7280"},
]
STAGE_IDS = [s["id"] for s in PIPELINE_STAGES]

DEFAULT_SETTINGS = {
    "smtp": {
        "host":       "smtp.strato.com",
        "port":       587,
        "user":       "email@mhsmedia.email",
        "password":   "TeamMHSMedia23@",
        "from_email": "email@mhsmedia.email",
        "from_name":  "Wandmeesters",
        "use_tls":    True,
    },
    # Mail 1 → company
    "company_email":    "info@wandmeesters.nl",
    "company_bcc":      "marjolein@mhsmedia.nl, julian@mhsmedia.nl, morris@mhsmedia.nl",
    "company_reply_to": "[field id=\"field_574f21f\"]",
    "template_company": {
        "subject":      "Nieuwe offerte aanvraag van [field id=\"name\"]",
        "body":         "[all-fields]",
        "content_type": "html",
    },
    # Mail 2 → customer
    "customer_to":       "[field id=\"field_574f21f\"]",
    "customer_bcc":      "marjolein@mhsmedia.nl",
    "customer_reply_to": "info@wandmeesters.nl",
    "template_customer": {
        "subject":      "We hebben je offerte aanvraag ontvangen!",
        "body": (
            "Hoi [field id=\"name\"],\n"
            "<br><br>\n"
            "We hebben uw aanvraag succesvol ontvangen. Op basis van de aangeleverde informatie zullen wij zo snel mogelijk contact met u opnemen om uw vraag te bespreken en om te kijken hoe wij u verder van dienst kunnen zijn.\n"
            "<br><br>\n"
            "Met vriendelijke groet,\n"
            "<br><br>\n"
            "Wandmeesters\n"
            "<br><br>\n"
            "<b>Overzicht aanvraag:</b> <br>\n"
            "[all-fields]\n"
        ),
        "content_type": "html",
    },
    # Gemiddelde offerte-waarde (EUR) — gebruikt voor dashboard omzet berekening
    "avg_quote_value": 2500,
    # Review-funnel (Kittenvoegen-extension)
    "review_gate_threshold": 4,
    "review_google_url": "",
    "review_feedback_email": "",
    "review_company_name": "Wandmeesters",
    "review_logo_url": "/wp-content/uploads/external-cache/logo-wandmeesters.webp",
    "review_email_subject": "Bedankt voor uw vertrouwen — laat een review achter",
    "review_email_intro": "Bedankt voor de samenwerking! Hoe tevreden bent u over ons werk?",
}

# Friendly labels for shortcode rendering ([all-fields] table)
FIELD_LABELS = {
    "name":         "Naam",
    "email":        "E-mailadres",
    "telefoon":     "Telefoonnummer",
    "woonplaats":   "Woonplaats",
    "soort_woning": "Soort woning",
    "m2":           "M² van de woning",
    "pakket":       "Gewenste pakket",
    "startdatum":   "Gewenste startdatum",
    "source_url":   "Aangevraagd via",
}

# Elementor field-ID → ctx-key aliases so shortcodes like [field id="field_574f21f"]
# resolve correctly. Mirrors the mapping in the front-end form-intercept JS.
FIELD_ID_ALIASES = {
    "field_ac897d8": "soort_woning",
    "field_3028dcc": "m2",
    "field_bd15801": "pakket",
    "field_6b35b98": "startdatum",
    "field_45bf4d6": "woonplaats",
    "field_574f21f": "email",          # the real e-mail input
    # NB: "email" werd vroeger gealiased naar "telefoon" omdat Elementor het tel-veld
    # "email" had genoemd. De frontend JS doet die mapping al voor verzending — als we
    # die alias hier OOK toepassen overschrijven we de échte email met het telefoonnummer.
    # Dus expres weggelaten.
    "name":          "name",
    "Naam":          "name",
    "E-mail":        "email",
    "Telefoonnummer":"telefoon",
}


def get_settings() -> dict:
    s = kv_get("settings", {}) or {}
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    for k, v in s.items():
        if isinstance(v, dict) and k in out:
            out[k].update(v)
        else:
            out[k] = v
    return out


def get_leads() -> list:
    return kv_get("leads", []) or []


def save_leads(leads):
    kv_set("leads", leads)


# App -----------------------------------------------------------------------
app = Flask(__name__, static_folder=None)
app.secret_key = SECRET
app.url_map.strict_slashes = False
# Sessions across serverless invocations need a SameSite=None + Secure cookie when
# the form on the static site posts to the API via fetch. Flask defaults are fine
# for first-party requests, so keep them.


def is_logged_in() -> bool:
    return session.get("user") in USERS


def require_login():
    if not is_logged_in():
        return redirect("/inloggen?next=" + urllib.parse.quote(request.path))
    return None


# ----- helpers for static-site browsing -----
# Pre-built indexes bundled with the function (Vercel excludes wp-content from the
# lambda for size; we read these JSONs instead of scanning the filesystem).
_INDEX_DIR = Path(__file__).resolve().parent / "data"


def _load_index(name: str, default):
    p = _INDEX_DIR / name
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return default


def list_pages() -> list:
    return _load_index("pages-index.json", [])


def sitemap_tree() -> dict:
    return _load_index("sitemap-tree.json", {"name": "/", "url": "/", "children": {}, "title": None})


def list_media(subdir="wp-content/uploads") -> list:
    return _load_index("media-index.json", [])


# ----- chatbot -----
SERVICE_TEMPLATE = """<!DOCTYPE html>
<html lang="nl"><head><meta charset="UTF-8"><title>{title} - Wandmeesters</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/wp-content/uploads/animations-disable.css?v=8">
<style>body{{font-family:Poppins,sans-serif;margin:0;color:#1f2937;line-height:1.6}}.hero{{background:linear-gradient(135deg,#0a5cad,#347677);color:#fff;padding:80px 24px;text-align:center}}.hero h1{{font-size:2.5rem;margin:0 0 12px;font-weight:700}}.hero p{{max-width:680px;margin:0 auto;opacity:.92;font-size:1.1rem}}.container{{max-width:920px;margin:0 auto;padding:48px 24px}}.card{{background:#fff;border-radius:10px;box-shadow:0 6px 22px rgba(0,0,0,.06);padding:32px;margin-bottom:24px}}.cta{{display:inline-block;background:#0a5cad;color:#fff;padding:14px 30px;border-radius:6px;text-decoration:none;font-weight:600;margin-top:16px}}nav{{background:#fff;padding:16px 24px;display:flex;gap:20px;border-bottom:1px solid #e5e7eb}}nav a{{color:#1f2937;text-decoration:none;font-weight:500}}footer{{background:#1f2937;color:#cbd5e1;padding:32px 24px;text-align:center}}</style></head>
<body><nav><a href="/">Home</a><a href="/diensten/">Diensten</a><a href="/over-ons/">Over ons</a><a href="/contact/">Contact</a></nav>
<header class="hero"><h1>{title}</h1><p>{intro}</p></header>
<main class="container"><div class="card"><h2>Over {title_lower}</h2><p>{body}</p><a class="cta" href="/contact/">Vraag een offerte aan</a></div></main>
<footer>© Wandmeesters</footer></body></html>
"""


def slugify(t): return re.sub(r"-+", "-", re.sub(r"\s+", "-", re.sub(r"[^a-z0-9\s-]", "", t.lower().strip()))).strip("-")


def cmd_add_page(args):
    parent = args.get("parent", "/").strip("/")
    name = args.get("name", "").strip()
    if not name: return {"ok": False, "error": "Naam ontbreekt"}
    slug = slugify(name)
    if not slug: return {"ok": False, "error": "Naam levert geen geldige URL slug op"}
    target = ROOT / (parent or "") / slug
    rel = target.relative_to(ROOT)
    if target.exists(): return {"ok": False, "error": f"Pagina /{rel}/ bestaat al"}
    # Serverless filesystem is read-only on Vercel — write to /tmp instead is not visible to next request
    # Store in KV as virtual page
    pages = kv_get("virtual_pages", {}) or {}
    url = f"/{rel}/"
    if url in pages: return {"ok": False, "error": "Pagina bestaat al"}
    pages[url] = {
        "title": name, "intro": args.get("intro") or f"Professioneel {name.lower()} door Wandmeesters.",
        "body": args.get("body") or f"Wij verzorgen {name.lower()} op maat. Voor een vrijblijvende offerte neem contact met ons op.",
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    kv_set("virtual_pages", pages)
    return {"ok": True, "message": f"Pagina aangemaakt: {url}", "url": url}


def cmd_list_pages(_args):
    p = list_pages()
    vp = kv_get("virtual_pages", {}) or {}
    for url, meta in vp.items():
        p.append({"url": url, "slug": url.strip("/"), "title": meta.get("title", url),
                  "path": "virtual", "size_kb": 0, "modified": meta.get("created", "")})
    return {"ok": True, "data": p, "count": len(p)}


def cmd_delete_page(args):
    page = args.get("page", "").strip("/")
    if not page: return {"ok": False, "error": "Pagina-URL ontbreekt"}
    if page in {"", "contact", "diensten", "over-ons", "projecten"}:
        return {"ok": False, "error": "Hoofdpagina mag niet verwijderd worden"}
    # Try virtual pages first
    url = f"/{page}/"
    vp = kv_get("virtual_pages", {}) or {}
    if url in vp:
        del vp[url]
        kv_set("virtual_pages", vp)
        return {"ok": True, "message": f"Virtuele pagina {url} verwijderd"}
    return {"ok": False, "error": "Statische pagina's kunnen niet via runtime verwijderd worden — bewerk de repo en deploy opnieuw."}


def cmd_edit_text(args):
    return {"ok": False, "error": "Tekst-edits op statische pagina's vereisen een redeploy. Gebruik git/Vercel."}


COMMAND_HANDLERS = {
    "add_page": cmd_add_page, "list_pages": cmd_list_pages,
    "delete_page": cmd_delete_page, "edit_text": cmd_edit_text,
}


def parse_chat(message):
    low = message.lower().strip()
    m = re.search(r"voeg(?:\s+(?:een|de))?\s+pagina\s+(?:toe\s+)?(?:voor|over)\s+(.+?)(?:\s+(?:in|onder)\s+(/\S+))?$", low)
    if m: return {"command": "add_page", "args": {"name": m.group(1).strip(".!? "), "parent": m.group(2) or "/diensten/"}}
    if low.startswith(("maak een pagina", "nieuwe pagina")):
        m = re.search(r"voor\s+(.+)", low)
        if m: return {"command": "add_page", "args": {"name": m.group(1).strip(".!? "), "parent": "/diensten/"}}
    if re.search(r"(toon|laat|geef|alle|lijst)\s+.*(pagina|pages)", low):
        return {"command": "list_pages", "args": {}}
    m = re.search(r"verwijder\s+(?:de\s+)?pagina\s+(\S+)", low)
    if m: return {"command": "delete_page", "args": {"page": m.group(1)}}
    m = re.search(r"(?:wijzig|vervang|verander)\s+['\"]?(.+?)['\"]?\s+(?:naar|in|door)\s+['\"]?(.+?)['\"]?\s+op\s+(?:pagina\s+)?(\S+)", message, re.I)
    if m: return {"command": "edit_text", "args": {"find": m.group(1), "replace": m.group(2), "page": m.group(3)}}
    return {"command": None, "error": "Ik begreep dat commando niet."}


# ----- mailing -----
def _build_field_ctx(lead: dict) -> dict:
    """Build a flat context that can resolve every Elementor field shortcode."""
    base = {k: lead.get(k, "") for k in (
        "name", "email", "telefoon", "woonplaats", "soort_woning", "m2", "pakket", "startdatum"
    )}
    # Bouw volledige URL waar de offerte aanvraag vandaan komt
    source = lead.get("source") or "/"
    if source.startswith("http"):
        base["source_url"] = source
    else:
        if not source.startswith("/"): source = "/" + source
        base["source_url"] = "https://wandmeesters.nl" + source
    # Add aliases so [field id="field_574f21f"] resolves to ctx["email"]
    for alias, target in FIELD_ID_ALIASES.items():
        base[alias] = base.get(target, "")
    return base


def render_template_text(tpl, ctx, html: bool = False):
    """Render Elementor-style shortcodes + {placeholder} substitutions.

    Supported shortcodes:
      [field id="key"]   → ctx[key] (key may be alias or direct ctx key)
      [all-fields]       → label: value list of populated fields
                           (rendered as a clean HTML <table> if html=True)
    """
    out = tpl or ""
    # [field id="key"] / [field id='key']
    def _field_sub(m): return str(ctx.get(m.group(1), "") or "")
    out = re.sub(r'\[field\s+id=["\']?([^"\'\]\s]+)["\']?\s*\]', _field_sub, out)
    # [all-fields]
    if "[all-fields]" in out:
        rows = [(label, ctx.get(k, "")) for k, label in FIELD_LABELS.items() if ctx.get(k, "")]
        if html:
            block = (
                '<table cellpadding="6" cellspacing="0" border="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px">'
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
    # Plain {placeholders} (backwards compat)
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
        # Build envelope recipients (incl. all bccs)
        recipients = [to_addr]
        if bcc:
            for b in [x.strip() for x in re.split(r"[,;]+", bcc) if x.strip()]:
                recipients.append(b)
        port = int(s.get("port", 587))
        if port == 465:
            with smtplib.SMTP_SSL(s["host"], port, context=ssl.create_default_context(), timeout=10) as srv:
                if s.get("user"): srv.login(s["user"], s.get("password", ""))
                srv.sendmail(s["from_email"].strip(), recipients, msg.as_string())
        else:
            with smtplib.SMTP(s["host"], port, timeout=10) as srv:
                srv.ehlo()
                if s.get("use_tls", True):
                    srv.starttls(context=ssl.create_default_context()); srv.ehlo()
                if s.get("user"): srv.login(s["user"], s.get("password", ""))
                srv.sendmail(s["from_email"].strip(), recipients, msg.as_string())
        return True, "Verzonden"
    except Exception as e:
        return False, f"SMTP fout: {e}"


def process_lead_emails(lead):
    settings = get_settings()
    ctx = _build_field_ctx(lead)
    is_html = lambda t: (t.get("content_type") == "html")
    # ----- Mail 1: company -----
    company_to = (settings.get("company_email") or "").strip()
    if company_to:
        tpl = settings["template_company"]
        subj = render_template_text(tpl["subject"], ctx)
        body_rendered = render_template_text(tpl["body"], ctx, html=is_html(tpl))
        ok, msg = send_email(
            to_addr=company_to,
            subject=subj,
            body=body_rendered,
            bcc=settings.get("company_bcc"),
            reply_to=render_template_text(settings.get("company_reply_to", ""), ctx) or None,
            content_type="html" if is_html(tpl) else "plain",
        )
        lead.setdefault("emails", []).append({
            "to": "company", "address": company_to,
            "subject": subj, "body": body_rendered,
            "content_type": "html" if is_html(tpl) else "plain",
            "ok": ok, "msg": msg, "ts": datetime.now().isoformat(timespec="seconds")
        })
    # ----- Mail 2: customer -----
    raw_to = settings.get("customer_to") or "[field id=\"field_574f21f\"]"
    customer_to = render_template_text(raw_to, ctx).strip()
    if customer_to and "@" in customer_to:
        tpl = settings["template_customer"]
        subj = render_template_text(tpl["subject"], ctx)
        body_rendered = render_template_text(tpl["body"], ctx, html=is_html(tpl))
        ok, msg = send_email(
            to_addr=customer_to,
            subject=subj,
            body=body_rendered,
            bcc=settings.get("customer_bcc"),
            reply_to=render_template_text(settings.get("customer_reply_to", ""), ctx) or None,
            content_type="html" if is_html(tpl) else "plain",
        )
        lead.setdefault("emails", []).append({
            "to": "customer", "address": customer_to,
            "subject": subj, "body": body_rendered,
            "content_type": "html" if is_html(tpl) else "plain",
            "ok": ok, "msg": msg, "ts": datetime.now().isoformat(timespec="seconds")
        })


# ----- routes -----
LOGIN_HTML = """<!DOCTYPE html><html lang="nl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inloggen — Wandmeesters Admin</title>
<link rel="icon" type="image/webp" href="/favicon.webp">
<meta name="robots" content="noindex, nofollow">
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  body{font-family:'Poppins',-apple-system,BlinkMacSystemFont,sans-serif;background:#f8fafc;background-image:radial-gradient(circle at 80% 20%,rgba(52,118,119,.07),transparent 55%),radial-gradient(circle at 20% 80%,rgba(52,118,119,.05),transparent 55%)}
  .ms-card{box-shadow:0 4px 14px rgba(15,23,42,.04),0 24px 48px rgba(15,23,42,.08);border:1px solid rgba(255,255,255,.6)}
  .ms-input{transition:border-color .2s,background .2s,box-shadow .2s}
  .ms-input:focus{box-shadow:0 0 0 3px rgba(52,118,119,.15)}
  .ms-btn{background:#347677;transition:background .2s,box-shadow .2s,transform .1s}
  .ms-btn:hover{background:#286061;box-shadow:0 6px 18px rgba(52,118,119,.25)}
  .ms-btn:active{transform:translateY(1px)}
  .ms-toggle-pw{transition:color .2s,background .2s}
  .ms-toggle-pw:hover{color:#347677;background:#f1f5f9}
  .ms-back-link:hover{color:#347677}
</style></head>
<body class="min-h-screen flex items-center justify-center p-5">
  <div class="w-full max-w-md">
    <form method="post" class="ms-card bg-white rounded-2xl p-8 sm:p-10">
      <div class="flex flex-col items-center mb-7">
        <img src="/wp-content/uploads/external-cache/logo-wandmeesters.webp" alt="Wandmeesters" class="h-11 mb-5" width="170" height="44">
        <h1 class="text-lg font-bold text-slate-900 tracking-tight">Welkom terug</h1>
        <p class="text-sm text-slate-500 mt-1">Log in om de admin te beheren</p>
      </div>
      {% if error %}<div class="bg-rose-50 border border-rose-200 text-rose-700 text-sm rounded-lg px-4 py-3 mb-5 flex items-start gap-2">
        <svg class="w-5 h-5 flex-shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
        <span>{{ error }}</span>
      </div>{% endif %}
      <div class="mb-4">
        <label class="block text-xs font-semibold text-slate-700 mb-2 uppercase tracking-wider">Gebruikersnaam</label>
        <input name="username" required autofocus autocomplete="username"
          class="ms-input w-full px-4 py-3 border border-slate-200 rounded-lg text-sm bg-slate-50 focus:bg-white focus:outline-none focus:border-[#347677]"
          placeholder="admin">
      </div>
      <div class="mb-6">
        <label class="block text-xs font-semibold text-slate-700 mb-2 uppercase tracking-wider">Wachtwoord</label>
        <div class="relative">
          <input id="pw" name="password" type="password" required autocomplete="current-password"
            class="ms-input w-full px-4 py-3 pr-16 border border-slate-200 rounded-lg text-sm bg-slate-50 focus:bg-white focus:outline-none focus:border-[#347677]"
            placeholder="••••••••">
          <button type="button" onclick="var p=document.getElementById('pw');var v=p.type==='password';p.type=v?'text':'password';this.textContent=v?'Verberg':'Toon';"
            class="ms-toggle-pw absolute right-2 top-1/2 -translate-y-1/2 text-xs text-slate-500 font-semibold px-3 py-1.5 rounded">Toon</button>
        </div>
      </div>
      <button class="ms-btn w-full text-white font-semibold py-3 rounded-lg shadow-sm flex items-center justify-center gap-2">
        Inloggen
        <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10.293 5.293a1 1 0 011.414 0l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414-1.414L12.586 11H5a1 1 0 110-2h7.586l-2.293-2.293a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>
      </button>
      <div class="mt-7 pt-5 border-t border-slate-100 text-center">
        <a href="/" class="ms-back-link text-xs text-slate-400 inline-flex items-center gap-1.5 transition-colors">
          <svg class="w-3 h-3" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9.707 14.707a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 1.414L7.414 9H15a1 1 0 110 2H7.414l2.293 2.293a1 1 0 010 1.414z" clip-rule="evenodd"/></svg>
          Terug naar wandmeesters.nl
        </a>
      </div>
    </form>
  </div>
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
    if r: return r
    return send_from_directory(ADMIN_DIR, "index.html")


@app.route("/admin/<path:sub>")
def admin_static(sub):
    if sub.startswith("data/"):  # never expose data
        abort(404)
    r = require_login()
    if r: return r
    p = (ADMIN_DIR / sub).resolve()
    if not str(p).startswith(str(ADMIN_DIR)) or not p.exists():
        abort(404)
    return send_from_directory(p.parent, p.name)


# Meta tag extraction / patching ------------------------------------
META_PATTERNS = {
    "title":         (r'<title>([^<]*)</title>',                       lambda v: f'<title>{v}</title>'),
    "description":   (r'<meta\s+name="description"\s+content="([^"]*)"\s*/?>',                              lambda v: f'<meta name="description" content="{v}"/>'),
    "og_title":      (r'<meta\s+property="og:title"\s+content="([^"]*)"\s*/?>',                              lambda v: f'<meta property="og:title" content="{v}"/>'),
    "og_description":(r'<meta\s+property="og:description"\s+content="([^"]*)"\s*/?>',                        lambda v: f'<meta property="og:description" content="{v}"/>'),
    "og_image":      (r'<meta\s+property="og:image"\s+content="([^"]*)"\s*/?>',                              lambda v: f'<meta property="og:image" content="{v}"/>'),
}


def page_url_to_path(url: str) -> Path | None:
    url = url.strip()
    if not url.startswith("/"): return None
    if url == "/": return ROOT / "index.html"
    p = ROOT / url.strip("/") / "index.html"
    if p.exists(): return p
    p2 = ROOT / url.strip("/")
    if p2.exists() and p2.is_file(): return p2
    return None


def get_page_meta(url: str) -> dict:
    p = page_url_to_path(url)
    if not p or not p.exists():
        return {"error": f"Pagina niet gevonden: {url}"}
    s = p.read_text(encoding="utf-8", errors="replace")
    out = {"url": url, "path": str(p.relative_to(ROOT))}
    for key, (pat, _) in META_PATTERNS.items():
        m = re.search(pat, s)
        out[key] = m.group(1) if m else ""
    return out


def set_page_meta(url: str, updates: dict) -> dict:
    """Update meta tags in a page. Only works when filesystem is writable (local dev)."""
    p = page_url_to_path(url)
    if not p or not p.exists():
        return {"ok": False, "error": f"Pagina niet gevonden: {url}"}
    try:
        s = p.read_text(encoding="utf-8", errors="replace")
        for key, value in updates.items():
            if key not in META_PATTERNS or value is None:
                continue
            pat, builder = META_PATTERNS[key]
            new_tag = builder(str(value).replace('"', '&quot;'))
            if re.search(pat, s):
                s = re.sub(pat, new_tag, s, count=1)
            elif key == "title":
                s = s.replace("</head>", new_tag + "</head>", 1)
            else:
                # Insert near other meta tags
                s = re.sub(r'(<meta[^>]*charset[^>]*>)', r'\1' + new_tag, s, count=1) or s + new_tag
        p.write_text(s, encoding="utf-8")
        return {"ok": True, "message": f"Meta opgeslagen voor {url}"}
    except OSError as e:
        return {"ok": False, "error": f"Filesystem is read-only ({e}). Edit lokaal en redeploy."}


# API ---------------------------------------------------------------
@app.route("/api/pages")
def api_pages():
    if require_login(): return jsonify({"error": "auth"}), 401
    p = list_pages()
    vp = kv_get("virtual_pages", {}) or {}
    for url, meta in vp.items():
        p.append({"url": url, "slug": url.strip("/"), "title": meta.get("title", url),
                  "path": "virtual", "size_kb": 0, "modified": meta.get("created", "")})
    return jsonify(p)


@app.route("/api/sitemap")
def api_sitemap():
    if require_login(): return jsonify({"error": "auth"}), 401
    return jsonify(sitemap_tree())


@app.route("/api/media")
def api_media():
    if require_login(): return jsonify({"error": "auth"}), 401
    return jsonify(list_media())


@app.route("/api/chat", methods=["POST"])
def api_chat():
    if require_login(): return jsonify({"error": "auth"}), 401
    msg = (request.get_json(silent=True) or {}).get("message", "").strip()
    parsed = parse_chat(msg)
    if not parsed.get("command"):
        return jsonify({"ok": False, "reply": parsed.get("error", "Onbekend"), "parsed": parsed})
    handler = COMMAND_HANDLERS.get(parsed["command"])
    if not handler: return jsonify({"ok": False, "reply": "Handler niet gevonden"})
    result = handler(parsed.get("args", {}))
    return jsonify({"ok": result.get("ok", False),
                    "reply": result.get("message") or result.get("error") or "Klaar",
                    "command": parsed["command"], "result": result, "parsed": parsed})


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
    # Send emails synchronously on serverless (no background threads)
    try: process_lead_emails(lead)
    except Exception as e: print(f"email error: {e}")
    # Persist with email status
    leads = get_leads()
    for i, l in enumerate(leads):
        if l.get("id") == lead["id"]:
            leads[i] = lead
            break
    save_leads(leads)
    return jsonify({"ok": True, "id": lead["id"], "message": "Bedankt! We nemen binnen 1 werkdag contact met je op."})


@app.route("/api/leads")
def api_leads():
    if require_login(): return jsonify({"error": "auth"}), 401
    return jsonify({"leads": get_leads(), "stages": PIPELINE_STAGES})


@app.route("/api/leads/<lead_id>", methods=["PATCH", "DELETE"])
def api_lead_update(lead_id):
    if require_login(): return jsonify({"error": "auth"}), 401
    leads = get_leads()
    idx = next((i for i, l in enumerate(leads) if l.get("id") == lead_id), -1)
    if idx == -1: return jsonify({"ok": False, "error": "Niet gevonden"}), 404
    if request.method == "DELETE":
        leads.pop(idx); save_leads(leads); return jsonify({"ok": True})
    patch = request.get_json(silent=True) or {}
    if "stage" in patch and patch["stage"] in STAGE_IDS:
        old = leads[idx].get("stage")
        leads[idx]["stage"] = patch["stage"]
        leads[idx].setdefault("history", []).append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "from": old, "stage": patch["stage"], "by": session.get("user", "admin"),
        })
    for k in ("note", "name", "email", "telefoon", "woonplaats"):
        if k in patch: leads[idx][k] = patch[k]
    save_leads(leads)
    return jsonify({"ok": True, "lead": leads[idx]})


@app.route("/api/settings", methods=["GET", "PUT"])
def api_settings():
    if require_login(): return jsonify({"error": "auth"}), 401
    if request.method == "GET":
        s = get_settings()
        if s.get("smtp", {}).get("password"): s["smtp"]["password"] = "••••••••"
        return jsonify(s)
    patch = request.get_json(silent=True) or {}
    existing = kv_get("settings", {}) or {}
    for k, v in patch.items():
        if isinstance(v, dict):
            existing.setdefault(k, {}).update({kk: vv for kk, vv in v.items() if vv != "••••••••"})
        else:
            existing[k] = v
    kv_set("settings", existing)
    return jsonify({"ok": True})


@app.route("/api/meta", methods=["GET", "PUT"])
def api_meta():
    if require_login(): return jsonify({"error": "auth"}), 401
    if request.method == "GET":
        url = request.args.get("url")
        if url:
            return jsonify(get_page_meta(url))
        # No url — return summary for all pages
        out = []
        for p in list_pages():
            m = get_page_meta(p["url"])
            out.append({**p, **{k: m.get(k, "") for k in ("title", "description")}})
        return jsonify(out)
    # PUT
    body = request.get_json(silent=True) or {}
    url = body.get("url")
    if not url: return jsonify({"ok": False, "error": "url ontbreekt"}), 400
    updates = {k: v for k, v in body.items() if k in META_PATTERNS}
    result = set_page_meta(url, updates)
    return jsonify(result)


@app.route("/api/smtp-test", methods=["POST"])
def api_smtp_test():
    if require_login(): return jsonify({"error": "auth"}), 401
    to = (request.get_json(silent=True) or {}).get("to", "").strip()
    if not to: return jsonify({"ok": False, "error": "Ontvanger ontbreekt"}), 400
    ok, msg = send_email(to, "Wandmeesters SMTP test", "Testbericht — SMTP werkt.")
    return jsonify({"ok": ok, "message": msg})


# ============================================================================
# EXTENDED ADMIN BACKEND -----------------------------------------------------
# Routes that power the new SPA admin (#pages, #page-editor, #media, #seo,
# #templates, #sitemap, #pipeline, #settings, #revisions, #dashboard).
# ============================================================================

BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
BLOB_API_BASE = "https://blob.vercel-storage.com"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL_DEFAULT = "claude-opus-4-8"
ANTHROPIC_MODEL_FAST = "claude-haiku-4-5"
AUDIT_CAP = 1000
REVISIONS_CAP = 20

# Generated HTML output dir (only writable locally)
GENERATED_DIR = ROOT / ".generated"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _auth_or_401():
    """Return a 401 JSON response if not logged in, else None."""
    if not is_logged_in():
        return jsonify({"error": "auth"}), 401
    return None


def _safe_slug(s: str) -> str:
    s = (s or "").strip().strip("/")
    # Allow path-style slugs like 'diensten/stucwerk'
    s = re.sub(r"[^a-z0-9/_-]+", "-", s.lower())
    s = re.sub(r"-+", "-", s).strip("-/")
    return s


# ---------- audit log ----------
def audit_log(action: str, target: str, summary: str = "", before=None, after=None) -> None:
    try:
        log = kv_get("audit:log", []) or []
        entry = {
            "ts": _now_iso(),
            "user": session.get("user", "system") if session else "system",
            "action": action,
            "target": target,
            "summary": summary,
        }
        if before is not None: entry["before"] = before
        if after is not None: entry["after"] = after
        log.insert(0, entry)
        if len(log) > AUDIT_CAP:
            log = log[:AUDIT_CAP]
        kv_set("audit:log", log)
    except Exception as e:
        print(f"audit_log failed: {e}")


# ---------- pages-index helpers ----------
def _pages_index() -> list[dict]:
    return kv_get("pages:index", []) or []


def _save_pages_index(items: list[dict]) -> None:
    kv_set("pages:index", items)


def _upsert_pages_index(page: dict) -> None:
    items = _pages_index()
    slug = page.get("slug")
    score = (kv_get("seo_scores", {}) or {}).get(slug, {}).get("score", 0)
    entry = {
        "slug": slug,
        "title": page.get("title", ""),
        "status": page.get("status", "draft"),
        "template": page.get("template"),
        "locale": page.get("locale", "nl"),
        "updated_at": page.get("updated_at"),
        "seo_score": score,
    }
    idx = next((i for i, x in enumerate(items) if x.get("slug") == slug), -1)
    if idx >= 0:
        items[idx] = entry
    else:
        items.append(entry)
    _save_pages_index(items)


def _remove_from_pages_index(slug: str) -> None:
    items = _pages_index()
    items = [x for x in items if x.get("slug") != slug]
    _save_pages_index(items)


def _default_page(slug: str, title: str, template: str | None = None, locale: str = "nl") -> dict:
    return {
        "slug": slug,
        "title": title,
        "status": "draft",
        "template": template,
        "locale": locale,
        "parent": None,
        "menu_position": 0,
        "scheduled_publish_at": None,
        "author": session.get("user", "admin") if session else "admin",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "published_at": None,
        "meta": {
            "title": title,
            "description": "",
            "canonical": "",
            "robots": "index,follow",
            "og_title": title,
            "og_description": "",
            "og_image": "",
            "twitter_card": "summary_large_image",
            "twitter_image": "",
            "hreflang": [],
            "keyword": "",
            "schema_jsonld": None,
        },
        "content_blocks": [],
    }


def _get_page(slug: str) -> dict | None:
    return kv_get(f"page:{slug}")


def _save_page(page: dict) -> None:
    page["updated_at"] = _now_iso()
    kv_set(f"page:{page['slug']}", page)
    _upsert_pages_index(page)


# ---------- revisions ----------
def _new_rev_id() -> str:
    return uuid.uuid4().hex[:12]


def _push_revision(slug: str, snapshot: dict, summary: str = "") -> str:
    rev_id = _new_rev_id()
    rev = {
        "rev_id": rev_id,
        "page_slug": slug,
        "snapshot": snapshot,
        "author": session.get("user", "admin") if session else "admin",
        "created_at": _now_iso(),
        "summary": summary,
    }
    kv_set(f"page:{slug}:rev:{rev_id}", rev)
    revs = kv_get(f"page:{slug}:revs", []) or []
    revs.insert(0, rev_id)
    # Drop old revisions
    for stale in revs[REVISIONS_CAP:]:
        kv_delete(f"page:{slug}:rev:{stale}")
    revs = revs[:REVISIONS_CAP]
    kv_set(f"page:{slug}:revs", revs)
    return rev_id


# ---------- block rendering ----------
def _esc(s) -> str:
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def render_block(b: dict) -> str:
    t = (b or {}).get("type", "")
    p = (b or {}).get("props", {}) or {}
    if t in ("heading-h1", "heading-h2", "heading-h3", "heading-h4"):
        lvl = t[-2:]
        return f"<{lvl}>{_esc(p.get('text', ''))}</{lvl}>"
    if t == "paragraph":
        return f"<p>{_esc(p.get('text', ''))}</p>"
    if t == "rich-text":
        # Trust HTML — assumes Tiptap-sanitised input
        return f"<div class='rich-text'>{p.get('html', '')}</div>"
    if t == "image":
        src = _esc(p.get("src", ""))
        alt = _esc(p.get("alt", ""))
        return f'<img src="{src}" alt="{alt}" loading="lazy"/>'
    if t == "image-gallery":
        items = p.get("images", []) or []
        return ('<div class="gallery">'
                + "".join(f'<img src="{_esc(i.get("src",""))}" alt="{_esc(i.get("alt",""))}" loading="lazy"/>' for i in items)
                + "</div>")
    if t == "button":
        href = _esc(p.get("href", "#"))
        text = _esc(p.get("text", "Lees meer"))
        return f'<a class="btn" href="{href}">{text}</a>'
    if t == "button-group":
        btns = p.get("buttons", []) or []
        return ('<div class="btn-group">'
                + "".join(f'<a class="btn" href="{_esc(b.get("href","#"))}">{_esc(b.get("text",""))}</a>' for b in btns)
                + "</div>")
    if t == "link":
        return f'<a href="{_esc(p.get("href","#"))}">{_esc(p.get("text",""))}</a>'
    if t == "list-ul":
        items = p.get("items", []) or []
        return "<ul>" + "".join(f"<li>{_esc(i)}</li>" for i in items) + "</ul>"
    if t == "list-ol":
        items = p.get("items", []) or []
        return "<ol>" + "".join(f"<li>{_esc(i)}</li>" for i in items) + "</ol>"
    if t == "hr":
        return "<hr/>"
    if t == "spacer":
        h = int(p.get("height", 24) or 24)
        return f'<div style="height:{h}px"></div>'
    if t == "quote":
        return f'<blockquote>{_esc(p.get("text",""))}<cite>{_esc(p.get("cite",""))}</cite></blockquote>'
    if t in ("section-1col", "section-2col", "section-3col"):
        cols = int(t.split("-")[1][0])
        children = p.get("children", []) or []
        inner = "".join(f'<div class="col">{render_blocks(c)}</div>' for c in children[:cols])
        return f'<section class="section-{cols}col">{inner}</section>'
    if t == "video-youtube":
        vid = _esc(p.get("video_id", ""))
        return f'<iframe loading="lazy" src="https://www.youtube.com/embed/{vid}" allowfullscreen></iframe>'
    if t == "video-vimeo":
        vid = _esc(p.get("video_id", ""))
        return f'<iframe loading="lazy" src="https://player.vimeo.com/video/{vid}" allowfullscreen></iframe>'
    if t == "embed-iframe":
        return f'<iframe loading="lazy" src="{_esc(p.get("src",""))}"></iframe>'
    if t == "html-raw":
        return p.get("html", "")
    if t == "cta-banner":
        return (f'<section class="cta-banner"><h2>{_esc(p.get("title",""))}</h2>'
                f'<p>{_esc(p.get("subtitle",""))}</p>'
                f'<a class="btn" href="{_esc(p.get("cta_href","#"))}">{_esc(p.get("cta_text","Vraag offerte"))}</a></section>')
    if t == "faq-item":
        return (f'<details class="faq"><summary>{_esc(p.get("question",""))}</summary>'
                f'<div>{_esc(p.get("answer",""))}</div></details>')
    if t == "faq-group":
        items = p.get("items", []) or []
        return ('<div class="faq-group">'
                + "".join(f'<details><summary>{_esc(i.get("question",""))}</summary><div>{_esc(i.get("answer",""))}</div></details>' for i in items)
                + "</div>")
    if t == "testimonial":
        return (f'<blockquote class="testimonial">{_esc(p.get("quote",""))}'
                f'<cite>— {_esc(p.get("author",""))}</cite></blockquote>')
    if t == "icon-box":
        return (f'<div class="icon-box"><div class="icon">{_esc(p.get("icon",""))}</div>'
                f'<h3>{_esc(p.get("title",""))}</h3><p>{_esc(p.get("text",""))}</p></div>')
    if t == "contact-form-ref":
        return f'<div class="contact-form" data-form="{_esc(p.get("form_id","default"))}"></div>'
    if t == "google-map":
        q = urllib.parse.quote(p.get("query", "Wandmeesters"))
        return f'<iframe class="gmap" loading="lazy" src="https://www.google.com/maps?q={q}&output=embed"></iframe>'
    if t == "breadcrumb":
        items = p.get("items", []) or []
        return ('<nav class="breadcrumb">'
                + " / ".join(f'<a href="{_esc(i.get("href","#"))}">{_esc(i.get("label",""))}</a>' for i in items)
                + "</nav>")
    if t == "table":
        rows = p.get("rows", []) or []
        return "<table>" + "".join(
            "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in rows
        ) + "</table>"
    # Unknown block — render as comment
    return f"<!-- unknown block: {_esc(t)} -->"


def render_blocks(blocks: list) -> str:
    return "".join(render_block(b) for b in (blocks or []))


PAGE_HTML_SHELL = """<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="UTF-8">
<title>{title}</title>
<meta name="description" content="{description}"/>
<meta name="robots" content="{robots}"/>
{canonical_tag}
<meta property="og:title" content="{og_title}"/>
<meta property="og:description" content="{og_description}"/>
<meta property="og:image" content="{og_image}"/>
<meta name="twitter:card" content="{twitter_card}"/>
<meta name="viewport" content="width=device-width, initial-scale=1">
{schema_tag}
{hreflang_tags}
<link rel="stylesheet" href="/wp-content/uploads/animations-disable.css?v=8">
<style>body{{font-family:Poppins,sans-serif;margin:0;color:#1f2937;line-height:1.6}}main{{max-width:1120px;margin:0 auto;padding:32px 24px}}.btn{{display:inline-block;background:#0a5cad;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600}}.section-2col,.section-3col{{display:grid;gap:24px}}.section-2col{{grid-template-columns:repeat(2,1fr)}}.section-3col{{grid-template-columns:repeat(3,1fr)}}</style>
</head><body>
<main>{body}</main>
</body></html>"""


def render_page_html(page: dict) -> str:
    meta = page.get("meta", {}) or {}
    schema = meta.get("schema_jsonld")
    schema_tag = (
        f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>'
        if schema else ""
    )
    hreflang_tags = "".join(
        f'<link rel="alternate" hreflang="{_esc(h.get("lang",""))}" href="{_esc(h.get("url",""))}"/>'
        for h in (meta.get("hreflang") or [])
    )
    canonical = meta.get("canonical") or ""
    canonical_tag = f'<link rel="canonical" href="{_esc(canonical)}"/>' if canonical else ""
    body = render_blocks(page.get("content_blocks") or [])
    return PAGE_HTML_SHELL.format(
        lang=page.get("locale", "nl"),
        title=_esc(meta.get("title") or page.get("title", "")),
        description=_esc(meta.get("description", "")),
        robots=_esc(meta.get("robots", "index,follow")),
        canonical_tag=canonical_tag,
        og_title=_esc(meta.get("og_title") or page.get("title", "")),
        og_description=_esc(meta.get("og_description", "")),
        og_image=_esc(meta.get("og_image", "")),
        twitter_card=_esc(meta.get("twitter_card", "summary_large_image")),
        schema_tag=schema_tag,
        hreflang_tags=hreflang_tags,
        body=body,
    )


def write_rendered_html(slug: str, html: str) -> tuple[bool, str | None]:
    """Write rendered HTML to disk (local) or Blob (prod). Returns (ok, url_or_path)."""
    # Try local filesystem first (only writable on dev)
    try:
        out = GENERATED_DIR / slug / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        return True, str(out)
    except OSError:
        pass
    # Production: store in KV (since Blob put requires multipart support);
    # final HTML is also retrievable via /api/render/<slug>
    kv_set(f"page:{slug}:html", html)
    return True, f"/api/render/{slug}"


# ---------- blob storage ----------
def blob_put(filename: str, data: bytes, content_type: str = "application/octet-stream") -> tuple[bool, str]:
    """Upload bytes to Vercel Blob. Falls back to data URL when token missing."""
    if not BLOB_TOKEN:
        # Fallback: base64 data URL (only viable for small files)
        if len(data) > 1024 * 1024:
            return False, "Blob token missing and file >1MB"
        b64 = base64.b64encode(data).decode("ascii")
        return True, f"data:{content_type};base64,{b64}"
    try:
        # Vercel Blob PUT API
        safe_name = re.sub(r"[^A-Za-z0-9._/-]", "_", filename)
        url = f"{BLOB_API_BASE}/{safe_name}"
        req = urllib.request.Request(
            url, data=data,
            headers={
                "Authorization": f"Bearer {BLOB_TOKEN}",
                "Content-Type": content_type,
                "x-content-type": content_type,
                "x-api-version": "7",
            },
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        return True, resp.get("url", "")
    except Exception as e:
        print(f"blob_put failed: {e}")
        # Fallback to KV if small enough
        if len(data) <= 500 * 1024:
            b64 = base64.b64encode(data).decode("ascii")
            return True, f"data:{content_type};base64,{b64}"
        return False, str(e)


def blob_delete(blob_url: str) -> bool:
    if not BLOB_TOKEN or not blob_url.startswith("http"):
        return True
    try:
        req = urllib.request.Request(
            f"{BLOB_API_BASE}/delete",
            data=json.dumps({"urls": [blob_url]}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {BLOB_TOKEN}",
                "Content-Type": "application/json",
                "x-api-version": "7",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8):
            pass
        return True
    except Exception as e:
        print(f"blob_delete failed: {e}")
        return False


# ---------- SEO scoring ----------
def compute_seo_score(page: dict) -> dict:
    meta = page.get("meta", {}) or {}
    issues: list[dict] = []
    score = 100
    title = meta.get("title") or page.get("title") or ""
    desc = meta.get("description", "")
    if not title:
        issues.append({"severity": "error", "field": "title", "message": "Title ontbreekt"}); score -= 25
    elif len(title) > 60:
        issues.append({"severity": "warn", "field": "title", "message": f"Title te lang ({len(title)} chars)"}); score -= 5
    elif len(title) < 20:
        issues.append({"severity": "warn", "field": "title", "message": "Title te kort"}); score -= 5
    if not desc:
        issues.append({"severity": "error", "field": "description", "message": "Description ontbreekt"}); score -= 20
    elif len(desc) > 160:
        issues.append({"severity": "warn", "field": "description", "message": f"Description te lang ({len(desc)} chars)"}); score -= 5
    elif len(desc) < 70:
        issues.append({"severity": "warn", "field": "description", "message": "Description te kort"}); score -= 5
    if not meta.get("canonical"):
        issues.append({"severity": "info", "field": "canonical", "message": "Geen canonical"}); score -= 5
    if not meta.get("og_image"):
        issues.append({"severity": "info", "field": "og_image", "message": "Geen OG image"}); score -= 5
    blocks = page.get("content_blocks") or []
    h1s = [b for b in blocks if b.get("type") == "heading-h1"]
    if not h1s:
        issues.append({"severity": "warn", "field": "content", "message": "Geen H1"}); score -= 8
    if len(h1s) > 1:
        issues.append({"severity": "warn", "field": "content", "message": "Meerdere H1's"}); score -= 5
    text_len = sum(len(((b.get("props") or {}).get("text") or "")) for b in blocks)
    if text_len < 300:
        issues.append({"severity": "info", "field": "content", "message": "Weinig tekst (<300 chars)"}); score -= 5
    score = max(0, min(100, score))
    return {"score": score, "issues": issues, "computed_at": _now_iso()}


def update_seo_score(page: dict) -> int:
    res = compute_seo_score(page)
    scores = kv_get("seo_scores", {}) or {}
    scores[page["slug"]] = res
    kv_set("seo_scores", scores)
    return res["score"]


# ---------- pages routes (new admin) ----------
@app.route("/api/admin/pages", methods=["GET"])
def api_admin_pages_list():
    """List pages from KV (the new block-based store)."""
    a = _auth_or_401()
    if a: return a
    items = _pages_index()
    status = request.args.get("status")
    template = request.args.get("template")
    q = (request.args.get("q") or "").lower()
    limit = int(request.args.get("limit", 200))
    offset = int(request.args.get("offset", 0))
    if status: items = [x for x in items if x.get("status") == status]
    if template: items = [x for x in items if x.get("template") == template]
    if q: items = [x for x in items if q in (x.get("title", "") + x.get("slug", "")).lower()]
    total = len(items)
    return jsonify({"items": items[offset:offset + limit], "total": total})


@app.route("/api/admin/pages", methods=["POST"])
def api_admin_pages_create():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    slug = _safe_slug(body.get("slug", ""))
    title = (body.get("title") or "").strip()
    if not slug or not title:
        return jsonify({"error": "slug en title verplicht"}), 400
    if _get_page(slug):
        return jsonify({"error": f"Pagina {slug} bestaat al"}), 409
    template = body.get("template")
    page = _default_page(slug, title, template=template, locale=body.get("locale", "nl"))
    if body.get("parent"): page["parent"] = body["parent"]
    # If template, instantiate
    if template:
        tpl = kv_get(f"template:{template}")
        if tpl:
            vars_ = body.get("variables", {}) or {}
            page["content_blocks"] = _substitute_template(tpl.get("content_blocks") or [], vars_)
            page["meta"].update(_substitute_template_meta(tpl.get("default_meta") or {}, vars_))
    _save_page(page)
    update_seo_score(page)
    audit_log("page.create", slug, f"Created page '{title}'")
    return jsonify(page), 201


@app.route("/api/admin/pages/<path:slug>", methods=["GET"])
def api_admin_page_get(slug):
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    page = _get_page(slug)
    if not page:
        return jsonify({"error": "Niet gevonden"}), 404
    if request.args.get("include_draft") == "true":
        draft = kv_get(f"page:{slug}:draft")
        if draft:
            page = {**page, **draft, "has_draft": True}
    return jsonify(page)


@app.route("/api/admin/pages/<path:slug>", methods=["PUT"])
def api_admin_page_update(slug):
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    body = request.get_json(silent=True) or {}
    page = _get_page(slug)
    if not page:
        return jsonify({"error": "Niet gevonden"}), 404
    publish = request.args.get("publish") == "1"
    # Snapshot previous version
    _push_revision(slug, page, summary=("publish" if publish else "save"))
    # Merge changes
    for k in ("title", "template", "locale", "parent", "menu_position", "scheduled_publish_at", "content_blocks", "status"):
        if k in body:
            page[k] = body[k]
    if "meta" in body and isinstance(body["meta"], dict):
        page.setdefault("meta", {}).update(body["meta"])
    if publish:
        page["status"] = "published"
        page["published_at"] = _now_iso()
        html = render_page_html(page)
        ok, url_or_path = write_rendered_html(slug, html)
        kv_delete(f"page:{slug}:draft")
        _save_page(page)
        update_seo_score(page)
        audit_log("page.publish", slug, f"Published '{page['title']}'")
        return jsonify({
            "slug": slug, "updated_at": page["updated_at"],
            "revision_id": _push_revision(slug, page, summary="post-publish"),
            "html_size_kb": round(len(html) / 1024, 1),
            "blob_url": url_or_path,
        })
    # Auto-save into draft
    kv_set(f"page:{slug}:draft", page)
    _save_page(page)
    update_seo_score(page)
    audit_log("page.save", slug, "Saved draft")
    return jsonify({"slug": slug, "updated_at": page["updated_at"], "revision_id": None,
                    "html_size_kb": 0, "blob_url": None})


@app.route("/api/admin/pages/<path:slug>", methods=["DELETE"])
def api_admin_page_delete(slug):
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    page = _get_page(slug)
    if not page:
        return jsonify({"error": "Niet gevonden"}), 404
    body = request.get_json(silent=True) or {}
    # Verwijder volledig uit KV (hard delete)
    kv_delete(f"page:{slug}")
    # Indien template-pagina (dienst-1to1 / locatie-1to1): ook gerenderde HTML weghalen
    if page.get("template") in ("dienst-1to1", "locatie-1to1"):
        sub = slug
        if sub.startswith("diensten/"):
            sub = sub[len("diensten/"):]
        kv_delete(f"dienst-html:{sub}")
    _remove_from_pages_index(slug)
    redirect_id = None
    if body.get("create_redirect_to"):
        redirect_id = _create_redirect(f"/{slug}/", body["create_redirect_to"], 301)
    audit_log("page.delete", slug, "Hard-deleted")
    return jsonify({"deleted": True, "redirect_id": redirect_id})


@app.route("/api/admin/dienst-html/<path:slug>", methods=["DELETE"])
def api_admin_dienst_html_delete(slug):
    """Verwijder los de gerenderde HTML voor een dienst-template pagina."""
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    if slug.startswith("diensten/"):
        slug = slug[len("diensten/"):]
    kv_delete(f"dienst-html:{slug}")
    return jsonify({"deleted": True})


@app.route("/api/admin/pages/<path:slug>/duplicate", methods=["POST"])
def api_admin_page_duplicate(slug):
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    body = request.get_json(silent=True) or {}
    src = _get_page(slug)
    if not src:
        return jsonify({"error": "Niet gevonden"}), 404
    new_slug = _safe_slug(body.get("new_slug", f"{slug}-kopie"))
    if _get_page(new_slug):
        return jsonify({"error": f"{new_slug} bestaat al"}), 409
    new_page = json.loads(json.dumps(src))
    new_page["slug"] = new_slug
    new_page["title"] = body.get("new_title") or (src.get("title", "") + " (kopie)")
    new_page["status"] = "draft"
    new_page["created_at"] = _now_iso()
    new_page["published_at"] = None
    _save_page(new_page)
    update_seo_score(new_page)
    audit_log("page.duplicate", new_slug, f"Duplicated from {slug}")
    return jsonify({"slug": new_slug, "title": new_page["title"], "status": "draft"}), 201


@app.route("/api/admin/pages/<path:slug>/slug", methods=["PATCH"])
def api_admin_page_rename(slug):
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    body = request.get_json(silent=True) or {}
    new_slug = _safe_slug(body.get("new_slug", ""))
    if not new_slug or new_slug == slug:
        return jsonify({"error": "new_slug ontbreekt of identiek"}), 400
    page = _get_page(slug)
    if not page:
        return jsonify({"error": "Niet gevonden"}), 404
    if _get_page(new_slug):
        return jsonify({"error": f"{new_slug} bestaat al"}), 409
    # Voor template-pagina's: verplaats ook de gerenderde HTML in KV
    if page.get("template") in ("dienst-1to1", "locatie-1to1"):
        old_sub = slug[len("diensten/"):] if slug.startswith("diensten/") else slug
        new_sub = new_slug[len("diensten/"):] if new_slug.startswith("diensten/") else new_slug
        existing_html = kv_get(f"dienst-html:{old_sub}")
        if existing_html:
            kv_set(f"dienst-html:{new_sub}", existing_html)
            kv_delete(f"dienst-html:{old_sub}")
        # Slots ook updaten zodat eventueel re-render correct werkt
        if page.get("dienst_slots"):
            page["dienst_slots"]["slug"] = new_sub
        if page.get("locatie_slots"):
            page["locatie_slots"]["slug"] = new_sub
        # Canonical updaten
        if page.get("meta"):
            page["meta"]["canonical"] = f"https://wandmeesters.nl/{new_slug}/"
    page["slug"] = new_slug
    kv_set(f"page:{new_slug}", page)
    kv_delete(f"page:{slug}")
    _remove_from_pages_index(slug)
    _upsert_pages_index(page)
    redirect_id = None
    if body.get("create_redirect", True):
        redirect_id = _create_redirect(f"/{slug}/", f"/{new_slug}/", 301)
    audit_log("page.rename", new_slug, f"{slug} -> {new_slug}")
    return jsonify({"old_slug": slug, "new_slug": new_slug, "redirect_id": redirect_id})


@app.route("/api/admin/pages/<path:slug>/publish", methods=["POST"])
def api_admin_page_publish(slug):
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    page = _get_page(slug)
    if not page:
        return jsonify({"error": "Niet gevonden"}), 404
    # Merge any draft
    draft = kv_get(f"page:{slug}:draft")
    if draft:
        page.update({k: v for k, v in draft.items() if k != "slug"})
    page["status"] = "published"
    page["published_at"] = _now_iso()
    _push_revision(slug, page, summary="publish")
    html = render_page_html(page)
    ok, url_or_path = write_rendered_html(slug, html)
    kv_delete(f"page:{slug}:draft")
    _save_page(page)
    update_seo_score(page)
    audit_log("page.publish", slug, "Publish")
    return jsonify({
        "slug": slug, "published_at": page["published_at"],
        "blob_url": url_or_path, "html_size_kb": round(len(html) / 1024, 1),
    })


@app.route("/api/admin/pages/bulk", methods=["POST"])
def api_admin_pages_bulk():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    slugs = body.get("slugs") or []
    updates = body.get("updates") or {}
    updated = 0
    failed = []
    for s in slugs:
        page = _get_page(_safe_slug(s))
        if not page:
            failed.append({"slug": s, "error": "not found"})
            continue
        try:
            if "meta" in updates and isinstance(updates["meta"], dict):
                page.setdefault("meta", {}).update(updates["meta"])
            if "status" in updates:
                page["status"] = updates["status"]
            _save_page(page)
            update_seo_score(page)
            updated += 1
        except Exception as e:
            failed.append({"slug": s, "error": str(e)})
    audit_log("pages.bulk", "*", f"Bulk update {updated} pages")
    return jsonify({"updated": updated, "failed": failed})


@app.route("/api/admin/pages/export", methods=["GET"])
def api_admin_pages_export():
    a = _auth_or_401()
    if a: return a
    fields = (request.args.get("fields") or "slug,title,status,meta.description").split(",")
    items = _pages_index()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(fields)
    for it in items:
        page = _get_page(it["slug"]) or it
        row = []
        for f in fields:
            if "." in f:
                a_, b_ = f.split(".", 1)
                row.append(((page.get(a_) or {}).get(b_, "")) if isinstance(page.get(a_), dict) else "")
            else:
                row.append(page.get(f, ""))
        writer.writerow(row)
    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=pages.csv"
    return resp


@app.route("/api/admin/pages/import", methods=["POST"])
def api_admin_pages_import():
    a = _auth_or_401()
    if a: return a
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Geen bestand"}), 400
    created = updated = 0
    errors = []
    try:
        text = f.read().decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            try:
                slug = _safe_slug(row.get("slug", ""))
                if not slug:
                    errors.append({"row": row, "error": "no slug"}); continue
                page = _get_page(slug)
                if page:
                    if row.get("title"): page["title"] = row["title"]
                    for mk in ("description", "canonical", "robots", "og_image", "keyword"):
                        if row.get(f"meta.{mk}") is not None:
                            page.setdefault("meta", {})[mk] = row[f"meta.{mk}"]
                    _save_page(page); updated += 1
                else:
                    page = _default_page(slug, row.get("title", slug))
                    _save_page(page); created += 1
            except Exception as e:
                errors.append({"row": row, "error": str(e)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    audit_log("pages.import", "*", f"Imported csv: +{created} ~{updated}")
    return jsonify({"created": created, "updated": updated, "errors": errors})


@app.route("/api/admin/pages/<path:slug>/preview", methods=["GET"])
def api_admin_page_preview(slug):
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    page = _get_page(slug)
    if not page:
        return Response("Pagina niet gevonden", status=404)
    html = render_page_html(page)
    viewport = request.args.get("viewport", "desktop")
    width = {"mobile": 375, "tablet": 768, "desktop": 1280}.get(viewport, 1280)
    wrapper = (f"<style>body{{margin:0;background:#eee}}.preview{{margin:0 auto;width:{width}px;"
               f"box-shadow:0 8px 24px rgba(0,0,0,.15);background:#fff;min-height:100vh}}</style>"
               f'<div class="preview">{html}</div>')
    return Response(wrapper, mimetype="text/html")


@app.route("/api/admin/pages/<path:slug>/validate", methods=["POST"])
def api_admin_page_validate(slug):
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    page = _get_page(slug)
    if not page:
        return jsonify({"error": "Niet gevonden"}), 404
    res = compute_seo_score(page)
    # Broken-link scan (internal only — synchronous)
    warnings = []
    for b in page.get("content_blocks", []) or []:
        props = b.get("props", {}) or {}
        href = props.get("href")
        if href and href.startswith("/"):
            target = _safe_slug(href)
            if target and not _get_page(target):
                warnings.append({"severity": "warn", "field": "link", "message": f"Interne link {href} bestaat niet"})
    return jsonify({"score": res["score"], "issues": res["issues"], "warnings": warnings})


@app.route("/api/admin/pages/<path:slug>/revisions", methods=["GET"])
def api_admin_page_revisions(slug):
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    limit = int(request.args.get("limit", 20))
    ids = (kv_get(f"page:{slug}:revs", []) or [])[:limit]
    items = []
    for rev_id in ids:
        rev = kv_get(f"page:{slug}:rev:{rev_id}")
        if rev:
            items.append({"rev_id": rev["rev_id"], "author": rev.get("author"),
                          "created_at": rev.get("created_at"), "summary": rev.get("summary")})
    return jsonify({"items": items})


@app.route("/api/admin/pages/<path:slug>/revisions/<rev_id>", methods=["GET"])
def api_admin_page_revision(slug, rev_id):
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    rev = kv_get(f"page:{slug}:rev:{rev_id}")
    if not rev:
        return jsonify({"error": "Niet gevonden"}), 404
    return jsonify(rev)


@app.route("/api/admin/pages/<path:slug>/restore", methods=["POST"])
def api_admin_page_restore(slug):
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    body = request.get_json(silent=True) or {}
    rev_id = body.get("rev_id")
    rev = kv_get(f"page:{slug}:rev:{rev_id}")
    if not rev:
        return jsonify({"error": "Revisie niet gevonden"}), 404
    snap = rev.get("snapshot") or {}
    page = _get_page(slug)
    if page:
        _push_revision(slug, page, summary=f"pre-restore from {rev_id}")
    snap["slug"] = slug
    _save_page(snap)
    new_rev = _push_revision(slug, snap, summary=f"restored from {rev_id}")
    audit_log("page.restore", slug, f"Restored {rev_id}")
    return jsonify({"slug": slug, "restored_from": rev_id, "new_rev_id": new_rev})


@app.route("/api/page-autocomplete", methods=["GET"])
def api_page_autocomplete():
    a = _auth_or_401()
    if a: return a
    q = (request.args.get("q") or "").lower()
    limit = int(request.args.get("limit", 10))
    items = _pages_index() + [{"slug": p["url"].strip("/"), "title": p.get("title", ""), "url": p["url"]}
                              for p in list_pages()]
    matches = []
    seen = set()
    for x in items:
        slug = x.get("slug", "")
        if slug in seen: continue
        seen.add(slug)
        haystack = (x.get("title", "") + slug).lower()
        if q in haystack:
            matches.append({"slug": slug, "title": x.get("title", slug), "url": x.get("url") or f"/{slug}/"})
    return jsonify({"items": matches[:limit]})


# ---------- block library ----------
BLOCK_LIBRARY = [
    {"type": "heading-h1", "label": "Heading H1", "icon": "H1", "default_props": {"text": "Titel"}, "schema": {"text": "string"}},
    {"type": "heading-h2", "label": "Heading H2", "icon": "H2", "default_props": {"text": "Subkop"}, "schema": {"text": "string"}},
    {"type": "heading-h3", "label": "Heading H3", "icon": "H3", "default_props": {"text": "Subkop"}, "schema": {"text": "string"}},
    {"type": "heading-h4", "label": "Heading H4", "icon": "H4", "default_props": {"text": "Kop"}, "schema": {"text": "string"}},
    {"type": "paragraph", "label": "Paragraaf", "icon": "P", "default_props": {"text": ""}, "schema": {"text": "string"}},
    {"type": "rich-text", "label": "Rich text", "icon": "RT", "default_props": {"html": "<p></p>"}, "schema": {"html": "html"}},
    {"type": "image", "label": "Afbeelding", "icon": "IMG", "default_props": {"src": "", "alt": ""}, "schema": {"src": "url", "alt": "string"}},
    {"type": "image-gallery", "label": "Galerij", "icon": "GAL", "default_props": {"images": []}, "schema": {"images": "array"}},
    {"type": "button", "label": "Knop", "icon": "BTN", "default_props": {"text": "Klik hier", "href": "#"}, "schema": {"text": "string", "href": "url"}},
    {"type": "button-group", "label": "Knop groep", "icon": "BG", "default_props": {"buttons": []}, "schema": {"buttons": "array"}},
    {"type": "link", "label": "Link", "icon": "LK", "default_props": {"text": "", "href": "#"}, "schema": {"text": "string", "href": "url"}},
    {"type": "list-ul", "label": "Lijst (bullet)", "icon": "UL", "default_props": {"items": []}, "schema": {"items": "array"}},
    {"type": "list-ol", "label": "Lijst (genummerd)", "icon": "OL", "default_props": {"items": []}, "schema": {"items": "array"}},
    {"type": "hr", "label": "Scheiding", "icon": "—", "default_props": {}, "schema": {}},
    {"type": "spacer", "label": "Spatie", "icon": "SP", "default_props": {"height": 24}, "schema": {"height": "number"}},
    {"type": "quote", "label": "Citaat", "icon": "Q", "default_props": {"text": "", "cite": ""}, "schema": {"text": "string", "cite": "string"}},
    {"type": "section-1col", "label": "Sectie 1 kolom", "icon": "1C", "default_props": {"children": [[]]}, "schema": {"children": "array"}},
    {"type": "section-2col", "label": "Sectie 2 kolommen", "icon": "2C", "default_props": {"children": [[], []]}, "schema": {"children": "array"}},
    {"type": "section-3col", "label": "Sectie 3 kolommen", "icon": "3C", "default_props": {"children": [[], [], []]}, "schema": {"children": "array"}},
    {"type": "video-youtube", "label": "YouTube video", "icon": "YT", "default_props": {"video_id": ""}, "schema": {"video_id": "string"}},
    {"type": "video-vimeo", "label": "Vimeo video", "icon": "VM", "default_props": {"video_id": ""}, "schema": {"video_id": "string"}},
    {"type": "embed-iframe", "label": "Iframe embed", "icon": "IF", "default_props": {"src": ""}, "schema": {"src": "url"}},
    {"type": "html-raw", "label": "HTML raw", "icon": "</>", "default_props": {"html": ""}, "schema": {"html": "html"}},
    {"type": "cta-banner", "label": "CTA banner", "icon": "CTA", "default_props": {"title": "", "subtitle": "", "cta_text": "Offerte", "cta_href": "/contact/"}, "schema": {}},
    {"type": "faq-item", "label": "FAQ item", "icon": "?", "default_props": {"question": "", "answer": ""}, "schema": {}},
    {"type": "faq-group", "label": "FAQ groep", "icon": "?+", "default_props": {"items": []}, "schema": {}},
    {"type": "testimonial", "label": "Testimonial", "icon": "TM", "default_props": {"quote": "", "author": ""}, "schema": {}},
    {"type": "icon-box", "label": "Icon box", "icon": "IB", "default_props": {"icon": "", "title": "", "text": ""}, "schema": {}},
    {"type": "contact-form-ref", "label": "Contact form", "icon": "CF", "default_props": {"form_id": "default"}, "schema": {}},
    {"type": "google-map", "label": "Google map", "icon": "MAP", "default_props": {"query": ""}, "schema": {}},
    {"type": "breadcrumb", "label": "Breadcrumb", "icon": "BC", "default_props": {"items": []}, "schema": {}},
    {"type": "table", "label": "Tabel", "icon": "TBL", "default_props": {"rows": []}, "schema": {}},
]


@app.route("/api/blocks/library", methods=["GET"])
def api_blocks_library():
    a = _auth_or_401()
    if a: return a
    return jsonify({"blocks": BLOCK_LIBRARY})


# ---------- media ----------
def _media_index() -> list:
    return kv_get("media:index", []) or []


def _save_media_index(items: list) -> None:
    kv_set("media:index", items)


@app.route("/api/admin/media", methods=["GET"])
def api_admin_media_list():
    a = _auth_or_401()
    if a: return a
    items = _media_index()
    typ = request.args.get("type")
    q = (request.args.get("q") or "").lower()
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    if typ: items = [m for m in items if (m.get("mime", "").startswith(typ))]
    if q: items = [m for m in items if q in (m.get("filename", "") + (m.get("alt") or "")).lower()]
    return jsonify({"items": items[offset:offset + limit], "total": len(items)})


@app.route("/api/media/upload", methods=["POST"])
def api_media_upload():
    a = _auth_or_401()
    if a: return a
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Geen bestand"}), 400
    data = f.read()
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", f.filename or "upload.bin")
    mime = f.mimetype or "application/octet-stream"
    ok, url = blob_put(f"media/{uuid.uuid4().hex[:8]}_{filename}", data, mime)
    if not ok:
        return jsonify({"error": url}), 500
    item = {
        "id": uuid.uuid4().hex[:12],
        "url": url,
        "filename": filename,
        "alt": request.form.get("alt", ""),
        "title": request.form.get("title", ""),
        "caption": request.form.get("caption", ""),
        "mime": mime,
        "bytes": len(data),
        "width": None,
        "height": None,
        "used_on": [],
        "variants": {"webp_url": None, "thumb_url": None},
        "uploaded_by": session.get("user", "admin"),
        "uploaded_at": _now_iso(),
    }
    kv_set(f"media:{item['id']}", item)
    idx = _media_index()
    idx.insert(0, {k: item[k] for k in ("id", "filename", "mime", "bytes", "url", "uploaded_at")})
    _save_media_index(idx)
    audit_log("media.upload", item["id"], f"Upload {filename}")
    return jsonify(item), 201


@app.route("/api/admin/media/<media_id>", methods=["PATCH"])
def api_admin_media_update(media_id):
    a = _auth_or_401()
    if a: return a
    item = kv_get(f"media:{media_id}")
    if not item:
        return jsonify({"error": "Niet gevonden"}), 404
    body = request.get_json(silent=True) or {}
    for k in ("alt", "title", "caption"):
        if k in body: item[k] = body[k]
    kv_set(f"media:{media_id}", item)
    audit_log("media.update", media_id, "Metadata bijgewerkt")
    return jsonify(item)


@app.route("/api/admin/media/<media_id>", methods=["DELETE"])
def api_admin_media_delete(media_id):
    a = _auth_or_401()
    if a: return a
    item = kv_get(f"media:{media_id}")
    if not item:
        return jsonify({"error": "Niet gevonden"}), 404
    force = request.args.get("force") == "1"
    used_on = item.get("used_on", []) or []
    if used_on and not force:
        return jsonify({"error": "Media is in gebruik", "used_on": used_on}), 409
    blob_delete(item.get("url", ""))
    kv_delete(f"media:{media_id}")
    idx = [m for m in _media_index() if m.get("id") != media_id]
    _save_media_index(idx)
    audit_log("media.delete", media_id, "Verwijderd")
    return jsonify({"deleted": True, "was_used_on": used_on})


@app.route("/api/admin/media/<media_id>/replace", methods=["POST"])
def api_admin_media_replace(media_id):
    a = _auth_or_401()
    if a: return a
    item = kv_get(f"media:{media_id}")
    if not item:
        return jsonify({"error": "Niet gevonden"}), 404
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Geen bestand"}), 400
    data = f.read()
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", f.filename or "upload.bin")
    ok, url = blob_put(f"media/{uuid.uuid4().hex[:8]}_{filename}", data, f.mimetype or "application/octet-stream")
    if not ok:
        return jsonify({"error": url}), 500
    item["url"] = url
    item["bytes"] = len(data)
    item["filename"] = filename
    kv_set(f"media:{media_id}", item)
    return jsonify(item)


@app.route("/api/admin/media/bulk", methods=["POST"])
def api_admin_media_bulk():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    ids = body.get("ids") or []
    action = body.get("action")
    payload = body.get("payload") or {}
    updated = 0
    failed = []
    for mid in ids:
        item = kv_get(f"media:{mid}")
        if not item:
            failed.append({"id": mid, "error": "not found"}); continue
        try:
            if action == "delete":
                blob_delete(item.get("url", ""))
                kv_delete(f"media:{mid}")
            elif action == "set_alt_prefix":
                item["alt"] = f"{payload.get('prefix', '')}{item.get('alt', '')}"
                kv_set(f"media:{mid}", item)
            elif action == "regenerate_webp":
                # No-op without Pillow; mark variants null
                item["variants"] = {"webp_url": None, "thumb_url": None}
                kv_set(f"media:{mid}", item)
            updated += 1
        except Exception as e:
            failed.append({"id": mid, "error": str(e)})
    if action == "delete":
        idx = [m for m in _media_index() if m.get("id") not in ids]
        _save_media_index(idx)
    return jsonify({"updated": updated, "failed": failed})


@app.route("/api/admin/media/<media_id>/usage", methods=["GET"])
def api_admin_media_usage(media_id):
    a = _auth_or_401()
    if a: return a
    item = kv_get(f"media:{media_id}")
    if not item:
        return jsonify({"error": "Niet gevonden"}), 404
    used = []
    for slug_meta in _pages_index():
        slug = slug_meta["slug"]
        page = _get_page(slug)
        if not page: continue
        for i, b in enumerate(page.get("content_blocks", []) or []):
            props = b.get("props", {}) or {}
            if (props.get("src") == item.get("url")
                    or (props.get("media_id") == media_id)):
                used.append({"slug": slug, "title": page.get("title"), "block_index": i})
    return jsonify({"used_on": used})


@app.route("/api/media/stats", methods=["GET"])
def api_media_stats():
    a = _auth_or_401()
    if a: return a
    items = _media_index()
    total = sum(m.get("bytes", 0) for m in items)
    by_mime: dict = {}
    for m in items:
        key = (m.get("mime") or "").split("/")[0] or "other"
        by_mime[key] = by_mime.get(key, 0) + 1
    return jsonify({"count": len(items), "total_bytes": total, "by_mime": by_mime})


# ---------- templates ----------
def _substitute(value, vars_: dict):
    if isinstance(value, str):
        for k, v in vars_.items():
            value = value.replace(f"{{{{{k}}}}}", str(v))
        return value
    if isinstance(value, dict):
        return {k: _substitute(v, vars_) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, vars_) for v in value]
    return value


def _substitute_template(blocks: list, vars_: dict) -> list:
    return _substitute(blocks, vars_) or []


def _substitute_template_meta(meta: dict, vars_: dict) -> dict:
    return _substitute(meta, vars_) or {}


@app.route("/api/templates", methods=["GET"])
def api_templates_list():
    a = _auth_or_401()
    if a: return a
    names = kv_get("templates:index", []) or []
    items = []
    for n in names:
        t = kv_get(f"template:{n}")
        if t:
            items.append({"name": t.get("name"), "slug_pattern": t.get("slug_pattern"),
                          "description": t.get("description", ""), "variables": t.get("variables", [])})
    return jsonify({"items": items})


@app.route("/api/templates/<name>", methods=["GET"])
def api_template_get(name):
    a = _auth_or_401()
    if a: return a
    t = kv_get(f"template:{name}")
    if not t:
        return jsonify({"error": "Niet gevonden"}), 404
    return jsonify(t)


@app.route("/api/templates", methods=["POST"])
def api_template_create():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not name:
        return jsonify({"error": "name verplicht"}), 400
    if kv_get(f"template:{name}"):
        return jsonify({"error": "Bestaat al"}), 409
    t = {
        "name": name,
        "slug_pattern": body.get("slug_pattern", "{slug}"),
        "description": body.get("description", ""),
        "content_blocks": body.get("content_blocks", []),
        "variables": body.get("variables", []),
        "default_meta": body.get("default_meta", {}),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    kv_set(f"template:{name}", t)
    idx = kv_get("templates:index", []) or []
    if name not in idx:
        idx.append(name); kv_set("templates:index", idx)
    audit_log("template.create", name, "Aangemaakt")
    return jsonify(t), 201


@app.route("/api/templates/<name>", methods=["PUT"])
def api_template_update(name):
    a = _auth_or_401()
    if a: return a
    t = kv_get(f"template:{name}")
    if not t:
        return jsonify({"error": "Niet gevonden"}), 404
    body = request.get_json(silent=True) or {}
    for k in ("slug_pattern", "description", "content_blocks", "variables", "default_meta"):
        if k in body: t[k] = body[k]
    t["updated_at"] = _now_iso()
    kv_set(f"template:{name}", t)
    audit_log("template.update", name, "Bijgewerkt")
    return jsonify({"name": name, "updated_at": t["updated_at"]})


@app.route("/api/templates/<name>", methods=["DELETE"])
def api_template_delete(name):
    a = _auth_or_401()
    if a: return a
    if not kv_get(f"template:{name}"):
        return jsonify({"error": "Niet gevonden"}), 404
    kv_delete(f"template:{name}")
    idx = [n for n in (kv_get("templates:index", []) or []) if n != name]
    kv_set("templates:index", idx)
    audit_log("template.delete", name, "Verwijderd")
    return jsonify({"deleted": True})


@app.route("/api/templates/<name>/apply", methods=["POST"])
def api_template_apply(name):
    a = _auth_or_401()
    if a: return a
    t = kv_get(f"template:{name}")
    if not t:
        return jsonify({"error": "Niet gevonden"}), 404
    body = request.get_json(silent=True) or {}
    vars_ = body.get("variables", {}) or {}
    slug_override = body.get("slug_override")
    slug = _safe_slug(slug_override or _substitute(t.get("slug_pattern", "{slug}"), vars_))
    if not slug:
        return jsonify({"error": "Kon geen slug bepalen"}), 400
    if _get_page(slug):
        return jsonify({"error": f"{slug} bestaat al"}), 409
    title = vars_.get("title") or vars_.get("stad") or vars_.get("dienst") or slug
    page = _default_page(slug, title, template=name)
    page["content_blocks"] = _substitute_template(t.get("content_blocks") or [], vars_)
    page["meta"].update(_substitute_template_meta(t.get("default_meta") or {}, vars_))
    _save_page(page)
    update_seo_score(page)
    audit_log("template.apply", name, f"Page {slug} aangemaakt")
    return jsonify({"slug": slug, "title": title, "status": "draft"}), 201


# Block library beschikbaar voor de AI
_AI_BLOCK_HINTS = (
    "Beschikbare block types (gebruik alleen deze namen in JSON):\n"
    "- heading-h1 / heading-h2 / heading-h3 / heading-h4 — {type, text}\n"
    "- paragraph — {type, text}\n"
    "- list-ul / list-ol — {type, items:[string,...]}\n"
    "- button — {type, text, href}\n"
    "- image — {type, src, alt}  (gebruik /wp-content/uploads/... paden)\n"
    "- quote — {type, text, cite}\n"
    "- cta-banner — {type, title, subtitle, cta_text, cta_href}\n"
    "- faq-group — {type, items:[{question, answer}, ...]}\n"
    "- testimonial — {type, quote, author}\n"
    "- icon-box — {type, icon, title, text}\n"
    "- hr — {type}\n"
)


@app.route("/api/admin/pages/generate-from-prompt", methods=["POST"])
def api_generate_page_from_prompt():
    """Genereer een complete pagina (alle blocks + SEO-meta) uit een natuurlijke prompt.
    Gebruikt door de Templates → 'Genereer met AI' UI.

    Body: {
      prompt: string,   # vrij Nederlands: "Maak een dienst-pagina over betoncire voor badkamers..."
      slug?: string,    # optioneel; anders auto-genereren uit dienst-naam
      template?: string,  # bv 'dienst' om de pagina-structuur te scopen
      reference_slug?: string  # optioneel: kopieer structuur van bestaande pagina
    }
    Returns: {slug, title, status:'draft'}.
    """
    a = _auth_or_401()
    if a: return a
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY ontbreekt — vul in Vercel env vars"}), 503
    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt verplicht"}), 400
    template = body.get("template") or "dienst"
    slug_override = body.get("slug")
    reference_slug = body.get("reference_slug")

    # Referentie ophalen voor stilistische context
    reference_blocks = []
    reference_title = ""
    if reference_slug:
        ref = _get_page(_safe_slug(reference_slug))
        if ref:
            reference_blocks = ref.get("content_blocks", [])[:25]
            reference_title = ref.get("title", "")
    elif template == "dienst":
        # Fall-back referentie: de bestaande dunpleisterwerk-pagina
        ref = _get_page("diensten/dunpleisterwerk")
        if ref:
            reference_blocks = ref.get("content_blocks", [])[:25]
            reference_title = ref.get("title", "")

    system = (
        "Je bent een SEO-content specialist voor Wandmeesters (Nederlands stucadoorsbedrijf in Monnickendam). "
        "Je schrijft Nederlandse webpagina-content gericht op zowel Google ranking als conversie naar offerte-aanvraag. "
        "Brand-tone: vakkundig, no-nonsense, gericht op kwaliteit en betrouwbaarheid. "
        "Gebruik altijd 'u' (niet 'jij'). "
        "Returneert STRIKT geldige JSON, geen markdown of uitleg er omheen. "
        "JSON-vorm: {\"title\":\"...\",\"meta\":{\"description\":\"...max 160 chars\",\"keyword\":\"...\"},\"content_blocks\":[...]}. "
        + _AI_BLOCK_HINTS +
        "Richtlijnen voor content_blocks:\n"
        "- Begin met heading-h1 (de paginatitel)\n"
        "- Volg met een korte intro paragraph (2-3 zinnen, vermeld het keyword)\n"
        "- Verdeel content in 3-5 logische h2-secties, elk met 1-2 paragraphs\n"
        "- Gebruik list-ul voor voordelen/kenmerken (minimaal 4 items)\n"
        "- Voeg een faq-group toe met 3-5 vragen (gericht op transactionele/lokale intent)\n"
        "- Eindig met cta-banner naar /contact/\n"
        "- Inlinks naar andere diensten waar relevant via paragraph tekst (geen aparte link-blocks)\n"
        "- Totaal ~12-18 blocks, minimum 600 woorden tekst\n"
    )

    ref_text = ""
    if reference_blocks:
        ref_text = (
            f"\n\nReferentie-pagina '{reference_title}' (kopieer NIET letterlijk, gebruik als stijl-/structuur-voorbeeld):\n"
            + json.dumps(reference_blocks, ensure_ascii=False)[:3500]
        )

    user_msg = (
        f"Verzoek: {prompt}\n"
        f"Template: {template}\n"
        + (f"Gewenste slug: {slug_override}\n" if slug_override else "")
        + ref_text
        + "\n\nGenereer nu de volledige pagina als JSON."
    )

    result = _anthropic_call(
        messages=[{"role": "user", "content": user_msg}],
        system=system,
        max_tokens=8000,
    )
    if "error" in result:
        return jsonify({"error": "AI-aanroep mislukt", "details": result}), 502
    raw_text = ""
    try:
        raw_text = result["content"][0]["text"]
    except Exception:
        return jsonify({"error": "Onverwacht AI-antwoord", "result": result}), 502

    # Strip markdown code fences als die er om staan
    raw_text = re.sub(r"^```(?:json)?\s*\n", "", raw_text.strip())
    raw_text = re.sub(r"\n```\s*$", "", raw_text)

    try:
        page_data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return jsonify({"error": "AI gaf geen geldige JSON", "raw": raw_text[:800], "parse_error": str(e)}), 502

    title = (page_data.get("title") or "").strip() or "Nieuwe AI-pagina"
    meta_in = page_data.get("meta") or {}
    blocks = page_data.get("content_blocks") or []
    if not isinstance(blocks, list) or not blocks:
        return jsonify({"error": "AI gaf geen content_blocks", "raw": raw_text[:600]}), 502

    # Slug bepalen
    if slug_override:
        slug = _safe_slug(slug_override)
    else:
        # Auto-slug van title (incl prefix 'diensten/' voor dienst-template)
        base = _safe_slug(title)
        if template == "dienst" and not base.startswith("diensten/"):
            base = "diensten/" + base
        slug = base
    if not slug:
        return jsonify({"error": "Kon geen slug bepalen"}), 400
    # Uniqueness
    orig_slug = slug
    suffix = 2
    while _get_page(slug):
        slug = f"{orig_slug}-{suffix}"
        suffix += 1

    page = _default_page(slug, title, template=template)
    page["content_blocks"] = blocks
    page["meta"]["description"] = (meta_in.get("description") or "")[:160]
    page["meta"]["keyword"] = meta_in.get("keyword") or ""
    page["meta"]["og_title"] = title
    page["meta"]["og_description"] = page["meta"]["description"]
    page["meta"]["canonical"] = f"https://wandmeesters.nl/{slug}/"
    _save_page(page)
    update_seo_score(page)
    audit_log("ai.generate", slug, f"AI-pagina aangemaakt uit prompt: {prompt[:80]}")
    return jsonify({
        "slug": slug,
        "title": title,
        "status": "draft",
        "blocks_count": len(blocks),
        "redirect": f"/admin/#page-editor/{slug}",
    }), 201


# ============ DIENST TEMPLATE (1-op-1 design copy van /diensten/dunpleisterwerk/) ============
DIENST_TEMPLATE_PATH = Path(__file__).resolve().parent / "data" / "dienst-template.html"
DIENST_DEFAULTS_PATH = Path(__file__).resolve().parent / "data" / "dienst-template-defaults.json"


def _load_dienst_template_html() -> str:
    try:
        return DIENST_TEMPLATE_PATH.read_text("utf-8")
    except Exception:
        return ""


def _load_dienst_template_defaults() -> dict:
    try:
        return json.loads(DIENST_DEFAULTS_PATH.read_text("utf-8"))
    except Exception:
        return {"dienst_name": "", "meta_description": "", "hero_image": "", "sections": []}


def _render_dienst_html(slug: str, dienst_name: str, meta_description: str,
                        sections: list, hero_image: str = "", seo: dict = None,
                        bullets: list = None) -> str:
    """Render een dienst-pagina HTML door slots in dunpleisterwerk-template te vervangen.

    sections = [{h2: str, body: str}, ...]  max 8 items (mappen 1-op-1 op de 8 H2s in template)
    """
    html = _load_dienst_template_html()
    if not html:
        raise RuntimeError("dienst-template.html niet gevonden in api/data/")

    seo = seo or {}

    # 1) <title> — gebruik seo.seo_title als overgeven, anders standaard
    safe_name = html_escape(dienst_name or "Dienst")
    title_tag = (seo.get("seo_title") or "").strip() or f"{dienst_name} - Wandmeesters"
    html = re.sub(r"<title[^>]*>[^<]+</title>",
                  f"<title>{html_escape(title_tag)}</title>", html, count=1)

    # 2) meta description
    if meta_description:
        html = re.sub(r'(<meta\s+name=["\']description["\']\s+content=)["\'][^"\']*["\']',
                      lambda m: m.group(1) + '"' + html_escape(meta_description) + '"',
                      html, count=1, flags=re.I)

    # 3) canonical (custom of auto)
    new_canonical = (seo.get("seo_canonical") or "").strip() or f"https://wandmeesters.nl/diensten/{slug}/"
    html = re.sub(r'(<link\s+rel=["\']canonical["\']\s+href=)["\'][^"\']*["\']',
                  lambda m: m.group(1) + '"' + html_escape(new_canonical) + '"',
                  html, count=1, flags=re.I)

    # 3b) robots
    robots_parts = []
    robots_parts.append("index" if seo.get("seo_index", True) else "noindex")
    robots_parts.append("follow" if seo.get("seo_follow", True) else "nofollow")
    if seo.get("seo_noarchive"): robots_parts.append("noarchive")
    robots_val = ",".join(robots_parts) + ",max-snippet:-1,max-video-preview:-1,max-image-preview:large"
    html = re.sub(r'(<meta\s+name=["\']robots["\']\s+content=)["\'][^"\']*["\']',
                  lambda m: m.group(1) + '"' + html_escape(robots_val) + '"',
                  html, count=1, flags=re.I)

    # 3c) hreflang — voeg toe in head
    if seo.get("seo_hreflang"):
        hrefl_tags = []
        for line in seo["seo_hreflang"].split("\n"):
            line = line.strip()
            if not line or "," not in line: continue
            locale, url = line.split(",", 1)
            locale = locale.strip(); url = url.strip()
            if not url.startswith("http"): url = "https://wandmeesters.nl" + (url if url.startswith("/") else "/" + url)
            hrefl_tags.append(f'<link rel="alternate" hreflang="{html_escape(locale)}" href="{html_escape(url)}">')
        if hrefl_tags:
            html = re.sub(r"</head>", "\n".join(hrefl_tags) + "\n</head>", html, count=1, flags=re.I)

    # 3d) Custom JSON-LD schema (voeg toe in head)
    if seo.get("seo_jsonld"):
        try:
            json.loads(seo["seo_jsonld"])  # valideer
            jsonld_tag = f'<script type="application/ld+json">{seo["seo_jsonld"]}</script>'
            html = re.sub(r"</head>", jsonld_tag + "\n</head>", html, count=1, flags=re.I)
        except Exception:
            pass

    # 4) og: tags (seo override of standaard)
    og_title = (seo.get("seo_og_title") or "").strip() or f"{dienst_name} - Wandmeesters"
    og_desc = (seo.get("seo_og_description") or "").strip() or meta_description
    twitter_card = seo.get("seo_twitter_card", "summary_large_image")
    for prop, val in [("og:title", og_title),
                      ("og:description", og_desc),
                      ("og:url", new_canonical),
                      ("og:image", hero_image or "")]:
        if not val: continue
        html = re.sub(
            rf'(<meta\s+property=["\']{re.escape(prop)}["\']\s+content=)["\'][^"\']*["\']',
            lambda m, v=val: m.group(1) + '"' + html_escape(v) + '"',
            html, count=1, flags=re.I,
        )
    # twitter:card meta-tag aanpassen
    html = re.sub(r'(<meta\s+name=["\']twitter:card["\']\s+content=)["\'][^"\']*["\']',
                  lambda m: m.group(1) + '"' + html_escape(twitter_card) + '"',
                  html, count=1, flags=re.I)

    # 5) H2 + bijbehorend text-editor blok vervangen (max 8 secties)
    # We pakken de eerste 8 <h2 class="elementor-heading-title…"> in volgorde.
    h2_pattern = re.compile(
        r'(<h2[^>]*class="elementor-heading-title[^"]*"[^>]*>)([\s\S]*?)(</h2>)',
        re.I,
    )
    text_editor_pattern = re.compile(
        r'(<div\s+class="elementor-widget-container">\s*)<p[^>]*>[\s\S]*?</p>(\s*</div>)',
        re.I,
    )

    h2_positions = [m for m in h2_pattern.finditer(html)]
    max_sections = min(8, len(sections), len(h2_positions))

    # Werk van achter naar voren zodat string-posities geldig blijven
    for i in range(max_sections - 1, -1, -1):
        sec = sections[i]
        new_h2 = html_escape((sec.get("h2") or "").strip()) or html_escape(dienst_name)
        new_body = (sec.get("body") or "").strip()
        if not new_body:
            continue
        # Splits body op blanco regels → meerdere <p> tags
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", new_body) if p.strip()]
        new_p_block = "".join(f"<p>{_render_inline_with_links(p)}</p>" for p in paragraphs)

        h2_match = h2_positions[i]
        # Replace H2 inner text
        h2_start = h2_match.start(2)
        h2_end = h2_match.end(2)
        html = html[:h2_start] + new_h2 + html[h2_end:]
        # Recompute h2 positions after this edit? Niet nodig: we werken achter→voren, dus alleen items i+1.. zijn al gepatched.
        # Maar daarna zoeken we de volgende text-editor block. Refresh search-positie:
        # Hervind dezelfde H2 (positie kan iets verschoven zijn door de replace hierboven)
        h2_pat_inst = re.compile(
            r'<h2[^>]*class="elementor-heading-title[^"]*"[^>]*>' + re.escape(new_h2) + r'</h2>',
            re.I,
        )
        after_h2 = h2_pat_inst.search(html)
        if not after_h2:
            continue
        search_start = after_h2.end()
        # Zoek eerste text-editor blok binnen volgende 8000 chars
        snippet = html[search_start:search_start + 8000]
        te = text_editor_pattern.search(snippet)
        if te:
            # Als sectie een image_url heeft: injecteer Elementor image widget vóór de text-editor
            section_img = (sec.get("image_url") or "").strip()
            img_block = ""
            if section_img:
                alt = html_escape(sec.get("image_alt") or sec.get("h2") or dienst_name)
                img_block = (
                    '<div class="elementor-element elementor-widget elementor-widget-image" '
                    'data-element_type="widget" data-widget_type="image.default">'
                    '<div class="elementor-widget-container">'
                    f'<img src="{html_escape(section_img)}" alt="{alt}" loading="lazy" '
                    'style="width:100%;height:auto;border-radius:8px;display:block;margin:16px 0">'
                    '</div></div>'
                )
            replacement = (img_block + te.group(1)) + new_p_block + te.group(2) if img_block else (te.group(1) + new_p_block + te.group(2))
            abs_start = search_start + te.start()
            abs_end = search_start + te.end()
            html = html[:abs_start] + replacement + html[abs_end:]

    # 6) Eyebrow-badges ("Dunpleisterwerk" badge boven elke H2) vervangen door dienst_name
    safe_dienst = html_escape(dienst_name)
    html = re.sub(
        r'(<span class="elementor-button-text">)Dunpleisterwerk(</span>)',
        lambda m, n=safe_dienst: m.group(1) + n + m.group(2),
        html,
    )
    # Breadcrumb-link "/Dunpleisterwerk" vervangen
    html = re.sub(
        r'<a href="/Dunpleisterwerk">',
        f'<a href="/diensten/{html_escape(slug)}/">',
        html,
    )
    # Breadcrumb icon-list-text "Dunpleisterwerk" → dienst_name
    html = re.sub(
        r'(<span class="elementor-icon-list-text">)Dunpleisterwerk(</span>)',
        lambda m, n=safe_dienst: m.group(1) + n + m.group(2),
        html, count=1,
    )

    # 7) Bullet list (Expertise / Kwaliteit / Ervaring) → editable
    bl = [b for b in (bullets or []) if (b or "").strip()]
    if bl:
        defaults_bl = ["Expertise", "Kwaliteit", "Ervaring"]
        for i, default_text in enumerate(defaults_bl):
            if i < len(bl):
                new_val = html_escape(bl[i])
                html = re.sub(
                    r'(<span class="elementor-icon-list-text">)' + re.escape(default_text) + r'(</span>)',
                    lambda m, v=new_val: m.group(1) + v + m.group(2),
                    html, count=1,
                )

    # 8) Inline-link hover styling + hero title bredere container
    hover_css = (
        "<style>"
        ".ms-inline-link{text-decoration:none;transition:opacity .15s ease,color .15s ease}"
        ".ms-inline-link:hover{opacity:.7 !important;color:#4d9091 !important;text-decoration:underline}"
        ".elementor-widget-heading:has(.ms-split-title){max-width:none !important;width:100% !important}"
        ".elementor-widget-heading:has(.ms-split-title) > .elementor-widget-container{max-width:1400px !important;width:100% !important;margin:0 auto !important;padding:0 24px !important;text-align:center !important}"
        ".ms-split-title{max-width:100% !important;width:100% !important;white-space:normal !important}"
        ".ms-split-title span{display:inline !important}"
        "</style>"
    )
    if "ms-inline-link" not in html.split("</head>", 1)[0]:
        html = re.sub(r"</head>", hover_css + "</head>", html, count=1, flags=re.I)

    # 9) Force consistent favicon site-wide
    html = re.sub(r'<link[^>]+rel=["\'](?:icon|shortcut icon|apple-touch-icon)["\'][^>]*/?>', '', html, flags=re.I)
    fav_tags = '<link rel="icon" type="image/webp" href="/favicon.webp" sizes="32x32"><link rel="apple-touch-icon" href="/favicon.webp">'
    html = re.sub(r'(<meta\s+charset=["\'][^"\']+["\']\s*/?>)', r'\1' + fav_tags, html, count=1, flags=re.I)

    return html


# ============ LOCATIE TEMPLATE (1-op-1 stukadoor-alkmaar design) ============
LOCATIE_TEMPLATE_PATH = Path(__file__).resolve().parent / "data" / "locatie-template.html"
LOCATIE_DEFAULTS_PATH = Path(__file__).resolve().parent / "data" / "locatie-template-defaults.json"


def _load_locatie_template_html() -> str:
    try:
        return LOCATIE_TEMPLATE_PATH.read_text("utf-8")
    except Exception:
        return ""


def _load_locatie_template_defaults() -> dict:
    try:
        return json.loads(LOCATIE_DEFAULTS_PATH.read_text("utf-8"))
    except Exception:
        return {"dienst_name": "", "stad": "", "meta_description": "", "hero_image": "", "sections": [], "faq": []}


def _render_locatie_html(slug: str, dienst_name: str, stad: str, meta_description: str,
                          sections: list, faq: list, hero_image: str = "",
                          usp_cards: list = None, seo: dict = None,
                          bullets: list = None) -> str:
    """Render een locatie-pagina (stukadoor-stad design) met slots."""
    html = _load_locatie_template_html()
    if not html:
        raise RuntimeError("locatie-template.html niet gevonden")
    seo = seo or {}
    safe_name = dienst_name or f"Stukadoor in {stad}"
    title_tag = (seo.get("seo_title") or "").strip() or f"{safe_name} | Wandmeesters"
    new_canonical = (seo.get("seo_canonical") or "").strip() or f"https://wandmeesters.nl/diensten/{slug}/"

    html = re.sub(r"<title[^>]*>[^<]+</title>",
                  f"<title>{html_escape(title_tag)}</title>", html, count=1)
    if meta_description:
        html = re.sub(r'(<meta\s+name=["\']description["\']\s+content=)["\'][^"\']*["\']',
                      lambda m: m.group(1) + '"' + html_escape(meta_description) + '"',
                      html, count=1, flags=re.I)
    html = re.sub(r'(<link\s+rel=["\']canonical["\']\s+href=)["\'][^"\']*["\']',
                  lambda m: m.group(1) + '"' + html_escape(new_canonical) + '"',
                  html, count=1, flags=re.I)

    # Robots
    rp = []
    rp.append("index" if seo.get("seo_index", True) else "noindex")
    rp.append("follow" if seo.get("seo_follow", True) else "nofollow")
    if seo.get("seo_noarchive"): rp.append("noarchive")
    robots_val = ",".join(rp) + ",max-snippet:-1,max-video-preview:-1,max-image-preview:large"
    html = re.sub(r'(<meta\s+name=["\']robots["\']\s+content=)["\'][^"\']*["\']',
                  lambda m: m.group(1) + '"' + html_escape(robots_val) + '"',
                  html, count=1, flags=re.I)

    # hreflang + JSON-LD
    if seo.get("seo_hreflang"):
        tags = []
        for line in seo["seo_hreflang"].split("\n"):
            line = line.strip()
            if not line or "," not in line: continue
            loc, url = line.split(",", 1); loc, url = loc.strip(), url.strip()
            if not url.startswith("http"): url = "https://wandmeesters.nl" + (url if url.startswith("/") else "/" + url)
            tags.append(f'<link rel="alternate" hreflang="{html_escape(loc)}" href="{html_escape(url)}">')
        if tags: html = re.sub(r"</head>", "\n".join(tags) + "\n</head>", html, count=1, flags=re.I)
    if seo.get("seo_jsonld"):
        try:
            json.loads(seo["seo_jsonld"])
            html = re.sub(r"</head>", f'<script type="application/ld+json">{seo["seo_jsonld"]}</script>\n</head>', html, count=1, flags=re.I)
        except Exception: pass

    og_title = (seo.get("seo_og_title") or "").strip() or title_tag
    og_desc = (seo.get("seo_og_description") or "").strip() or meta_description
    for prop, val in [("og:title", og_title), ("og:description", og_desc),
                      ("og:url", new_canonical), ("og:image", hero_image)]:
        if not val: continue
        html = re.sub(
            rf'(<meta\s+property=["\']{re.escape(prop)}["\']\s+content=)["\'][^"\']*["\']',
            lambda m, v=val: m.group(1) + '"' + html_escape(v) + '"',
            html, count=1, flags=re.I,
        )
    tc = seo.get("seo_twitter_card", "summary_large_image")
    html = re.sub(r'(<meta\s+name=["\']twitter:card["\']\s+content=)["\'][^"\']*["\']',
                  lambda m: m.group(1) + '"' + html_escape(tc) + '"',
                  html, count=1, flags=re.I)

    # 2) Vervang oude stad-naam ("Alkmaar") door nieuwe stad in alle plain text
    # Belangrijke: vervang alleen in <h2> en <p> tekst, niet in attributen
    if stad and stad.lower() != "alkmaar":
        # Vervang in H1/H2/P inhoud, hoofdletter-gevoelig
        def replace_stad(match):
            return match.group(1) + match.group(2).replace("Alkmaar", stad).replace("alkmaar", stad.lower()) + match.group(3)
        html = re.sub(r'(<(?:h1|h2|h3|p|span|a)[^>]*>)([\s\S]*?)(</(?:h1|h2|h3|p|span|a)>)',
                       replace_stad, html, flags=re.I)

    # 3) Vervang H2 + text-editor + image per sectie
    h2_pattern = re.compile(
        r'(<h2[^>]*class="elementor-heading-title[^"]*"[^>]*>)([\s\S]*?)(</h2>)',
        re.I,
    )
    text_editor_pattern = re.compile(
        r'(<div\s+class="elementor-widget-container">\s*)<p[^>]*>[\s\S]*?</p>(\s*</div>)',
        re.I,
    )
    image_widget_pattern = re.compile(
        r'(<div\s+class="elementor-widget-container">\s*)<img[^>]+src=["\']([^"\']+)["\'](\s+alt=["\'][^"\']*["\'])?([^>]*>)(\s*</div>)',
        re.I,
    )

    h2_positions = list(h2_pattern.finditer(html))
    max_sections = min(8, len(sections), len(h2_positions))

    for i in range(max_sections - 1, -1, -1):
        sec = sections[i]
        new_h2 = html_escape((sec.get("h2") or "").strip()) or safe_name
        new_body = (sec.get("body") or "").strip()
        section_img = (sec.get("image_url") or "").strip()
        section_alt = html_escape(sec.get("image_alt") or sec.get("h2") or "")

        h2_match = h2_positions[i]
        html = html[:h2_match.start(2)] + new_h2 + html[h2_match.end(2):]

        h2_pat_inst = re.compile(
            r'<h2[^>]*class="elementor-heading-title[^"]*"[^>]*>' + re.escape(new_h2) + r'</h2>',
            re.I,
        )
        after_h2 = h2_pat_inst.search(html)
        if not after_h2:
            continue
        search_start = after_h2.end()
        search_end = search_start + 10000

        # Substituut image widget binnen sectie (eerstvolgende)
        if section_img:
            snippet = html[search_start:search_end]
            img_m = image_widget_pattern.search(snippet)
            if img_m:
                abs_start = search_start + img_m.start()
                abs_end = search_start + img_m.end()
                # Behoud de structuur, vervang alleen src + alt
                rebuilt = (
                    img_m.group(1)
                    + f'<img src="{html_escape(section_img)}" alt="{section_alt}"'
                    + (f' loading="lazy" decoding="async">')
                    + img_m.group(5)
                )
                html = html[:abs_start] + rebuilt + html[abs_end:]

        # Substituut text-editor (paragraph)
        if new_body:
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", new_body) if p.strip()]
            new_p_block = "".join(f"<p>{_render_inline_with_links(p)}</p>" for p in paragraphs)
            snippet = html[search_start:search_start + 12000]
            te = text_editor_pattern.search(snippet)
            if te:
                replacement = te.group(1) + new_p_block + te.group(2)
                abs_start = search_start + te.start()
                abs_end = search_start + te.end()
                html = html[:abs_start] + replacement + html[abs_end:]

    # 4) FAQ items vervangen (ElementsKit accordion)
    if faq:
        faq_card_pattern = re.compile(
            r'(<span class="ekit-accordion-title">)([^<]+)(</span>[\s\S]*?<div class="elementskit-card-body[^"]*">\s*)<p>[\s\S]*?</p>',
            re.I,
        )
        faq_matches = list(faq_card_pattern.finditer(html))
        for i in range(min(len(faq), len(faq_matches)) - 1, -1, -1):
            item = faq[i]
            q = html_escape((item.get("q") or "").strip())
            a = (item.get("a") or "").strip()
            if not q or not a:
                continue
            parts = [p.strip() for p in re.split(r"\n\s*\n", a) if p.strip()]
            a_html = "".join(f"<p>{_render_inline_with_links(p)}</p>" for p in parts)
            m = faq_matches[i]
            html = html[:m.start()] + m.group(1) + q + m.group(3) + a_html + html[m.end():]

    # 5) USP cards (3x H4 + body) vervangen
    if usp_cards:
        usp_pattern = re.compile(
            r'(<h4[^>]*class="elementor-heading-title[^"]*"[^>]*>)([\s\S]{1,80}?)(</h4>)'
            r'([\s\S]{0,2500}?)<div class="elementor-widget-container">\s*<p[^>]*>([\s\S]{1,500}?)</p>\s*</div>',
            re.I,
        )
        usp_matches = list(usp_pattern.finditer(html))
        for i in range(min(len(usp_cards), len(usp_matches)) - 1, -1, -1):
            card = usp_cards[i]
            new_h4 = html_escape((card.get("h4") or "").strip())
            new_body = (card.get("body") or "").strip()
            if not new_h4 or not new_body:
                continue
            m = usp_matches[i]
            new_p_inner = _render_inline_with_links(new_body)
            html = (
                html[:m.start()]
                + m.group(1) + new_h4 + m.group(3)
                + m.group(4) + '<div class="elementor-widget-container"><p>' + new_p_inner + '</p></div>'
                + html[m.end():]
            )

    # 6) Eyebrow-badges ("Stucwerk" badge boven elke H2) vervangen naar Stukadoor in <stad>
    safe_badge = html_escape(f"Stukadoor in {stad}" if stad else (dienst_name or "Stucwerk"))
    html = re.sub(
        r'(<span class="elementor-button-text">)Stucwerk(</span>)',
        lambda m, n=safe_badge: m.group(1) + n + m.group(2),
        html,
    )
    # Breadcrumb-link "/Stukadoor-Alkmaar" of stadsnaam vervangen
    html = re.sub(
        r'<a href="/Stukadoor[^"]*">',
        f'<a href="/diensten/{html_escape(slug)}/">',
        html,
    )
    # Breadcrumb icon-list-text → nieuwe naam
    html = re.sub(
        r'(<span class="elementor-icon-list-text">)Stukadoor[^<]*(</span>)',
        lambda m, n=safe_badge: m.group(1) + n + m.group(2),
        html, count=1,
    )

    # 7) Bullet list editable (Expertise/Kwaliteit/Ervaring)
    bl_loc = [b for b in (bullets or []) if (b or "").strip()]
    if bl_loc:
        defaults_bl = ["Expertise", "Kwaliteit", "Ervaring"]
        for i, default_text in enumerate(defaults_bl):
            if i < len(bl_loc):
                new_val = html_escape(bl_loc[i])
                html = re.sub(
                    r'(<span class="elementor-icon-list-text">)' + re.escape(default_text) + r'(</span>)',
                    lambda m, v=new_val: m.group(1) + v + m.group(2),
                    html, count=1,
                )

    # 8) Inline-link hover styling + hero title brede container
    hover_css = (
        "<style>"
        ".ms-inline-link{text-decoration:none;transition:opacity .15s ease,color .15s ease}"
        ".ms-inline-link:hover{opacity:.7 !important;color:#4d9091 !important;text-decoration:underline}"
        ".elementor-widget-heading:has(.ms-split-title){max-width:none !important;width:100% !important}"
        ".elementor-widget-heading:has(.ms-split-title) > .elementor-widget-container{max-width:1400px !important;width:100% !important;margin:0 auto !important;padding:0 24px !important;text-align:center !important}"
        ".ms-split-title{max-width:100% !important;width:100% !important;white-space:normal !important}"
        ".ms-split-title span{display:inline !important}"
        "</style>"
    )
    if "ms-inline-link" not in html.split("</head>", 1)[0]:
        html = re.sub(r"</head>", hover_css + "</head>", html, count=1, flags=re.I)

    # 9) Force consistent favicon site-wide
    html = re.sub(r'<link[^>]+rel=["\'](?:icon|shortcut icon|apple-touch-icon)["\'][^>]*/?>', '', html, flags=re.I)
    fav_tags = '<link rel="icon" type="image/webp" href="/favicon.webp" sizes="32x32"><link rel="apple-touch-icon" href="/favicon.webp">'
    html = re.sub(r'(<meta\s+charset=["\'][^"\']+["\']\s*/?>)', r'\1' + fav_tags, html, count=1, flags=re.I)

    return html


@app.route("/api/admin/locatie-template/defaults", methods=["GET"])
def api_locatie_template_defaults():
    a = _auth_or_401()
    if a: return a
    return jsonify(_load_locatie_template_defaults())


@app.route("/api/admin/locatie-template/preview", methods=["POST"])
def api_locatie_template_preview():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    try:
        html = _render_locatie_html(
            slug=_safe_slug(body.get("slug", "preview")),
            dienst_name=body.get("dienst_name", ""),
            stad=body.get("stad", ""),
            meta_description=body.get("meta_description", ""),
            sections=body.get("sections", []) or [],
            faq=body.get("faq", []) or [],
            hero_image=body.get("hero_image", ""),
            usp_cards=body.get("usp_cards", []) or [],
            seo=_extract_seo(body),
            bullets=body.get("bullets", []) or [],
        )
        return Response(html, mimetype="text/html")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/locatie-template/create", methods=["POST"])
def api_locatie_template_create():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    slug_in = (body.get("slug") or "").strip().strip("/")
    if not slug_in: return jsonify({"error": "slug verplicht"}), 400
    if slug_in.startswith("diensten/"):
        slug_in = slug_in[len("diensten/"):]
    slug = _safe_slug(slug_in)
    full_slug = f"diensten/{slug}"
    stad = (body.get("stad") or "").strip() or slug.replace("stukadoor-", "").replace("-", " ").title()
    dienst_name = (body.get("dienst_name") or f"Stukadoor in {stad}").strip()
    meta_desc = (body.get("meta_description") or "").strip()
    sections = body.get("sections") or []
    faq = body.get("faq") or []
    usp_cards = body.get("usp_cards") or []
    hero_image = body.get("hero_image", "")
    seo_data = _extract_seo(body)
    if not sections:
        return jsonify({"error": "sections verplicht"}), 400

    try:
        html = _render_locatie_html(
            slug=slug, dienst_name=dienst_name, stad=stad,
            meta_description=meta_desc, sections=sections, faq=faq,
            hero_image=hero_image, usp_cards=usp_cards, seo=seo_data,
            bullets=body.get("bullets", []) or [],
        )
    except Exception as e:
        return jsonify({"error": "render failed", "details": str(e)}), 500

    kv_set(f"dienst-html:{slug}", html)
    page = _default_page(full_slug, dienst_name, template="locatie-1to1")
    page["status"] = "published"
    page["meta"]["description"] = meta_desc
    page["meta"]["canonical"] = seo_data.get("seo_canonical") or f"https://wandmeesters.nl/diensten/{slug}/"
    page["meta"]["og_title"] = seo_data.get("seo_og_title") or f"{dienst_name} | Wandmeesters"
    page["meta"]["og_description"] = seo_data.get("seo_og_description") or meta_desc
    page["meta"]["og_image"] = hero_image
    if seo_data.get("seo_jsonld"):
        try: page["meta"]["schema_jsonld"] = json.loads(seo_data["seo_jsonld"])
        except Exception: pass
    page["locatie_slots"] = {
        "dienst_name": dienst_name, "stad": stad, "meta_description": meta_desc,
        "hero_image": hero_image, "sections": sections, "faq": faq, "usp_cards": usp_cards,
    }
    page["rendered_html_kb"] = round(len(html) / 1024, 1)
    _save_page(page)
    audit_log("locatie.create", full_slug, f"Locatie '{dienst_name}' aangemaakt")
    return jsonify({
        "slug": full_slug, "url": f"/diensten/{slug}/",
        "redirect_admin": f"/admin/#page-editor/{full_slug}",
        "html_kb": round(len(html) / 1024, 1),
    }), 201


@app.route("/api/admin/locatie-template/ai-fill", methods=["POST"])
def api_locatie_template_ai_fill():
    a = _auth_or_401()
    if a: return a
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY ontbreekt"}), 503
    body = request.get_json(silent=True) or {}
    stad = (body.get("stad") or "").strip()
    prompt = (body.get("prompt") or "").strip()
    # Als stad ontbreekt maar prompt aanwezig: laat AI stad zelf extraheren
    if not stad and not prompt:
        return jsonify({"error": "stad of prompt verplicht"}), 400
    defaults = _load_locatie_template_defaults()
    ref_sections = defaults.get("sections", [])
    ref_faq = defaults.get("faq", [])
    ref_usp = defaults.get("usp_cards", [])
    target_lengths = [max(40, len((s.get('body') or '').split())) for s in ref_sections[:8]]
    targets_str = ", ".join(f"sec{i+1}: ~{w} wrd" for i, w in enumerate(target_lengths))
    available_pages = _ai_context_pages(25)
    available_media = _ai_context_media(20)
    system = (
        "Je schrijft locatie-SEO-content voor Wandmeesters (stucadoorsbedrijf). "
        "Tone: vakkundig, 'u'-vorm, lokaal sterk gericht op de stad. "
        "Returneer STRIKT geldige JSON in deze vorm: "
        "{\"stad\":\"<Stad>\",\"slug\":\"stukadoor-<stad>\","
        "\"dienst_name\":\"Stukadoor in <Stad>\",\"meta_description\":\"...max 160\","
        "\"hero_image\":\"/wp-content/uploads/...\","
        "\"sections\":[{\"h2\":\"...\",\"body\":\"...met [markdown links](/diensten/x/) waar relevant\","
        "\"image_url\":\"/wp-content/...\"} x8],"
        "\"faq\":[{\"q\":\"...\",\"a\":\"...\"} x5],"
        "\"usp_cards\":[{\"h4\":\"...max 30 chars\",\"body\":\"...max 100 chars\"} x3]}. "
        "Geen markdown code fences. Geen uitleg. "
        "SLUG: lowercase, alleen letters/cijfers/streepjes, vorm 'stukadoor-<stadnaam>'. "
        "STAD: als de gebruiker een stad in de prompt noemt, gebruik die exact. "
        "HERO_IMAGE: kies de meest pakkende foto uit media-lijst die past bij stukadoor-werk, of laat leeg. "
        "INTERNE LINKS: scan de body-tekst actief op zinsdelen waarin je een andere bestaande pagina kunt noemen, "
        "en wikkel die in [tekst](/url/) markdown. Max 2 links per sectie, alleen "
        "relevante diensten uit de meegegeven pagina-lijst. "
        "IMAGE_URL per sectie: kies passende foto uit media-lijst, of leeg laten als geen match."
    )
    user_msg = (
        f"Stad: {stad}\n"
        f"Extra context: {prompt or '(geen)'}\n\n"
        "Schrijf 8 secties + 5 FAQ items + 3 USP cards voor een stukadoor-stad pagina, in dezelfde stijl als deze referentie:\n"
        f"SECTIONS: {json.dumps(ref_sections, ensure_ascii=False)[:2500]}\n"
        f"FAQ: {json.dumps(ref_faq, ensure_ascii=False)[:1500]}\n"
        f"USP_CARDS (3x): {json.dumps(ref_usp, ensure_ascii=False)}\n\n"
        f"BESCHIKBARE PAGINA'S voor interne links (gebruik in body-tekst waar relevant): "
        f"{json.dumps(available_pages, ensure_ascii=False)[:1800]}\n\n"
        f"BESCHIKBARE MEDIA voor image_url (alleen exact match):\n"
        f"{json.dumps(available_media, ensure_ascii=False)[:1500]}\n\n"
        f"Houd lengtes aan: {targets_str}.\n"
        "Vervang inhoud, behoud opbouw en intent. "
        "Sectie 1 = hero met 'Stukadoor in <Stad>'. Verwerk lokale referenties (regio, dichtbije steden, prijzen voor de stad). "
        "USP-cards: 3 korte krachtige claims (echte vakmannen, alles onder één dak, ervaring). "
        "BELANGRIJK: in elke sectie waar je een gerelateerde dienst noemt (zoals stucwerk, dunpleister, latex spuitwerk), "
        "wikkel die woorden in markdown links naar de bestaande dienst-pagina's. "
        "Schrijf INHOUDELIJK rijk, geen vulwoorden."
    )
    result = _anthropic_call(
        messages=[{"role": "user", "content": user_msg}],
        system=system,
        max_tokens=5000,
        model=ANTHROPIC_MODEL_FAST,
    )
    if "error" in result:
        return jsonify({"error": "AI-call mislukt", "details": result}), 502
    try:
        raw = result["content"][0]["text"]
    except Exception:
        return jsonify({"error": "Geen AI-antwoord"}), 502
    raw = re.sub(r"^```(?:json)?\s*\n", "", raw.strip())
    raw = re.sub(r"\n```\s*$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return jsonify({"error": "Ongeldige JSON van AI", "raw": raw[:400]}), 502
    return jsonify(data)


# Avoid name conflict — use stdlib's html.escape via alias
from html import escape as html_escape  # noqa: E402


def _ai_context_pages(limit: int = 30) -> list:
    """Lijst van pagina's die AI kan gebruiken voor auto-linking in body-tekst.
    Robuust voor list_pages() dat soms strings teruggeeft (slugs) i.p.v. dicts."""
    try:
        pages = []
        seen = set()
        for entry in _pages_index()[:limit]:
            if not isinstance(entry, dict): continue
            slug = entry.get("slug", "")
            title = entry.get("title", "")
            url = f"/{slug}/" if not slug.startswith("/") else slug
            if slug and slug not in seen:
                seen.add(slug)
                pages.append({"title": title, "url": url, "slug": slug})
        for p in list_pages():
            if not isinstance(p, dict): continue
            slug = p.get("slug", "")
            if slug and slug not in seen and len(pages) < limit:
                seen.add(slug)
                pages.append({
                    "title": p.get("title", "").replace(" - Wandmeesters", ""),
                    "url": p.get("url", f"/{slug}/"),
                    "slug": slug,
                })
        return pages
    except Exception:
        return []


def _ai_context_media(limit: int = 30) -> list:
    """Lijst van bruikbare media-bestanden (gefilterd op naam-relevantie). Guard voor non-dict."""
    try:
        media = list_media()
        good = []
        seen_names = set()
        for m in media:
            if not isinstance(m, dict): continue
            url = m.get("url", "")
            name = m.get("name", "")
            ext = (m.get("ext") or "").lower()
            if ext not in ("jpg", "jpeg", "png", "webp"):
                continue
            if "logo" in url.lower() or "gravatar" in url:
                continue
            if "scaled" in name.lower() and "-scaled" in name:
                continue
            if m.get("size_kb", 0) < 30:
                continue
            base = re.sub(r"-\d+x\d+", "", name)
            if base in seen_names: continue
            seen_names.add(base)
            good.append({"url": url, "name": name})
            if len(good) >= limit: break
        return good
    except Exception:
        return []


def _render_inline_with_links(text: str) -> str:
    """Sta '[text](url)' Markdown-links toe binnen body-tekst. Alle andere HTML wordt escaped.
    Wim selecteert tekst in form → krijgt link-picker → wij injecteren [tekst](url) in textarea.
    Bij render zetten wij dat om naar <a href="url">tekst</a>. Veilig: tekst+url worden escaped.
    """
    if not text:
        return ""
    parts = []
    last_end = 0
    for m in re.finditer(r"\[([^\]]+)\]\(([^)\s]+)\)", text):
        parts.append(html_escape(text[last_end:m.start()]))
        link_text = html_escape(m.group(1))
        link_url = html_escape(m.group(2))
        # Externe URL → target=_blank
        rel_attr = ' target="_blank" rel="noopener"' if link_url.startswith(("http://", "https://")) else ""
        parts.append(f'<a href="{link_url}"{rel_attr} class="ms-inline-link" style="color:#347677">{link_text}</a>')
        last_end = m.end()
    parts.append(html_escape(text[last_end:]))
    return "".join(parts)


@app.route("/api/admin/dienst-template/defaults", methods=["GET"])
def api_dienst_template_defaults():
    """Return de huidige slot-waarden uit dunpleisterwerk zodat Wim ze ziet en kan overschrijven."""
    a = _auth_or_401()
    if a: return a
    return jsonify(_load_dienst_template_defaults())


@app.route("/api/admin/dienst-template/preview", methods=["POST"])
def api_dienst_template_preview():
    """Render een dienst-pagina HTML zonder op te slaan (voor live preview in admin)."""
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    try:
        html = _render_dienst_html(
            slug=_safe_slug(body.get("slug", "preview")),
            dienst_name=body.get("dienst_name", ""),
            meta_description=body.get("meta_description", ""),
            sections=body.get("sections", []) or [],
            hero_image=body.get("hero_image", ""),
            seo=_extract_seo(body),
            bullets=body.get("bullets", []) or [],
        )
        return Response(html, mimetype="text/html")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _extract_seo(body: dict) -> dict:
    """Haal alle SEO-veld waardes uit de form body."""
    return {k: body.get(k) for k in [
        "seo_title","seo_keyword","seo_canonical","seo_index","seo_follow","seo_noarchive",
        "seo_og_title","seo_og_description","seo_twitter_card","seo_jsonld","seo_hreflang"
    ] if body.get(k) is not None}


@app.route("/api/admin/dienst-template/create", methods=["POST"])
def api_dienst_template_create():
    """Maak een nieuwe dienst-pagina aan op basis van het dunpleisterwerk-design.

    Body: {
      slug: "betoncire",          # → /diensten/betoncire/
      dienst_name: "Betoncire",
      meta_description: "...",
      hero_image: "/wp-content/uploads/.../foo.webp" (optioneel),
      sections: [{h2, body}, ... max 8]
    }
    Returns: {slug, url, redirect}
    """
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    slug_in = (body.get("slug") or "").strip().strip("/")
    if not slug_in:
        return jsonify({"error": "slug verplicht"}), 400
    if slug_in.startswith("diensten/"):
        slug_in = slug_in[len("diensten/"):]
    slug = _safe_slug(slug_in)
    full_slug = f"diensten/{slug}"
    dienst_name = (body.get("dienst_name") or slug.replace("-", " ").title()).strip()
    meta_desc = (body.get("meta_description") or "").strip()
    sections = body.get("sections") or []
    hero_image = body.get("hero_image", "")
    if not sections or not isinstance(sections, list):
        return jsonify({"error": "sections verplicht (min 1)"}), 400

    seo_data = _extract_seo(body)
    try:
        html = _render_dienst_html(
            slug=slug,
            dienst_name=dienst_name,
            meta_description=meta_desc,
            sections=sections,
            hero_image=hero_image,
            seo=seo_data,
            bullets=body.get("bullets", []) or [],
        )
    except Exception as e:
        return jsonify({"error": "render failed", "details": str(e)}), 500

    # Opslaan: HTML in KV onder 'dienst-html:<slug>', + page-record voor admin index
    kv_set(f"dienst-html:{slug}", html)
    page = _default_page(full_slug, dienst_name, template="dienst-1to1")
    page["status"] = "published"
    page["meta"]["description"] = meta_desc
    page["meta"]["canonical"] = seo_data.get("seo_canonical") or f"https://wandmeesters.nl/diensten/{slug}/"
    page["meta"]["og_title"] = seo_data.get("seo_og_title") or f"{dienst_name} - Wandmeesters"
    page["meta"]["og_description"] = seo_data.get("seo_og_description") or meta_desc
    page["meta"]["og_image"] = hero_image
    if seo_data.get("seo_jsonld"):
        try: page["meta"]["schema_jsonld"] = json.loads(seo_data["seo_jsonld"])
        except Exception: pass
    # Bewaar de slots zodat we kunnen re-renderen bij latere edits
    page["dienst_slots"] = {
        "dienst_name": dienst_name,
        "meta_description": meta_desc,
        "hero_image": hero_image,
        "sections": sections,
        "seo": seo_data,
    }
    page["rendered_html_kb"] = round(len(html) / 1024, 1)
    _save_page(page)
    audit_log("dienst.create", full_slug, f"Dienst-pagina '{dienst_name}' aangemaakt")

    return jsonify({
        "slug": full_slug,
        "url": f"/diensten/{slug}/",
        "redirect_admin": f"/admin/#page-editor/{full_slug}",
        "html_kb": round(len(html) / 1024, 1),
    }), 201


@app.route("/api/admin/dienst-template/ai-fill", methods=["POST"])
def api_dienst_template_ai_fill():
    """Gebruik Claude om dienst-naam + korte prompt om te zetten in 8 H2+body secties.
    Vult de form-velden zodat Wim alleen nog hoeft te reviewen.
    """
    a = _auth_or_401()
    if a: return a
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY ontbreekt"}), 503
    body = request.get_json(silent=True) or {}
    dienst_name = (body.get("dienst_name") or "").strip()
    prompt = (body.get("prompt") or "").strip()
    if not dienst_name and not prompt:
        return jsonify({"error": "dienst_name of prompt verplicht"}), 400

    defaults = _load_dienst_template_defaults()
    reference_sections = defaults.get("sections", [])

    # Bereken doel-woordlengte per sectie op basis van referentie
    target_lengths = []
    for s in reference_sections[:8]:
        wc = len((s.get('body') or '').split())
        target_lengths.append(max(40, wc))  # minimum 40 woorden
    targets_str = ", ".join(f"sectie {i+1}: ~{w} woorden" for i, w in enumerate(target_lengths))
    available_pages = _ai_context_pages(25)
    available_media = _ai_context_media(20)

    system = (
        "Je schrijft SEO-content voor Wandmeesters (Nederlands stucadoorsbedrijf). "
        "Tone: vakkundig, no-nonsense, 'u'-vorm. "
        "Returneer STRIKT geldige JSON in deze vorm: "
        "{\"dienst_name\":\"...\",\"slug\":\"<dienst-naam>\",\"meta_description\":\"max 160 chars\","
        "\"hero_image\":\"/wp-content/uploads/...\","
        "\"sections\":[{\"h2\":\"...\",\"body\":\"paragraaf 1 met [markdown links](/diensten/x/) waar relevant\\n\\nparagraaf 2 (optioneel)\","
        "\"image_url\":\"/wp-content/...\"}, ... EXACT 8 items]}. "
        "Geen markdown code-fences. Geen uitleg. Alleen het JSON object. "
        "SLUG: lowercase, alleen letters/cijfers/streepjes, gebruik dienst-naam zonder spaties. "
        "HERO_IMAGE: kies de meest pakkende foto uit media-lijst, of laat leeg. "
        "INTERNE LINKS: scan tijdens schrijven actief op zinsdelen die naar bestaande pagina's verwijzen "
        "(zoals 'stucwerk', 'latex spuiten', 'houtschilderwerk') — wikkel die in [tekst](/url/) markdown. "
        "Max 2 links per sectie, alleen uit de meegegeven pagina-lijst. "
        "IMAGE_URL: kies een afbeelding uit de meegegeven media-lijst als exact passend, anders leeg laten."
    )
    user_msg = (
        f"Dienst: {dienst_name or '(uit prompt)'}\n"
        f"Prompt/context: {prompt or '(geen)'}\n\n"
        f"Schrijf 8 secties voor de dienst-pagina, in dezelfde stijl als deze referentie (vervang inhoud, behoud opbouw en lengte):\n"
        f"{json.dumps(reference_sections, ensure_ascii=False)}\n\n"
        "Houd dezelfde woordaantallen aan als de referentie:\n"
        f"{targets_str}\n\n"
        f"BESCHIKBARE PAGINA'S voor interne links (gebruik in body waar relevant):\n"
        f"{json.dumps(available_pages, ensure_ascii=False)[:1800]}\n\n"
        f"BESCHIKBARE MEDIA voor image_url:\n"
        f"{json.dumps(available_media, ensure_ascii=False)[:1500]}\n\n"
        "Sectie 1 = hero (H2 = dienst-naam + USP). Sectie 2 = subtitel/vraag aan klant. "
        "Sectie 3 = 'Wat is X en hoe werkt het?'. Sectie 4 = 'Strak en modern afgewerkt' (of vergelijkbaar). "
        "Sectie 5 = 'Voordelen van X'. Sectie 6 = 'X voor nieuwbouw/renovatie/etc'. "
        "Sectie 7 = 'Vakwerk dat blijft staan'. Sectie 8 = 'Uw specialist in X'. "
        "BELANGRIJK: noem in elke sectie waar het natuurlijk past gerelateerde diensten (stucwerk, dunpleister, latex etc.) "
        "en wikkel die woorden in markdown links naar hun bestaande dienst-pagina's. "
        "Schrijf INHOUDELIJK rijk, geen vulwoorden."
    )
    result = _anthropic_call(
        messages=[{"role": "user", "content": user_msg}],
        system=system,
        max_tokens=4000,
        model=ANTHROPIC_MODEL_FAST,
    )
    if "error" in result:
        return jsonify({"error": "AI-call mislukt", "details": result}), 502
    try:
        raw = result["content"][0]["text"]
    except Exception:
        return jsonify({"error": "Geen AI-antwoord"}), 502
    raw = re.sub(r"^```(?:json)?\s*\n", "", raw.strip())
    raw = re.sub(r"\n```\s*$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return jsonify({"error": "Ongeldige JSON van AI", "raw": raw[:400]}), 502
    return jsonify(data)


@app.route("/diensten/<path:slug>/", methods=["GET"])
@app.route("/diensten/<path:slug>", methods=["GET"])
def serve_dynamic_dienst(slug):
    """Catch-all voor /diensten/<slug>/ EN /diensten/<parent>/<sub>/: serveert dynamische
    dienst-pagina uit KV. Static files matchen eerst in Vercel routing.
    """
    # Strip trailing slash if any
    safe = _safe_slug(slug.rstrip("/"))
    html = kv_get(f"dienst-html:{safe}")
    if not html:
        return Response("Niet gevonden", status=404, mimetype="text/plain")
    return Response(html, mimetype="text/html")


@app.route("/api/templates/<name>/bulk-apply", methods=["POST"])
def api_template_bulk_apply(name):
    a = _auth_or_401()
    if a: return a
    t = kv_get(f"template:{name}")
    if not t:
        return jsonify({"error": "Niet gevonden"}), 404
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Geen CSV"}), 400
    created = []
    failed = []
    try:
        text = f.read().decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for i, row in enumerate(reader):
            try:
                slug = _safe_slug(row.get("slug") or _substitute(t.get("slug_pattern", "{slug}"), row))
                if not slug or _get_page(slug):
                    failed.append({"row": i, "error": f"slug ongeldig of bestaat al: {slug}"}); continue
                title = row.get("title") or row.get("stad") or row.get("dienst") or slug
                page = _default_page(slug, title, template=name)
                page["content_blocks"] = _substitute_template(t.get("content_blocks") or [], row)
                page["meta"].update(_substitute_template_meta(t.get("default_meta") or {}, row))
                _save_page(page)
                update_seo_score(page)
                created.append(slug)
            except Exception as e:
                failed.append({"row": i, "error": str(e)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    audit_log("template.bulk_apply", name, f"Created {len(created)}")
    return jsonify({"created": created, "failed": failed})


# ---------- menus ----------
@app.route("/api/menus", methods=["GET"])
def api_menus_list():
    a = _auth_or_401()
    if a: return a
    names = kv_get("menus:index", ["main", "footer"]) or ["main", "footer"]
    menus = []
    for n in names:
        m = kv_get(f"menu:{n}") or {"name": n, "items": []}
        menus.append(m)
    return jsonify({"menus": menus})


@app.route("/api/menus/<name>", methods=["PUT"])
def api_menu_update(name):
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    items = body.get("items") or []
    menu = {"name": name, "items": items, "updated_at": _now_iso()}
    kv_set(f"menu:{name}", menu)
    idx = kv_get("menus:index", ["main", "footer"]) or []
    if name not in idx:
        idx.append(name); kv_set("menus:index", idx)
    audit_log("menu.update", name, "Menu bijgewerkt")
    return jsonify({"name": name, "updated_at": menu["updated_at"]})


# ---------- sitemap ----------
@app.route("/api/sitemap/regenerate", methods=["POST"])
def api_sitemap_regenerate():
    a = _auth_or_401()
    if a: return a
    pages = [p for p in _pages_index() if p.get("status") == "published"]
    base = request.host_url.rstrip("/")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in pages:
        lines.append("<url>")
        lines.append(f"<loc>{base}/{p['slug']}/</loc>")
        if p.get("updated_at"):
            lines.append(f"<lastmod>{p['updated_at']}</lastmod>")
        lines.append("</url>")
    lines.append("</urlset>")
    xml = "\n".join(lines)
    ok, url = blob_put("sitemap.xml", xml.encode("utf-8"), "application/xml")
    meta = {
        "last_generated": _now_iso(),
        "last_pinged": (kv_get("sitemap:meta", {}) or {}).get("last_pinged", {"google": None, "bing": None}),
        "urls_count": len(pages),
        "blob_url": url if ok else "",
    }
    kv_set("sitemap:meta", meta)
    audit_log("sitemap.regenerate", "*", f"{len(pages)} urls")
    return jsonify({"urls_count": len(pages), "blob_url": meta["blob_url"], "generated_at": meta["last_generated"]})


@app.route("/api/sitemap/ping", methods=["POST"])
def api_sitemap_ping():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    targets = body.get("targets") or ["google", "bing"]
    base = request.host_url.rstrip("/")
    sitemap_url = f"{base}/sitemap.xml"
    out = {}
    for t in targets:
        if t == "google":
            ping_url = f"https://www.google.com/ping?sitemap={urllib.parse.quote(sitemap_url)}"
        else:
            ping_url = f"https://www.bing.com/ping?sitemap={urllib.parse.quote(sitemap_url)}"
        try:
            with urllib.request.urlopen(ping_url, timeout=5) as r:
                out[t] = {"ok": True, "status": r.status}
        except Exception as e:
            out[t] = {"ok": False, "status": str(e)}
    meta = kv_get("sitemap:meta", {}) or {}
    pinged = meta.get("last_pinged", {}) or {}
    for t in targets:
        if out.get(t, {}).get("ok"):
            pinged[t] = _now_iso()
    meta["last_pinged"] = pinged
    kv_set("sitemap:meta", meta)
    return jsonify(out)


# ---------- redirects ----------
def _redirects_index() -> list:
    return kv_get("redirects:index", []) or []


def _create_redirect(from_path: str, to_path: str, code: int = 301) -> str:
    rid = uuid.uuid4().hex[:10]
    item = {
        "id": rid, "from_path": from_path, "to_path": to_path,
        "code": code, "created_at": _now_iso(), "hit_count": 0,
    }
    kv_set(f"redirect:{rid}", item)
    idx = _redirects_index()
    idx.append({k: item[k] for k in ("id", "from_path", "to_path", "code", "hit_count")})
    kv_set("redirects:index", idx)
    return rid


@app.route("/api/redirects", methods=["GET"])
def api_redirects_list():
    a = _auth_or_401()
    if a: return a
    return jsonify({"items": _redirects_index()})


@app.route("/api/redirects", methods=["POST"])
def api_redirects_create():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    f_, t_ = body.get("from_path"), body.get("to_path")
    if not f_ or not t_:
        return jsonify({"error": "from_path & to_path verplicht"}), 400
    rid = _create_redirect(f_, t_, int(body.get("code", 301)))
    audit_log("redirect.create", rid, f"{f_} -> {t_}")
    return jsonify(kv_get(f"redirect:{rid}")), 201


@app.route("/api/redirects/<rid>", methods=["DELETE"])
def api_redirects_delete(rid):
    a = _auth_or_401()
    if a: return a
    kv_delete(f"redirect:{rid}")
    idx = [r for r in _redirects_index() if r.get("id") != rid]
    kv_set("redirects:index", idx)
    audit_log("redirect.delete", rid, "verwijderd")
    return jsonify({"deleted": True})


# ---------- robots.txt ----------
@app.route("/api/robots-txt", methods=["GET"])
def api_robots_txt_get():
    a = _auth_or_401()
    if a: return a
    rt = kv_get("robots_txt") or {"content": "User-agent: *\nAllow: /\n", "updated_at": None}
    return jsonify(rt)


@app.route("/api/robots-txt", methods=["PUT"])
def api_robots_txt_put():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    content = body.get("content", "")
    rt = {"content": content, "updated_at": _now_iso(), "updated_by": session.get("user", "admin")}
    kv_set("robots_txt", rt)
    ok, url = blob_put("robots.txt", content.encode("utf-8"), "text/plain")
    audit_log("robots_txt.update", "*", "updated")
    return jsonify({"updated_at": rt["updated_at"], "blob_url": url if ok else ""})


# ---------- SEO overview ----------
@app.route("/api/seo/overview", methods=["GET"])
def api_seo_overview():
    a = _auth_or_401()
    if a: return a
    missing_only = request.args.get("missing_only") == "1"
    scores = kv_get("seo_scores", {}) or {}
    out = []
    for it in _pages_index():
        slug = it["slug"]
        page = _get_page(slug) or {}
        sc = scores.get(slug) or compute_seo_score(page)
        if missing_only and sc["score"] >= 90:
            continue
        out.append({
            "slug": slug, "title": page.get("title") or it.get("title"),
            "meta": page.get("meta", {}),
            "score": sc.get("score", 0), "issues": sc.get("issues", []),
        })
    return jsonify({"items": out})


@app.route("/api/seo/meta/<path:slug>", methods=["PATCH"])
def api_seo_meta(slug):
    a = _auth_or_401()
    if a: return a
    slug = _safe_slug(slug)
    page = _get_page(slug)
    if not page:
        return jsonify({"error": "Niet gevonden"}), 404
    body = request.get_json(silent=True) or {}
    page.setdefault("meta", {}).update({k: v for k, v in body.items() if v is not None})
    _save_page(page)
    update_seo_score(page)
    audit_log("seo.meta", slug, "meta updated")
    return jsonify({"slug": slug, "meta": page["meta"]})


@app.route("/api/seo/bulk", methods=["POST"])
def api_seo_bulk():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    slugs = body.get("slugs") or []
    upd = body.get("meta_updates") or {}
    updated = 0
    failed = []
    for s in slugs:
        page = _get_page(_safe_slug(s))
        if not page:
            failed.append({"slug": s, "error": "not found"}); continue
        try:
            page.setdefault("meta", {}).update(upd)
            _save_page(page)
            update_seo_score(page)
            updated += 1
        except Exception as e:
            failed.append({"slug": s, "error": str(e)})
    audit_log("seo.bulk", "*", f"{updated} pages updated")
    return jsonify({"updated": updated, "failed": failed})


# ---------- broken links audit ----------
@app.route("/api/links/audit", methods=["POST"])
def api_links_audit():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    scope = body.get("scope") or "all"
    pages_to_scan = _pages_index() if scope == "all" else [{"slug": s} for s in scope]
    results = []
    for it in pages_to_scan:
        slug = it["slug"]
        page = _get_page(slug)
        if not page: continue
        for b in page.get("content_blocks", []) or []:
            props = b.get("props", {}) or {}
            href = props.get("href") or props.get("src")
            if not href or not isinstance(href, str): continue
            typ = "internal" if href.startswith("/") else "external"
            status = None
            if typ == "internal":
                target = _safe_slug(href)
                status = 200 if _get_page(target) else 404
            else:
                try:
                    req = urllib.request.Request(href, method="HEAD")
                    with urllib.request.urlopen(req, timeout=4) as r:
                        status = r.status
                except Exception:
                    status = 0
            if status and status >= 400:
                results.append({"page_slug": slug, "link": href, "status_code": status, "type": typ})
    out = {"ran_at": _now_iso(), "results": results}
    kv_set("broken_links:last", out)
    return jsonify(out)


# ---------- AI page chat ----------
def _anthropic_call(messages: list, system: str = "", max_tokens: int = 2048, model: str = None) -> dict:
    if not ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY missing"}
    body = {
        "model": model or ANTHROPIC_MODEL_DEFAULT,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "details": e.read().decode("utf-8", errors="replace")}
    except Exception as e:
        return {"error": str(e)}


@app.route("/api/page-chat", methods=["POST"])
def api_page_chat():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    slug = _safe_slug(body.get("slug", ""))
    msg = (body.get("message") or "").strip()
    current_blocks = body.get("current_blocks") or []
    history = body.get("chat_history") or []
    if not msg:
        return jsonify({"error": "message verplicht"}), 400
    system = (
        "Je bent een AI page editor voor Wandmeesters (stukadoorsbedrijf, nl). "
        "Je krijgt de huidige blokken (JSON) van een pagina en een instructie van de gebruiker. "
        "Geef ALTIJD geldige JSON terug met EXACT deze velden: "
        '{"response": "...", "proposed_changes": [ {"block_index": int, "action": "add|edit|delete|move", "new_value": {...block...}, "new_index": int|null, "rationale": "..."} ] }. '
        "Block-types die geldig zijn: " + ", ".join(b["type"] for b in BLOCK_LIBRARY) + ". "
        "Hou je strikt aan deze types. Voor 'edit' is block_index verplicht. Voor 'add' mag block_index -1 zijn voor 'aan het einde'."
    )
    user_msg = (
        f"Pagina slug: {slug}\n"
        f"Huidige blokken (JSON):\n```json\n{json.dumps(current_blocks, ensure_ascii=False)}\n```\n"
        f"Instructie: {msg}"
    )
    messages = []
    for h in history[-10:]:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": user_msg})
    resp = _anthropic_call(messages, system=system, max_tokens=3072)
    if resp.get("error"):
        return jsonify({"response": f"AI fout: {resp.get('error')}", "proposed_changes": []}), 200
    # Extract assistant text
    text = ""
    for c in (resp.get("content") or []):
        if c.get("type") == "text":
            text += c.get("text", "")
    parsed: dict = {}
    # Try to find JSON in text
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try: parsed = json.loads(m.group(0))
        except Exception: parsed = {}
    response_text = parsed.get("response") or text
    proposed = parsed.get("proposed_changes") or []
    # Validate / clamp
    valid_types = {b["type"] for b in BLOCK_LIBRARY}
    clean = []
    for p in proposed:
        if not isinstance(p, dict): continue
        action = p.get("action")
        if action not in ("add", "edit", "delete", "move"): continue
        nv = p.get("new_value") or {}
        if action in ("add", "edit"):
            if nv.get("type") not in valid_types: continue
        clean.append(p)
    # Persist chat history
    chat = kv_get(f"ai:chat:{slug}", []) or []
    chat.append({"role": "user", "content": msg, "ts": _now_iso(), "proposed_changes": None})
    chat.append({"role": "assistant", "content": response_text, "ts": _now_iso(), "proposed_changes": clean})
    chat = chat[-50:]
    kv_set(f"ai:chat:{slug}", chat)
    return jsonify({"response": response_text, "proposed_changes": clean})


@app.route("/api/page-chat/apply", methods=["POST"])
def api_page_chat_apply():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    slug = _safe_slug(body.get("slug", ""))
    accepted_indexes = body.get("accepted_change_ids") or []
    chat = kv_get(f"ai:chat:{slug}", []) or []
    last_proposals = []
    for entry in reversed(chat):
        if entry.get("role") == "assistant" and entry.get("proposed_changes"):
            last_proposals = entry["proposed_changes"]
            break
    if not last_proposals:
        return jsonify({"error": "Geen voorstellen gevonden"}), 400
    page = _get_page(slug)
    if not page:
        return jsonify({"error": "Pagina niet gevonden"}), 404
    blocks = list(page.get("content_blocks") or [])
    # Apply in deterministic order: deletes high-to-low, then moves, then edits, then adds
    accepted = [last_proposals[i] for i in accepted_indexes if 0 <= i < len(last_proposals)]
    deletes = sorted([c for c in accepted if c["action"] == "delete"], key=lambda c: -int(c.get("block_index", 0)))
    edits = [c for c in accepted if c["action"] == "edit"]
    moves = [c for c in accepted if c["action"] == "move"]
    adds = [c for c in accepted if c["action"] == "add"]
    for c in deletes:
        i = int(c.get("block_index", -1))
        if 0 <= i < len(blocks): blocks.pop(i)
    for c in edits:
        i = int(c.get("block_index", -1))
        if 0 <= i < len(blocks) and c.get("new_value"):
            blocks[i] = c["new_value"]
    for c in moves:
        i = int(c.get("block_index", -1))
        ni = int(c.get("new_index", i))
        if 0 <= i < len(blocks) and 0 <= ni < len(blocks):
            blk = blocks.pop(i); blocks.insert(ni, blk)
    for c in adds:
        nv = c.get("new_value")
        if not nv: continue
        ni = c.get("new_index")
        if ni is None or ni < 0 or ni > len(blocks):
            blocks.append(nv)
        else:
            blocks.insert(int(ni), nv)
    page["content_blocks"] = blocks
    _push_revision(slug, page, summary="ai-apply")
    _save_page(page)
    update_seo_score(page)
    audit_log("page.ai_apply", slug, f"Applied {len(accepted)} AI changes")
    return jsonify({"slug": slug, "new_blocks": blocks, "updated_at": page["updated_at"]})


# ---------- traffic tracking ----------
TRACKING_PATHS_CAP = 200  # max unieke paden per dag
TRACKING_RETENTION_DAYS = 90


def _today_bucket() -> str:
    return datetime.now().strftime("%Y%m%d")


def _bump_counter(key: str, by: int = 1) -> int:
    val = (kv_get(key) or 0)
    if not isinstance(val, int):
        try: val = int(val)
        except: val = 0
    val += by
    kv_set(key, val)
    return val


@app.route("/api/track", methods=["POST", "OPTIONS"])
def api_track():
    """Cookie-loze first-party traffic tracker. Geen PII opgeslagen, alleen counters.
    Body: {type: 'pageview'|'click', path?, kind?, target?}
    """
    if request.method == "OPTIONS":
        return ("", 204, {"Access-Control-Allow-Origin": "*",
                           "Access-Control-Allow-Methods": "POST,OPTIONS",
                           "Access-Control-Allow-Headers": "Content-Type"})
    data = request.get_json(silent=True) or {}
    typ = (data.get("type") or "").lower().strip()
    if typ not in ("pageview", "click"):
        return jsonify({"ok": False, "error": "Onbekend type"}), 400
    today = _today_bucket()
    if typ == "pageview":
        path = (data.get("path") or "/").strip()
        # Normaliseer: max 200 chars, geen query/fragment
        path = path.split("?")[0].split("#")[0][:200]
        # Skip admin/api paths
        if path.startswith(("/admin", "/api", "/inloggen", "/uitloggen", "/wp-")):
            return ("", 204)
        # Per-pagina totaal + per dag
        _bump_counter(f"stat:pv:total:{path}")
        _bump_counter(f"stat:pv:day:{today}:{path}")
        _bump_counter(f"stat:pv:total")
        _bump_counter(f"stat:pv:day:{today}")
    else:  # click
        kind = (data.get("kind") or "").strip().lower()
        target = (data.get("target") or "").strip()[:200]
        if kind not in ("email", "phone", "route", "external", "form_open"):
            return jsonify({"ok": False, "error": "Onbekend kind"}), 400
        _bump_counter(f"stat:click:total:{kind}")
        _bump_counter(f"stat:click:day:{today}:{kind}")
        if target:
            _bump_counter(f"stat:click:target:{kind}:{target}")
    return ("", 204)


def _list_pageview_paths() -> list:
    """Return geaggregeerde top-pagina lijst uit KV."""
    keys = kv_list("stat:pv:total:")
    paths = []
    for k in keys:
        # k zou kunnen zijn 'stat:pv:total:/diensten/stucwerk/' OF safe-encoded
        raw = k
        # Strip prefix
        if raw.startswith("stat:pv:total:"):
            path = raw[len("stat:pv:total:"):]
        else:
            # safe-encoded variant: replaceback
            safe_prefix = _safe_kv_filename("stat:pv:total:")
            if raw.startswith(safe_prefix):
                path = raw[len(safe_prefix):].replace("_", "/")  # rough
            else:
                continue
        count = kv_get(f"stat:pv:total:{path}", 0) or 0
        if isinstance(count, int) and count > 0:
            paths.append({"path": path, "views": count})
    paths.sort(key=lambda x: x["views"], reverse=True)
    return paths


def _daily_views_chart(days: int = 14) -> list:
    """Per-dag totale pageviews + leads-count voor laatste N dagen.
    Returns: [{date, views, leads}, ...] (Kittenvoegen-extension)."""
    # Count leads per ISO-date (lead.created[:10])
    leads_per_day = {}
    try:
        for lead in get_leads():
            created = (lead.get("created") or "")[:10]   # YYYY-MM-DD
            if created:
                leads_per_day[created] = leads_per_day.get(created, 0) + 1
    except Exception:
        leads_per_day = {}
    out = []
    for i in range(days - 1, -1, -1):
        d = datetime.now() - timedelta(days=i)
        bucket = d.strftime("%Y%m%d")
        iso_date = d.strftime("%Y-%m-%d")
        views = kv_get(f"stat:pv:day:{bucket}", 0) or 0
        out.append({
            "date": d.strftime("%d-%m"),
            "views": int(views) if isinstance(views, int) else 0,
            "leads": int(leads_per_day.get(iso_date, 0)),
        })
    return out


def _click_breakdown() -> dict:
    """Return per-kind klik-totalen + top-targets per kind."""
    kinds = ["email", "phone", "route", "external", "form_open"]
    out = {}
    for kind in kinds:
        total = kv_get(f"stat:click:total:{kind}", 0) or 0
        # Top targets
        target_keys = kv_list(f"stat:click:target:{kind}:")
        targets = []
        for k in target_keys:
            if k.startswith(f"stat:click:target:{kind}:"):
                t = k[len(f"stat:click:target:{kind}:"):]
            else:
                safe_p = _safe_kv_filename(f"stat:click:target:{kind}:")
                if k.startswith(safe_p):
                    t = k[len(safe_p):]
                else:
                    continue
            c = kv_get(f"stat:click:target:{kind}:{t}", 0) or 0
            if isinstance(c, int) and c > 0:
                targets.append({"target": t, "count": c})
        targets.sort(key=lambda x: x["count"], reverse=True)
        out[kind] = {"total": int(total) if isinstance(total, int) else 0, "top": targets[:5]}
    return out


# ---------- dashboard ----------
@app.route("/api/dashboard/stats", methods=["GET"])
def api_dashboard_stats():
    a = _auth_or_401()
    if a: return a
    items = _pages_index()
    by_status = {"published": 0, "draft": 0, "trashed": 0, "scheduled": 0}
    for it in items:
        by_status[it.get("status", "draft")] = by_status.get(it.get("status", "draft"), 0) + 1
    leads = get_leads()
    open_leads = [l for l in leads if l.get("stage") not in ("closed", "lost")]
    closed_leads = [l for l in leads if l.get("stage") == "closed"]
    lost_leads = [l for l in leads if l.get("stage") == "lost"]
    media = _media_index()
    media_bytes = sum(m.get("bytes", 0) for m in media)
    scores = kv_get("seo_scores", {}) or {}
    avg_score = int(sum(s.get("score", 0) for s in scores.values()) / max(1, len(scores))) if scores else 0
    broken = (kv_get("broken_links:last") or {}).get("results", [])
    sitemap_meta = kv_get("sitemap:meta", {}) or {}
    settings = get_settings()
    try: avg_value = int(settings.get("avg_quote_value") or 0)
    except: avg_value = 0
    # Per-stage breakdown met value
    stage_breakdown = {}
    for l in leads:
        st = l.get("stage", "ontvangen")
        if st not in stage_breakdown: stage_breakdown[st] = {"count": 0, "value": 0}
        stage_breakdown[st]["count"] += 1
        stage_breakdown[st]["value"] += avg_value
    # Paid value: BETAALDE facturen (Kittenvoegen-extension) — niet speculatief
    invoices = get_invoices_index()
    paid_total = sum(int(i.get("total", 0) or 0) for i in invoices if i.get("status") == "betaald")
    invoiced_open = sum(int(i.get("total", 0) or 0) for i in invoices if i.get("status") in ("open", "verzonden"))
    invoiced_overdue = sum(int(i.get("total", 0) or 0) for i in invoices if i.get("status") == "vervallen")
    # Traffic stats
    total_pv = kv_get("stat:pv:total", 0) or 0
    today_pv = kv_get(f"stat:pv:day:{_today_bucket()}", 0) or 0
    top_pages = _list_pageview_paths()[:10]
    daily_chart = _daily_views_chart(14)
    clicks = _click_breakdown()
    # Aanvragen-overzicht met datums + dagen in pipeline
    requests_overview = []
    now = datetime.now()
    for l in leads:
        created_str = l.get("created", "")
        history = l.get("history", []) or []
        # Tijd in current stage = sinds laatste history entry
        try:
            current_stage_since = datetime.fromisoformat(history[-1]["ts"]) if history else datetime.fromisoformat(created_str)
        except Exception:
            current_stage_since = now
        try:
            created_dt = datetime.fromisoformat(created_str)
        except Exception:
            created_dt = now
        days_in_stage = max(0, (now - current_stage_since).days)
        days_total = max(0, (now - created_dt).days)
        requests_overview.append({
            "id": l.get("id"),
            "name": l.get("name") or "(geen naam)",
            "email": l.get("email") or "",
            "telefoon": l.get("telefoon") or "",
            "pakket": l.get("pakket") or "",
            "stage": l.get("stage") or "ontvangen",
            "created": created_str,
            "days_total": days_total,
            "days_in_stage": days_in_stage,
            "stuck": days_in_stage >= 7 and l.get("stage") not in ("closed", "lost"),
            "value": avg_value if l.get("stage") not in ("lost",) else 0,
        })
    requests_overview.sort(key=lambda x: x["created"], reverse=True)
    return jsonify({
        "pages": by_status,
        "leads": {"open": len(open_leads), "total": len(leads), "closed": len(closed_leads), "lost": len(lost_leads)},
        "media": {"count": len(media), "bytes": media_bytes},
        "avg_seo_score": avg_score,
        "broken_links_count": len(broken),
        "sitemap": {
            "last_generated": sitemap_meta.get("last_generated"),
            "urls_count": sitemap_meta.get("urls_count", 0),
        },
        "revenue": {
            "avg_value": avg_value,
            "closed_total": avg_value * len(closed_leads),
            "open_pipeline": avg_value * len(open_leads),
            "lost_total": avg_value * len(lost_leads),
            "stage_breakdown": stage_breakdown,
            # Kittenvoegen-extension: alleen echt BETAALDE bedragen uit facturen
            "paid_total": paid_total,
            "invoiced_open": invoiced_open,
            "invoiced_overdue": invoiced_overdue,
            "invoices_count": len(invoices),
        },
        "requests": requests_overview,
        "traffic": {
            "total_pageviews": int(total_pv) if isinstance(total_pv, int) else 0,
            "today_pageviews": int(today_pv) if isinstance(today_pv, int) else 0,
            "top_pages": top_pages,
            "daily_chart": daily_chart,
            "clicks": clicks,
        },
    })


@app.route("/api/audit-log", methods=["GET"])
def api_audit_log():
    a = _auth_or_401()
    if a: return a
    log = kv_get("audit:log", []) or []
    user = request.args.get("user")
    action = request.args.get("action")
    fr = request.args.get("from")
    to = request.args.get("to")
    limit = int(request.args.get("limit", 50))
    items = log
    if user: items = [x for x in items if x.get("user") == user]
    if action: items = [x for x in items if action in (x.get("action") or "")]
    if fr: items = [x for x in items if x.get("ts", "") >= fr]
    if to: items = [x for x in items if x.get("ts", "") <= to]
    return jsonify({"items": items[:limit], "total": len(items)})


# ---------- integrations health ----------
@app.route("/api/integrations/health", methods=["GET"])
def api_integrations_health():
    a = _auth_or_401()
    if a: return a
    # KV check
    kv_ok = False
    try:
        kv_ok = kv_set("__health__", _now_iso()) and (kv_get("__health__") is not None)
    except Exception: kv_ok = False
    # Blob check
    blob_ok = bool(BLOB_TOKEN)
    blob_latency = None
    if blob_ok:
        t = time.time()
        ok, _ = blob_put("health-check.txt", b"ok", "text/plain")
        blob_ok = ok
        blob_latency = int((time.time() - t) * 1000)
    # SMTP minimal config check
    s = get_settings().get("smtp", {})
    smtp_ok = bool(s.get("host") and s.get("from_email"))
    return jsonify({
        "blob": {"ok": blob_ok, "latency_ms": blob_latency},
        "kv": {"ok": kv_ok},
        "ai": {"ok": bool(ANTHROPIC_API_KEY), "model": ANTHROPIC_MODEL_DEFAULT},
        "smtp": {"ok": smtp_ok},
    })


@app.route("/api/ai-test", methods=["POST"])
def api_ai_test():
    a = _auth_or_401()
    if a: return a
    prompt = (request.get_json(silent=True) or {}).get("prompt") or "Zeg in 1 zin hallo."
    resp = _anthropic_call(
        [{"role": "user", "content": prompt}],
        system="Antwoord kort en in het Nederlands.",
        max_tokens=200,
    )
    if resp.get("error"):
        return jsonify({"ok": False, "response": resp.get("error"), "model": ANTHROPIC_MODEL_DEFAULT, "tokens": 0}), 200
    text = "".join(c.get("text", "") for c in (resp.get("content") or []) if c.get("type") == "text")
    usage = resp.get("usage") or {}
    return jsonify({
        "ok": True, "response": text, "model": resp.get("model", ANTHROPIC_MODEL_DEFAULT),
        "tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
    })


# ---------- users ----------
def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


@app.route("/api/users", methods=["GET"])
def api_users_list():
    a = _auth_or_401()
    if a: return a
    users = kv_get("users", []) or []
    return jsonify({"items": [{"username": u.get("username"), "role": u.get("role", "editor"),
                               "created_at": u.get("created_at")} for u in users]})


@app.route("/api/users", methods=["POST"])
def api_users_create():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    role = body.get("role", "editor")
    if not username or not password:
        return jsonify({"error": "username & password verplicht"}), 400
    users = kv_get("users", []) or []
    if any(u.get("username") == username for u in users):
        return jsonify({"error": "Bestaat al"}), 409
    users.append({"username": username, "password_hash": _hash_pw(password),
                  "role": role, "created_at": _now_iso()})
    kv_set("users", users)
    audit_log("user.create", username, f"Aangemaakt rol={role}")
    return jsonify({"username": username, "role": role}), 201


@app.route("/api/users/<username>", methods=["DELETE"])
def api_users_delete(username):
    a = _auth_or_401()
    if a: return a
    users = kv_get("users", []) or []
    new_users = [u for u in users if u.get("username") != username]
    if len(new_users) == len(users):
        return jsonify({"error": "Niet gevonden"}), 404
    kv_set("users", new_users)
    audit_log("user.delete", username, "verwijderd")
    return jsonify({"deleted": True})


# ---------- public render proxy ----------
@app.route("/api/render/<path:slug>", methods=["GET"])
def api_render_page(slug):
    slug = _safe_slug(slug)
    # Check redirects first
    target_path = f"/{slug}/"
    for r in _redirects_index():
        if r.get("from_path") == target_path:
            return redirect(r.get("to_path"), code=int(r.get("code", 301)))
    # Serve generated HTML if any
    html = kv_get(f"page:{slug}:html")
    if not html:
        page = _get_page(slug)
        if not page or page.get("status") not in ("published",):
            return Response("Niet gevonden", status=404)
        html = render_page_html(page)
    return Response(html, mimetype="text/html")


# ============================================================
# REVIEW-FUNNEL (sterren-gate) — Kittenvoegen-extension
# ============================================================
REVIEW_HTML = """<!DOCTYPE html><html lang="nl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Geef een review — {{company}}</title>
<link rel="icon" type="image/webp" href="/favicon.webp">
<meta name="robots" content="noindex, nofollow">
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
body{font-family:'Poppins',-apple-system,BlinkMacSystemFont,sans-serif;background:#f8fafc;background-image:radial-gradient(circle at 80% 20%,rgba(52,118,119,.07),transparent 55%),radial-gradient(circle at 20% 80%,rgba(52,118,119,.05),transparent 55%)}
.ms-card{box-shadow:0 4px 14px rgba(15,23,42,.04),0 24px 48px rgba(15,23,42,.08);border:1px solid rgba(255,255,255,.6)}
.ms-star{cursor:pointer;transition:transform .15s ease, color .15s ease;color:#e2e8f0;font-size:54px;line-height:1;background:none;border:0;padding:6px}
.ms-star:hover, .ms-star.active{color:#fbbf24;transform:scale(1.1)}
.ms-star:focus{outline:none}
.ms-btn{background:#347677;transition:background .2s,box-shadow .2s}
.ms-btn:hover{background:#286061;box-shadow:0 6px 18px rgba(52,118,119,.25)}
.ms-input:focus{outline:none;border-color:#347677;box-shadow:0 0 0 3px rgba(52,118,119,.15)}
</style></head><body class="min-h-screen flex items-center justify-center p-5">
<div class="w-full max-w-lg" id="root">
  <div class="ms-card bg-white rounded-2xl p-8 sm:p-12 text-center" id="step1">
    <img src="{{logo}}" alt="{{company}}" class="h-12 mb-6 mx-auto" loading="lazy">
    <h1 class="text-2xl font-bold text-slate-900 mb-2 tracking-tight">Hoe was uw ervaring?</h1>
    <p class="text-sm text-slate-500 mb-8">Klik op het aantal sterren dat past bij uw ervaring met {{company}}.</p>
    <div class="flex justify-center gap-1 mb-2" id="stars">
      <button class="ms-star" data-s="1" aria-label="1 ster">★</button>
      <button class="ms-star" data-s="2" aria-label="2 sterren">★</button>
      <button class="ms-star" data-s="3" aria-label="3 sterren">★</button>
      <button class="ms-star" data-s="4" aria-label="4 sterren">★</button>
      <button class="ms-star" data-s="5" aria-label="5 sterren">★</button>
    </div>
    <div class="text-xs text-slate-400">Uw beoordeling wordt vertrouwelijk behandeld.</div>
  </div>
  <form class="ms-card bg-white rounded-2xl p-8 sm:p-10 hidden" id="step2">
    <h2 class="text-xl font-bold text-slate-900 mb-2">Sorry dat het beter kan</h2>
    <p class="text-sm text-slate-600 mb-6">Vertel ons wat we beter kunnen doen — uw feedback gaat direct naar onze eigenaar en helpt ons verbeteren.</p>
    <input type="hidden" name="stars" id="f-stars">
    <div class="mb-4"><label class="text-xs font-semibold text-slate-700 uppercase tracking-wider block mb-2">Uw naam</label>
      <input name="name" required class="ms-input w-full px-4 py-3 border border-slate-200 rounded-lg text-sm bg-slate-50 focus:bg-white"></div>
    <div class="mb-4"><label class="text-xs font-semibold text-slate-700 uppercase tracking-wider block mb-2">E-mail</label>
      <input type="email" name="email" required class="ms-input w-full px-4 py-3 border border-slate-200 rounded-lg text-sm bg-slate-50 focus:bg-white"></div>
    <div class="mb-6"><label class="text-xs font-semibold text-slate-700 uppercase tracking-wider block mb-2">Uw feedback</label>
      <textarea name="feedback" required rows="5" class="ms-input w-full px-4 py-3 border border-slate-200 rounded-lg text-sm bg-slate-50 focus:bg-white resize-vertical"></textarea></div>
    <button class="ms-btn w-full text-white font-semibold py-3 rounded-lg shadow-sm">Verstuur feedback</button>
  </form>
  <div class="ms-card bg-white rounded-2xl p-8 sm:p-12 text-center hidden" id="step3">
    <div class="w-16 h-16 mx-auto mb-5 rounded-full bg-emerald-100 flex items-center justify-center">
      <svg class="w-8 h-8 text-emerald-600" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
    </div>
    <h2 class="text-xl font-bold text-slate-900 mb-2">Bedankt!</h2>
    <p class="text-sm text-slate-600">Uw feedback is verstuurd. We nemen contact op als we vragen hebben.</p>
  </div>
</div>
<script>
(function(){
var cfg = {threshold:{{threshold}}, google_url:"{{google_url}}"};
var stars = document.querySelectorAll('.ms-star');
var step1 = document.getElementById('step1');
var step2 = document.getElementById('step2');
var step3 = document.getElementById('step3');
function picked(n){
  if (n > cfg.threshold && cfg.google_url){
    window.location.href = cfg.google_url;
    return;
  }
  document.getElementById('f-stars').value = n;
  step1.classList.add('hidden');
  step2.classList.remove('hidden');
}
stars.forEach(function(b){
  b.addEventListener('mouseenter', function(){
    var s = parseInt(b.dataset.s);
    stars.forEach(function(x, i){ x.classList.toggle('active', i < s); });
  });
  b.addEventListener('click', function(){ picked(parseInt(b.dataset.s)); });
});
document.getElementById('stars').addEventListener('mouseleave', function(){
  stars.forEach(function(x){ x.classList.remove('active'); });
});
step2.addEventListener('submit', async function(e){
  e.preventDefault();
  var fd = new FormData(step2);
  var payload = {stars: parseInt(fd.get('stars')), name: fd.get('name'), email: fd.get('email'), feedback: fd.get('feedback')};
  try {
    var r = await fetch('/api/review-feedback/', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
    if (r.ok){ step2.classList.add('hidden'); step3.classList.remove('hidden'); }
    else { alert('Verzenden mislukt. Probeer het later opnieuw.'); }
  } catch(err){ alert('Netwerkfout. Probeer het later opnieuw.'); }
});
// Pre-select stars uit ?stars=N
var url = new URL(window.location.href);
var pre = parseInt(url.searchParams.get('stars'));
if (pre >= 1 && pre <= 5) setTimeout(function(){ picked(pre); }, 100);
})();
</script></body></html>"""


@app.route("/review", methods=["GET"])
@app.route("/review/", methods=["GET"])
def review_page():
    s = get_settings()
    html = REVIEW_HTML
    html = html.replace("{{company}}", str(s.get("review_company_name", "Wandmeesters")))
    html = html.replace("{{logo}}", str(s.get("review_logo_url", "/favicon.webp")))
    html = html.replace("{{threshold}}", str(int(s.get("review_gate_threshold", 4) or 4)))
    html = html.replace("{{google_url}}", str(s.get("review_google_url", "") or ""))
    return Response(html, mimetype="text/html")


@app.route("/api/review-config", methods=["GET"])
@app.route("/api/review-config/", methods=["GET"])
def api_review_config():
    s = get_settings()
    return jsonify({
        "threshold": int(s.get("review_gate_threshold", 4) or 4),
        "google_url": s.get("review_google_url", "") or "",
        "company": s.get("review_company_name", "Wandmeesters"),
        "logo": s.get("review_logo_url", "/favicon.webp"),
    })


@app.route("/api/review-feedback", methods=["POST"])
@app.route("/api/review-feedback/", methods=["POST"])
def api_review_feedback():
    body = request.get_json(silent=True) or {}
    stars = int(body.get("stars") or 0)
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    fb = (body.get("feedback") or "").strip()
    if not (stars and name and email and fb):
        return jsonify({"error": "Velden ontbreken"}), 400
    feedback_id = uuid.uuid4().hex[:12]
    item = {
        "id": feedback_id, "stars": stars, "name": name, "email": email, "feedback": fb,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "ip": (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or request.remote_addr or "",
    }
    feedback_list = kv_get("review:feedback", []) or []
    feedback_list.insert(0, item)
    kv_set("review:feedback", feedback_list[:500])  # cap 500
    # Mail intern
    s = get_settings()
    to = (s.get("review_feedback_email") or s.get("company_email") or "").strip()
    if to:
        subj = f"Review-feedback ({stars}★) van {name}"
        body_html = (
            f"<h2>Review-feedback</h2>"
            f"<p><strong>Sterren:</strong> {'★'*stars}{'☆'*(5-stars)}</p>"
            f"<p><strong>Naam:</strong> {html_escape(name)}<br>"
            f"<strong>E-mail:</strong> <a href='mailto:{html_escape(email)}'>{html_escape(email)}</a><br>"
            f"<strong>Tijd:</strong> {item['ts']}</p>"
            f"<p><strong>Feedback:</strong></p>"
            f"<blockquote style='border-left:3px solid #347677;padding:8px 14px;background:#f8fafc;color:#1f2937'>{html_escape(fb)}</blockquote>"
        )
        try: send_email(to_addr=to, subject=subj, body=body_html, content_type="html")
        except Exception: pass
    return jsonify({"ok": True, "id": feedback_id})


@app.route("/api/admin/review-feedback", methods=["GET"])
def api_admin_review_feedback():
    a = _auth_or_401()
    if a: return a
    feedback_list = kv_get("review:feedback", []) or []
    return jsonify({"items": feedback_list})


def _send_review_request(lead, base_url):
    """Stuurt een reviewverzoek-mail naar de klant (`field_574f21f` of `email`).
    HTML met 5 klikbare gouden sterren; ster 1..threshold → /review/?stars=N,
    de hoogste ster → google_url direct."""
    s = get_settings()
    ctx = _build_field_ctx(lead)
    to = (ctx.get("field_574f21f") or "").strip()
    if not to or "@" not in to: return False, "Geen geldig klant-e-mailadres"
    threshold = int(s.get("review_gate_threshold", 4) or 4)
    google_url = (s.get("review_google_url") or "").strip()
    company = s.get("review_company_name", "Wandmeesters")
    intro = s.get("review_email_intro", "Bedankt voor de samenwerking! Hoe tevreden bent u over ons werk?")
    subject = s.get("review_email_subject", "Bedankt voor uw vertrouwen — laat een review achter")
    stars_html = ""
    for i in range(1, 6):
        href = google_url if (i > threshold and google_url) else f"{base_url}/review/?stars={i}"
        stars_html += (
            f'<a href="{href}" style="text-decoration:none;color:#fbbf24;font-size:38px;line-height:1;margin:0 3px" target="_blank">★</a>'
        )
    body = (
        f'<div style="font-family:Poppins,Arial,sans-serif;max-width:520px;margin:0 auto;padding:20px;color:#1f2937">'
        f'<h2 style="color:#347677;margin:0 0 12px">Bedankt, {ctx.get("name", "klant")}!</h2>'
        f'<p style="font-size:14px;line-height:1.6;margin:0 0 24px">{html_escape(intro)}</p>'
        f'<div style="text-align:center;margin:24px 0">{stars_html}</div>'
        f'<p style="font-size:13px;color:#64748b;text-align:center;margin:8px 0 24px">Klik op het aantal sterren dat past bij uw ervaring.</p>'
        f'<p style="font-size:12px;color:#94a3b8;text-align:center;border-top:1px solid #e2e8f0;padding-top:16px;margin-top:24px">{html_escape(company)}</p>'
        f'</div>'
    )
    ok, msg = send_email(to_addr=to, subject=subject, body=body, content_type="html")
    if ok:
        lead.setdefault("review_requests", []).append({
            "to": to, "ts": datetime.now().isoformat(timespec="seconds"), "ok": True
        })
        leads = get_leads()
        for i, l in enumerate(leads):
            if l.get("id") == lead.get("id"):
                leads[i] = lead; break
        kv_set("leads", leads)
    return ok, msg


@app.route("/api/leads/<lead_id>/send-review-request", methods=["POST"])
def api_lead_send_review_request(lead_id):
    a = _auth_or_401()
    if a: return a
    leads = get_leads()
    lead = next((l for l in leads if l.get("id") == lead_id), None)
    if not lead:
        return jsonify({"error": "Lead niet gevonden"}), 404
    host = request.headers.get("X-Forwarded-Host") or request.host
    proto = request.headers.get("X-Forwarded-Proto") or "https"
    base_url = f"{proto}://{host}"
    ok, msg = _send_review_request(lead, base_url)
    audit_log("review.request", lead_id, f"{'OK' if ok else 'FAIL'}: {msg}")
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 502)


# ============================================================
# FACTUUR-MODULE + paid-value pipeline — Kittenvoegen-extension
# ============================================================
def get_invoices_index() -> list:
    return kv_get("invoices:index", []) or []


def _save_invoices_index(invoices: list):
    kv_set("invoices:index", invoices)


def _lead_paid_value(lead_id: str) -> int:
    """Som van facturen met status='betaald' voor één lead."""
    if not lead_id: return 0
    total = 0
    for inv in get_invoices_index():
        if inv.get("lead_id") == lead_id and inv.get("status") == "betaald":
            try: total += int(inv.get("total") or 0)
            except: pass
    return total


@app.route("/api/admin/invoices", methods=["GET"])
def api_admin_invoices_list():
    a = _auth_or_401()
    if a: return a
    items = get_invoices_index()
    # Filter optioneel op lead_id
    lead_id = request.args.get("lead_id", "").strip()
    if lead_id: items = [i for i in items if i.get("lead_id") == lead_id]
    # Sort by created desc
    items = sorted(items, key=lambda x: x.get("created", ""), reverse=True)
    return jsonify({"items": items})


@app.route("/api/admin/invoices", methods=["POST"])
def api_admin_invoices_create():
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    inv = {
        "id": "INV-" + datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6].upper(),
        "lead_id": (body.get("lead_id") or "").strip(),
        "customer_name": (body.get("customer_name") or "").strip(),
        "customer_email": (body.get("customer_email") or "").strip(),
        "description": (body.get("description") or "").strip(),
        "total": int(body.get("total") or 0),
        "status": body.get("status") or "open",  # open | verzonden | betaald | vervallen
        "created": datetime.now().isoformat(timespec="seconds"),
        "due_date": (body.get("due_date") or "").strip(),
        "paid_at": "",
    }
    if inv["status"] == "betaald":
        inv["paid_at"] = datetime.now().isoformat(timespec="seconds")
    invs = get_invoices_index()
    invs.insert(0, inv)
    _save_invoices_index(invs)
    audit_log("invoice.create", inv["id"], f"€{inv['total']} ({inv['status']})")
    return jsonify(inv), 201


@app.route("/api/admin/invoices/<inv_id>", methods=["GET"])
def api_admin_invoices_get(inv_id):
    a = _auth_or_401()
    if a: return a
    inv = next((i for i in get_invoices_index() if i.get("id") == inv_id), None)
    if not inv: return jsonify({"error": "Niet gevonden"}), 404
    return jsonify(inv)


@app.route("/api/admin/invoices/<inv_id>", methods=["PUT", "PATCH"])
def api_admin_invoices_update(inv_id):
    a = _auth_or_401()
    if a: return a
    body = request.get_json(silent=True) or {}
    invs = get_invoices_index()
    for i, inv in enumerate(invs):
        if inv.get("id") == inv_id:
            old_status = inv.get("status")
            for k in ("customer_name", "customer_email", "description", "total", "status", "due_date", "lead_id"):
                if k in body:
                    if k == "total":
                        try: inv[k] = int(body[k] or 0)
                        except: pass
                    else:
                        inv[k] = body[k]
            if inv.get("status") == "betaald" and old_status != "betaald":
                inv["paid_at"] = datetime.now().isoformat(timespec="seconds")
            elif inv.get("status") != "betaald":
                inv["paid_at"] = ""
            invs[i] = inv
            _save_invoices_index(invs)
            audit_log("invoice.update", inv_id, f"status={inv.get('status')}")
            return jsonify(inv)
    return jsonify({"error": "Niet gevonden"}), 404


@app.route("/api/admin/invoices/<inv_id>", methods=["DELETE"])
def api_admin_invoices_delete(inv_id):
    a = _auth_or_401()
    if a: return a
    invs = get_invoices_index()
    new = [i for i in invs if i.get("id") != inv_id]
    if len(new) == len(invs): return jsonify({"error": "Niet gevonden"}), 404
    _save_invoices_index(new)
    audit_log("invoice.delete", inv_id, "verwijderd")
    return jsonify({"deleted": True})


@app.route("/api/admin/leads/<lead_id>/paid-value", methods=["GET"])
def api_admin_lead_paid_value(lead_id):
    a = _auth_or_401()
    if a: return a
    return jsonify({"lead_id": lead_id, "paid_value": _lead_paid_value(lead_id)})


# Vercel needs `app` exposed at module level (WSGI auto-detected by @vercel/python)
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8080)))
