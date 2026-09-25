'use strict';
/* Tradebot Dashboard. Aufbau: Helfer · Formatierung · Charts · Router · Seiten. */

// ================================================================= Helfer
const $ = (sel, root = document) => root.querySelector(sel);
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'style') e.style.cssText = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e[k] = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) { if (kid == null || kid === false) continue; e.append(kid.nodeType ? kid : document.createTextNode(String(kid))); }
  return e;
}
const svgIcon = (d) => { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '1.8'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round'); s.innerHTML = d; return s; };
async function api(path) { const r = await fetch('/api/' + path); if (!r.ok) throw new Error(path + ': ' + r.status); return r.json(); }
async function post(path, body) {
  const r = await fetch('/api/' + path, { method: 'POST', headers: { 'X-Requested-With': 'tradebot-dashboard', 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) { let msg = r.status; try { msg = (await r.json()).detail || msg; } catch (e) {} throw new Error(msg); }
  return r.json();
}
const store = {
  get(k, d) { try { const v = localStorage.getItem('tb.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('tb.' + k, JSON.stringify(v)); } catch (e) {} },
};

// ================================================================= Formatierung
const NF = {}; const nf = (d) => (NF[d] ||= new Intl.NumberFormat('de-DE', { minimumFractionDigits: d, maximumFractionDigits: d }));
const num = (x, d = 2) => (x == null || Number.isNaN(x) ? '–' : nf(d).format(x));
const money = (x, d) => (x == null ? '–' : nf(d ?? (Math.abs(x) >= 1000 ? 0 : 2)).format(x));
const price = (x) => (x == null ? '–' : nf(x < 1 ? 4 : x < 100 ? 3 : 2).format(x));
const pct = (x, d = 1, sign = true) => (x == null || Number.isNaN(x) ? '–' : (sign && x > 0 ? '+' : '') + nf(d).format(x * 100) + ' %');
const signed = (x, d = 2) => (x == null ? '–' : (x > 0 ? '+' : '') + nf(d).format(x));
const tone = (x) => (x == null || x === 0 ? '' : x > 0 ? 'up' : 'down');
const dtm = (ms) => (ms ? new Date(ms).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }) : '–');
const dday = (ms) => (ms ? new Date(ms).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit' }) : '–');
const ago = (s) => (s == null ? '–' : s < 90 ? Math.round(s) + ' s' : s < 5400 ? Math.round(s / 60) + ' min' : s < 172800 ? num(s / 3600, 1) + ' h' : Math.round(s / 86400) + ' Tage');
const days = (d) => (d == null ? '–' : d < 1 ? Math.round(d * 24) + ' h' : num(d, 1) + ' T');
const coin = (s) => s.replace('USDT', '');
const STRAT = { trend: 'Trend-Ausbruch', meanrev: 'Mean Reversion' };
const IVL = { '15m': '15 Minuten', '1h': '1 Stunde', '4h': '4 Stunden', '1d': '1 Tag' };

// ================================================================= Bausteine
const info = (text) => (text ? h('i', { class: 'info', 'data-tip': text, tabindex: 0 }, 'i') : null);
const badge = (text, kind = '', dot = false) => h('span', { class: 'badge ' + kind }, dot ? h('span', { class: 'dot' }) : null, text);
const card = (title, body, opts = {}) => h('section', { class: 'card ' + (opts.class || '') },
  title ? h('div', { class: 'hd' }, h('h2', null, title), opts.tip ? info(opts.tip) : null, opts.sub ? h('span', { class: 'sub' }, opts.sub) : null, h('span', { class: 'grow' }), opts.actions || null) : null,
  h('div', { class: 'bd' + (opts.flush ? ' flush' : '') }, body), opts.foot ? h('div', { class: 'ft' }, opts.foot) : null);
const kpi = (label, value, sub, cls = '', tip = null, flat = false) => h('div', { class: 'kpi' + (flat ? ' flat' : '') }, h('div', { class: 'l' }, label, info(tip)), h('div', { class: 'v ' + cls }, value), sub ? h('div', { class: 's' }, sub) : null);
const empty = (t) => h('div', { class: 'empty' }, t);
function seg(options, value, onChange) {
  const el = h('div', { class: 'seg' });
  for (const [v, label] of options) el.append(h('button', { type: 'button', class: String(v) === String(value) ? 'on' : '', onclick: () => onChange(v) }, label));
  return el;
}
function statusBadge(w) { return w.paused ? badge('pausiert', 'warn', true) : badge('aktiv', 'ok', true); }
function M(key) { return (META.metrics[key] || {}).what; }

/** Tabelle mit sortierbaren Spalten. cols: {h, key, a:'l', tip, render(row), sort(row)} */
function table(cols, rows, opts = {}) {
  if (!rows.length) return empty(opts.empty || 'Keine Daten.');
  let sortKey = opts.sortKey || null, dir = opts.dir || -1;
  const tbody = h('tbody');
  const head = h('tr', null, cols.map(c => {
    const th = h('th', { class: (c.a === 'l' ? 'l ' : '') + (c.sort ? 'sortable' : '') }, c.h, c.tip ? h('span', { style: 'margin-left:4px;display:inline-flex;vertical-align:-2px' }, info(c.tip)) : null);
    if (c.sort) th.onclick = () => { dir = sortKey === c.h ? -dir : -1; sortKey = c.h; paint(); };
    return th;
  }));
  function paint() {
    let list = rows.slice();
    const sc = cols.find(c => c.h === sortKey);
    if (sc) list.sort((a, b) => { const x = sc.sort(a), y = sc.sort(b); return (x == null) - (y == null) || (x < y ? -1 : x > y ? 1 : 0) * dir; });
    head.querySelectorAll('th').forEach((th, i) => { th.querySelector('.arr')?.remove(); if (cols[i].h === sortKey) th.append(h('span', { class: 'arr' }, dir < 0 ? '↓' : '↑')); });
    tbody.replaceChildren(...list.map(r => {
      const tr = h('tr', { class: opts.onRow ? 'click' : '' }, cols.map(c => { const v = c.render(r); const td = h('td', { class: (c.a === 'l' ? 'l ' : '') + (c.wrap ? 'wrap ' : '') + (c.cls ? c.cls(r) : '') }); td.append(v == null ? '–' : v.nodeType ? v : String(v)); return td; }));
      if (opts.onRow) tr.onclick = (ev) => { if (!ev.target.closest('a,button')) opts.onRow(r); };
      return tr;
    }));
  }
  paint();
  return h('div', { class: 'tbl', style: opts.maxH ? `max-height:${opts.maxH}px` : '' }, h('table', null, h('thead', null, head), tbody));
}

// Tooltip für alle [data-tip]
const tip = $('#tip');
function showTip(t) { const text = t.getAttribute('data-tip'); if (!text) return; tip.textContent = text; tip.classList.add('show'); const r = t.getBoundingClientRect(); const w = Math.min(320, window.innerWidth - 24); tip.style.maxWidth = w + 'px'; const tw = tip.offsetWidth, th = tip.offsetHeight; let x = r.left + r.width / 2 - tw / 2; x = Math.max(12, Math.min(x, window.innerWidth - tw - 12)); let y = r.top - th - 8; if (y < 8) y = r.bottom + 8; tip.style.left = x + 'px'; tip.style.top = y + 'px'; }
document.addEventListener('mouseover', (e) => { const t = e.target.closest('[data-tip]'); if (t) showTip(t); });
document.addEventListener('mouseout', (e) => { if (e.target.closest('[data-tip]')) tip.classList.remove('show'); });
document.addEventListener('focusin', (e) => { const t = e.target.closest('[data-tip]'); if (t) showTip(t); });
document.addEventListener('focusout', () => tip.classList.remove('show'));

// ================================================================= Charts
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const alpha = (hex, a) => { const x = hex.replace('#', ''); const n = parseInt(x.length === 3 ? x.split('').map(c => c + c).join('') : x, 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };
const SERIES = () => [1, 2, 3, 4, 5, 6, 7, 8].map(i => css('--s' + i));
let CHARTS = [], LINKS = {};
function disposeCharts() { CHARTS.forEach(c => { try { c.remove(); } catch (e) {} }); CHARTS = []; LINKS = {}; }
const toSec = (ms) => Math.floor(ms / 1000);
function toSeries(points, tf) { const m = new Map(); for (const [t, v] of points) if (v != null) m.set(toSec(t), tf ? tf(v) : v); return [...m].sort((a, b) => a[0] - b[0]).map(([time, value]) => ({ time, value })); }
const fmtTime = (t) => new Date(t * 1000).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
function baseChart(el, fmt) {
  const c = LightweightCharts.createChart(el, {
    layout: { background: { type: 'solid', color: 'transparent' }, textColor: css('--ink-3'), fontFamily: css('--font'), fontSize: 11, attributionLogo: false },
    grid: { vertLines: { visible: false }, horzLines: { color: css('--grid') } },
    rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.1, bottom: 0.08 } }, timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 2 },
    crosshair: { mode: 0, vertLine: { color: css('--line-strong'), width: 1, style: 3, labelBackgroundColor: css('--surface-3') }, horzLine: { color: css('--line-strong'), width: 1, style: 3, labelBackgroundColor: css('--surface-3') } },
    localization: { locale: 'de-DE', priceFormatter: fmt || ((v) => nf(1).format(v * 100) + ' %'), timeFormatter: fmtTime },
    autoSize: true, handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false }, handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true },
  });
  CHARTS.push(c);
  return c;
}
/** Tooltip am Mauszeiger, weicht an den Rändern aus. */
function placeTip(xh, box, point) {
  xh.style.display = 'block';
  const w = xh.offsetWidth, hgt = xh.offsetHeight, W = box.clientWidth;
  let x = point.x + 16; if (x + w > W - 60) x = point.x - w - 16; if (x < 4) x = 4;
  let y = point.y - hgt / 2; y = Math.max(4, Math.min(y, box.clientHeight - hgt - 28));
  xh.style.left = x + 'px'; xh.style.top = y + 'px';
}
function download(name, href) { const a = h('a', { href, download: name }); document.body.append(a); a.click(); a.remove(); }
function chartPng(c, name) {
  const src = c.takeScreenshot(), out = document.createElement('canvas');
  out.width = src.width; out.height = src.height;
  const g = out.getContext('2d'); g.fillStyle = css('--surface'); g.fillRect(0, 0, out.width, out.height); g.drawImage(src, 0, 0);
  download(name + '.png', out.toDataURL('image/png'));
}
function seriesCsv(series, name, valueFmt = (v) => v) {
  const times = [...new Set(series.flatMap(s => s.data.map(p => p[0])))].sort((a, b) => a - b);
  const maps = series.map(s => new Map(s.data.map(p => [p[0], p[1]])));
  const rows = [['Zeit', ...series.map(s => s.name)].join(';'), ...times.map(t => [new Date(t).toISOString(), ...maps.map(m => m.has(t) ? String(valueFmt(m.get(t))).replace('.', ',') : '')].join(';'))];
  download(name + '.csv', URL.createObjectURL(new Blob(['﻿' + rows.join('\n')], { type: 'text/csv;charset=utf-8' })));
}
const RANGES = [['1M', 30], ['3M', 91], ['6M', 182], ['1J', 365], ['Alles', 0]];
/** Werkzeugleiste: Zeitraum, Log-Skala, Vollbild, PNG, CSV. */
function chartTools(o) {
  const bar = h('div', { class: 'ctools' });
  const spanDays = o.spanDays || 0;
  if (o.range !== false && spanDays > 20) {
    const rs = RANGES.filter(([, d]) => d === 0 || d < spanDays * 0.9);
    const segEl = seg(rs.map(([l, d]) => [d, l]), 0, () => {});
    segEl.querySelectorAll('button').forEach((b, i) => b.onclick = () => {
      segEl.querySelectorAll('button').forEach(x => x.classList.remove('on')); b.classList.add('on');
      const d = rs[i][1], c = o.chart(); if (!c) return;
      if (!d) c.timeScale().fitContent(); else c.timeScale().setVisibleRange({ from: o.lastTime() - d * 86400, to: o.lastTime() + 3600 });
    });
    bar.append(segEl);
  }
  bar.append(h('span', { class: 'grow' }));
  if (o.onLog) {
    const btn = h('button', { class: 'btn sm ghost', type: 'button', 'data-tip': 'Logarithmische Skala: gleiche prozentuale Bewegungen sind gleich hoch. Hilfreich bei langen Zeiträumen mit starkem Wachstum.' }, 'Log');
    btn.onclick = () => { btn.classList.toggle('on'); o.onLog(btn.classList.contains('on')); };
    bar.append(btn);
  }
  bar.append(h('button', { class: 'btn sm ghost', type: 'button', 'data-tip': 'Zoom und Verschiebung zurücksetzen', onclick: () => o.chart()?.timeScale().fitContent() }, '⟲'));
  if (o.csv) bar.append(h('button', { class: 'btn sm ghost', type: 'button', 'data-tip': 'Daten als CSV herunterladen (für Excel)', onclick: o.csv }, 'CSV'));
  bar.append(h('button', { class: 'btn sm ghost', type: 'button', 'data-tip': 'Chart als Bild (PNG) herunterladen', onclick: () => chartPng(o.chart(), o.name || 'chart') }, 'PNG'));
  bar.append(h('button', { class: 'btn sm ghost', type: 'button', 'data-tip': 'Vollbild (Esc beendet)', onclick: () => { const el = o.fullscreenEl(); document.fullscreenElement ? document.exitFullscreen() : el.requestFullscreen?.(); } }, '⛶'));
  return bar;
}
/** Charts einer Gruppe teilen Zeitausschnitt und Fadenkreuz. */
function link(group, entry) {
  if (!group) return;
  const list = (LINKS[group] ||= []); list.push(entry);
  const lock = (list.lock ||= { range: false, xh: false });
  entry.chart.timeScale().subscribeVisibleTimeRangeChange((r) => {
    if (lock.range || !r) return; lock.range = true;
    for (const o of list) if (o !== entry) { try { o.chart.timeScale().setVisibleRange(r); } catch (e) {} }
    lock.range = false;
  });
  entry.chart.subscribeCrosshairMove((p) => {
    if (lock.xh) return; lock.xh = true;
    for (const o of list) if (o !== entry) {
      try {
        if (!p.time || !p.point) o.chart.clearCrosshairPosition();
        else { const v = o.valueAt(p.time); if (v != null) o.chart.setCrosshairPosition(v, p.time, o.series); }
      } catch (e) {}
    }
    lock.xh = false;
  });
}
/** Linienchart mit Legende, Tooltip und Werkzeugleiste. series: [{name, color, data:[[ms, wert]], dashed, area, fill}] */
function lineChart(series, opts = {}) {
  const wrap = h('div', { class: 'chartwrap' }), legend = h('div', { class: 'legend' }), box = h('div', { class: 'chart ' + (opts.size || '') }), xh = h('div', { class: 'xhair' });
  box.append(xh);
  const fmt = opts.fmt || ((v) => pct(v, 1));
  const points = series.reduce((n, s) => n + s.data.length, 0);
  if (opts.emptyBelow && series.every(s => s.data.length < opts.emptyBelow)) { wrap.append(empty(opts.empty || 'Noch zu wenige Datenpunkte für einen Verlauf.')); return { node: wrap, after: () => {} }; }
  const hidden = new Set(opts.hidden || []);
  const allT = series.flatMap(s => s.data.map(p => p[0])), t0 = Math.min(...allT), t1 = Math.max(...allT);
  let chart = null, refs = [], logMode = false, zero = null;
  const tf = () => (logMode ? (v) => 1 + v : null);
  const tools = opts.tools === false ? null : chartTools({ chart: () => chart, lastTime: () => toSec(t1), spanDays: points ? (t1 - t0) / 864e5 : 0, name: opts.name,
    fullscreenEl: () => wrap, csv: () => seriesCsv(series, opts.name || 'daten', (v) => opts.csvFmt ? opts.csvFmt(v) : v),
    onLog: opts.logable === false ? null : (on) => { logMode = on; chart.priceScale('right').applyOptions({ mode: on ? 1 : 0 }); chart.applyOptions({ localization: { priceFormatter: on ? (v) => nf(1).format((v - 1) * 100) + ' %' : (opts.axisFmt || ((v) => nf(1).format(v * 100) + ' %')) } }); series.forEach((s, i) => refs[i].setData(toSeries(s.data, tf()))); zero?.applyOptions({ price: on ? 1 : 0 }); } });
  if (tools) wrap.append(tools);
  if (series.length > 1 || opts.legend) wrap.append(legend);
  wrap.append(box);
  const after = () => {
    const c = chart = baseChart(box, opts.axisFmt);
    refs = series.map(s => {
      const l = s.area
        ? c.addBaselineSeries({ baseValue: { type: 'price', price: 0 }, topLineColor: s.color, bottomLineColor: s.color, topFillColor1: 'transparent', topFillColor2: 'transparent', bottomFillColor1: s.fill || 'transparent', bottomFillColor2: s.fill || 'transparent', lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerRadius: 4 })
        : c.addLineSeries({ color: s.color, lineWidth: s.width || 2, lineStyle: s.dashed ? 2 : 0, priceLineVisible: false, lastValueVisible: !!opts.lastValue, crosshairMarkerRadius: 4, crosshairMarkerBorderColor: css('--surface') });
      l.setData(toSeries(s.data));
      if (hidden.has(s.name)) l.applyOptions({ visible: false });
      return l;
    });
    if (opts.zeroLine !== false && !series.some(s => s.area)) zero = refs[0]?.createPriceLine({ price: 0, color: css('--line-strong'), lineWidth: 1, lineStyle: 0, axisLabelVisible: false });
    series.forEach((s, i) => {
      const last = s.data.length ? s.data[s.data.length - 1][1] : null;
      const it = h('span', { class: 'it' + (hidden.has(s.name) ? ' off' : ''), 'data-tip': 'Klick blendet die Linie ein oder aus' }, h('span', { class: 'sw' + (s.dashed ? ' dashed' : ''), style: `--c:${s.color}` }), s.name, h('b', null, fmt(last)));
      it.onclick = () => { const vis = it.classList.toggle('off'); refs[i].applyOptions({ visible: !vis }); vis ? hidden.add(s.name) : hidden.delete(s.name); opts.onToggle?.(s.name, vis); };
      legend.append(it);
    });
    c.subscribeCrosshairMove((p) => {
      if (!p.time || !p.point || p.point.x < 0) { xh.style.display = 'none'; return; }
      const rows = series.map((s, i) => { const d = p.seriesData.get(refs[i]); return d && refs[i].options().visible ? h('div', { class: 'r' }, h('span', null, h('span', { class: 'sw' + (s.dashed ? ' dashed' : ''), style: `--c:${s.color}` }), s.name), h('b', null, fmt(logMode && !s.area ? d.value - 1 : d.value))) : null; }).filter(Boolean);
      if (!rows.length) { xh.style.display = 'none'; return; }
      xh.replaceChildren(h('div', { class: 't' }, fmtTime(p.time)), ...rows);
      placeTip(xh, box, p.point);
    });
    const map0 = new Map(toSeries(series[0].data).map(d => [d.time, d.value]));
    link(opts.group, { chart: c, series: refs[0], valueAt: (t) => { const v = map0.get(t); return v == null ? null : logMode ? 1 + v : v; } });
    c.timeScale().fitContent();
  };
  return { node: wrap, after, chart: () => chart };
}
function sparkline(values, color) {
  const w = 200, hgt = 38;
  if (!values.length) return h('div', { class: 'spark' });
  const mn = Math.min(...values), mx = Math.max(...values), span = mx - mn || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${hgt - 3 - ((v - mn) / span) * (hgt - 6)}`).join(' ');
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', `0 0 ${w} ${hgt}`); s.setAttribute('preserveAspectRatio', 'none'); s.setAttribute('class', 'spark');
  s.innerHTML = `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"/>`;
  return s;
}
/** Monatsrenditen als Jahres x Monats-Raster (divergierend: rot negativ, blau positiv). */
function heatmap(monthly, label = 'Strategie') {
  if (!monthly.length) return empty('Noch keine Monatsdaten.');
  const by = {}; for (const m of monthly) { const [y, mo] = m.month.split('-'); (by[y] ||= {})[+mo] = m.return; }
  const years = Object.keys(by).sort();
  const cap = Math.max(0.05, Math.min(0.3, Math.max(...monthly.map(m => Math.abs(m.return)))));
  const g = h('div', { class: 'heat', style: 'grid-template-columns: 44px repeat(12, minmax(34px,1fr)) 64px' });
  g.append(h('div', { class: 'h' }, ''), ...'Jan Feb Mär Apr Mai Jun Jul Aug Sep Okt Nov Dez'.split(' ').map(m => h('div', { class: 'h' }, m)), h('div', { class: 'h' }, 'Jahr'));
  const cell = (v, title) => {
    if (v == null) return h('div', { class: 'c', style: 'background:var(--surface-2)' });
    const k = Math.min(1, Math.abs(v) / cap), p = Math.round(k * 100);
    const col = v >= 0 ? 'var(--div-pos)' : 'var(--div-neg)';
    return h('div', { class: 'c', 'data-tip': `${title}: ${pct(v, 1)}`, style: `background:color-mix(in oklab, ${col} ${p}%, var(--div-mid));color:${p > 55 ? '#fff' : 'var(--ink)'}` }, nf(1).format(v * 100));
  };
  for (const y of years) {
    g.append(h('div', { class: 'h' }, y));
    let yr = 1; for (let m = 1; m <= 12; m++) { const v = by[y][m]; if (v != null) yr *= 1 + v; g.append(cell(v, `${label} ${m}/${y}`)); }
    g.append(cell(yr - 1, `${label} ${y} gesamt`));
  }
  return h('div', null, h('div', { class: 'tbl' }, g), h('div', { class: 'small muted', style: 'margin-top:8px' }, `Monatsrendite in %. Blau positiv, rot negativ, Farbskala bis ±${nf(0).format(cap * 100)} %.`));
}
/** Verteilung der Trade-Ergebnisse in Prozent. */
function histogram(values) {
  if (values.length < 2) return empty('Zu wenige Trades für eine Verteilung.');
  const lo = Math.max(-0.5, Math.min(...values)), hi = Math.min(1.5, Math.max(...values));
  const n = 18, step = (hi - lo) / n || 0.01, bins = Array(n).fill(0);
  for (const v of values) bins[Math.min(n - 1, Math.max(0, Math.floor((v - lo) / step)))]++;
  const mx = Math.max(...bins);
  return h('div', null, h('div', { class: 'hist' }, bins.map((b, i) => {
    const a = lo + i * step, mid = a + step / 2;
    return h('div', { class: 'b', 'data-tip': `${pct(a, 1)} bis ${pct(a + step, 1)}: ${b} Trades`, style: `height:${(b / mx) * 100}%;background:${mid < 0 ? 'var(--div-neg)' : 'var(--div-pos)'}` });
  })), h('div', { class: 'hist-axis' }, h('span', null, pct(lo, 0)), h('span', null, '0 %'), h('span', null, pct(hi, 0))));
}

// ================================================================= Router & Rahmen
const ICONS = {
  overview: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  bots: '<rect x="4" y="7" width="16" height="12" rx="3"/><path d="M12 3v4M9 12h.01M15 12h.01M9 16h6"/>',
  lab: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3"/><path d="M7.5 15h9"/>',
  strategies: '<path d="M4 19V5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M8 7h7M8 11h5"/>',
  system: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17h.01"/>',
};
const PAGES = [
  { path: 'overview', label: 'Übersicht', render: overviewPage, live: true },
  { path: 'bots', label: 'Bots', render: botsPage, live: true },
  { path: 'lab', short: 'Labor', label: 'Analyse-Labor', render: labPage, live: false },
  { path: 'strategies', label: 'Strategien', render: strategiesPage, live: false },
  { path: 'system', short: 'System', label: 'Master & System', render: systemPage, live: true },
  { path: 'help', label: 'Glossar', render: helpPage, live: false },
];
let META = null, ROUTE = null, lastHealth = null;
function parseHash() {
  const raw = (location.hash || '#/overview').slice(2); const [path, q] = raw.split('?');
  const parts = path.split('/').map(decodeURIComponent);
  return { parts, q: Object.fromEntries(new URLSearchParams(q || '')) };
}
function go(path, q) { const qs = q ? '?' + new URLSearchParams(Object.entries(q).filter(([, v]) => v != null && v !== '')) : ''; location.hash = '#/' + path + qs; }
function setQuery(q) { const r = parseHash(); const qs = new URLSearchParams({ ...r.q, ...q }); history.replaceState(null, '', '#/' + r.parts.map(encodeURIComponent).join('/') + '?' + qs); }

function renderNav(active) {
  $('#nav').replaceChildren(...PAGES.map(p => h('a', { href: '#/' + p.path, class: p.path === active ? 'on' : '' }, svgIcon(ICONS[p.path]), h('span', { class: 'lbl' }, p.label), h('span', { class: 'lbl-s' }, p.short || p.label))));
}
function renderChrome(health, master) {
  lastHealth = health;
  const bad = [];
  for (const [k, v] of Object.entries(health.heartbeat_age_s)) if (v == null || v > 60) bad.push(`${k}: ${v == null ? 'kein Signal' : ago(v)}`);
  if (health.last_15m_candle_age_s == null || health.last_15m_candle_age_s > 1500) bad.push('Kursdaten veraltet');
  const st = bad.length ? badge('Störung', 'bad', true) : badge('System läuft', 'ok', true);
  if (bad.length) st.setAttribute('data-tip', bad.join('\n'));
  $('#top-status').replaceChildren(st);
  $('#side-status').replaceChildren(bad.length ? h('span', { class: 'down' }, '● ', bad.length, ' Problem(e)') : h('span', { class: 'up' }, '● alle Dienste aktiv'));
  const b = [];
  if (health.kill_switch) b.push(h('div', { class: 'banner bad' }, h('b', null, 'Kill-Switch aktiv.'), ' Alle Positionen wurden geschlossen, keine neuen Einstiege.', h('span', { class: 'grow' }),
    h('button', { class: 'btn sm', onclick: async () => { if (confirm('Kill-Switch aufheben?')) { await post('control/unkill'); refresh(); } } }, 'Aufheben')));
  const paused = Object.entries(master.paused || {});
  if (paused.length) b.push(h('div', { class: 'banner warn' }, h('b', null, 'Pausiert: '), paused.map(([n, p]) => h('span', null, h('a', { href: '#/bots/' + encodeURIComponent(n) }, n), h('span', { class: 'muted' }, ` (${p.reason || 'pausiert'})  `)))));
  $('#banner').replaceChildren(...b);
}
async function refresh(auto = false) {
  const r = parseHash();
  const page = PAGES.find(p => p.path === r.parts[0]) || PAGES[0];
  if (auto && !page.live) return;
  renderNav(page.path);
  try {
    if (!META) META = await api('meta');
    const [health, master] = await Promise.all([api('health'), api('master')]);
    renderChrome(health, master);
    const scrollY = window.scrollY;
    const view = await page.render(r, { master, health });
    disposeCharts();
    $('#crumbs').replaceChildren(...(view.crumbs || [page.label]).flatMap((c, i, a) => i < a.length - 1 ? [c, h('span', { class: 'muted' }, '  /  ')] : [c]));
    $('#view').replaceChildren(view.node);
    (view.after || []).forEach(fn => fn());
    if (auto) window.scrollTo(0, scrollY);
    $('#updated').textContent = 'Stand ' + new Date().toLocaleTimeString('de-DE');
  } catch (err) {
    console.error(err);
    $('#top-status').replaceChildren(badge('API nicht erreichbar', 'bad', true));
    if (!auto) $('#view').replaceChildren(card('Fehler', h('div', null, 'Die Seite konnte nicht geladen werden: ', String(err.message || err))));
  }
}
window.addEventListener('hashchange', () => refresh());
$('#refresh-btn').onclick = () => refresh();
$('#theme-btn2').onclick = () => $('#theme-btn').click();
$('#theme-btn').onclick = () => {
  const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next; try { localStorage.setItem('theme', next); } catch (e) {}
  refresh();
};
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => refresh());
setInterval(() => { if (!document.hidden) refresh(true); }, 30000);
const pageHead = (title, desc, actions) => h('div', { class: 'page-head' }, h('div', null, h('h1', null, title), desc ? h('p', null, desc) : null), h('span', { class: 'grow' }), actions || null);
const walletLink = (n) => h('a', { href: '#/bots/' + encodeURIComponent(n) }, n);
const colorMap = (names) => { const c = SERIES(); return Object.fromEntries(names.map((n, i) => [n, c[i % c.length]])); };

// ================================================================= Übersicht
async function overviewPage() {
  const range = store.get('ov.range', 'all');
  const [prices, wallets, eq, bench, events, fills, ...sparks] = await Promise.all([api('prices'), api('wallets'), api('equity'), api('benchmark'), api('events?limit=10'), api('fills?limit=10'),
    ...META.symbols.map(s => api(`candles?symbol=${s}&interval=1h&limit=72`))]);
  const colors = colorMap(wallets.map(w => w.name));
  const active = wallets.filter(w => !w.paused).length, openPos = wallets.reduce((s, w) => s + w.positions.length, 0), trades = wallets.reduce((s, w) => s + w.trades, 0);
  const fees = wallets.reduce((s, w) => s + w.fees, 0);
  const sorted = [...wallets].sort((a, b) => b.return - a.return);
  const since = Math.min(...wallets.map(w => w.since));
  const cut = range === '7d' ? Date.now() - 7 * 864e5 : range === '30d' ? Date.now() - 30 * 864e5 : 0;
  const clip = (pts) => pts.filter(p => p[0] >= cut);
  const markets = h('div', { class: 'grid g3' }, META.symbols.map((s, i) => {
    const p = prices[s], sp = sparks[i].candles.map(c => c.close);
    return h('div', { class: 'card' }, h('div', { class: 'bd' }, h('div', { class: 'row' }, h('b', null, coin(s)), h('span', { class: 'muted small' }, '/ USDT'), h('span', { class: 'grow' }), h('span', { class: 'small ' + tone(p?.change_24h) }, pct(p?.change_24h), ' 24 h')),
      h('div', { style: 'font-size:22px;font-weight:620;margin:2px 0 6px' }, price(p?.price)), sparkline(sp, css(p?.change_24h >= 0 ? '--candle-up' : '--candle-down')), h('div', { class: 'small muted', style: 'margin-top:4px' }, 'Letzte 72 Stunden')));
  }));
  const chart = lineChart([...wallets.map(w => ({ name: w.name, color: colors[w.name], data: clip(eq[w.name] || []) })), { name: 'Buy & Hold', color: css('--bench'), dashed: true, data: clip(bench) }], { name: 'rendite-wallets', hidden: store.get('ov.hidden', []), onToggle: (n, off) => { const s = new Set(store.get('ov.hidden', [])); off ? s.add(n) : s.delete(n); store.set('ov.hidden', [...s]); } });
  const cols = [
    { h: 'Wallet', a: 'l', render: w => h('span', { class: 'row', style: 'gap:8px;flex-wrap:nowrap' }, h('span', { class: 'sw', style: 'background:' + colors[w.name] }), walletLink(w.name)), sort: w => w.name },
    { h: 'Strategie', a: 'l', render: w => `${STRAT[w.strategy] || w.strategy} · ${w.interval}`, sort: w => w.strategy + w.interval },
    { h: 'Start', render: w => money(w.start_cash, 0), sort: w => w.start_cash },
    { h: 'Wert', render: w => money(w.equity), sort: w => w.equity },
    { h: 'Rendite', render: w => pct(w.return, 2), cls: w => tone(w.return), sort: w => w.return, tip: M('return') },
    { h: 'Max. DD', render: w => w.max_drawdown ? pct(-w.max_drawdown) : '–', sort: w => w.max_drawdown, tip: M('max_drawdown') },
    { h: 'Trades', render: w => w.trades, sort: w => w.trades, tip: M('trades') },
    { h: 'Treffer', render: w => w.win_rate == null ? '–' : pct(w.win_rate, 0, false), sort: w => w.win_rate, tip: M('win_rate') },
    { h: 'Investiert', render: w => pct(w.exposure, 0, false), sort: w => w.exposure, tip: 'Anteil des Wallet-Werts, der gerade in Coins steckt.' },
    { h: 'Status', a: 'l', render: statusBadge, sort: w => w.paused },
  ];
  const lv = { info: '', warn: 'warn', error: 'bad' };
  const node = h('div', { class: 'stack' },
    pageHead('Übersicht', 'Alle Bots handeln mit echten Live-Kursen von Binance, aber nur mit virtuellem Geld. Jede Wallet startet unabhängig mit vollem Kapital, damit sie direkt vergleichbar ist.'),
    h('div', { class: 'kpis' },
      kpi('Wallets aktiv', `${active} / ${wallets.length}`, wallets.length - active ? `${wallets.length - active} pausiert` : 'alle handeln'),
      kpi('Offene Positionen', openPos, 'über alle Wallets'),
      kpi('Abgeschlossene Trades', trades, 'seit ' + dday(since), '', M('trades')),
      kpi('Beste Wallet', pct(sorted[0]?.return, 2), sorted[0]?.name, tone(sorted[0]?.return)),
      kpi('Schwächste Wallet', pct(sorted.at(-1)?.return, 2), sorted.at(-1)?.name, tone(sorted.at(-1)?.return)),
      kpi('Gebühren gesamt', money(fees), 'USDT, alle Wallets', '', M('fees'))),
    markets,
    card('Rendite seit Start', chart.node, { tip: 'Wertentwicklung jeder Wallet in Prozent ihres Startkapitals. Klick auf einen Namen blendet die Linie aus. Gestrichelt: gleichgewichtetes Buy & Hold aus BTC, ETH und SOL ab Start, ohne Kosten.',
      actions: seg([['7d', '7 T'], ['30d', '30 T'], ['all', 'Alles']], range, (v) => { store.set('ov.range', v); refresh(); }),
      foot: 'Die Linien springen nach jeder abgeschlossenen Kerze (4 h bzw. 1 Tag). Zwischen den Kerzen ist nur der letzte Punkt live bewertet.' }),
    card('Wallets', table(cols, wallets, { onRow: w => go('bots/' + w.name), sortKey: 'Rendite' }), { flush: true, sub: 'Spaltenköpfe sortieren, Zeile öffnet die Detailansicht' }),
    h('div', { class: 'grid g2' },
      card('Ereignisse', eventsTable(events, lv), { flush: true, actions: h('a', { href: '#/system', class: 'small' }, 'Alle anzeigen') }),
      card('Letzte Trades', fillsTable(fills), { flush: true })));
  return { node, after: [chart.after] };
}
function eventsTable(ev) {
  const kind = { info: ['Info', ''], warn: ['Warnung', 'warn'], error: ['Fehler', 'bad'] };
  return table([
    { h: 'Zeit', a: 'l', render: e => dtm(e.ts) },
    { h: 'Stufe', a: 'l', render: e => badge(...(kind[e.level] || [e.level, ''])) },
    { h: 'Quelle', a: 'l', render: e => e.source },
    { h: 'Wallet', a: 'l', render: e => e.wallet ? walletLink(e.wallet) : '' },
    { h: 'Meldung', a: 'l', wrap: true, render: e => e.message },
  ], ev, { empty: 'Noch keine Ereignisse.' });
}
function fillsTable(fs) {
  return table([
    { h: 'Zeit', a: 'l', render: f => dtm(f.ts) },
    { h: 'Wallet', a: 'l', render: f => walletLink(f.wallet) },
    { h: 'Coin', a: 'l', render: f => coin(f.symbol) },
    { h: 'Seite', a: 'l', render: f => badge(f.side === 'buy' ? 'Kauf' : 'Verkauf', f.side === 'buy' ? 'accent' : '') },
    { h: 'Preis', render: f => price(f.price) },
    { h: 'Ergebnis', render: f => f.side === 'sell' ? signed(f.realized_pnl) : '–', cls: f => f.side === 'sell' ? tone(f.realized_pnl) : 'muted' },
  ], fs, { empty: 'Noch keine Trades. Die Strategien warten auf ein Signal: 4h-Kerzen schließen um 0, 4, 8, 12, 16 und 20 Uhr UTC, Tageskerzen um 0 Uhr UTC.' });
}

// ================================================================= Bots
function nextClose(interval, now) { const step = { '1h': 36e5, '4h': 144e5, '1d': 864e5 }[interval] || 9e5; return Math.floor(now / step) * step + step; }
/** Wie weit ist ein Coin vom nächsten Signal entfernt? */
function signalDistance(strategy, st, docs) {
  const ind = st.indicators || {}, c = st.close;
  if (strategy === 'trend') {
    if (st.in_position) return { text: `Stop ${price(ind.stop)} (${pct(ind.stop / c - 1)})`, tip: 'Die Position wird verkauft, wenn der Kurs den mitlaufenden Stop erreicht oder unter den Ausstiegskanal schließt.', frac: null };
    if (!ind.entry_level) return { text: 'Indikatoren laden', frac: null };
    const d = ind.entry_level / c - 1;
    return { text: `Ausbruch bei ${price(ind.entry_level)} (${pct(d)})`, tip: `Gekauft wird, wenn eine Kerze über ${price(ind.entry_level)} schließt. Dafür fehlen noch ${pct(d, 1, false)}.`, frac: Math.max(0, Math.min(1, 1 - d / 0.2)) };
  }
  if (strategy === 'meanrev') {
    if (st.in_position) return { text: `Ziel ${price(ind.bb_mid)} · Stop ${price(ind.stop)}`, tip: 'Verkauf am mittleren Bollinger-Band, am Stop oder nach der maximalen Haltedauer.', frac: null };
    if (ind.rsi == null) return { text: 'Indikatoren laden', frac: null };
    return { text: `RSI ${num(ind.rsi, 1)} (Kauf unter 30)`, tip: 'Kauf, wenn der RSI unter 30 fällt, der Kurs unter dem unteren Bollinger-Band schließt und über dem EMA-Trendfilter liegt.', frac: Math.max(0, Math.min(1, (70 - ind.rsi) / 40)) };
  }
  return { text: '–', frac: null };
}
async function botsPage(r) {
  if (r.parts[1]) return botDetail(r.parts[1], r.q);
  const [wallets, health] = await Promise.all([api('wallets'), api('health')]);
  const details = await Promise.all(wallets.map(w => api('wallet/' + encodeURIComponent(w.name))));
  const colors = colorMap(wallets.map(w => w.name)), now = health.server_time;
  const cards = wallets.map((w, i) => {
    const d = details[i];
    return h('section', { class: 'card' }, h('div', { class: 'botcard' },
      h('div', { class: 'h' }, h('span', { class: 'sw', style: 'background:' + colors[w.name] }), h('a', { href: '#/bots/' + encodeURIComponent(w.name) }, w.name), h('span', { class: 'grow' }), statusBadge(w)),
      h('div', { class: 'small muted' }, `${STRAT[w.strategy]} · ${IVL[w.interval]}-Kerzen · Start ${money(w.start_cash, 0)} USDT · nächste Kerze in ${ago((nextClose(w.interval, now) - now) / 1000)}`),
      h('div', { class: 'kpis mini' }, kpi('Wert', money(w.equity), null, '', null, true), kpi('Rendite', pct(w.return, 2), null, tone(w.return), M('return'), true), kpi('Trades', w.trades, w.win_rate == null ? '' : pct(w.win_rate, 0, false) + ' Treffer', '', M('trades'), true), kpi('Investiert', pct(w.exposure, 0, false), null, '', null, true)),
      h('div', { class: 'coins' }, d.states.map(s => {
        const sd = signalDistance(w.strategy, s.state);
        return h('div', { class: 'coin' }, h('span', { class: 'name' }, coin(s.symbol)),
          h('div', null, h('div', { class: 'small', 'data-tip': sd.tip || '' }, sd.text), sd.frac != null ? h('div', { class: 'meter', style: 'margin-top:4px' }, h('i', { style: `width:${sd.frac * 100}%` })) : null),
          s.state.in_position ? badge('Position', 'accent') : badge('flach'));
      })),
      h('div', { class: 'row' }, h('a', { class: 'btn sm', href: '#/bots/' + encodeURIComponent(w.name) }, 'Details'), h('a', { class: 'btn sm ghost', href: '#/bots/' + encodeURIComponent(w.name) + '?tab=chart' }, 'Chart & Signale'))));
  });
  return { node: h('div', { class: 'stack' }, pageHead('Bots', 'Jeder Bot ist eine Wallet aus Strategie, Kerzenintervall und Startkapital. Der Balken zeigt, wie nah ein Coin am nächsten Kaufsignal ist.'), h('div', { class: 'grid g2' }, cards)) };
}

async function botDetail(name, q) {
  const tab = q.tab || 'overview';
  const d = await api('wallet/' + encodeURIComponent(name));
  const m = d.metrics, p = m.params || {};
  const tabs = [['overview', 'Überblick'], ['chart', 'Chart & Signale'], ['trades', 'Trades'], ['config', 'Konfiguration'], ['log', 'Protokoll']];
  const control = d.kill_switch ? badge('Kill-Switch aktiv', 'bad', true)
    : d.paused ? h('button', { class: 'btn sm', onclick: async () => { await post('control/resume/' + encodeURIComponent(name)); refresh(); } }, 'Freigeben')
      : h('button', { class: 'btn sm', 'data-tip': 'Keine neuen Einstiege mehr. Offene Positionen verwaltet die Strategie weiter (Stops und Ausstiege bleiben aktiv).', onclick: async () => { if (confirm(name + ' pausieren?')) { await post('control/pause/' + encodeURIComponent(name)); refresh(); } } }, 'Pausieren');
  const head = h('div', { class: 'page-head' }, h('div', null, h('h1', null, name), h('div', { class: 'row', style: 'margin-top:8px' }, statusBadge({ paused: d.paused }), badge(STRAT[m.strategy]), badge(IVL[m.interval] + '-Kerzen'), badge('Start ' + money(m.start_cash, 0) + ' USDT'), h('span', { class: 'small muted' }, 'läuft seit ' + days(d.days_running)), d.pause_reason ? h('span', { class: 'small muted' }, '· ' + d.pause_reason) : null)),
    h('span', { class: 'grow' }), h('div', { class: 'row' }, h('a', { class: 'btn sm', href: '#/lab?' + new URLSearchParams({ strategy: m.strategy, interval: m.interval, capital: m.start_cash, params: JSON.stringify((p.strategy_params) || {}) }) }, 'Im Labor testen'), control));
  const tabBar = h('div', { class: 'tabs' }, tabs.map(([k, l]) => h('button', { class: k === tab ? 'on' : '', onclick: () => go('bots/' + name, { tab: k }) }, l)));
  let body, after = [];
  if (tab === 'overview') ({ body, after } = await botOverview(name, d));
  else if (tab === 'chart') ({ body, after } = await botChart(name, d, q));
  else if (tab === 'trades') body = botTrades(d);
  else if (tab === 'config') body = botConfig(d);
  else body = card('Ereignisse dieser Wallet', eventsTable(d.events.map(e => ({ ...e, wallet: null }))), { flush: true });
  return { node: h('div', null, head, tabBar, body), after, crumbs: [h('a', { href: '#/bots' }, 'Bots'), name] };
}
async function botOverview(name, d) {
  const m = d.metrics, bt = d.backtest;
  const [eq, bench] = await Promise.all([api('equity'), api('benchmark')]);
  const c1 = lineChart([{ name, color: SERIES()[0], data: eq[name] || [] }, { name: 'Buy & Hold', color: css('--bench'), dashed: true, data: bench }], { name: name + '-wert', group: 'bot' });
  const c2 = lineChart([{ name: 'Drawdown', color: css('--candle-down'), fill: alpha(css('--candle-down'), 0.18), area: true, data: d.drawdown_curve }], { size: 'sm', name: name + '-drawdown', group: 'bot', logable: false, emptyBelow: 2, empty: 'Noch kein Drawdown-Verlauf: Er entsteht mit den ersten abgeschlossenen Kerzen.' });
  const cmp = table([
    { h: 'Kennzahl', a: 'l', render: r => h('span', { class: 'row', style: 'gap:6px' }, r[0], info(r[3])) },
    { h: 'Live seit Start', render: r => r[1] }, { h: 'Backtest 4 Jahre', render: r => r[2] },
  ], [
    ['Rendite', pct(m.return, 2), bt ? pct(bt.return) : '–', M('return')], ['Buy & Hold', '–', bt ? pct(bt.bh_return) : '–', M('bh_return')],
    ['Max. Drawdown', m.max_drawdown ? pct(-m.max_drawdown) : '–', bt ? pct(-bt.max_dd) : '–', M('max_drawdown')], ['Sharpe', m.sharpe == null ? 'zu wenig Daten' : num(m.sharpe), bt ? num(bt.sharpe) : '–', M('sharpe')],
    ['Trades', m.trades, bt ? bt.trades : '–', M('trades')], ['Trefferquote', m.win_rate == null ? '–' : pct(m.win_rate, 0, false), bt?.win_rate != null ? pct(bt.win_rate, 0, false) : '–', M('win_rate')],
    ['Profit-Faktor', m.profit_factor == null ? '–' : num(m.profit_factor), bt?.profit_factor != null ? num(bt.profit_factor) : '–', M('profit_factor')]]);
  const pos = table([
    { h: 'Coin', a: 'l', render: x => coin(x.symbol) }, { h: 'Menge', render: x => num(x.qty, 5) }, { h: 'Einstand', render: x => price(x.avg_cost) },
    { h: 'Kurs', render: x => price(x.price) }, { h: 'Wert', render: x => money(x.value) }, { h: 'Unrealisiert', render: x => signed(x.unrealized) + ' (' + pct(x.unrealized_pct) + ')', cls: x => tone(x.unrealized) },
  ], m.positions, { empty: 'Keine offenen Positionen.' });
  const body = h('div', { class: 'stack' },
    h('div', { class: 'kpis' },
      kpi('Wert', money(m.equity), 'Start ' + money(m.start_cash, 0)), kpi('Rendite', pct(m.return, 2), null, tone(m.return), M('return')),
      kpi('Realisiert', signed(m.realized_pnl), 'nach Gebühren', tone(m.realized_pnl), 'Gewinn oder Verlust aus bereits geschlossenen Trades.'), kpi('Unrealisiert', signed(m.unrealized_pnl), 'offene Positionen', tone(m.unrealized_pnl), 'Buchgewinn der offenen Positionen zum aktuellen Kurs.'),
      kpi('Max. Drawdown', m.max_drawdown ? pct(-m.max_drawdown) : '–', 'vom Höchststand', '', M('max_drawdown')), kpi('Sharpe', m.sharpe == null ? '–' : num(m.sharpe), m.sharpe == null ? 'noch zu wenig Daten' : 'annualisiert', '', M('sharpe')),
      kpi('Trades', m.trades, m.win_rate == null ? 'noch keine' : pct(m.win_rate, 0, false) + ' Treffer', '', M('trades')), kpi('Profit-Faktor', m.profit_factor == null ? '–' : num(m.profit_factor), null, '', M('profit_factor')),
      kpi('Erwartungswert', m.expectancy == null ? '–' : signed(m.expectancy), 'je Trade', tone(m.expectancy), M('expectancy')), kpi('Gebühren', money(m.fees), pct(m.fees / m.start_cash, 2, false) + ' vom Start', '', M('fees')),
      kpi('Cash', money(m.cash), pct(1 - m.exposure, 0, false) + ' des Werts'), kpi('Umsatz', money(m.turnover, 0), m.n_fills + ' Orders', '', 'Summe aller Ordervolumina. Hoher Umsatz bedeutet viele Gebühren.')),
    card('Wertentwicklung', c1.node, { tip: 'Rendite der Wallet in Prozent des Startkapitals, gegen gleichgewichtetes Buy & Hold ohne Kosten.' }),
    card('Drawdown', c2.node, { tip: M('max_drawdown') }),
    h('div', { class: 'grid g2' }, card('Live gegen Backtest', cmp, { flush: true, foot: 'Der Backtest nutzt dieselben Regeln und Kosten über 4 Jahre. In den ersten Wochen sind die Live-Werte kaum aussagekräftig.' }), card('Offene Positionen', pos, { flush: true })),
    card('Monatsrenditen', heatmap(d.monthly, name)));
  return { body, after: [c1.after, c2.after] };
}
async function botChart(name, d, q) {
  const m = d.metrics, sym = q.coin || META.symbols[0], lim = +(q.n || 240);
  const cd = await api(`candles?symbol=${sym}&interval=${m.interval}&limit=${lim}&wallet=${encodeURIComponent(name)}`);
  const st = (d.states.find(s => s.symbol === sym) || {}).state || {};
  const ind = st.indicators || {};
  const wrap = h('div', { class: 'chartwrap' }), legend = h('div', { class: 'legend' }), box = h('div', { class: 'chart lg' }), xh = h('div', { class: 'xhair' });
  box.append(xh);
  const rsiBox = h('div', { class: 'chart xs' });
  const S = SERIES();
  const OV = m.strategy === 'trend'
    ? [['entry_level', 'Einstiegskanal (Hoch)', S[0], 0], ['exit_level', 'Ausstiegskanal (Tief)', S[1], 0], ['atr_stop', 'ATR-Stop-Niveau', S[2], 2], ['trend_ema', 'EMA-Trendfilter', S[3], 0]]
    : [['bb_upper', 'Bollinger oben', S[0], 2], ['bb_mid', 'Bollinger Mitte (Ziel)', S[0], 0], ['bb_lower', 'Bollinger unten (Kaufzone)', S[1], 0], ['trend_ema', 'EMA 200 (Trendfilter)', S[3], 0]];
  let chart = null, cs = null, vol = null;
  const k0 = cd.candles[0]?.time || 0, k1 = cd.candles.at(-1)?.time || 0;
  const tools = chartTools({ chart: () => chart, lastTime: () => toSec(k1), spanDays: (k1 - k0) / 864e5, name: `${name}-${coin(sym)}`, fullscreenEl: () => wrap,
    onLog: (on) => chart.priceScale('right').applyOptions({ mode: on ? 1 : 0 }),
    csv: () => { const rows = ['Zeit;Eröffnung;Hoch;Tief;Schluss;Volumen', ...cd.candles.map(k => [new Date(k.time).toISOString(), k.open, k.high, k.low, k.close, k.volume].join(';').replace(/\./g, ','))];
      download(`${name}-${coin(sym)}.csv`, URL.createObjectURL(new Blob(['﻿' + rows.join('\n')], { type: 'text/csv;charset=utf-8' }))); } });
  const volBtn = h('button', { class: 'btn sm ghost on', type: 'button', 'data-tip': 'Handelsvolumen ein- oder ausblenden' }, 'Volumen');
  volBtn.onclick = () => { volBtn.classList.toggle('on'); vol?.applyOptions({ visible: volBtn.classList.contains('on') }); };
  tools.insertBefore(volBtn, tools.querySelector('.grow').nextSibling);
  wrap.append(tools, legend, box);
  const after = () => {
    const c = chart = baseChart(box, (v) => price(v));
    c.applyOptions({ rightPriceScale: { scaleMargins: { top: 0.08, bottom: 0.22 } } });
    cs = c.addCandlestickSeries({ upColor: css('--candle-up'), downColor: css('--candle-down'), borderVisible: false, wickUpColor: css('--candle-up'), wickDownColor: css('--candle-down'), priceLineVisible: true, priceLineStyle: 3 });
    cs.setData(cd.candles.map(k => ({ time: toSec(k.time), open: k.open, high: k.high, low: k.low, close: k.close })));
    vol = c.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
    c.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(cd.candles.map(k => ({ time: toSec(k.time), value: k.volume, color: alpha(k.close >= k.open ? css('--candle-up') : css('--candle-down'), 0.35) })));
    const lines = [];
    for (const [key, label, color, style] of OV) {
      const data = cd.overlays[key]; if (!data || !data.length) continue;
      const l = c.addLineSeries({ color, lineWidth: style ? 1 : 2, lineStyle: style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      l.setData(toSeries(data)); lines.push([label, color, l]);
      const it = h('span', { class: 'it', 'data-tip': 'Klick blendet die Linie ein oder aus' }, h('span', { class: 'sw' + (style ? ' dashed' : ''), style: `--c:${color}` }), label);
      it.onclick = () => { const off = it.classList.toggle('off'); l.applyOptions({ visible: !off }); };
      legend.append(it);
    }
    // Aktuelle Signal-Niveaus als beschriftete Linien
    const lvl = (v, title, color) => v != null && cs.createPriceLine({ price: v, color, lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title });
    if (m.strategy === 'trend') { if (st.in_position) { lvl(ind.stop, 'Stop', css('--candle-down')); lvl(ind.exit_level, 'Ausstieg unter', S[1]); } else lvl(ind.entry_level, 'Kauf über', S[0]); }
    else { if (st.in_position) { lvl(ind.bb_mid, 'Ziel', S[0]); lvl(ind.stop, 'Stop', css('--candle-down')); } else lvl(ind.bb_lower, 'Kaufzone unter', S[1]); }
    const step = cd.candles.length > 1 ? cd.candles[1].time - cd.candles[0].time : 1;
    const markers = cd.trades.map(t => { const bar = cd.candles.find(k => t.ts >= k.time && t.ts < k.time + step); if (!bar) return null;
      return { time: toSec(bar.time), position: t.side === 'buy' ? 'belowBar' : 'aboveBar', color: t.side === 'buy' ? css('--accent') : css('--candle-down'), shape: t.side === 'buy' ? 'arrowUp' : 'arrowDown', text: t.side === 'buy' ? 'Kauf' : `Verkauf ${signed(t.pnl)}` }; }).filter(Boolean);
    cs.setMarkers(markers.sort((a, b) => a.time - b.time));
    legend.append(h('span', { class: 'it' }, h('span', { class: 'sw', style: `--c:${css('--accent')}` }), `Käufe und Verkäufe dieser Wallet (${cd.trades.length})`));
    c.subscribeCrosshairMove((pp) => {
      if (!pp.time || !pp.point) { xh.style.display = 'none'; return; }
      const k = pp.seriesData.get(cs); if (!k) { xh.style.display = 'none'; return; }
      const v = pp.seriesData.get(vol), chg = k.close / k.open - 1;
      xh.replaceChildren(h('div', { class: 't' }, fmtTime(pp.time)),
        h('div', { class: 'r' }, h('span', null, 'Eröffnung'), h('b', null, price(k.open))), h('div', { class: 'r' }, h('span', null, 'Hoch'), h('b', null, price(k.high))),
        h('div', { class: 'r' }, h('span', null, 'Tief'), h('b', null, price(k.low))), h('div', { class: 'r' }, h('span', null, 'Schluss'), h('b', { class: tone(chg) }, price(k.close) + ' (' + pct(chg, 2) + ')')),
        v ? h('div', { class: 'r' }, h('span', null, 'Volumen'), h('b', null, nf(0).format(v.value))) : null,
        ...lines.map(([label, color, l]) => { const x = pp.seriesData.get(l); return x && l.options().visible ? h('div', { class: 'r' }, h('span', null, h('span', { class: 'sw', style: `--c:${color}` }), label), h('b', null, price(x.value))) : null; }));
      placeTip(xh, box, pp.point);
    });
    c.timeScale().fitContent();
    if (cd.overlays.rsi) {
      const rc = baseChart(rsiBox, (v) => num(v, 0));
      const rl = rc.addLineSeries({ color: S[6], lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
      rl.setData(toSeries(cd.overlays.rsi));
      rl.createPriceLine({ price: (cd.params.rsi_entry ?? 30), color: css('--candle-down'), lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'Kaufschwelle' });
      const rmap = new Map(toSeries(cd.overlays.rsi).map(x => [x.time, x.value])), cmap = new Map(cd.candles.map(k => [toSec(k.time), k.close]));
      link('candle', { chart: c, series: cs, valueAt: (t) => cmap.get(t) ?? null });
      link('candle', { chart: rc, series: rl, valueAt: (t) => rmap.get(t) ?? null });
    }
  };
  const sd = signalDistance(m.strategy, st);
  const rule = m.strategy === 'trend'
    ? (st.in_position ? `Position offen. Verkauf, wenn eine Kerze unter ${price(ind.exit_level)} schließt oder der Kurs den Stop bei ${price(ind.stop)} berührt.` : `Kein Bestand. Kauf, wenn eine ${m.interval}-Kerze über ${price(ind.entry_level)} schließt (aktuell ${price(st.close)}, es fehlen ${pct(ind.entry_level / st.close - 1, 1, false)}).`)
    : (st.in_position ? `Position offen. Verkauf bei Schluss über ${price(ind.bb_mid)}, am Stop ${price(ind.stop)} oder nach der maximalen Haltedauer.` : `Kein Bestand. Kauf, wenn RSI unter ${cd.params.rsi_entry ?? 30} (aktuell ${num(ind.rsi, 1)}), Schluss unter ${price(ind.bb_lower)} und über dem EMA ${price(ind.trend_ema)}.`);
  const indRows = Object.entries(ind).filter(([k]) => !(k === 'trend_ema' && m.strategy === 'trend' && !cd.params.trend_n)).map(([k, v]) => ({ k, v }));
  const body = h('div', { class: 'stack' },
    h('div', { class: 'row' }, seg(META.symbols.map(s => [s, coin(s)]), sym, v => go('bots/' + name, { tab: 'chart', coin: v, n: lim })),
      seg([[120, '120'], [240, '240'], [600, '600'], [1200, '1200']], lim, v => go('bots/' + name, { tab: 'chart', coin: sym, n: v })), h('span', { class: 'small muted hide-m' }, 'Kerzen geladen · Mausrad zoomt, Ziehen verschiebt, Doppelklick auf die Achse setzt zurück')),
    card(`${coin(sym)} / USDT · ${IVL[m.interval]}`, h('div', null, wrap, cd.overlays.rsi ? h('div', { style: 'margin-top:12px' }, h('div', { class: 'small muted', style: 'margin-bottom:4px' }, 'RSI (0 bis 100), gestrichelt die Kaufschwelle. Zoom und Fadenkreuz laufen mit dem Kerzenchart mit.'), rsiBox) : null),
      { tip: 'Kerzen mit den Linien, die die Strategie tatsächlich nutzt. Pfeile markieren Käufe und Verkäufe dieser Wallet, beschriftete Linien die aktuellen Signal-Niveaus. Klick auf einen Legenden-Eintrag blendet die Linie aus.' }),
    h('div', { class: 'grid g2' },
      card('Was muss passieren?', h('div', { class: 'prose' }, h('p', null, rule), h('p', { class: 'small muted' }, 'Stand nach der Kerze bis ', dtm(st.candle_close_time), '. Letztes Signal: ', st.last_signal ? `${st.last_signal.action === 'enter' ? 'Einstieg' : 'Ausstieg'} (${st.last_signal.reason}) am ${dtm(st.last_signal.time)}` : 'noch keines', '.'),
        sd.frac != null ? h('div', null, h('div', { class: 'small muted', style: 'margin-bottom:4px' }, 'Nähe zum Kaufsignal'), h('div', { class: 'meter' }, h('i', { style: `width:${sd.frac * 100}%` }))) : null)),
      card('Aktuelle Indikatorwerte', table([
        { h: 'Indikator', a: 'l', render: r => h('span', { class: 'row', style: 'gap:6px;flex-wrap:nowrap' }, (META.indicators[r.k] || {}).label || r.k, info((META.indicators[r.k] || {}).what)) },
        { h: 'Wert', render: r => r.v == null ? (r.k === 'stop' ? 'nur mit Position' : 'noch nicht bereit') : r.k === 'rsi' ? num(r.v, 1) : r.k === 'held_candles' ? r.v : price(r.v) },
        { h: 'Abstand', tip: 'Abstand des Niveaus zum aktuellen Kurs', render: r => (r.v == null || ['rsi', 'held_candles', 'atr'].includes(r.k)) ? '' : pct(r.v / st.close - 1) },
      ], indRows, { empty: 'Noch kein Zustand.' }), { flush: true })));
  return { body, after: [after] };
}
function botTrades(d) {
  const trips = d.round_trips, m = d.metrics;
  const cols = [
    { h: 'Coin', a: 'l', render: t => coin(t.symbol), sort: t => t.symbol },
    { h: 'Einstieg', a: 'l', render: t => dtm(t.opened), sort: t => t.opened }, { h: 'Ausstieg', a: 'l', render: t => dtm(t.closed), sort: t => t.closed },
    { h: 'Dauer', render: t => days(t.hold_days), sort: t => t.hold_days }, { h: 'Einstiegskurs', render: t => price(t.entry) }, { h: 'Ausstiegskurs', render: t => price(t.exit) },
    { h: 'Ergebnis', render: t => signed(t.pnl), cls: t => tone(t.pnl), sort: t => t.pnl }, { h: '%', render: t => pct(t.pnl_pct), cls: t => tone(t.pnl_pct), sort: t => t.pnl_pct },
  ];
  return h('div', { class: 'stack' },
    h('div', { class: 'kpis' }, kpi('Trades', m.trades, null, '', M('trades')), kpi('Trefferquote', m.win_rate == null ? '–' : pct(m.win_rate, 0, false), null, '', M('win_rate')), kpi('Ø Gewinn', m.avg_win == null ? '–' : signed(m.avg_win), null, 'up'), kpi('Ø Verlust', m.avg_loss == null ? '–' : signed(m.avg_loss), null, 'down'),
      kpi('Bester Trade', m.best == null ? '–' : signed(m.best), null, tone(m.best)), kpi('Schlechtester', m.worst == null ? '–' : signed(m.worst), null, tone(m.worst))),
    h('div', { class: 'grid g2' }, card('Verteilung der Trade-Ergebnisse', histogram(trips.map(t => t.pnl_pct)), { tip: 'Wie viele Trades welches Ergebnis in Prozent hatten. Trendfolger haben typisch viele kleine Verluste links und wenige große Gewinne rechts.' }),
      card('Alle Orders', table([{ h: 'Zeit', a: 'l', render: f => dtm(f.ts) }, { h: 'Coin', a: 'l', render: f => coin(f.symbol) }, { h: 'Seite', a: 'l', render: f => f.side === 'buy' ? 'Kauf' : 'Verkauf' }, { h: 'Menge', render: f => num(f.qty, 5) }, { h: 'Preis', render: f => price(f.price) }, { h: 'Gebühr', render: f => num(f.fee, 4) }], d.fills, { empty: 'Noch keine Orders.', maxH: 320 }), { flush: true })),
    card('Abgeschlossene Trades', table(cols, trips, { empty: 'Noch keine abgeschlossenen Trades.', sortKey: 'Ausstieg' }), { flush: true }));
}
function fmtParam(v, unit) {
  if (typeof v === 'boolean') return v ? 'ja' : 'nein';
  if (Array.isArray(v)) return v.map(coin).join(', ');
  if (typeof v === 'number' && unit && unit.startsWith('Anteil')) return `${num(v, v < 0.01 ? 3 : 2)} (${pct(v, v < 0.01 ? 2 : 1, false)})`;
  return String(v);
}
function paramTable(params, docs, extra = {}) {
  const order = Object.keys(docs);
  const rows = Object.entries(params).map(([k, v]) => ({ k, v, d: docs[k] || {} })).sort((a, b) => ((order.indexOf(a.k) + 1) || 99) - ((order.indexOf(b.k) + 1) || 99));
  return table([
    { h: 'Parameter', a: 'l', render: r => h('div', null, h('div', { style: 'font-weight:600' }, r.d.label || r.k), h('div', { class: 'code' }, r.k)) },
    { h: 'Wert', a: 'l', wrap: true, render: r => h('b', null, fmtParam(r.v, r.d.unit)) },
    { h: 'Einheit', a: 'l', render: r => h('span', { class: 'muted' }, r.d.unit || '') },
    { h: 'Bedeutung', a: 'l', wrap: true, render: r => r.d.what || h('span', { class: 'muted' }, 'keine Beschreibung') },
    { h: 'Wirkung beim Erhöhen / Ändern', a: 'l', wrap: true, render: r => r.d.effect || '' },
  ], rows, extra);
}
function botConfig(d) {
  const p = d.metrics.params || {}, sp = p.strategy_params || {}, docs = d.param_docs;
  const wallet = { interval: IVL[p.interval] || p.interval, symbols: p.symbols || [], position_fraction: p.position_fraction, fee_rate: +p.fee_rate, slippage_bps: +p.slippage_bps, long_only: p.long_only, execution: p.execution };
  return h('div', { class: 'stack' },
    h('div', { class: 'banner note' }, h('div', null, 'Alle Variablen dieses Bots mit Erklärung. Zum Ausprobieren anderer Werte öffne ', h('a', { href: '#/lab?' + new URLSearchParams({ strategy: d.metrics.strategy, interval: d.metrics.interval, capital: d.metrics.start_cash, params: JSON.stringify(sp) }) }, 'das Analyse-Labor'), '. Dort siehst du sofort, wie sich eine Änderung im Backtest ausgewirkt hätte.')),
    card('Strategie-Parameter · ' + STRAT[d.metrics.strategy], paramTable(sp, docs.strategy), { flush: true }),
    card('Wallet, Kosten und Ausführung', paramTable(wallet, docs.wallet), { flush: true }));
}

// ================================================================= Analyse-Labor
const LAB = { req: null, result: null, sweep: null, busy: false, tab: 'result', pinned: store.get('lab.pinned', []) };
function labDefaults(strategy) { return { strategy, interval: strategy === 'trend' ? '1d' : '4h', days: 1460, capital: 10000, fraction: 0.33, fee: 0.001, slippage_bps: 5, params: { ...META.defaults[strategy] } }; }
async function labPage(r) {
  if (!LAB.req || r.q.strategy) {
    const s = r.q.strategy && META.defaults[r.q.strategy] ? r.q.strategy : 'trend';
    LAB.req = labDefaults(s);
    if (r.q.interval) LAB.req.interval = r.q.interval;
    if (r.q.capital) LAB.req.capital = +r.q.capital;
    if (r.q.params) try { Object.assign(LAB.req.params, JSON.parse(r.q.params)); } catch (e) {}
    if (r.q.strategy) { history.replaceState(null, '', '#/lab'); LAB.result = null; LAB.sweep = null; }
  }
  const view = h('div'), after = [];
  const paint = () => { disposeCharts(); const { node, fns } = labBody(paint); view.replaceChildren(node); fns.forEach(f => f()); };
  after.push(paint);
  if (!LAB.result && !LAB.busy) after.push(() => runLab(paint));
  return { node: h('div', null, pageHead('Analyse-Labor', 'Backtests mit beliebigen Parametern über bis zu 4 Jahre echte Binance-Daten. Gleicher Code und gleiche Kosten wie die Live-Bots. Nichts hier verändert die laufenden Bots.'), view), after };
}
async function runLab(paint) {
  LAB.busy = true; paint();
  try { LAB.result = await post('lab/run', LAB.req); LAB.error = null; } catch (e) { LAB.error = e.message; }
  LAB.busy = false; paint();
}
function labBody(paint) {
  const R = LAB.req, docs = META.params, def = META.defaults[R.strategy];
  const setField = (k, v, isParam) => { if (isParam) R.params[k] = v; else R[k] = v; };
  const numField = (key, value, doc, isParam, defVal) => {
    const rg = doc.range;
    const inp = h('input', { type: 'number', value, step: rg ? rg[2] : 'any', min: rg ? rg[0] : null, max: rg ? rg[1] : null });
    const slider = rg ? h('input', { type: 'range', min: rg[0], max: rg[1], step: rg[2], value }) : null;
    const f = h('div', { class: 'field' + (defVal != null && +value !== +defVal ? ' changed' : '') },
      h('div', { class: 'lab' }, doc.label || key, info([doc.what, doc.effect && 'Wirkung: ' + doc.effect, defVal != null && 'Standard: ' + defVal].filter(Boolean).join('\n\n')), h('span', { class: 'code' }, key)),
      h('div', { class: 'ctl' }, slider, inp), doc.unit ? h('div', { class: 'hint' }, doc.unit) : null);
    const upd = (v) => { const x = v === '' ? null : +v; setField(key, x, isParam); inp.value = v; if (slider) slider.value = v; f.classList.toggle('changed', defVal != null && x !== +defVal); };
    inp.oninput = () => upd(inp.value); if (slider) slider.oninput = () => upd(slider.value);
    return f;
  };
  const form = h('div', null,
    h('div', { class: 'form-group' }, 'Strategie und Daten'),
    h('div', { class: 'field' }, h('div', { class: 'lab' }, 'Strategie'), seg(Object.entries(STRAT), R.strategy, v => { const keep = { capital: R.capital, days: R.days }; LAB.req = { ...labDefaults(v), ...keep }; LAB.result = null; LAB.sweep = null; paint(); runLab(paint); })),
    h('div', { class: 'field' }, h('div', { class: 'lab' }, 'Kerzenintervall', info(docs['wallet.interval'].what + '\n\n' + docs['wallet.interval'].effect)), seg(META.intervals.map(i => [i, i]), R.interval, v => { R.interval = v; paint(); })),
    h('div', { class: 'field' }, h('div', { class: 'lab' }, 'Zeitraum'), seg([[365, '1 Jahr'], [730, '2 Jahre'], [1460, '4 Jahre']], R.days, v => { R.days = v; paint(); })),
    h('div', { class: 'field' }, h('div', { class: 'lab' }, 'Startkapital', h('span', { class: 'code' }, 'USDT')), h('div', { class: 'ctl' }, seg([[100, '100'], [10000, '10.000']], R.capital, v => { R.capital = v; paint(); }))),
    h('div', { class: 'form-group' }, 'Strategie-Parameter'),
    ...Object.entries(R.params).map(([k, v]) => {
      const doc = docs[`${R.strategy}.${k}`] || { label: k };
      if (typeof def[k] === 'boolean') {
        const cb = h('input', { type: 'checkbox', checked: v });
        cb.onchange = () => { R.params[k] = cb.checked; };
        return h('div', { class: 'field' }, h('label', { class: 'lab' }, cb, doc.label, info(doc.what + '\n\nWirkung: ' + doc.effect), h('span', { class: 'code' }, k)));
      }
      return numField(k, v, doc, true, def[k]);
    }),
    h('div', { class: 'form-group' }, 'Positionsgröße und Kosten'),
    numField('fraction', R.fraction, docs['wallet.position_fraction'], false, 0.33),
    numField('fee', R.fee, docs['wallet.fee_rate'], false, 0.001),
    numField('slippage_bps', R.slippage_bps, docs['wallet.slippage_bps'], false, 5));
  const actions = h('div', { class: 'row', style: 'margin-top:14px' },
    h('button', { class: 'btn primary', disabled: LAB.busy, onclick: () => runLab(paint) }, LAB.busy ? h('span', { class: 'spinner' }) : null, LAB.busy ? 'Rechnet …' : 'Backtest starten'),
    h('button', { class: 'btn', onclick: () => { LAB.req = labDefaults(R.strategy); paint(); } }, 'Standardwerte'));
  const left = h('details', { class: 'card sticky labform', open: LAB.formOpen ?? window.innerWidth > 1100, ontoggle: (e) => { LAB.formOpen = e.target.open; } }, h('summary', null, 'Parameter anpassen', h('span', { class: 'small muted' }, `${STRAT[R.strategy]} · ${R.interval}`)), h('div', { class: 'bd' }, form, actions, h('div', { class: 'small muted', style: 'margin-top:10px' }, 'Ein blauer Punkt markiert Werte, die vom Standard abweichen. Das i-Symbol erklärt jeden Parameter.')));
  const tabs = [['result', 'Ergebnis'], ['sweep', 'Sensitivität'], ['compare', `Vergleich (${LAB.pinned.length})`], ['saved', 'Gespeicherte Tests']];
  const tabBar = h('div', { class: 'tabs' }, tabs.map(([k, l]) => h('button', { class: k === LAB.tab ? 'on' : '', onclick: () => { LAB.tab = k; paint(); } }, l)));
  const fns = [];
  let right;
  if (LAB.tab === 'result') right = labResult(fns, paint);
  else if (LAB.tab === 'sweep') right = labSweep(fns, paint);
  else if (LAB.tab === 'compare') right = labCompare(fns, paint);
  else { right = h('div', { class: 'skeleton' }, 'Lädt …'); labSaved(right, fns); }
  return { node: h('div', { class: 'split' }, left, h('div', { style: 'min-width:0' }, tabBar, right)), fns };
}
function labKpis(m) {
  return h('div', { class: 'kpis' },
    kpi('Rendite', pct(m.return), 'Buy & Hold ' + pct(m.bh_return), tone(m.return), M('return')), kpi('Rendite p. a.', pct(m.cagr), null, tone(m.cagr), M('cagr')),
    kpi('Max. Drawdown', pct(-m.max_drawdown), 'Buy & Hold ' + pct(-m.bh_max_drawdown), '', M('max_drawdown')), kpi('Sharpe', num(m.sharpe), null, '', M('sharpe')),
    kpi('Calmar', num(m.calmar), null, '', M('calmar')), kpi('Volatilität p. a.', pct(m.volatility, 1, false), null, '', M('volatility')),
    kpi('Trades', m.trades, m.avg_hold == null ? '' : 'Ø ' + days(m.avg_hold), '', M('trades')), kpi('Trefferquote', m.win_rate == null ? '–' : pct(m.win_rate, 0, false), null, '', M('win_rate')),
    kpi('Profit-Faktor', num(m.profit_factor), null, '', M('profit_factor')), kpi('Erwartungswert', signed(m.expectancy), 'USDT je Trade', tone(m.expectancy), M('expectancy')),
    kpi('Gebühren', money(m.fees), pct(m.fees / (m.end_equity / (1 + m.return)), 1, false) + ' vom Start', '', M('fees')), kpi('Investitionsgrad', pct(m.exposure, 0, false), null, '', M('exposure')));
}
function labResult(fns, paint) {
  if (LAB.error) return card('Fehler', h('div', { class: 'down' }, LAB.error));
  const res = LAB.result;
  if (!res) return h('div', { class: 'skeleton' }, h('div', { class: 'spinner', style: 'margin:0 auto 10px' }), 'Backtest läuft …');
  const m = res.metrics, rq = res.request, S = SERIES();
  const c1 = lineChart([{ name: 'Strategie', color: S[0], data: res.curve }, { name: 'Buy & Hold', color: css('--bench'), dashed: true, data: res.bh_curve }], { size: 'lg', name: 'backtest-wert', group: 'lab' });
  const c2 = lineChart([{ name: 'Drawdown', color: css('--candle-down'), area: true, fill: alpha(css('--candle-down'), 0.18), data: res.drawdown }], { size: 'sm', name: 'backtest-drawdown', group: 'lab', logable: false });
  fns.push(c1.after, c2.after);
  const changed = Object.entries(rq.params).filter(([k, v]) => META.defaults[rq.strategy][k] !== v);
  const per = Object.entries(m.per_symbol || {}).map(([s, x]) => ({ s, ...x }));
  const pin = h('button', { class: 'btn sm', onclick: () => {
    const label = `${STRAT[rq.strategy]} ${rq.interval}` + (changed.length ? ' · ' + changed.map(([k, v]) => `${k}=${v}`).join(', ') : ' · Standard');
    LAB.pinned = [...LAB.pinned.filter(p => p.label !== label), { label, metrics: m, curve: res.curve, request: rq }].slice(-6); store.set('lab.pinned', LAB.pinned); paint(); } }, '+ Zum Vergleich');
  const verdict = m.return > m.bh_return ? ['besser als Buy & Hold', 'ok'] : m.max_drawdown < m.bh_max_drawdown && m.return > 0 ? ['weniger Rendite, aber weniger Risiko als Buy & Hold', 'warn'] : ['schlechter als Buy & Hold', 'bad'];
  return h('div', { class: 'stack' },
    h('div', { class: 'row' }, badge(verdict[0], verdict[1], true), h('span', { class: 'small muted' }, `${STRAT[rq.strategy]} · ${rq.interval} · ${dday(m.period[0])} bis ${dday(m.period[1])} · Start ${money(rq.capital, 0)} USDT` + (changed.length ? ' · geändert: ' + changed.map(([k, v]) => `${k} = ${v}`).join(', ') : ' · Standardparameter')), h('span', { class: 'grow' }), pin),
    labKpis(m),
    card('Wertentwicklung gegen Buy & Hold', c1.node, { tip: 'Buy & Hold: am ersten Tag gleichgewichtet BTC, ETH und SOL gekauft und gehalten, mit denselben Gebühren.' }),
    card('Drawdown', c2.node, { tip: M('max_drawdown') }),
    h('div', { class: 'grid g2' }, card('Monatsrenditen · Strategie', heatmap(res.monthly, 'Strategie')), card('Monatsrenditen · Buy & Hold', heatmap(res.bh_monthly, 'Buy & Hold'))),
    h('div', { class: 'grid g2' },
      card('Verteilung der Trade-Ergebnisse', histogram(res.trades.map(t => t.pnl_pct)), { tip: 'Anzahl Trades je Ergebnisbereich in Prozent.' }),
      card('Ergebnis je Coin', table([{ h: 'Coin', a: 'l', render: x => coin(x.s) }, { h: 'Trades', render: x => x.trades, sort: x => x.trades }, { h: 'Treffer', render: x => pct(x.win_rate, 0, false), sort: x => x.win_rate }, { h: 'Ergebnis USDT', render: x => signed(x.pnl), cls: x => tone(x.pnl), sort: x => x.pnl }], per, { empty: 'Keine Trades.', sortKey: 'Ergebnis USDT' }), { flush: true })),
    card(`Trades (${res.trades.length})`, table([
      { h: 'Coin', a: 'l', render: t => coin(t.symbol), sort: t => t.symbol }, { h: 'Einstieg', a: 'l', render: t => dday(t.opened), sort: t => t.opened }, { h: 'Ausstieg', a: 'l', render: t => dday(t.closed), sort: t => t.closed },
      { h: 'Dauer', render: t => days(t.hold_days), sort: t => t.hold_days }, { h: 'Einstieg', render: t => price(t.entry) }, { h: 'Ausstieg', render: t => price(t.exit) },
      { h: 'Ergebnis', render: t => signed(t.pnl), cls: t => tone(t.pnl), sort: t => t.pnl }, { h: '%', render: t => pct(t.pnl_pct), cls: t => tone(t.pnl_pct), sort: t => t.pnl_pct }],
    res.trades, { maxH: 420, sortKey: 'Ausstieg' }), { flush: true }));
}
function sweepValues(key) {
  const doc = META.params[`${LAB.req.strategy}.${key}`] || META.params['wallet.' + key] || {}, rg = doc.range, cur = +(LAB.req.params[key] ?? LAB.req[key]);
  if (!rg) return [];
  const [lo, hi, st] = rg, span = (hi - lo) / 6, vals = new Set();
  for (let i = -2; i <= 3; i++) { let v = cur + i * Math.max(st, Math.round(span / 2 / st) * st); v = Math.round(Math.min(hi, Math.max(lo, v)) / st) * st; vals.add(+v.toFixed(6)); }
  return [...vals].sort((a, b) => a - b);
}
function labSweep(fns, paint) {
  const R = LAB.req;
  const keys = Object.keys(R.params).filter(k => typeof R.params[k] === 'number' && (META.params[`${R.strategy}.${k}`] || {}).range);
  const sel = h('select', { class: 'inp', style: 'width:auto' }, keys.map(k => h('option', { value: k, selected: LAB.sweepKey === k }, (META.params[`${R.strategy}.${k}`] || {}).label + ' (' + k + ')')));
  LAB.sweepKey = LAB.sweepKey && keys.includes(LAB.sweepKey) ? LAB.sweepKey : keys[0];
  const vals = h('input', { class: 'inp', style: 'width:260px', value: (LAB.sweepVals && LAB.sweepValsFor === LAB.sweepKey ? LAB.sweepVals : sweepValues(LAB.sweepKey)).join('; ') });
  sel.onchange = () => { LAB.sweepKey = sel.value; LAB.sweepVals = null; paint(); };
  const run = h('button', { class: 'btn primary', disabled: LAB.busy, onclick: async () => {
    const values = vals.value.split(/[;\s]+/).map(v => v.replace(',', '.')).filter(Boolean).map(Number).filter(v => !Number.isNaN(v)).slice(0, 8);
    LAB.sweepVals = values; LAB.sweepValsFor = LAB.sweepKey; LAB.busy = true; paint();
    try { LAB.sweep = await post('lab/sweep', { ...R, param: LAB.sweepKey, values }); LAB.error = null; } catch (e) { LAB.sweep = { error: e.message }; }
    LAB.busy = false; paint(); } }, LAB.busy ? h('span', { class: 'spinner' }) : null, LAB.busy ? 'Rechnet …' : 'Scan starten');
  const doc = META.params[`${R.strategy}.${LAB.sweepKey}`] || {};
  const controls = card('Parameter-Sensitivität', h('div', { class: 'stack' },
    h('p', { class: 'ink2', style: 'margin:0' }, 'Rechnet denselben Backtest mehrmals und verändert dabei nur einen Parameter. Robuste Strategien zeigen über benachbarte Werte ähnliche Ergebnisse. Wenn nur ein einzelner Wert gut aussieht, ist das meist Zufall (Überanpassung).'),
    h('div', { class: 'row' }, sel, vals, run), doc.what ? h('div', { class: 'small muted' }, doc.what, ' ', doc.effect) : null));
  const out = [controls];
  const sw = LAB.sweep;
  if (sw?.error) out.push(card('Fehler', h('div', { class: 'down' }, sw.error)));
  else if (sw && sw.rows) {
    const S = SERIES();
    const best = Math.max(...sw.rows.map(r => r.return));
    const bar = (v, mx, col) => h('div', { style: 'display:flex;align-items:center;gap:8px;justify-content:flex-end' }, h('span', null, pct(v)), h('div', { class: 'meter', style: 'width:90px' }, h('i', { style: `width:${Math.max(0, Math.min(1, Math.abs(v) / mx)) * 100}%;background:${col}` })));
    const mxR = Math.max(...sw.rows.map(r => Math.abs(r.return))) || 1, mxD = Math.max(...sw.rows.map(r => r.max_drawdown)) || 1;
    const ch = lineChart([...sw.rows.map((r, i) => ({ name: `${sw.param} = ${r.value}`, color: S[i % 8], data: r.curve }))], { size: 'lg', name: 'sensitivitaet-' + sw.param });
    fns.push(ch.after);
    out.push(card(`Ergebnis je Wert von ${(META.params[`${R.strategy}.${sw.param}`] || {}).label || sw.param}`, table([
      { h: 'Wert', a: 'l', render: r => h('b', null, String(r.value)) },
      { h: 'Rendite', render: r => bar(r.return, mxR, r.return >= 0 ? 'var(--div-pos)' : 'var(--div-neg)'), sort: r => r.return, cls: r => r.return === best ? 'up' : '' },
      { h: 'Max. DD', render: r => bar(-r.max_drawdown, mxD, 'var(--div-neg)'), sort: r => r.max_drawdown },
      { h: 'Sharpe', render: r => num(r.sharpe), sort: r => r.sharpe }, { h: 'Calmar', render: r => num(r.calmar), sort: r => r.calmar },
      { h: 'Trades', render: r => r.trades, sort: r => r.trades }, { h: 'Treffer', render: r => r.win_rate == null ? '–' : pct(r.win_rate, 0, false) },
      { h: 'Gebühren', render: r => money(r.fees), sort: r => r.fees }], sw.rows), { flush: true, foot: `Buy & Hold im gleichen Zeitraum: ${pct(sw.bh_return)}` }));
    out.push(card('Verläufe im Vergleich', ch.node));
  }
  return h('div', { class: 'stack' }, out);
}
function labCompare(fns, paint) {
  const P = LAB.pinned;
  if (!P.length) return card('Vergleich', empty('Noch nichts gemerkt. Starte einen Backtest und klicke auf „+ Zum Vergleich“. So kannst du bis zu 6 Varianten nebeneinanderlegen.'));
  const S = SERIES();
  const ch = lineChart(P.map((p, i) => ({ name: p.label, color: S[i % 8], data: p.curve })), { size: 'lg', name: 'vergleich' });
  fns.push(ch.after);
  const metricsRows = [['Rendite', 'return', pct], ['Rendite p. a.', 'cagr', pct], ['Max. Drawdown', 'max_drawdown', v => pct(-v)], ['Sharpe', 'sharpe', num], ['Calmar', 'calmar', num], ['Trades', 'trades', v => v], ['Trefferquote', 'win_rate', v => pct(v, 0, false)], ['Profit-Faktor', 'profit_factor', num], ['Gebühren', 'fees', money], ['Buy & Hold', 'bh_return', pct]];
  const tbl = h('div', { class: 'tbl' }, h('table', null,
    h('thead', null, h('tr', null, h('th', { class: 'l' }, 'Kennzahl'), P.map((p, i) => h('th', null, h('span', { class: 'row', style: 'gap:6px;justify-content:flex-end;flex-wrap:nowrap' }, h('span', { class: 'sw', style: 'background:' + S[i % 8] }), 'Variante ' + (i + 1), h('button', { class: 'btn sm ghost', title: 'Entfernen', onclick: () => { LAB.pinned = P.filter(x => x !== p); store.set('lab.pinned', LAB.pinned); paint(); } }, '×')))))),
    h('tbody', null, metricsRows.map(([l, k, f]) => { const vals = P.map(p => p.metrics[k]); const best = k === 'max_drawdown' || k === 'fees' ? Math.min(...vals) : Math.max(...vals);
      return h('tr', null, h('td', { class: 'l' }, h('span', { class: 'row', style: 'gap:6px' }, l, info(M(k)))), P.map((p, i) => h('td', { class: vals[i] === best && P.length > 1 && k !== 'bh_return' && k !== 'trades' ? 'up' : '' }, p.metrics[k] == null ? '–' : f(p.metrics[k])))); }))));
  return h('div', { class: 'stack' }, card('Varianten', h('div', null, h('ol', { class: 'small ink2', style: 'margin:0 0 0 18px;padding:0' }, P.map(p => h('li', null, p.label)))), { actions: h('button', { class: 'btn sm', onclick: () => { LAB.pinned = []; store.set('lab.pinned', []); paint(); } }, 'Alle entfernen') }),
    card('Wertentwicklung', ch.node), card('Kennzahlen', tbl, { flush: true, foot: 'Grün markiert jeweils den besten Wert (beim Drawdown und bei den Gebühren den niedrigsten).' }));
}
async function labSaved(el, fns) {
  const runs = await api('analytics/backtests');
  const R = runs.filter(r => r.kind === 'run').sort((a, b) => (a.strategy + a.interval).localeCompare(b.strategy + b.interval) || b.capital - a.capital);
  const W = runs.filter(r => r.kind === 'walkforward');
  const S = SERIES(), big = R.filter(r => r.capital === 10000);
  const ch = lineChart([...big.map((r, i) => ({ name: `${STRAT[r.strategy]} ${r.interval}`, color: S[i % 8], data: r.curve })), big[0] ? { name: 'Buy & Hold', color: css('--bench'), dashed: true, data: big[0].bh_curve } : null].filter(Boolean), { size: 'lg', name: 'standard-backtests' });
  const node = h('div', { class: 'stack' },
    h('div', { class: 'banner note' }, 'Diese Tests sind die Referenz für die Live-Bots: Standardparameter, 4 Jahre, gleiche Kosten. Sie werden mit dem Backtest-Werkzeug erstellt und gespeichert.'),
    card('Standard-Backtests (10.000 USDT)', ch.node),
    card('Kennzahlen', table([
      { h: 'Strategie', a: 'l', render: r => `${STRAT[r.strategy]} · ${r.interval}`, sort: r => r.strategy + r.interval }, { h: 'Kapital', render: r => money(r.capital, 0), sort: r => r.capital },
      { h: 'Rendite', render: r => pct(r.metrics.return), cls: r => tone(r.metrics.return), sort: r => r.metrics.return }, { h: 'Buy & Hold', render: r => pct(r.metrics.bh_return) },
      { h: 'Max. DD', render: r => pct(-r.metrics.max_dd), sort: r => r.metrics.max_dd }, { h: 'Sharpe', render: r => num(r.metrics.sharpe), sort: r => r.metrics.sharpe },
      { h: 'Trades', render: r => r.metrics.trades, sort: r => r.metrics.trades }, { h: 'Profit-F.', render: r => num(r.metrics.profit_factor), sort: r => r.metrics.profit_factor }, { h: 'Gebühren', render: r => money(r.metrics.fees), sort: r => r.metrics.fees }], R), { flush: true }),
    card('Walk-Forward-Tests', h('div', { class: 'stack' }, W.map(w => h('div', null, h('div', { class: 'row', style: 'margin-bottom:6px' }, h('b', null, `${STRAT[w.strategy]} · ${w.interval}`), badge('optimiert ' + pct(w.metrics.cumulative.opt), tone(w.metrics.cumulative.opt) === 'up' ? 'ok' : 'bad'), badge('Standard ' + pct(w.metrics.cumulative.def)), badge('Buy & Hold ' + pct(w.metrics.cumulative.bh))),
      table([{ h: 'Test ab', a: 'l', render: x => x.test_start }, { h: 'Gewählte Parameter', a: 'l', render: x => h('span', { class: 'code' }, Object.entries(x.params || {}).map(([k, v]) => `${k}=${v}`).join(' ')) }, { h: 'Optimiert', render: x => pct(x.optimized), cls: x => tone(x.optimized) }, { h: 'Standard', render: x => pct(x.default), cls: x => tone(x.default) }, { h: 'Buy & Hold', render: x => pct(x.buy_hold) }], w.metrics.windows || [])))), { tip: M('walkforward') }));
  el.replaceWith(node);
  ch.after();
}

// ================================================================= Strategien
async function strategiesPage() {
  const list = await api('strategies');
  const cards = list.map(s => {
    const key = s.strategy;
    const params = { ...(META.defaults[key] || {}), ...(s.params || {}) };
    const docs = Object.fromEntries(Object.entries(META.params).filter(([k]) => k.startsWith(key + '.')).map(([k, v]) => [k.split('.')[1], v]));
    const runs = s.backtests.filter(b => b.kind === 'run').sort((a, b) => b.capital - a.capital), wf = s.backtests.find(b => b.kind === 'walkforward');
    return card(s.title, h('div', { class: 'stack' },
      h('p', { style: 'margin:0;font-size:15px' }, s.summary),
      h('div', { class: 'grid g2' },
        h('div', { class: 'prose' }, h('h3', null, 'So funktioniert sie'), s.how_it_works.map(t => h('p', null, t))),
        h('div', { class: 'prose' }, h('h3', null, 'Einstieg'), h('ul', null, s.entry.map(t => h('li', null, t))), h('h3', null, 'Ausstieg'), h('ul', null, s.exit.map(t => h('li', null, t))),
          h('h3', null, 'Positionsgröße'), h('p', null, s.sizing), h('h3', null, 'Ausführung und Kosten'), h('p', null, s.execution))),
      h('details', { class: 'box' }, h('summary', null, 'Alle Parameter mit Erklärung'), h('div', null, paramTable(params, docs))),
      h('details', { class: 'box' }, h('summary', null, 'Schwächen und Risiken'), h('div', { class: 'prose' }, h('ul', null, s.weaknesses.map(t => h('li', null, t))))),
      s.findings.length ? h('details', { class: 'box', open: true }, h('summary', null, 'Erkenntnisse aus den Tests'), h('div', { class: 'prose' }, h('ul', null, s.findings.map(t => h('li', null, t))))) : null,
      runs.length ? h('details', { class: 'box', open: true }, h('summary', null, 'Backtest (4 Jahre, Standardparameter)'), h('div', null, table([
        { h: 'Kapital', render: r => money(r.capital, 0) }, { h: 'Rendite', render: r => pct(r.metrics.return), cls: r => tone(r.metrics.return) }, { h: 'Buy & Hold', render: r => pct(r.metrics.bh_return) },
        { h: 'Max. DD', render: r => pct(-r.metrics.max_dd) }, { h: 'Sharpe', render: r => num(r.metrics.sharpe) }, { h: 'Trades', render: r => r.metrics.trades }, { h: 'Profit-F.', render: r => num(r.metrics.profit_factor) }], runs),
        wf ? h('div', { class: 'small muted', style: 'margin-top:8px' }, `Walk-Forward (ungesehene Zeiträume): optimiert ${pct(wf.metrics.cumulative.opt)}, Standard ${pct(wf.metrics.cumulative.def)}, Buy & Hold ${pct(wf.metrics.cumulative.bh)}.`) : null)) : null,
      h('div', { class: 'row' }, s.live.map(w => h('a', { class: 'btn sm', href: '#/bots/' + encodeURIComponent(w.name) }, w.name, ' ', h('span', { class: tone(w.return) }, pct(w.return, 2)))), h('span', { class: 'grow' }),
        h('a', { class: 'btn sm primary', href: '#/lab?' + new URLSearchParams({ strategy: key, interval: s.interval || '1d', params: JSON.stringify(s.params || {}) }) }, 'Im Labor ausprobieren'))),
      { sub: `${s.family} · ${s.market}` });
  });
  return { node: h('div', { class: 'stack' }, pageHead('Strategien', 'Wie jede Strategie entscheidet, welche Parameter sie hat und was die Tests über sie sagen. Alle laufen nur mit virtuellem Geld.'), ...cards) };
}

// ================================================================= Master & System
async function systemPage(r, ctx) {
  const [sys, wallets, events] = await Promise.all([api('system'), api('wallets'), api('events?limit=80')]);
  const m = ctx.master, rep = m.report, rules = rep ? rep.rules : {};
  const risk = rep ? rep.wallets : [];
  const ruleRows = [
    ['Max. Drawdown je Wallet', pct(rules.max_drawdown, 0, false), 'Wird er überschritten, pausiert der Master die Wallet: keine neuen Einstiege, offene Positionen laufen normal aus. Freigabe nur manuell.'],
    ['Max. Tagesverlust', pct(rules.daily_loss, 0, false), 'Verlust innerhalb von 24 Stunden, der eine Pause auslöst.'],
    ['Qualitätswarnung', `ab ${rules.min_trades_for_quality} Trades bei Profit-Faktor unter ${num(rules.min_profit_factor, 1)}`, 'Nur ein Hinweis im Protokoll, kein Stopp. Paper-Trading dient dem Lernen.'],
    ['Heartbeat-Toleranz', `${rules.heartbeat_max_age_s} s`, 'Meldet sich ein Dienst länger nicht, entsteht ein Fehler-Ereignis.'],
    ['Kursdaten-Alter', `${rules.candle_max_age_s} s`, 'Sind die 15-Minuten-Kerzen älter, entsteht ein Fehler-Ereignis.'],
    ['Kill-Switch', 'manuell', 'Schließt alle Positionen aller Wallets sofort zum aktuellen Kurs und stoppt neue Einstiege.']];
  const node = h('div', { class: 'stack' },
    pageHead('Master & System', 'Der Master-Bot prüft alle 30 Sekunden Dienste, Kursdaten und das Risiko jeder Wallet. Hier steuerst du Pausen und den Kill-Switch.'),
    h('div', { class: 'kpis' },
      kpi('Master-Bot', m.age_s != null && m.age_s < 120 ? 'aktiv' : 'keine Meldung', m.age_s == null ? '' : 'letzte Prüfung vor ' + ago(m.age_s), m.age_s != null && m.age_s < 120 ? 'up' : 'down'),
      ...Object.entries(sys.heartbeats).map(([k, v]) => kpi('Dienst ' + k, v == null ? 'kein Signal' : v < 60 ? 'aktiv' : 'Störung', v == null ? '' : 'vor ' + ago(v), v != null && v < 60 ? 'up' : 'down')),
      kpi('Kill-Switch', m.kill_switch ? 'AKTIV' : 'aus', m.kill_switch ? m.kill_reason : 'alle Bots dürfen handeln', m.kill_switch ? 'down' : ''),
      kpi('Datenbank', num(sys.db_bytes / 1e6, 0) + ' MB', 'Redis ' + (sys.redis_ping ? 'ok' : 'Fehler'))),
    card('Notfall-Steuerung', h('div', { class: 'row' },
      m.kill_switch ? h('button', { class: 'btn', onclick: async () => { if (confirm('Kill-Switch aufheben?')) { await post('control/unkill'); refresh(); } } }, 'Kill-Switch aufheben')
        : h('button', { class: 'btn danger', onclick: async () => { if (confirm('KILL-SWITCH\n\nAlle Positionen aller Wallets werden sofort zum aktuellen Kurs geschlossen und es gibt keine neuen Einstiege. Fortfahren?')) { await post('control/kill'); refresh(); } } }, 'Kill-Switch auslösen'),
      h('span', { class: 'small muted' }, 'Gilt für alle Wallets. Aufheben gibt nur den Handel frei; einzeln pausierte Wallets bleiben pausiert.'))),
    card('Wallet-Risiko', table([
      { h: 'Wallet', a: 'l', render: w => walletLink(w.wallet), sort: w => w.wallet }, { h: 'Rendite', render: w => pct(w.return, 2), cls: w => tone(w.return), sort: w => w.return },
      { h: 'Drawdown', render: w => h('div', { style: 'display:flex;gap:8px;align-items:center;justify-content:flex-end' }, pct(-w.drawdown), h('div', { class: 'meter', style: 'width:80px', 'data-tip': `Grenze ${pct(rules.max_drawdown, 0, false)}` }, h('i', { style: `width:${Math.min(1, w.drawdown / rules.max_drawdown) * 100}%;background:${w.drawdown > rules.max_drawdown * 0.7 ? 'var(--bad)' : 'var(--accent)'}` }))), sort: w => w.drawdown, tip: 'Balken: Anteil an der Drawdown-Grenze des Masters.' },
      { h: '24 h', render: w => pct(w.day_change, 2), cls: w => tone(w.day_change), sort: w => w.day_change }, { h: 'Trades', render: w => w.trades }, { h: 'Profit-F.', render: w => num(w.profit_factor) },
      { h: 'Status', a: 'l', render: w => w.status === 'pausiert' ? badge('pausiert', 'warn', true) : badge('aktiv', 'ok', true) },
      { h: '', render: w => (wallets.find(x => x.name === w.wallet) || {}).paused ? h('button', { class: 'btn sm', onclick: async () => { await post('control/resume/' + encodeURIComponent(w.wallet)); refresh(); } }, 'Freigeben')
        : h('button', { class: 'btn sm', onclick: async () => { if (confirm(w.wallet + ' pausieren?')) { await post('control/pause/' + encodeURIComponent(w.wallet)); refresh(); } } }, 'Pausieren') }], risk, { empty: 'Master-Bericht noch nicht verfügbar.' }), { flush: true }),
    h('div', { class: 'grid g2' },
      card('Risikoregeln', table([{ h: 'Regel', a: 'l', render: x => h('b', null, x[0]) }, { h: 'Grenze', a: 'l', render: x => x[1] }, { h: 'Wirkung', a: 'l', wrap: true, render: x => x[2] }], ruleRows), { flush: true }),
      card('Kursdaten', table([{ h: 'Coin', a: 'l', render: c => coin(c.symbol) }, { h: 'Intervall', a: 'l', render: c => c.interval }, { h: 'Kerzen', render: c => nf(0).format(c.n) }, { h: 'ab', render: c => dday(c.first) }, { h: 'Alter', render: c => ago(c.age_s), cls: c => (c.interval === '15m' && c.age_s > 1500) ? 'down' : '' }], sys.candles, { maxH: 380 }), { flush: true })),
    card('Ereignisprotokoll', eventsTable(events), { flush: true }));
  return { node };
}

// ================================================================= Glossar
async function helpPage() {
  const groups = [['trend', 'Trend-Ausbruch'], ['meanrev', 'Mean Reversion'], ['wallet', 'Wallet und Kosten']];
  const node = h('div', { class: 'stack' },
    pageHead('Glossar', 'Alle Kennzahlen, Indikatoren und Parameter an einem Ort erklärt. Dieselben Texte erscheinen im ganzen Dashboard hinter dem i-Symbol.'),
    card('Kennzahlen', table([{ h: 'Begriff', a: 'l', render: x => h('b', null, x[1].label) }, { h: 'Erklärung', a: 'l', wrap: true, render: x => x[1].what }], Object.entries(META.metrics)), { flush: true }),
    card('Indikatoren', table([{ h: 'Indikator', a: 'l', render: x => h('b', null, x[1].label) }, { h: 'Erklärung', a: 'l', wrap: true, render: x => x[1].what }], Object.entries(META.indicators)), { flush: true }),
    ...groups.map(([g, title]) => card('Parameter · ' + title, table([
      { h: 'Parameter', a: 'l', render: x => h('div', null, h('b', null, x[1].label), h('div', { class: 'code' }, x[0].split('.')[1])) }, { h: 'Einheit', a: 'l', render: x => h('span', { class: 'muted' }, x[1].unit) },
      { h: 'Bedeutung', a: 'l', wrap: true, render: x => x[1].what }, { h: 'Wirkung', a: 'l', wrap: true, render: x => x[1].effect }], Object.entries(META.params).filter(([k]) => k.startsWith(g + '.'))), { flush: true })));
  return { node };
}

refresh();
