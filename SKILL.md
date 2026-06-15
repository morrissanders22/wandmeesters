---
name: wandmeesters
description: Werken aan de Wandmeesters static-export site (WordPress export via Simply Static) gehost op Vercel met een Python/Flask serverless admin-backend. Gebruik dit als je bestaande pages, hero, marquee, reviews carousel, multistep form, mobile menu, of het admin paneel aanpast.
---

# Wandmeesters static site

## Wat dit is
- Static export van een WordPress (Elementor-gebouwde) site, gedeployed op Vercel
- Domein: production via Vercel project `morrissanders22s-projects/wandmeesters`
- Custom Python/Flask serverless backend onder `api/index.py` voor login, admin, leads-pipeline, SMTP-mailing en chatbot
- Belangrijkste assets liggen onder `wp-content/` (uploads/plugins/themes) en `wp-includes/`

## Critical files
- `index.html` — homepage (Elementor inline CSS ~237 KB)
- `*/index.html` — 32 subpagina's (diensten, contact, over-ons, projecten, project/[city], algemene-voorwaarden, etc.)
- `wp-content/uploads/animations-disable.css` — **alle custom CSS** wordt inline geïnjecteerd in elke HTML via `<style id="ms-inline-css">`
- `wp-content/uploads/multistep-fix.js` — **alle custom JS**: multistep-form, mobile menu toggle, video iframe injectie, counter polyfill, carousel, marquee builder, form-submit intercept
- `wp-content/uploads/external-cache/logo-wandmeesters.webp` — lokaal gecachede versie van het Google-Storage logo
- `api/index.py` — Flask serverless function (login, /admin/*, /api/*)
- `api/data/*.json` — pre-built indexes voor pages/sitemap/media (Vercel lambda heeft geen filesystem-toegang tot static files)
- `admin/index.html` — admin UI (Tailwind via CDN)
- `vercel.json` — routing en `functions.api/index.py.excludeFiles` om lambda-bundle onder 245 MB te houden
- `server.py` — lokale Flask dev server (zelfde routes als api/index.py)

## Belangrijke conventies & gotchas

### 1. CSS-injectie pipeline
Mijn CSS staat in **één** bron-file: `wp-content/uploads/animations-disable.css`. Elke HTML-pagina heeft een `<style id="ms-inline-css">` met die hele CSS-inhoud inline (in `<head>`). Bij elke aanpassing moet je deze syncen:
```python
import re, glob
with open('wp-content/uploads/animations-disable.css') as f: css = f.read().strip()
tag = '<style id="ms-inline-css">' + css + '</style>'
for f in glob.glob('**/*.html', recursive=True):
    if '/.git/' in f or f.startswith('admin/'): continue
    with open(f) as fh: s = fh.read()
    s2 = re.sub(r'<style[^>]*id="ms-inline-css"[^>]*>[\s\S]*?</style>',
                lambda m: tag, s)  # lambda voorkomt regex backref-bug bij \uXXXX in css
    if s != s2: open(f,'w').write(s2)
```
**Bump de JS cache** ook in alle HTML's na een wijziging:
```python
s = re.sub(r'(/wp-content/uploads/multistep-fix\.js)\?v=\d+', r'\1?v=N+1', s)
```

### 2. Elementor's per-widget CSS is **specifieker dan jouw mobile overrides**
Bij elke per-widget `margin: 0 100px`-achtige rule kun je op mobile een rare layout krijgen. Vuistregel:
- Maak overrides scoped (`main .elementor-top-section.foo` niet `.foo`) — anders raak je inner-header sections
- Gebruik `:has(.ms-marker-class)` om alleen specifieke widgets te targeten
- Plaats desktop-only rules binnen `@media (min-width: 1025px)` zodat ze mobile rules niet vechten

### 3. Wat Elementor's JS NIET doet in een static export
De volgende moeten **wij** zelf doen via `multistep-fix.js`:
- Multi-step form (Elementor's `FormSteps` bundle wordt async geladen en faalt vaak) → ik parse step-markers, tag fields met `data-ms-step`, bouw `.ms-indicator` + `.ms-nav` (Vorige/Verder)
- Mobile hamburger toggle → `aria-expanded` flip + `.ms-mobile-open` class
- Submenu accordion op mobiel / hover dropdown op desktop
- YouTube iframe injectie in `.elementor-widget-video > .elementor-video`
- Counter animation (`elementor-counter-number` with IntersectionObserver)
- Partners marquee rail builder (Element Pack's bdt-marquee is broken zonder GSAP)
- Reviews carousel (3 cards, autoplay 3s)
- Service-card click-routing (icon-boxes zonder href → kies URL op basis van title)
- Trustindex reviews fallback (echte widget heeft `data-pid=""` op live, dus we renderen hardcoded reviews)
- Form-submit intercept → POST naar `/api/submit/`

### 4. Mobile menu structure
Header dropdown nav heeft class `elementor-nav-menu--dropdown`. Footer nav heeft class `elementor-nav-menu--main elementor-nav-menu--layout-vertical`. CSS-selectors moeten **beide** dekken voor de accordion-styling op mobiel.

Mijn JS click-handler runt op alle `.elementor-nav-menu li.menu-item-has-children > a`. Op desktop navigeert klik naar het **eerste sub-item** van de dropdown; op mobile (`window.matchMedia('(max-width: 1024px)')`) togglet `.ms-open` voor accordion-gedrag.

### 5. Vercel deploy quirks
- `vercel.json > functions.api/index.py.excludeFiles` moet **alles excluden behalve admin/api/wp-content/uploads** anders raakt de lambda-bundle boven 245 MB (max). Volledige list staat in `vercel.json`.
- `api/data/*.json` (pages/sitemap/media indexes) **moeten mee in de bundle** — `list_pages()` en co. lezen deze ipv filesystem te scannen.
- Bij elke deploy: `python3 -c "from build_index import build" && vercel deploy --prod --yes` — of regenereer indexes handmatig (zie het Python script in `/tmp/reapply.py` voor logic).
- Aliases: `wandmeesters-morrissanders22s-projects.vercel.app` wijst altijd naar laatste production deploy.

### 6. Admin & SMTP
- Default credentials in `api/index.py` `DEFAULT_SETTINGS`:
  - Login: `admin / admin`
  - SMTP: `smtp.strato.com` poort 587 TLS, gebruiker `email@mhsmedia.email`, wachtwoord `TeamMHSMedia23@`
  - Mail 1 → `info@wandmeesters.nl`, BCC `marjolein@mhsmedia.nl, julian@mhsmedia.nl`, subject `Nieuwe offerte aanvraag van [field id="name"]`, body `[all-fields]`, HTML
  - Mail 2 → dynamic `[field id="field_574f21f"]` (= klant e-mail), BCC `marjolein@mhsmedia.nl`, reply-to `info@wandmeesters.nl`
- Storage: lokaal als `admin/data/*.json` (Flask dev server), productie via Vercel KV (REST API) — env vars `KV_REST_API_URL` + `KV_REST_API_TOKEN`. Configureer via Vercel marketplace (Upstash KV integration).
- Pipeline stages: `ontvangen → contact → gebeld → ingepland → closed → lost`. Elke nieuwe lead start in `ontvangen`. Drag-and-drop in admin UI.
- Chatbot commands (`/api/chat` POST `{message}`): `voeg pagina toe voor X`, `toon alle pagina's`, `verwijder pagina /pad/`, `wijzig 'tekst' naar 'andere' op /pad/` (laatste werkt alleen lokaal, fs is read-only op Vercel).

### 7. Performance optimisaties die al gedaan zijn
- 692 plugin-scripts gestript (alleen `multistep-fix.js` blijft)
- 621 noise-CSS-links gestript (animations, sticky, social-icons, apple-webkit)
- Resterende 46 stylesheets via `media="print" onload="this.media='all'"` trick (async)
- 16 MB images bespaard via WebP-conversie van 181 jpg/png
- 35 hero-images extra gecomprimeerd (q65, max 1600w)
- All transitions/animations site-wide uitgezet via `*:not(...){animation:none;transition:none}` met whitelist voor onze `.ms-reviews-track`, `.ms-partners-track`, `.bdt-marquee .ms-marquee-rail`
- Cache-Control: HTML `max-age=0 must-revalidate`, assets `max-age=31536000 immutable`
- Resource hints: `dns-prefetch` + `preconnect` voor `fonts.googleapis.com`, `fonts.gstatic.com`
- Image lazy-loading + `width`/`height` attributes
- GTranslate plugin verwijderd (96 matches stripped)
- Trustindex/Cookiebot/reCAPTCHA scripts verwijderd
- Hallo-wereld post + bijbehorende listings opgeschoond
- `body { overflow-x: hidden }` om horizontal scroll te blokkeren op mobile

### 8. Pagina-specifieke fixes
- Homepage hero: slideshow vervangen door **één statische webp** (`IMG_0155.webp`) via CSS-override op `#homeSection` (Elementor's slideshow JS draait niet betrouwbaar)
- `/dunpleister-latexspuiten/`: dubbele sectie "Ideaal voor nieuwbouw en renovatie" verwijderd (regels 840-902)
- `/diensten/dunpleisterwerk/` titel: `<h2 class="ms-split-title"><span>Dunpleisterwerk voor</span> <span>gladde muren en plafonds</span></h2>` voor mobile-friendly wrap

### 9. Visuele fundamenten
- Brand kleuren: primary teal `#347677`, dark `#1f2937`
- Typografie: **Poppins** voor alle hoofdtekst (overal `font-family: 'Poppins',-apple-system,sans-serif !important` waar nodig overschrijven)
- Border-radius: 6px buttons, 8-12px cards, 8px badge
- Hover op buttons: opacity .92 + zacht donker

## Workflows

### Wijziging aan styling
1. Edit `wp-content/uploads/animations-disable.css`
2. Run inline-script (zie sectie 1) om alle HTML's bij te werken
3. `node -c wp-content/uploads/multistep-fix.js` voor syntax check als JS ook is aangepast
4. `vercel deploy --prod --yes`

### Wijziging aan layout/content van één pagina
1. Edit de specifieke `*/index.html`
2. Niet vergeten te inline-syncen ALS je ook CSS hebt aangepast
3. Deploy

### Subpage hero broken op mobile
Check of de subpage-hero CSS rule óók een inner-header-section pakt. Selector moet zijn:
```css
main .elementor-section.elementor-top-section.elementor-section-content-middle.elementor-section-height-default:not(:first-of-type)
```
**niet** zonder `main` ancestor.

### Heading "raar" gewrapped op mobile
1. Voeg `class="ms-split-title"` toe aan de `<h2>`
2. Wrap de twee logische delen in `<span>...</span>`
3. CSS in `animations-disable.css` heeft al de regel voor `display: block` op spans en `width:100% + margin:auto` voor centreren
4. Sync + deploy

### Admin / leads
- Login: `/inloggen` (admin/admin)
- Pipeline: `/admin/#pipeline` (kanban met drag-and-drop)
- SMTP test: `/admin/#settings` → "Verstuur test"
- Chatbot: floating bubble rechtsonder op admin → typ commando

### Restore vanuit zip
Bij `simply-static-1-*.zip` redo:
1. Backup `admin/`, `api/`, `server.py`, `vercel.json`, `requirements.txt`, `wp-content/uploads/{animations-disable.css,multistep-fix.js,external-cache/}`, en alle eerder geconverteerde WebP-files
2. `cp -R /tmp/zip-extract/. .` (overlay zonder delete)
3. Restore backups
4. Run `/tmp/reapply.py` (URL rewrite, blocker strip, WebP rewrite, CSS/JS inject) en de projects-injection
5. Cache bump, deploy

## Known limitations
- **PageSpeed 100 is niet realistisch** bij Elementor. ~237 KB inline CSS per pagina is hardcoded; tree-shaking vereist build-tool dat we niet hebben. Realistisch: Performance 70-85, Accessibility 95+, Best Practices 90+, SEO 100.
- Trustindex `data-pid=""` ook leeg op de **live** wandmeesters.nl — we tonen 10 placeholder Google-reviews (Justin Seel, Denise Molenaar, Hans Okx, etc.) via JS fallback. Voor echte data is een Google Places API key nodig.
- YouTube iframe kan zwart blijven in headless puppeteer-test (origin-handshake faalt op localhost); in echte browser werkt het.
