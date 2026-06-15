
(function () {
'use strict';
function init() {
var forms = document.querySelectorAll('form.elementor-form');
forms.forEach(function (form) {
if (form.dataset.msFixApplied === '1') return;
var wrapper = form.querySelector('.elementor-form-fields-wrapper');
if (!wrapper) return;
var stepContainers = Array.from(wrapper.querySelectorAll(':scope > .e-form__step, :scope > .elementor-field-type-step'));
stepContainers.forEach(function (container, stepIdx) {
Array.from(container.children).forEach(function (child) {
if (child.classList.contains('e-field-step')) {
child.remove();
return;
}
child.dataset.msStep = String(stepIdx);
});
});
stepContainers.forEach(function (container) {
while (container.firstChild) wrapper.insertBefore(container.firstChild, container);
container.remove();
});
var children = Array.from(wrapper.children);
var submitGroup = wrapper.querySelector('.elementor-field-type-submit');
var taggedFields = children.filter(function (c) { return c.dataset.msStep !== undefined; });
var stepCount;
if (taggedFields.length > 0) {
stepCount = stepContainers.length;
} else {
var markerIdx = [];
children.forEach(function (el, i) {
if (el.classList.contains('elementor-field-type-step')) markerIdx.push(i);
});
if (markerIdx.length > 0) {
stepCount = markerIdx.length;
for (var i = 0; i < stepCount; i++) {
var start = markerIdx[i] + 1;
var end = (i + 1 < stepCount) ? markerIdx[i + 1] : children.length;
for (var j = start; j < end; j++) {
var el = children[j];
if (el === submitGroup || el.classList.contains('elementor-field-type-step')) continue;
el.dataset.msStep = String(i);
}
}
markerIdx.forEach(function (i) { children[i].style.display = 'none'; });
} else {
var personalIds = ['name', 'email', 'field_574f21f', 'field_45bf4d6'];
var personalSelectors = ['elementor-field-type-text','elementor-field-type-email','elementor-field-type-tel'];
var splitAt = -1;
for (var k = 0; k < children.length; k++) {
var c = children[k];
if (c === submitGroup) continue;
if (c.classList.contains('elementor-field-type-recaptcha') ||
c.classList.contains('elementor-field-type-recaptcha_v3')) continue;
var matchesPersonal = personalIds.some(function (id) { return c.className.indexOf('elementor-field-group-' + id) !== -1; });
if (matchesPersonal) { splitAt = k; break; }
}
if (splitAt === -1) {
var nonSubmit = children.filter(function (c) {
return c !== submitGroup &&
!c.classList.contains('elementor-field-type-recaptcha') &&
!c.classList.contains('elementor-field-type-recaptcha_v3');
});
if (nonSubmit.length < 4) return; 
splitAt = children.indexOf(nonSubmit[Math.ceil(nonSubmit.length / 2)]);
}
stepCount = 2;
for (var idx = 0; idx < children.length; idx++) {
var el2 = children[idx];
if (el2 === submitGroup) continue;
if (el2.classList.contains('elementor-field-type-recaptcha') ||
el2.classList.contains('elementor-field-type-recaptcha_v3')) {
el2.dataset.msStep = '1';
continue;
}
el2.dataset.msStep = (idx < splitAt) ? '0' : '1';
}
}
}
if (stepCount < 2) return;
form.dataset.msFixApplied = '1';
if (submitGroup) submitGroup.dataset.msStep = String(stepCount - 1);
var fieldsByStep = [];
for (var s = 0; s < stepCount; s++) {
fieldsByStep.push(wrapper.querySelectorAll('[data-ms-step="' + s + '"]'));
}
var indicator = document.createElement('div');
indicator.className = 'ms-indicator';
for (var k = 0; k < stepCount; k++) {
var dot = document.createElement('span');
dot.className = 'ms-dot';
dot.dataset.idx = k;
dot.textContent = String(k + 1);
indicator.appendChild(dot);
}
wrapper.insertBefore(indicator, wrapper.firstChild);
var nav = document.createElement('div');
nav.className = 'ms-nav elementor-field-group elementor-col-100';
var prevBtn = document.createElement('button');
prevBtn.type = 'button';
prevBtn.className = 'ms-prev';
prevBtn.textContent = 'Vorige';
var nextBtn = document.createElement('button');
nextBtn.type = 'button';
nextBtn.className = 'ms-next';
nextBtn.textContent = 'Verder';
nav.appendChild(prevBtn);
nav.appendChild(nextBtn);
if (submitGroup && submitGroup.parentNode === wrapper) {
wrapper.insertBefore(nav, submitGroup);
} else {
wrapper.appendChild(nav);
}
var current = 0;
function show(idx) {
form.dataset.msCurrent = String(idx);
indicator.querySelectorAll('.ms-dot').forEach(function (d, i) {
d.classList.toggle('ms-done', i < idx);
d.classList.toggle('ms-active', i === idx);
});
prevBtn.classList.toggle('ms-hidden', idx === 0);
var isLast = (idx === stepCount - 1);
nextBtn.classList.toggle('ms-hidden', isLast);
current = idx;
}
function validateStep(idx) {
var stepFields = fieldsByStep[idx];
for (var i = 0; i < stepFields.length; i++) {
var fieldEl = stepFields[i];
var inputs = fieldEl.querySelectorAll('input, select, textarea');
for (var j = 0; j < inputs.length; j++) {
var f = inputs[j];
if (f.type === 'hidden') continue;
if (f.required && !f.checkValidity()) { f.reportValidity(); return false; }
if (f.tagName === 'SELECT' && f.required && (f.value === '' || f.value === 'Selecteer')) {
f.focus(); f.reportValidity(); return false;
}
}
}
return true;
}
nextBtn.addEventListener('click', function () {
if (validateStep(current)) show(current + 1);
});
prevBtn.addEventListener('click', function () {
if (current > 0) show(current - 1);
});
show(0);
});
}
function youtubeId(url) {
var m = url.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?(?:.*&)?v=|embed\/|v\/|shorts\/))([A-Za-z0-9_-]{11})/);
return m ? m[1] : null;
}
function vimeoId(url) {
var m = url.match(/vimeo\.com\/(?:video\/)?(\d+)/);
return m ? m[1] : null;
}
var DEFAULT_YT_ID = 'eRNi_Gz8g9Y';
function makeYouTubeIframe(yid, cfg) {
cfg = cfg || {};
var params = ['rel=0'];
if (cfg.controls === 'no') params.push('controls=0');
if (cfg.autoplay === 'yes') params.push('autoplay=1', 'mute=1');
if (cfg.loop === 'yes') params.push('loop=1', 'playlist=' + yid);
if (cfg.mute === 'yes') params.push('mute=1');
var iframe = document.createElement('iframe');
iframe.src = 'https://www.youtube.com/embed/' + yid + '?' + params.join('&');
iframe.title = 'Wandmeesters video';
iframe.frameBorder = '0';
iframe.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
iframe.allowFullscreen = true;
iframe.loading = 'lazy';
iframe.style.cssText = 'width:100%;aspect-ratio:16/9;display:block;border:0;background:#000;';
return iframe;
}
function initVideos() {
document.querySelectorAll('.elementor-widget-video').forEach(function (widget) {
if (widget.dataset.videoFixApplied === '1') return;
widget.querySelectorAll('iframe, .elementor-video[tagName="iframe"]').forEach(function (i) { i.remove(); });
var container = widget.querySelector('.elementor-wrapper, .elementor-widget-container') || widget;
var raw = widget.getAttribute('data-settings');
var cfg = {};
try { cfg = raw ? JSON.parse(raw) : {}; } catch (e) {}
var yid = DEFAULT_YT_ID;
if (cfg.video_type === 'youtube' && cfg.youtube_url) {
var parsed = youtubeId(cfg.youtube_url);
if (parsed) yid = parsed;
} else if (cfg.video_type === 'vimeo' && cfg.vimeo_url) {
var v = vimeoId(cfg.vimeo_url);
if (v) {
var vf = document.createElement('iframe');
vf.src = 'https://player.vimeo.com/video/' + v;
vf.style.cssText = 'width:100%;aspect-ratio:16/9;display:block;border:0;';
vf.allow = 'autoplay; fullscreen; picture-in-picture';
vf.allowFullscreen = true;
container.appendChild(vf);
widget.dataset.videoFixApplied = '1';
return;
}
}
var inner = widget.querySelector('.elementor-video');
if (inner && inner.tagName !== 'IFRAME') {
inner.innerHTML = '';
inner.appendChild(makeYouTubeIframe(yid, cfg));
} else {
var wrap = widget.querySelector('.elementor-wrapper') || widget.querySelector('.elementor-widget-container');
if (wrap) wrap.appendChild(makeYouTubeIframe(yid, cfg));
}
widget.dataset.videoFixApplied = '1';
});
}
function initSlideshow() {
document.querySelectorAll('.elementor-background-slideshow').forEach(function (host) {
if (host.dataset.slideshowFix === '1') return;
var slides = host.querySelectorAll(':scope > .elementor-background-slideshow__slide__image, :scope .elementor-background-slideshow__slide__image');
if (slides.length < 2) return;
host.dataset.slideshowFix = '1';
slides.forEach(function (s, i) {
s.style.opacity = (i === 0) ? '1' : '0';
s.style.transition = 'opacity 1.4s ease-in-out';
s.style.position = s.style.position || 'absolute';
s.style.top = '0'; s.style.left = '0';
s.style.width = '100%'; s.style.height = '100%';
});
var idx = 0;
setInterval(function () {
slides[idx].style.opacity = '0';
idx = (idx + 1) % slides.length;
slides[idx].style.opacity = '1';
}, 5000);
});
}
function initNavMenu() {
// Hamburger toggle for mobile menus (Elementor's own handler may not init in static export)
document.querySelectorAll('.elementor-menu-toggle').forEach(function (t) {
if (t.dataset.msToggleBound === '1') return;
t.dataset.msToggleBound = '1';
t.addEventListener('click', function (e) {
e.preventDefault();
e.stopPropagation();
var expanded = t.getAttribute('aria-expanded') === 'true';
t.setAttribute('aria-expanded', String(!expanded));
var widget = t.closest('.elementor-widget-nav-menu, .elementor-element');
var dropdown = widget && widget.querySelector('nav.elementor-nav-menu--dropdown');
if (dropdown) {
// Set the top offset to where the toggle ends (so dropdown sits right below header)
var rect = t.getBoundingClientRect();
var top = Math.round(rect.bottom) + 'px';
document.documentElement.style.setProperty('--ms-mobile-menu-top', top);
dropdown.classList.toggle('ms-mobile-open', !expanded);
dropdown.setAttribute('aria-hidden', String(expanded));
}
});
});
// Close mobile menu when clicking a link
document.querySelectorAll('nav.elementor-nav-menu--dropdown a.elementor-item, nav.elementor-nav-menu--dropdown a.elementor-sub-item').forEach(function (a) {
a.addEventListener('click', function () {
var dropdown = a.closest('nav.elementor-nav-menu--dropdown');
if (dropdown && !a.closest('li.menu-item-has-children > a') === a) {
dropdown.classList.remove('ms-mobile-open');
var widget = dropdown.closest('.elementor-widget-nav-menu, .elementor-element');
var t = widget && widget.querySelector('.elementor-menu-toggle');
if (t) t.setAttribute('aria-expanded', 'false');
}
});
});
document.querySelectorAll('.elementor-nav-menu li.menu-item-has-children > a, .elementor-nav-menu--dropdown li.menu-item-has-children > a').forEach(function (a) {
if (a.dataset.msNavApplied === '1') return;
a.dataset.msNavApplied = '1';
a.addEventListener('click', function (e) {
var parent = a.parentElement;
var hasSub = parent.querySelector('.sub-menu');
if (!hasSub) return;
var noTarget = (!a.getAttribute('href') || a.getAttribute('href') === '#');
// Detect "mobile context": parent is inside the mobile dropdown OR viewport is narrow
var inMobileDropdown = !!a.closest('.elementor-nav-menu--dropdown:not(.elementor-nav-menu--main)') ||
                       window.matchMedia('(max-width: 1024px)').matches;
if (inMobileDropdown) {
e.preventDefault();
parent.parentElement.querySelectorAll(':scope > li.menu-item-has-children.ms-open').forEach(function (li) {
if (li !== parent) li.classList.remove('ms-open');
});
parent.classList.toggle('ms-open');
} else if (noTarget) {
// Desktop: clicking a parent with href="#" navigates to the first real sub-item
e.preventDefault();
var firstSub = parent.querySelector('.sub-menu a[href]:not([href="#"]):not([href=""])');
if (firstSub) window.location.href = firstSub.getAttribute('href');
}
});
});
if (!document._msNavOutsideBound) {
document._msNavOutsideBound = true;
document.addEventListener('click', function (e) {
if (!e.target.closest('.elementor-nav-menu')) {
document.querySelectorAll('.elementor-nav-menu li.ms-open').forEach(function (li) {
li.classList.remove('ms-open');
});
}
});
}
}
function initCounters() {
var counters = document.querySelectorAll('.elementor-counter-number');
if (!counters.length || !('IntersectionObserver' in window)) {
counters.forEach(animateCounter);
return;
}
var io = new IntersectionObserver(function (entries) {
entries.forEach(function (e) {
if (e.isIntersecting) { animateCounter(e.target); io.unobserve(e.target); }
});
}, { threshold: 0.3 });
counters.forEach(function (c) { io.observe(c); });
}
function animateCounter(el) {
if (el.dataset.counterAnimated === '1') return;
el.dataset.counterAnimated = '1';
var to = parseFloat(el.dataset.toValue) || 0;
var from = parseFloat(el.dataset.fromValue) || 0;
var duration = parseInt(el.dataset.duration, 10) || 2000;
var delim = el.dataset.delimiter || ',';
var start = performance.now();
function frame(now) {
var t = Math.min(1, (now - start) / duration);
var eased = 1 - Math.pow(1 - t, 3);
var v = from + (to - from) * eased;
var n = (to % 1 === 0 && from % 1 === 0) ? Math.round(v) : v.toFixed(1);
el.textContent = formatNumber(n, delim);
if (t < 1) requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
}
function formatNumber(n, delim) {
return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, delim);
}
var SERVICE_URL_MAP = {
'dunpleisterwerk': '/diensten/dunpleisterwerk/',
'dunpleister': '/diensten/dunpleisterwerk/',
'latex verfspuiten': '/diensten/latex-spuitwerk/',
'latex spuitwerk': '/diensten/latex-spuitwerk/',
'latex spuiten': '/diensten/latex-spuitwerk/',
'stucwerk': '/diensten/stucwerk/',
'traditioneel stucwerk': '/diensten/stucwerk/',
'houtschilderwerk': '/diensten/houtschilderwerk/',
'schilderwerk': '/diensten/houtschilderwerk/',
'betoncire': '/diensten/betoncire/',
'zolderplaat afwerking': '/diensten/zolderplaten-afwerken/',
'zolderplaten afwerken': '/diensten/zolderplaten-afwerken/',
'zolder afwerking': '/diensten/zolderplaten-afwerken/',
'stucwerk & latex verfspuiten': '/stucwerk-latexspuiten/',
'stucwerk + latex spuiten': '/stucwerk-latexspuiten/',
'dunpleister & latex verfspuiten': '/dunpleister-latexspuiten/',
'dunpleisterwerk + latex spuiten': '/dunpleister-latexspuiten/',
'combinatie pakket: stuc- en verfspuiten': '/stucwerk-latexspuiten/',
'combinatie pakket: dunpleister and latex': '/dunpleister-latexspuiten/',
};
function initServiceCardLinks() {
document.querySelectorAll('.elementor-widget-icon-box').forEach(function (box) {
if (box.dataset.svcLinkApplied === '1') return;
if (box.querySelector('a[href]:not([href="#"])')) return;
var title = box.querySelector('.elementor-icon-box-title');
if (!title) return;
var raw = title.textContent.trim().toLowerCase().replace(/\s+/g, ' ');
raw = raw.replace(/[^a-z0-9 &+:\-]/g, '').trim();
var url = SERVICE_URL_MAP[raw];
if (!url) {
for (var key in SERVICE_URL_MAP) {
if (raw.indexOf(key) !== -1) { url = SERVICE_URL_MAP[key]; break; }
}
}
if (!url) return;
box.dataset.svcLinkApplied = '1';
box.style.cursor = 'pointer';
box.dataset.svcUrl = url;
if (title.children.length === 0) {
var titleText = title.textContent;
title.innerHTML = '';
var a = document.createElement('a');
a.href = url;
a.textContent = titleText;
a.style.color = 'inherit';
a.style.textDecoration = 'none';
title.appendChild(a);
}
box.addEventListener('click', function (e) {
if (e.target.closest('a')) return; 
window.location.href = url;
});
});
}
function renderReviewFallback(target) {
if (!target || target.dataset.tiFallback === '1') return;
target.dataset.tiFallback = '1';
var reviews = (window.WANDMEESTERS_REVIEWS || [
{ name: 'Justin Seel',          stars: 5, when: '3 maanden geleden', text: 'Wat zijn wij blij dat we voor de Wandmeesters hebben gekozen! Na lang zoeken en vergelijken kwamen we bij hen uit. Na één telefoontje wisten we genoeg.' },
{ name: 'Denise Molenaar',      stars: 5, when: '6 maanden geleden', text: 'We zijn super blij met het stuc werk en betonsire afwerking die bij ons is gedaan. Het is echt prachtig — de wanden zijn superstrak en de betonsire geeft onze keuken een sfeervolle uitstraling!' },
{ name: 'Hans Okx',             stars: 5, when: '3 maanden geleden', text: 'Ik heb gekozen voor Wandmeesters omdat ze mij werden aangeraden, en daar ben ik ontzettend blij mee. Ze komen hun afspraken na, leveren werk van hoge kwaliteit en werken duidelijk met vakmanschap.' },
{ name: 'Loraina en Annemarijn', stars: 5, when: '3 maanden geleden', text: 'Wij hebben ons volledige huis laten latex spuiten en zijn zeer tevreden over het eindresultaat. De afwerking is strak en professioneel uitgevoerd. Ronduit toppertjes.' },
{ name: 'Demelza van Berk',     stars: 5, when: '6 maanden geleden', text: 'Wij hebben ons hele huis laten stucen, betoncire laten aanbrengen en de plafonds laten verfspuiten door De Wandmeesters, en het resultaat is werkelijk fantastisch! Vanaf het eerste contact tot de laatste afwerking was alles professioneel.' },
{ name: 'Aaron de Boer',        stars: 5, when: '6 maanden geleden', text: 'Wandmeesters hebben bij ons het hele huis gestuct en alles verf gespoten. Alles ziet er superstrak en netjes uit, echt vakwerk. Ze werkten snel, kwamen hun afspraken na en lieten alles keurig achter.' },
{ name: 'Elza Van Vlaanderen',  stars: 5, when: '6 maanden geleden', text: 'Wij hadden de Wandmeesters nodig voor het stucken van meerdere ruimtes. Keurig werk afgeleverd, alles volgens afspraak en alles weer netjes achtergelaten.' },
{ name: 'Jordi Koerse',         stars: 5, when: '6 maanden geleden', text: 'Duidelijke communicatie zowel voor, tijdens als na de klus. Professioneel meedenken en afspraken werden nagekomen.' },
{ name: 'Maupipio',             stars: 5, when: '7 maanden geleden', text: 'Vakmannen!' },
{ name: 'F.W. Lenselink',       stars: 5, when: '1 dag geleden',     text: 'Wij zijn heel blij met Kevin en Yordi! Onze muren zijn superstrak afgewerkt! De boys houden zich aan de afspraken en leveren alles netjes op!' },
]);
var GOOGLE_SVG = '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path fill="#4285F4" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#34A853" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#EA4335" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>';
var CHEVRON_LEFT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg>';
var CHEVRON_RIGHT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>';
function esc(s) { return (s || '').replace(/[&<>"']/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]; }); }
var html = '<div class="ms-reviews-wrap">';
html += '<button type="button" class="ms-reviews-nav ms-prev-rev" aria-label="Vorige reviews">' + CHEVRON_LEFT + '</button>';
html += '<div class="ms-reviews-carousel"><div class="ms-reviews-track">';
reviews.forEach(function (r) {
var stars = '★'.repeat(r.stars) + '☆'.repeat(Math.max(0, 5 - r.stars));
var initial = ((r.name || '?').trim().charAt(0) || '?').toUpperCase();
html += '<div class="ms-review-card">';
html += '<span class="ms-review-quote" aria-hidden="true">&ldquo;</span>';
html += '<div class="ms-review-head">';
html += '<div class="ms-stars" aria-label="' + r.stars + ' van 5 sterren">' + stars + '</div>';
html += '<div class="ms-google-badge" aria-label="Google review">' + GOOGLE_SVG + '</div>';
html += '</div>';
html += '<div class="ms-review-text">' + esc(r.text) + '</div>';
html += '<div class="ms-review-foot">';
html += '<div class="ms-review-avatar" aria-hidden="true">' + initial + '</div>';
html += '<div class="ms-review-meta">';
html += '<div class="ms-review-name">' + esc(r.name) + '</div>';
html += '<div class="ms-review-source">Google' + (r.when ? ' · ' + esc(r.when) : '') + '</div>';
html += '</div></div></div>';
});
html += '</div></div>';
html += '<button type="button" class="ms-reviews-nav ms-next-rev" aria-label="Volgende reviews">' + CHEVRON_RIGHT + '</button>';
html += '</div>'; // /ms-reviews-wrap
html += '<div class="ms-reviews-dots" role="tablist" aria-label="Review navigatie"></div>';
target.innerHTML = html;
// Carousel logic: auto-advance every 5s, pause on hover, clickable dots + arrows
var wrap = target.querySelector('.ms-reviews-wrap');
var carousel = target.querySelector('.ms-reviews-carousel');
var track = target.querySelector('.ms-reviews-track');
var dotsBox = target.querySelector('.ms-reviews-dots');
var prevBtn = target.querySelector('.ms-prev-rev');
var nextBtn = target.querySelector('.ms-next-rev');
var n = reviews.length;
if (!carousel || !track || !dotsBox || n === 0) return;
function getVisible() {
var w = window.innerWidth;
if (w <= 600) return 1;
if (w <= 900) return 2;
return 3;
}
var idx = 0;
var visible = getVisible();
var pageCount = Math.max(1, n - visible + 1);
function buildDots(count) {
dotsBox.innerHTML = '';
for (var i = 0; i < count; i++) {
var b = document.createElement('button');
b.type = 'button';
b.setAttribute('aria-label', 'Ga naar review ' + (i + 1));
if (i === idx) b.className = 'ms-active';
(function (k) {
b.addEventListener('click', function () {
idx = k;
update();
resetTimer();
});
})(i);
dotsBox.appendChild(b);
}
}
function update() {
var card = track.querySelector('.ms-review-card');
if (!card) return;
var step = card.getBoundingClientRect().width + 24;
track.style.transform = 'translateX(-' + (idx * step) + 'px)';
var dots = dotsBox.querySelectorAll('button');
dots.forEach(function (d, i) { d.classList.toggle('ms-active', i === idx); });
}
var timer = null;
function tick() { idx = (idx + 1) % pageCount; update(); }
function startTimer() { if (!timer && pageCount > 1) timer = setInterval(tick, 5000); }
function stopTimer() { if (timer) { clearInterval(timer); timer = null; } }
function resetTimer() { stopTimer(); startTimer(); }
if (prevBtn) prevBtn.addEventListener('click', function () {
idx = (idx - 1 + pageCount) % pageCount;
update();
resetTimer();
});
if (nextBtn) nextBtn.addEventListener('click', function () {
idx = (idx + 1) % pageCount;
update();
resetTimer();
});
if (wrap) {
wrap.addEventListener('mouseenter', stopTimer);
wrap.addEventListener('mouseleave', startTimer);
}
carousel.addEventListener('touchstart', stopTimer, { passive: true });
var resizeTimer = null;
window.addEventListener('resize', function () {
clearTimeout(resizeTimer);
resizeTimer = setTimeout(function () {
var newVisible = getVisible();
if (newVisible !== visible) {
visible = newVisible;
pageCount = Math.max(1, n - visible + 1);
if (idx >= pageCount) idx = 0;
buildDots(pageCount);
}
update();
}, 200);
});
buildDots(pageCount);
update();
startTimer();
}
function initTrustindexFallback() {
// Render fallback reviews immediately — the Trustindex script was removed for performance,
// so there's no point waiting for it.
document.querySelectorAll('.ti-widget').forEach(function (w) {
renderReviewFallback(w);
});
document.querySelectorAll('.elementor-shortcode').forEach(function (sc) {
var hasTi = sc.querySelector('[data-src*="trustindex"], .ti-widget');
if (!hasTi) return;
var widget = sc.closest('.elementor-widget');
if (widget && getComputedStyle(widget).display === 'none') return;
renderReviewFallback(sc);
});
}
function initMarqueesBuild() {
document.querySelectorAll('.bdt-marquee').forEach(function (m) {
if (m.dataset.msRailBuilt === '1') return;
var seen = {};
var sources = [];
m.querySelectorAll('img').forEach(function (img) {
var src = img.getAttribute('src');
if (!src || seen[src]) return;
seen[src] = true;
sources.push(src);
});
if (sources.length === 0) return;
m.dataset.msRailBuilt = '1';
var rail = document.createElement('div');
rail.className = 'ms-marquee-rail';
for (var pass = 0; pass < 2; pass++) {
sources.forEach(function (src) {
var img = document.createElement('img');
img.src = src;
img.loading = 'lazy';
img.alt = '';
rail.appendChild(img);
});
}
m.appendChild(rail);
});
}
function keepRailAlive() {
var tries = 0;
var timer = setInterval(function () {
tries++;
initMarqueesBuild();
if (tries > 8) clearInterval(timer);
}, 800);
}
function getAnimSettings(el) {
var raw = el.getAttribute('data-settings');
if (!raw) return {};
try { return JSON.parse(raw.replace(/&quot;/g, '"').replace(/&amp;/g, '&')); }
catch (e) {}
try { return JSON.parse(raw); } catch (e) { return {}; }
}
function initScrollAnimations() {
// Eerst alle elementor-invisible normaal zichtbaar (zoals voor de breakage)
document.querySelectorAll('.elementor-invisible').forEach(function (el) { el.classList.remove('elementor-invisible'); });
// Daarna SCOPED waterval-animatie voor 7 specifieke homepage element-IDs
initWaterfallAnimations();
return;
var SUPPORTED = {fadeIn:1, fadeInUp:1, fadeInDown:1, fadeInLeft:1, fadeInRight:1, slideInUp:1, slideInDown:1, slideInLeft:1, slideInRight:1, zoomIn:1, zoomInUp:1, bounceIn:1};
var vw = window.innerWidth || 1024;
var mode = vw <= 767 ? 'mobile' : (vw <= 1024 ? 'tablet' : 'desktop');
function parseSettings(el) {
var raw = el.getAttribute('data-settings');
if (!raw) return null;
try { return JSON.parse(raw.replace(/&quot;/g, '"')); } catch (e) { return null; }
}
function pickAnim(s) {
if (!s) return null;
// Elementor stores responsive overrides as _animation_tablet / _animation_mobile
var key = mode === 'mobile' ? '_animation_mobile' : (mode === 'tablet' ? '_animation_tablet' : '_animation');
var v = s[key] || s._animation;
if (!v || v === 'none' || v === '') return null;
return SUPPORTED[v] ? v : 'fadeInUp';
}
var pending = [];
document.querySelectorAll('.elementor-invisible').forEach(function (el) {
var s = parseSettings(el);
var anim = pickAnim(s);
if (!anim) {
// No animation requested → ms-anim-skip = instant visible (no flash via baseline-hide rule)
el.classList.add('ms-anim-skip');
return;
}
el.dataset.msAnim = anim;
var delay = s && (s._animation_delay || s._animation_delay_mobile || s._animation_delay_tablet);
if (delay) el.dataset.msAnimDelay = String(delay);
pending.push(el);
});
// FORCE-animate specific element-IDs that don't have _animation in data-settings
// Format: [eid, anim, delay-ms] — runup uses stagger 200-400ms voor cascade-feel
var FORCE_ANIM = [
// Top 3 USP icon-boxes — waterval: elk pas starten na vorige bijna klaar (1.8s duration, ~700ms tussentijd)
['41c0c334', 'fadeInUp', 400],
['a972fb5',  'fadeInUp', 1100],
['cc2edd4',  'fadeInUp', 1800],
// 4 "Wat ons uniek maakt" cards — zelfde waterval-feel
['860109e', 'fadeInUp', 300],
['b8ee83f', 'fadeInUp', 900],
['a885233', 'fadeInUp', 1500],
['cefac12', 'fadeInUp', 2100],
];
FORCE_ANIM.forEach(function (cfg) {
var el = document.querySelector('.elementor-element-' + cfg[0]);
if (!el) return;
// Skip als al een data-ms-anim heeft (al door polyfill verwerkt)
if (el.hasAttribute('data-ms-anim')) return;
el.dataset.msAnim = cfg[1] || 'fadeInUp';
if (cfg[2]) el.dataset.msAnimDelay = String(cfg[2]);
pending.push(el);
});
if (!pending.length || typeof IntersectionObserver === 'undefined') {
// Fallback: just show everything
pending.forEach(function (el) { el.classList.add('ms-anim-go'); });
return;
}
var observer = new IntersectionObserver(function (entries) {
entries.forEach(function (entry) {
if (!entry.isIntersecting) return;
var el = entry.target;
var d = parseInt(el.dataset.msAnimDelay || '0', 10);
if (d > 0) setTimeout(function () { el.classList.add('ms-anim-go'); }, d);
else el.classList.add('ms-anim-go');
observer.unobserve(el);
});
}, { rootMargin: '0px 0px -100px 0px', threshold: 0.1 });
pending.forEach(function (el) { observer.observe(el); });
// If element is already in viewport at load (above-the-fold), trigger immediately
requestAnimationFrame(function () {
pending.forEach(function (el) {
var rect = el.getBoundingClientRect();
if (rect.top < (window.innerHeight - 60) && rect.bottom > 0) {
var d = parseInt(el.dataset.msAnimDelay || '0', 10);
if (d > 0) setTimeout(function () { el.classList.add('ms-anim-go'); }, d);
else el.classList.add('ms-anim-go');
observer.unobserve(el);
}
});
});
// Safety-net: na 5s alles hidden-by-CSS forceren naar visible (mocht observer/JS falen op een edge-case)
setTimeout(function () {
document.querySelectorAll('.elementor-invisible:not(.ms-anim-skip):not(.ms-anim-go)').forEach(function (el) {
el.classList.add('ms-anim-skip');
});
}, 5000);
}
function initWaterfallAnimations() {
// Scoped naar 7 specifieke homepage element-IDs. Andere pagina's: geen match, geen effect.
// CSS verbergt deze elementen al by default; JS triggert .ms-anim-go op viewport-enter.
// 3e veld = true → triggert direct bij page-load (geen scroll nodig); false → wacht op viewport-enter
var WATERFALL = [
// Hero title — direct bij page-load
['fe3af22', 0, true],     // Hero titel "Perfect gladde muren en plafonds"
// USP-icons: links → midden → rechts, ALLEMAAL direct bij page-load
['41c0c334', 200, true],  // USP LINKS ("Vakmanschap")
['a972fb5',  340, true],  // USP MIDDEN ("Van A tot Z")
['cc2edd4',  480, true],  // USP RECHTS ("Heldere communicatie")
// Uniek cards: wachten tot ze in beeld scrollen (ruimere stagger voor een rustigere cascade)
['dbe1d46', 0,   false],
['6b0f285', 170, false],
['9ec4910', 340, false],
['5f075fa', 510, false],
// Diensten cards: 4 parent columns met foto+blok samen
['f7b37d4', 0,   false],
['e504656', 170, false],
['a6c5855', 340, false],
['38a7dde', 510, false],
// Overige homepage-secties: fade-up op scroll-into-view
['3cba875c', 0, false],   // Witte blok "Experts in wand- en plafondafwerking" (kolom binnen cce5420)
['1931bb4',  0, false],   // "15+ jaren ervaring"
['2c468eb',  0, false],   // "Partners waar we trots op zijn"
// 5656f939 ("Totaaloplossingen") OVERGESLAGEN — bevat de 4 uniek-cards die al apart animeren
// eef441e ("Onze diensten") OVERGESLAGEN — bevat de 4 diensten-cards die al apart animeren
['f9c0d1a',  0, false],   // "Onze stappen naar topkwaliteit"
['ffc6ad5',  0, false],   // "Benieuwd geworden?"
['e7409f1',  0, false],   // "De nieuwste updates"
['68e0906',  0, false],   // "Ons verhaal"
['214ebd3',  0, false],   // "Klanten aan het woord" (reviews)
['19941bd8', 0, false],   // "Neem contact op"
];
// Counter widgets — element-IDs die "15+" tekst hebben en moeten count-up animeren
var COUNT_UP_IDS = ['64ea1d60', '40d454a'];
var pending = [];
WATERFALL.forEach(function (cfg) {
var el = document.querySelector('.elementor-element-' + cfg[0]);
if (el) {
el.dataset.msAnimDelay = String(cfg[1]);
if (cfg[2]) el.dataset.msAnimImmediate = '1';
pending.push(el);
}
});
if (!pending.length) return;
function trigger(el) {
var d = parseInt(el.dataset.msAnimDelay || '0', 10);
if (d > 0) setTimeout(function () { el.classList.add('ms-anim-go'); }, d);
else el.classList.add('ms-anim-go');
}
if (typeof IntersectionObserver === 'undefined') {
pending.forEach(function (el) { el.classList.add('ms-anim-go'); });
return;
}
var observer = new IntersectionObserver(function (entries) {
entries.forEach(function (entry) {
if (!entry.isIntersecting) return;
trigger(entry.target);
observer.unobserve(entry.target);
});
}, { rootMargin: '0px 0px -120px 0px', threshold: 0.15 });
// PAGE-LOAD WACHT: 150ms — immediate elements firen direct, scroll elements wachten op viewport
setTimeout(function () {
pending.forEach(function (el) {
if (el.dataset.msAnimImmediate === '1') {
trigger(el);
} else {
observer.observe(el);
}
});
// Above-the-fold check voor scroll-elementen (niet voor immediate)
requestAnimationFrame(function () {
pending.forEach(function (el) {
if (el.dataset.msAnimImmediate === '1') return;
var rect = el.getBoundingClientRect();
if (rect.top < window.innerHeight - 120 && rect.bottom > 0) {
trigger(el);
observer.unobserve(el);
}
});
});
}, 150);
// Safety net: 6s force visible (mocht observer falen)
setTimeout(function () {
pending.forEach(function (el) {
if (!el.classList.contains('ms-anim-go')) el.classList.add('ms-anim-go');
});
}, 6000);
// Count-up animatie voor "15+" counter — setInterval-based (bestendig tegen frame-drops)
if (typeof IntersectionObserver !== 'undefined') {
var countObserver = new IntersectionObserver(function (entries) {
entries.forEach(function (entry) {
if (!entry.isIntersecting) return;
countObserver.unobserve(entry.target);
var el = entry.target.querySelector('.elementor-heading-title') || entry.target;
var origText = el.textContent.trim();
var match = origText.match(/(\d+)/);
if (!match) return;
var target = parseInt(match[1], 10);
if (!target || target > 999) return;
var suffix = origText.replace(/^\d+/, '');
var steps = 30;
var duration = 1500;
var current = 0;
var stepIdx = 0;
el.textContent = '0' + suffix;
var iv = setInterval(function () {
stepIdx++;
var p = stepIdx / steps;
var eased = 1 - Math.pow(1 - p, 3);
var val = Math.round(eased * target);
el.textContent = val + suffix;
if (stepIdx >= steps) {
el.textContent = target + suffix;
clearInterval(iv);
}
}, duration / steps);
});
}, { rootMargin: '0px 0px -100px 0px', threshold: 0.3 });
COUNT_UP_IDS.forEach(function (id) {
var el = document.querySelector('.elementor-element-' + id);
if (el) countObserver.observe(el);
});
}
}
function initFormSubmit() {
document.querySelectorAll('form.elementor-form').forEach(function (form) {
if (form.dataset.msSubmitApplied === '1') return;
form.dataset.msSubmitApplied = '1';
form.addEventListener('submit', async function (e) {
e.preventDefault();
var fd = new FormData(form);
var payload = { source: location.pathname };
var map = {
'form_fields[field_ac897d8]': 'soort_woning',
'form_fields[field_3028dcc]': 'm2',
'form_fields[field_bd15801]': 'pakket',
'form_fields[field_6b35b98]': 'startdatum',
'form_fields[name]':          'name',
'form_fields[field_45bf4d6]': 'woonplaats',
'form_fields[email]':         'telefoon', 
'form_fields[field_574f21f]': 'email',
};
fd.forEach(function (v, k) {
if (map[k]) payload[map[k]] = v;
});
var btn = form.querySelector('button[type="submit"], input[type="submit"]');
if (btn) { btn.disabled = true; if (btn.textContent) btn.textContent = 'Versturen…'; }
try {
var res = await fetch('/api/submit', {
method: 'POST',
headers: { 'Content-Type': 'application/json' },
body: JSON.stringify(payload),
}).then(function (r) { return r.json(); });
if (res.ok) {
window.location.href = '/bedankpagina/';
return;
} else {
alert('Er ging iets mis: ' + (res.error || 'onbekende fout'));
if (btn) { btn.disabled = false; }
}
} catch (err) {
alert('Netwerkfout: ' + err.message);
if (btn) { btn.disabled = false; }
}
});
});
}
// Getrouwe Elementor entrance-animaties — site-breed. Leest per element de in Elementor
// geconfigureerde _animation (fadeInUp/fadeInDown/slideInUp/…) + _animation_delay uit
// data-settings en speelt die af bij scroll-into-view (above-the-fold direct, zoals Elementor
// zelf op de live WordPress-site). Matcht het concept op concepten-mhsmedia.nl.
// De getunede homepage-waterval (21 IDs, data-ms-anim-delay) wordt overgeslagen om dubbele
// animatie te vermijden. data-anim + data-ms-anim escapen beide globale kill-rules; een
// keyframe-animatie wint van statische !important opacity-regels en loopt betrouwbaar.
function initEntranceAnimations() {
try {
if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
if (typeof IntersectionObserver === 'undefined') return;
if (!document.getElementById('wm-ent-css')) {
var st = document.createElement('style');
st.id = 'wm-ent-css';
// Keyframes 1-op-1 als Elementor/Animate.css op de referentie: 100% van de elementhoogte.
st.textContent =
'@keyframes wmEntFadeIn{from{opacity:0}to{opacity:1}}' +
'@keyframes wmEntFadeInUp{from{opacity:0;transform:translate3d(0,100%,0)}to{opacity:1;transform:none}}' +
'@keyframes wmEntFadeInDown{from{opacity:0;transform:translate3d(0,-100%,0)}to{opacity:1;transform:none}}' +
'@keyframes wmEntFadeInLeft{from{opacity:0;transform:translate3d(-100%,0,0)}to{opacity:1;transform:none}}' +
'@keyframes wmEntFadeInRight{from{opacity:0;transform:translate3d(100%,0,0)}to{opacity:1;transform:none}}' +
'@keyframes wmEntSlideInUp{from{opacity:0;transform:translate3d(0,100%,0)}to{opacity:1;transform:none}}' +
'@keyframes wmEntSlideInDown{from{opacity:0;transform:translate3d(0,-100%,0)}to{opacity:1;transform:none}}' +
'@keyframes wmEntZoomIn{from{opacity:0;transform:scale3d(.5,.5,.5)}to{opacity:1;transform:none}}';
(document.head || document.documentElement).appendChild(st);
}
var KF = { fadeIn:'wmEntFadeIn', fadeInUp:'wmEntFadeInUp', fadeInDown:'wmEntFadeInDown',
fadeInLeft:'wmEntFadeInLeft', fadeInRight:'wmEntFadeInRight', slideInUp:'wmEntSlideInUp',
slideInDown:'wmEntSlideInDown', zoomIn:'wmEntZoomIn', zoomInUp:'wmEntZoomIn' };
var vw = window.innerWidth || 1024;
var mode = vw <= 767 ? 'mobile' : (vw <= 1024 ? 'tablet' : 'desktop');
function pickAnim(s) {
if (!s) return null;
var v;
if (mode === 'mobile') v = s._animation_mobile;
else if (mode === 'tablet') v = s._animation_tablet;
if (v === undefined || v === '') v = s._animation;
if (!v || v === 'none') return null;
return KF[v] || 'wmEntFadeInUp';
}
function pickDelay(s) {
if (!s) return 0;
var d = s._animation_delay;
if (mode === 'mobile' && s._animation_delay_mobile != null) d = s._animation_delay_mobile;
else if (mode === 'tablet' && s._animation_delay_tablet != null) d = s._animation_delay_tablet;
d = parseInt(d, 10);
return isNaN(d) ? 0 : Math.max(0, Math.min(d, 2000));
}
var vh = window.innerHeight || 800;
var targets = [];
document.querySelectorAll('[data-settings]').forEach(function (el) {
if (el.dataset.wmEnt) return;
var raw = el.getAttribute('data-settings');
if (!raw || raw.indexOf('_animation') === -1) return;                 // snelle pre-filter
if (el.closest('#homeSection')) return;                               // hero (eigen Ken Burns)
if (el.hasAttribute('data-ms-anim-delay') || el.closest('[data-ms-anim-delay]')) return; // homepage-waterval
if (el.classList.contains('ms-anim-go') || el.classList.contains('ms-anim-skip')) return;
if (el.closest('header,footer,.elementor-location-header,.elementor-location-footer')) return;
if (el.closest('.swiper,.swiper-container,.slick-slider,.bdt-marquee,[data-aos],.ms-reviews-track,.ms-partners-track,[class*="bdt-anim"]')) return;
var s = getAnimSettings(el);
var name = pickAnim(s);
if (!name) return;
var r = el.getBoundingClientRect();
if (r.width === 0 && r.height === 0) return;
el._wmName = name;
el._wmDelay = pickDelay(s);
// duur zoals Elementor: animated-slow=2s (site-default), animated-fast=.75s, anders 1.25s
el._wmDur = el.classList.contains('animated-fast') ? '0.75s'
          : el.classList.contains('animated-slow') ? '2s' : '1.25s';
el._wmAbove = r.top < vh * 0.95 && r.bottom > 0;
targets.push(el);
});
if (!targets.length) return;
targets.forEach(function (el) {
el.dataset.wmEnt = '1';
el.setAttribute('data-anim', 'entrance');        // escape *:not([data-anim]) kill-rule
el.setAttribute('data-ms-anim', 'entrance');     // escape .animated:not([data-ms-anim]) rule
var s2 = el.style;
s2.animationName = el._wmName;
s2.animationDuration = el._wmDur || '1.25s';
s2.animationTimingFunction = 'ease';
s2.animationFillMode = 'both';
s2.animationPlayState = 'paused';                // toont 'from'-state (verborgen) tot trigger
s2.willChange = 'opacity, transform';
if (el._wmDelay) s2.animationDelay = (el._wmDelay / 1000) + 's';
});
function play(el) { el.style.animationPlayState = 'running'; }
var io = new IntersectionObserver(function (entries) {
entries.forEach(function (e) {
if (!e.isIntersecting) return;
io.unobserve(e.target);
play(e.target);
});
}, { rootMargin: '0px 0px -8% 0px', threshold: 0.12 });
targets.forEach(function (el) {
if (el._wmAbove) play(el);                        // above-the-fold → direct (zoals Elementor bij load)
else io.observe(el);
});
// Safety-net: na 6s alles afspelen (mocht de observer falen)
setTimeout(function () { targets.forEach(play); }, 6000);
} catch (e) {}
}
// Extra beweging — hover-microinteracties (kaarten liften, klikbare thumbnails zoomen) +
// entree voor de statische "Onze projecten"-sectie. Additief; raakt de getunede waterval niet.
// data-anim escaped de globale transition:none!important kill-rule (smooth hover beide kanten op).
function initHomeMotion() {
try {
if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
if (!document.getElementById('wm-motion-css')) {
var ms = document.createElement('style');
ms.id = 'wm-motion-css';
ms.textContent =
'@keyframes wmHomeUp{from{opacity:0;transform:translateY(40px)}to{opacity:1;transform:none}}' +
'html body .wm-hoverable{transition:transform .35s cubic-bezier(.22,.61,.36,1),box-shadow .35s cubic-bezier(.22,.61,.36,1)!important}' +
'html body .wm-hoverable:hover{transform:translateY(-7px)!important}' +
'html body .wm-card.wm-hoverable:hover{box-shadow:0 18px 42px rgba(10,30,60,.13)!important}' +
'html body .wm-zoom{overflow:hidden!important}' +
'html body .wm-zoom img{transition:transform .6s cubic-bezier(.22,.61,.36,1)!important;will-change:transform}' +
'html body .wm-zoom:hover img{transform:scale(1.06)!important}';
(document.head || document.documentElement).appendChild(ms);
}
var skip = 'header,footer,.elementor-location-header,.elementor-location-footer';
// kaarten liften
document.querySelectorAll('.elementor-widget-icon-box,.elementor-widget-image-box,.elementor-widget-call-to-action').forEach(function (el) {
if (el.dataset.wmHover || el.closest(skip)) return;
el.dataset.wmHover = '1';
el.setAttribute('data-anim', 'hover');
el.setAttribute('data-ms-anim', 'hover');
el.classList.add('wm-hoverable', 'wm-card');
});
// klikbare image-thumbnails zoomen
document.querySelectorAll('.elementor-widget-image').forEach(function (el) {
if (el.dataset.wmHover || !el.querySelector('img')) return;
if (el.closest(skip + ',.bdt-marquee,.ms-partners-track,.ms-reviews-track')) return;
if (!el.closest('a') && !el.querySelector('a')) return;   // alleen klikbare thumbnails
el.dataset.wmHover = '1';
el.setAttribute('data-anim', 'hover');
el.classList.add('wm-zoom');
});
// statische "Onze projecten"-sectie laten infaden met lichte stagger
if (typeof IntersectionObserver !== 'undefined') {
var proj = document.querySelector('.elementor-element-a77d7f4');
if (proj && !proj.dataset.wmHomeDone) {
proj.dataset.wmHomeDone = '1';
var items = [].slice.call(proj.querySelectorAll('.elementor-widget-heading,.elementor-widget-text-editor,.elementor-widget-button,.elementor-widget-loop-grid,.elementor-widget-image')).slice(0, 10);
items.forEach(function (el, i) {
el.setAttribute('data-anim', 'entrance');
el.setAttribute('data-ms-anim', 'entrance');
var s = el.style;
s.animationName = 'wmHomeUp'; s.animationDuration = '0.7s';
s.animationTimingFunction = 'cubic-bezier(.22,.61,.36,1)';
s.animationFillMode = 'both'; s.animationPlayState = 'paused';
s.animationDelay = (i * 0.12) + 's'; s.willChange = 'opacity, transform';
});
var go = function () { items.forEach(function (el) { el.style.animationPlayState = 'running'; }); };
var pio = new IntersectionObserver(function (entries) {
entries.forEach(function (e) { if (e.isIntersecting) { go(); pio.disconnect(); } });
}, { rootMargin: '0px 0px -10% 0px', threshold: 0.05 });
pio.observe(proj);
setTimeout(go, 6000);
}
}
} catch (e) {}
}
// Soepelere entree voor de uniek- + diensten-kaarten. De uniek-kaarten hadden .animated-slow
// ZONDER data-ms-anim, waardoor de baseline-regel .animated-slow:not([data-ms-anim]) hun
// transition op none zette → abrupt snappen. data-ms-anim (+ data-anim) heft dat op; de eigen
// CSS-override geeft alle 8 kaarten een langere, vloeiende rise-in (combineert met de grotere
// stagger-delays in de WATERFALL-config hierboven). Moet vóór de 150ms waterval-trigger draaien.
function initCardEntrance() {
try {
if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
var ids = ['dbe1d46','6b0f285','9ec4910','5f075fa','f7b37d4','e504656','a6c5855','38a7dde'];
ids.forEach(function (id) {
var el = document.querySelector('.elementor-element-' + id);
if (el) { el.setAttribute('data-anim', 'card'); el.setAttribute('data-ms-anim', 'card'); }
});
if (!document.getElementById('wm-card-css')) {
var base = ids.map(function (id) { return 'html body .elementor-element-' + id; }).join(',');
var hidden = ids.map(function (id) { return 'html body .elementor-element-' + id + ':not(.ms-anim-go)'; }).join(',');
var st = document.createElement('style');
st.id = 'wm-card-css';
// Zelfde gevoel als de referentie: animated-slow (2s) + fadeInUp (100% van de elementhoogte), ease.
st.textContent =
base + '{transition:opacity 2s ease,transform 2s ease!important;will-change:opacity,transform}' +
hidden + '{opacity:0!important;transform:translate3d(0,100%,0)!important}';
(document.head || document.documentElement).appendChild(st);
}
} catch (e) {}
}
// Footer-contacticonen → dunne outline-stijl (zoals de referentie): handset-telefoon,
// envelope-outline, locatie-pin. Behoudt per icoon de huidige kleur (leest de fill uit).
function initFooterContactIcons() {
try {
var footer = document.querySelector('.elementor-location-footer, [data-elementor-type="footer"], footer');
if (!footer) return;
var S = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
var MAIL  = '<svg ' + S + '><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 5L2 7"/></svg>';
var PHONE = '<svg ' + S + '><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/></svg>';
var PIN   = '<svg ' + S + '><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>';
if (!document.getElementById('wm-footer-ico-css')) {
var st = document.createElement('style');
st.id = 'wm-footer-ico-css';
st.textContent = '.wm-footer-ico{display:inline-flex;align-items:center;justify-content:center;line-height:0}'
+ 'html body .wm-footer-ico svg{width:24px!important;height:24px!important;display:block}';
(document.head || document.documentElement).appendChild(st);
}
footer.querySelectorAll('.elementor-icon-list-icon').forEach(function (span) {
if (span.dataset.wmFico) return;
var cur = span.querySelector('svg,i');
if (!cur) return;
var cls = cur.getAttribute('class') || '';
var svg = /phone/.test(cls) ? PHONE
        : /envelope|mail/.test(cls) ? MAIL
        : /map-marker|map-pin|marker|location/.test(cls) ? PIN : null;
if (!svg) return;
// huidige kleur overnemen (fill van de oude svg, of color)
var col = '';
try { var ccs = getComputedStyle(cur); col = (ccs.fill && ccs.fill !== 'none' && ccs.fill !== 'rgb(0, 0, 0)') ? ccs.fill : ccs.color; } catch (e) {}
span.dataset.wmFico = '1';
span.classList.add('wm-footer-ico');
span.innerHTML = svg;
var ns = span.querySelector('svg');
if (ns && col) ns.style.stroke = col;
});
} catch (e) {}
}
function bootAll() {
init(); initVideos(); initSlideshow(); initNavMenu(); initCounters();
initServiceCardLinks(); initTrustindexFallback();
initMarqueesBuild();
keepRailAlive();
initScrollAnimations();
initCardEntrance();
initEntranceAnimations();
initHomeMotion();
initFooterContactIcons();
initFormSubmit();
}
if (document.readyState === 'loading') {
document.addEventListener('DOMContentLoaded', bootAll);
} else {
bootAll();
}
window.addEventListener('load', function () {
setTimeout(bootAll, 50);
setTimeout(bootAll, 500);
});
})();


/* a11y: ensure anchors with only icon/SVG have an aria-label */
(function(){
function label(){
document.querySelectorAll('a').forEach(function(a){
if (a.getAttribute('aria-label')) return;
var text = (a.textContent || '').trim();
if (text.length > 0) return;
var href = a.getAttribute('href') || '';
var alt = null;
if (/facebook/i.test(href)) alt = 'Facebook';
else if (/instagram/i.test(href)) alt = 'Instagram';
else if (/tiktok/i.test(href)) alt = 'TikTok';
else if (/wa\.me|whatsapp/i.test(href)) alt = 'WhatsApp';
else if (/^tel:/i.test(href)) alt = 'Bel ' + href.replace(/^tel:/i,'');
else if (/^mailto:/i.test(href)) alt = 'Mail ' + href.replace(/^mailto:/i,'');
else if (/youtu/i.test(href)) alt = 'YouTube';
else if (/linkedin/i.test(href)) alt = 'LinkedIn';
if (alt) a.setAttribute('aria-label', alt);
});
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', label);
else label();
})();

/* ElementsKit accordion polyfill (FAQ widgets op stukadoor-* pagina's) */
(function () {
  function initFaqAccordion() {
    document.querySelectorAll('[data-ekit-toggle="collapse"]').forEach(function (toggler) {
      if (toggler.dataset.msEkitInit === '1') return;
      toggler.dataset.msEkitInit = '1';
      toggler.addEventListener('click', function (e) {
        e.preventDefault();
        var sel = toggler.getAttribute('data-target') || toggler.getAttribute('href');
        if (!sel) return;
        var target = document.querySelector(sel);
        if (!target) return;
        var container = toggler.closest('.elementskit-accordion');
        var isOpen = target.classList.contains('show');
        if (container) {
          container.querySelectorAll('.collapse.show').forEach(function (other) {
            if (other === target) return;
            other.classList.remove('show');
            var otherSel = '[data-target="#' + other.id + '"], [href="#' + other.id.toLowerCase() + '"]';
            container.querySelectorAll(otherSel).forEach(function (t) {
              t.classList.add('collapsed');
              t.setAttribute('aria-expanded', 'false');
            });
            var otherCard = other.closest('.elementskit-card');
            if (otherCard) otherCard.classList.remove('active');
          });
        }
        if (isOpen) {
          target.classList.remove('show');
          toggler.classList.add('collapsed');
          toggler.setAttribute('aria-expanded', 'false');
        } else {
          target.classList.add('show');
          toggler.classList.remove('collapsed');
          toggler.setAttribute('aria-expanded', 'true');
        }
        var card = toggler.closest('.elementskit-card');
        if (card) card.classList.toggle('active', !isOpen);
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initFaqAccordion);
  else initFaqAccordion();
})();

/* BDT (Element-Pack) accordion polyfill (FAQ op contact + andere bdt-ep-accordion widgets) */
(function () {
  function initBdtAccordion() {
    document.querySelectorAll('.bdt-ep-accordion-title').forEach(function (title) {
      if (title.dataset.msBdtInit === '1') return;
      title.dataset.msBdtInit = '1';
      var item = title.closest('.bdt-ep-accordion-item');
      if (!item) return;
      title.setAttribute('role', 'button');
      title.setAttribute('tabindex', '0');
      title.setAttribute('aria-expanded', item.classList.contains('bdt-open') ? 'true' : 'false');
      function toggle() {
        var container = item.closest('.bdt-ep-accordion');
        var isOpen = item.classList.contains('bdt-open');
        // One-at-a-time accordion behavior (standard FAQ UX)
        if (container) {
          container.querySelectorAll('.bdt-ep-accordion-item.bdt-open').forEach(function (other) {
            if (other === item) return;
            other.classList.remove('bdt-open');
            var t = other.querySelector('.bdt-ep-accordion-title');
            if (t) t.setAttribute('aria-expanded', 'false');
          });
        }
        item.classList.toggle('bdt-open', !isOpen);
        title.setAttribute('aria-expanded', !isOpen ? 'true' : 'false');
      }
      title.addEventListener('click', function (e) { e.preventDefault(); toggle(); });
      title.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initBdtAccordion);
  else initBdtAccordion();
})();

/* === First-party traffic tracker (Wandmeesters analytics) === */
(function () {
  var TRACK_URL = '/api/track/';
  function send(payload) {
    try {
      var json = JSON.stringify(payload);
      if (navigator.sendBeacon) {
        navigator.sendBeacon(TRACK_URL, new Blob([json], { type: 'application/json' }));
      } else {
        fetch(TRACK_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: json, keepalive: true }).catch(function () {});
      }
    } catch (e) {}
  }

  function trackPageView() {
    var path = location.pathname || '/';
    send({ type: 'pageview', path: path });
  }

  function classifyAnchor(a) {
    if (!a || !a.href) return null;
    var href = a.getAttribute('href') || '';
    if (href.indexOf('mailto:') === 0) return { kind: 'email', target: href.slice(7).split('?')[0] };
    if (href.indexOf('tel:') === 0) return { kind: 'phone', target: href.slice(4) };
    if (/share\.google|google\.com\/maps|maps\.google|goo\.gl\/maps/.test(href)) return { kind: 'route', target: a.href };
    if (a.hostname && a.hostname !== location.hostname && /^https?:/.test(a.protocol)) return { kind: 'external', target: a.href };
    return null;
  }

  function bindClicks() {
    document.addEventListener('click', function (e) {
      var a = e.target && e.target.closest ? e.target.closest('a') : null;
      if (!a) return;
      var info = classifyAnchor(a);
      if (info) send({ type: 'click', kind: info.kind, target: info.target });
      // Form-knop intent ("Verstuur" / submit-button) wordt al getrackt via /api/submit success
    }, true);
  }

  function trackFormOpen() {
    // First time scroll into view → form_open event
    var form = document.querySelector('form.elementor-form');
    if (!form) return;
    var fired = false;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting && !fired) {
          fired = true;
          send({ type: 'click', kind: 'form_open', target: location.pathname });
          io.disconnect();
        }
      });
    }, { threshold: 0.2 });
    io.observe(form);
  }

  function init() {
    trackPageView();
    bindClicks();
    trackFormOpen();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

/* === Mobile phone display: vervang "+31 6 ..." door "06 ..." op mobile (<768px) === */
(function () {
  var MOBILE_QUERY = '(max-width: 768px)';
  var mq = window.matchMedia(MOBILE_QUERY);
  var PHONE_REGEX = /\+31[\s\-]?6[\s\-]?(\d{2}[\s\-]?\d{3}[\s\-]?\d{3,4}|\d{8,9})/g;
  var PHONE_REGEX_COMPACT = /\+316(\d{8,9})/g;

  function formatToMobile(text) {
    return text
      .replace(PHONE_REGEX, '06 $1')
      .replace(PHONE_REGEX_COMPACT, '06$1');
  }

  function processNode(el) {
    if (!el || el.dataset === undefined) return;
    if (el.tagName === 'A' && (el.getAttribute('href') || '').toLowerCase().indexOf('tel:') === 0) {
      // tel: link → ALLEEN de tekst-nodes in de link herschrijven.
      // NIET el.textContent zetten: dat vervangt alle children door één tekstnode
      // en verwijdert daarmee het telefoon-icoon (<svg>) uit de link.
      walkTextNodes(el);
    }
  }

  function walkTextNodes(root) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    var node;
    var changed = [];
    while ((node = walker.nextNode())) {
      var t = node.textContent;
      if (t.indexOf('+31 6') !== -1 || t.indexOf('+316') !== -1 || t.indexOf('+31-6') !== -1) {
        if (node._phoneOrig === undefined) node._phoneOrig = t;
        node.textContent = mq.matches ? formatToMobile(node._phoneOrig) : node._phoneOrig;
        changed.push(node);
      }
    }
    return changed;
  }

  function applyPhoneFormat() {
    // 1) Alle tel: links
    document.querySelectorAll('a[href^="tel:"], a[href*="tel:"]').forEach(processNode);
    // 2) Text-nodes met +31 6 erin (header bar, contact section, footer, etc.)
    walkTextNodes(document.body);
  }

  function init() {
    applyPhoneFormat();
    // Bij rotatie/resize de mobile-toggle volgen
    if (mq.addEventListener) mq.addEventListener('change', applyPhoneFormat);
    else if (mq.addListener) mq.addListener(applyPhoneFormat);
    // Re-apply als DOM-elementen later worden toegevoegd (bv door andere scripts)
    var ro = new MutationObserver(function (mutations) {
      var needsApply = false;
      mutations.forEach(function (m) {
        m.addedNodes && m.addedNodes.forEach(function (n) {
          if (n.nodeType === 1) needsApply = true;
        });
      });
      if (needsApply) setTimeout(applyPhoneFormat, 50);
    });
    ro.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else { init(); }
})();
