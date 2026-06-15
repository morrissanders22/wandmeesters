#!/usr/bin/env python3
"""
Migreer de 25 bestaande statische index.html pagina's naar block-based pages
in admin/data/ zodat ze in de admin editor bewerkbaar zijn.

Output:
- admin/data/page-<safe-slug>.json (één per pagina, matches kv_get('page:<slug>'))
- admin/data/pages-index.json (geüpdate index list)
- api/data/pages-bootstrap.json (read-only bundle voor lambda fallback als KV leeg is)
"""
import re, os, json, glob, hashlib
from html.parser import HTMLParser
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN_DATA = os.path.join(ROOT, 'admin', 'data')
ADMIN_KV = os.path.join(ROOT, 'admin', 'data', 'kv')
API_DATA = os.path.join(ROOT, 'api', 'data')
os.makedirs(ADMIN_KV, exist_ok=True)
os.makedirs(API_DATA, exist_ok=True)

SKIP_DIRS = ('admin/', 'api/', 'wp-admin/', 'wp-content/', 'wp-includes/', 'node_modules/', '.backups/', '.git/', '.vercel/')
TEMPLATE_HINTS = {
    'diensten/stukadoor-': 'stukadoor-stad',
    'diensten/': 'dienst',
}


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def safe_kv_filename(key: str) -> str:
    return re.sub(r'[^a-zA-Z0-9._-]', '_', key) + '.json'


def slug_for(path: str) -> str:
    p = path.replace('index.html', '').rstrip('/')
    p = p.replace('./', '')
    if not p:
        return ''
    if p.startswith('/'):
        p = p[1:]
    return p


def detect_template(slug: str) -> "str | None":
    for hint, tmpl in TEMPLATE_HINTS.items():
        if slug.startswith(hint.rstrip('/')):
            return tmpl
    return 'basic-page'


def strip_tags(html: str) -> str:
    text = re.sub(r'<[^>]+>', '', html or '')
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#039;|&apos;', "'", text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_meta(html: str, slug: str) -> dict:
    def grab(pattern, default=''):
        m = re.search(pattern, html, re.I | re.S)
        return m.group(1).strip() if m else default

    title = grab(r'<title[^>]*>([^<]+)</title>')
    description = grab(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']*)["\']')
    canonical = grab(r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']*)["\']')
    og_title = grab(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']*)["\']') or title
    og_description = grab(r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']*)["\']') or description
    og_image = grab(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']*)["\']')
    twitter_card = grab(r'<meta\s+name=["\']twitter:card["\']\s+content=["\']([^"\']*)["\']') or 'summary_large_image'
    twitter_image = grab(r'<meta\s+name=["\']twitter:image["\']\s+content=["\']([^"\']*)["\']') or og_image
    robots = grab(r'<meta\s+name=["\']robots["\']\s+content=["\']([^"\']*)["\']') or 'index,follow'

    schema_jsonld = None
    schema_m = re.search(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.I | re.S)
    if schema_m:
        try:
            schema_jsonld = json.loads(schema_m.group(1).strip())
        except Exception:
            schema_jsonld = None

    return {
        'title': title,
        'description': description,
        'canonical': canonical,
        'robots': robots,
        'og_title': og_title,
        'og_description': og_description,
        'og_image': og_image,
        'twitter_card': twitter_card,
        'twitter_image': twitter_image,
        'hreflang': [],
        'keyword': '',
        'schema_jsonld': schema_jsonld,
    }


def extract_main_html(html: str) -> str:
    m = re.search(r'<main[^>]*>(.*?)</main>', html, re.I | re.S)
    if m:
        return m.group(1)
    m = re.search(r'<body[^>]*>(.*?)</body>', html, re.I | re.S)
    if m:
        body = m.group(1)
        body = re.sub(r'<header[^>]*>.*?</header>', '', body, flags=re.I | re.S)
        body = re.sub(r'<footer[^>]*>.*?</footer>', '', body, flags=re.I | re.S)
        body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.I | re.S)
        body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.I | re.S)
        body = re.sub(r'<noscript[^>]*>.*?</noscript>', '', body, flags=re.I | re.S)
        return body
    return ''


def extract_headings_and_paragraphs(main_html: str) -> list[dict]:
    """Maak een grove block-decompositie van de main-content.
    Strategie: pak h1/h2/h3 als heading blocks, pak <p> tekst als paragraph blocks,
    pak <ul>/<ol> als list blocks, pak FAQ-achtige accordion items als faq-group.
    Negeer breadcrumbs/buttons/hero-overlay. Bewaar de rauwe section als rich-text als fallback.
    """
    blocks: list[dict] = []
    seen_text: set[str] = set()

    def dedupe(text: str) -> bool:
        key = re.sub(r'\s+', ' ', (text or '').strip()).lower()[:200]
        if not key or key in seen_text:
            return False
        seen_text.add(key)
        return True

    # Headings (in volgorde van voorkomen, gemerged H1/H2/H3)
    for m in re.finditer(r'<(h[1-6])[^>]*>(.*?)</\1>', main_html, re.I | re.S):
        tag = m.group(1).lower()
        text = strip_tags(m.group(2))
        if not text or len(text) > 250:
            continue
        if not dedupe(text):
            continue
        blocks.append({'type': f'heading-{tag}', 'text': text})

    # Paragrafen — directe <p> children
    for m in re.finditer(r'<p[^>]*>(.*?)</p>', main_html, re.I | re.S):
        text = strip_tags(m.group(1))
        if not text or len(text) < 12 or len(text) > 1200:
            continue
        if not dedupe(text):
            continue
        blocks.append({'type': 'paragraph', 'text': text})

    # Lijsten
    for m in re.finditer(r'<(ul|ol)[^>]*>(.*?)</\1>', main_html, re.I | re.S):
        list_tag = m.group(1).lower()
        items_html = m.group(2)
        items = [strip_tags(li.group(1)) for li in re.finditer(r'<li[^>]*>(.*?)</li>', items_html, re.I | re.S)]
        items = [i for i in items if i and len(i) < 400]
        if 2 <= len(items) <= 30:
            list_key = '|'.join(items[:3]).lower()[:200]
            if list_key not in seen_text:
                seen_text.add(list_key)
                blocks.append({'type': f'list-{list_tag}', 'items': items})

    # Afbeeldingen (alleen content imgs, geen logos)
    for m in re.finditer(r'<img[^>]*src=["\']([^"\']+)["\'][^>]*>', main_html, re.I):
        src = m.group(1)
        if 'logo' in src.lower() or 'external-cache' in src or 'gravatar' in src:
            continue
        alt_m = re.search(r'alt=["\']([^"\']*)["\']', m.group(0), re.I)
        alt = alt_m.group(1) if alt_m else ''
        img_key = src[:200]
        if img_key not in seen_text:
            seen_text.add(img_key)
            blocks.append({'type': 'image', 'src': src, 'alt': alt})

    # FAQ (ElementsKit accordion: ekit-accordion-title + ekit-accordion--content)
    faq_items = []
    for m in re.finditer(
        r'<span[^>]*class="[^"]*ekit-accordion-title[^"]*"[^>]*>(.*?)</span>'
        r'.*?<div[^>]*class="[^"]*ekit-accordion--content[^"]*"[^>]*>(.*?)</div>',
        main_html, re.I | re.S
    ):
        q = strip_tags(m.group(1))
        a = strip_tags(m.group(2))
        if q and a:
            faq_items.append({'question': q, 'answer': a})
    if faq_items:
        blocks.append({'type': 'faq-group', 'items': faq_items})

    return blocks


def build_page(html_path: str) -> dict:
    rel = os.path.relpath(html_path, ROOT)
    slug = slug_for(rel)
    with open(html_path, encoding='utf-8') as f:
        html = f.read()

    meta = extract_meta(html, slug)
    main_html = extract_main_html(html)
    blocks = extract_headings_and_paragraphs(main_html)

    title = meta['title']
    # Heuristic title strip: "X - Wandmeesters" → "X" als display title
    title_short = re.sub(r'\s*[\-|]\s*Wandmeesters\s*$', '', title).strip() or title

    template = detect_template(slug)
    now = now_iso()

    page = {
        'slug': slug,
        'title': title_short,
        'status': 'published',
        'template': template,
        'locale': 'nl',
        'parent': None,
        'menu_position': 0,
        'scheduled_publish_at': None,
        'author': 'migration',
        'created_at': now,
        'updated_at': now,
        'published_at': now,
        'meta': meta,
        'content_blocks': blocks,
        'migrated_from': rel,
    }
    return page


def main():
    pages = []
    for html_path in sorted(glob.glob(os.path.join(ROOT, '**/*.html'), recursive=True)):
        rel = os.path.relpath(html_path, ROOT)
        if any(rel.startswith(d) for d in SKIP_DIRS):
            continue
        if 'index.html' not in rel:
            continue
        if rel.endswith('.elementor-backup'):
            continue
        try:
            page = build_page(html_path)
        except Exception as e:
            print(f'  ✗ {rel}: {e}')
            continue
        pages.append(page)

        # Write per-page JSON in admin/data/ (kv local fallback)
        fname = safe_kv_filename(f"page:{page['slug']}")
        with open(os.path.join(ADMIN_KV, fname), 'w', encoding='utf-8') as f:
            json.dump(page, f, ensure_ascii=False, indent=2)
        print(f'  ✓ {rel}  →  page:{page["slug"]}  ({len(page["content_blocks"])} blocks)')

    # Pages index voor admin list
    index = [
        {
            'slug': p['slug'],
            'title': p['title'],
            'status': p['status'],
            'template': p['template'],
            'locale': p['locale'],
            'updated_at': p['updated_at'],
            'seo_score': 0,
        }
        for p in pages
    ]
    with open(os.path.join(ADMIN_KV, safe_kv_filename('pages:index')), 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    # Bootstrap bundle in api/data/ — read-only fallback voor lambda als KV leeg
    bootstrap = {
        'pages_index': index,
        'pages': {f"page:{p['slug']}": p for p in pages},
        'generated_at': now_iso(),
        'note': 'Bootstrap data uit migratie van statische HTML. Wordt door lambda gelezen als KV leeg is.',
    }
    with open(os.path.join(API_DATA, 'pages-bootstrap.json'), 'w', encoding='utf-8') as f:
        json.dump(bootstrap, f, ensure_ascii=False, indent=2)

    print()
    print(f'Migrated {len(pages)} pages')
    print(f'  → admin/data/page-*.json (lokaal werkend, KV-fallback)')
    print(f'  → admin/data/pages_index.json')
    print(f'  → api/data/pages-bootstrap.json (lambda fallback voor productie)')
    return pages


if __name__ == '__main__':
    main()
