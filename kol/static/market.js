"use strict";
// Market Conditions page (information only). Uses helpers from app.js: esc, usd, num, pct, api, tile, clock.

const MC = { period: "daily", tip: null };
// Fixed colour per chain (colour follows the entity, never its rank). Tron and Sui (~1% share each) fold into Other.
const MC_SLOT = { "Solana": 1, "Ethereum": 2, "BSC": 3, "Base": 4, "Arbitrum": 5, "Hyperliquid L1": 6, "Robinhood Chain": 7 };
const MC_LAUNCH = { "pump.fun": 1, "pumpswap": 2 };

function mcColor(slot) { return `var(--series-${slot || 8})`; }   // slot 8 = "Other"
function mcArrow(p) { return p == null ? "–" : (p > 0 ? "▲ " : p < 0 ? "▼ " : "– ") + Math.abs(p).toFixed(1) + "%"; }
function mcMoney(v) { return v == null ? "n/a" : (Math.abs(v) < 1000 ? "$" + v.toFixed(2) : usd(v)); }
function mcLabelChip(l) { return l ? `<span class="chip lab-${esc(l.toLowerCase())}">${esc(l)}</span>` : '<span class="chip">n/a</span>'; }
function mcPeriodLabel(iso, kind) {
  const d = new Date(iso + "T00:00:00Z");
  const opt = kind === "monthly" ? { month: "short", year: "numeric", timeZone: "UTC" } : { day: "numeric", month: "short", timeZone: "UTC" };
  return (kind === "weekly" ? "w/c " : "") + d.toLocaleDateString(undefined, opt);
}

// ---- tooltip --------------------------------------------------------------------------------------
function mcTip() {
  if (!MC.tip) { MC.tip = document.createElement("div"); MC.tip.className = "mc-tip hidden"; document.body.appendChild(MC.tip); }
  return MC.tip;
}
function mcShowTip(e, html) {
  const t = mcTip(); t.innerHTML = html; t.classList.remove("hidden");
  const w = t.offsetWidth, h = t.offsetHeight;
  let x = e.clientX + 14, y = e.clientY + 14;
  if (x + w > window.innerWidth - 8) x = e.clientX - w - 14;
  if (y + h > window.innerHeight - 8) y = e.clientY - h - 14;
  t.style.left = x + "px"; t.style.top = y + "px";
}
function mcHideTip() { mcTip().classList.add("hidden"); }

// ---- charts (inline SVG, one y-axis each) ---------------------------------------------------------
function mcNice(max) {
  if (!(max > 0)) return [1, [0, 1]];
  const p = Math.pow(10, Math.floor(Math.log10(max))), n = max / p;
  const step = (n <= 1.5 ? 0.25 : n <= 3 ? 0.5 : n <= 6 ? 1 : 2) * p;
  const top = Math.ceil(max / step) * step;
  const ticks = []; for (let v = 0; v <= top + 1e-9; v += step) ticks.push(v);
  return [top, ticks];
}

function mcBars(el, periods, kind, series, opts = {}) {
  // series: [{name, values, color}] stacked; opts.percent = 100% stacked shares
  const W = opts.W || 640, H = opts.H || 220, L = 52, R = 8, T = 10, B = 24, n = periods.length;
  const totals = periods.map((_, i) => series.reduce((a, s) => a + (s.values[i] || 0), 0));
  const [top, ticks] = opts.percent ? [100, [0, 25, 50, 75, 100]] : mcNice(Math.max(0, ...totals));
  const y = v => T + (H - T - B) * (1 - v / top);
  const band = (W - L - R) / n, bw = Math.max(1, band * 0.78);
  let g = ticks.map(v => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>` +
    `<text class="axis" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${opts.percent ? v + "%" : usd(v).replace(".00", "")}</text>`).join("");
  periods.forEach((p, i) => {
    const x = L + i * band + (band - bw) / 2;
    let base = 0;
    const segs = series.filter(s => s.values[i] != null && s.values[i] > 0);
    segs.forEach((s, k) => {
      const v = s.values[i], y0 = y(base), y1 = y(base + v);
      const h = Math.max(0, y0 - y1 - (k < segs.length - 1 ? 2 : 0));   // 2px surface gap between segments
      const r = k === segs.length - 1 ? Math.min(4, bw / 2, h) : 0;    // rounded data end on top only
      g += r > 0
        ? `<path fill="${s.color}" d="M${x},${y0} V${y0 - h + r} Q${x},${y0 - h} ${x + r},${y0 - h} H${x + bw - r} Q${x + bw},${y0 - h} ${x + bw},${y0 - h + r} V${y0} Z"/>`
        : `<rect fill="${s.color}" x="${x}" y="${y0 - h}" width="${bw}" height="${h}"/>`;
      base += v;
    });
    g += `<rect class="hit" data-i="${i}" x="${L + i * band}" y="${T}" width="${band}" height="${H - T - B}"/>`;
  });
  const lab = [0, Math.floor(n / 2), n - 1].map(i => `<text class="axis" x="${L + i * band + band / 2}" y="${H - 6}" text-anchor="middle">${esc(mcPeriodLabel(periods[i], kind))}</text>`).join("");
  const fmtV = v => v == null ? "n/a" : opts.percent ? v.toFixed(1) + "%" : usd(v);
  const table = `<details class="mc-table"><summary>Table view</summary><div class="tablewrap" style="max-height:240px"><table><tr><th>Period</th>${series.map(s => `<th>${esc(s.name)}</th>`).join("")}</tr>` +
    periods.map((p, i) => i).reverse().map(i => `<tr><td>${esc(mcPeriodLabel(periods[i], kind))}</td>${series.map(s => `<td>${fmtV(s.values[i])}</td>`).join("")}</tr>`).join("") + `</table></div></details>`;
  el.innerHTML = mcLegend(series) + `<svg viewBox="0 0 ${W} ${H}" class="mc-svg" role="img">${g}<line class="base" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/>${lab}</svg>` + table;
  el.querySelectorAll(".hit").forEach(r => {
    r.addEventListener("mousemove", e => {
      const i = Number(r.dataset.i);
      const rows = series.map(s => `<div><span class="sw" style="background:${s.color}"></span>${esc(s.name)} <b>${s.values[i] == null ? "n/a" : opts.percent ? s.values[i].toFixed(1) + "%" : usd(s.values[i])}</b></div>`).join("");
      mcShowTip(e, `<div class="muted">${esc(mcPeriodLabel(periods[i], kind))}</div>${rows}` + (!opts.percent && series.length > 1 ? `<div>Total <b>${usd(totals[i])}</b></div>` : ""));
    });
    r.addEventListener("mouseleave", mcHideTip);
  });
}

function mcLine(el, periods, kind, s, fmt) {
  const W = 300, H = 150, L = 48, R = 8, T = 10, B = 22, n = periods.length;
  const vals = s.values.filter(v => v != null);
  if (!vals.length) { el.innerHTML = `<h4>${esc(s.name)}</h4><p class="muted">No data</p>`; return; }
  let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.08 || hi * 0.05 || 1; lo -= pad; hi += pad;
  const x = i => L + (W - L - R) * (n === 1 ? 0.5 : i / (n - 1));
  const y = v => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  let d = "", pen = false;
  s.values.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); pen = true; });
  const ticks = [lo + pad, (lo + hi) / 2, hi - pad];
  const grid = ticks.map(v => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${L - 5}" y="${y(v) + 4}" text-anchor="end">${esc(fmt(v))}</text>`).join("");
  const lab = [0, n - 1].map(i => `<text class="axis" x="${x(i)}" y="${H - 5}" text-anchor="${i ? "end" : "start"}">${esc(mcPeriodLabel(periods[i], kind))}</text>`).join("");
  el.innerHTML = `<h4>${esc(s.name)}</h4><svg viewBox="0 0 ${W} ${H}" class="mc-svg">${grid}<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2"/>` +
    `<line class="cross hidden" y1="${T}" y2="${H - B}"/><circle class="dot hidden" r="4" fill="${s.color}"/>` +
    `<rect class="hit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}"/>${lab}</svg>`;
  const svg = el.querySelector("svg"), cross = el.querySelector(".cross"), dot = el.querySelector(".dot");
  el.querySelector(".hit").addEventListener("mousemove", e => {
    const b = svg.getBoundingClientRect(), px = (e.clientX - b.left) / b.width * W;
    const i = Math.max(0, Math.min(n - 1, Math.round((px - L) / ((W - L - R) / Math.max(1, n - 1)))));
    const v = s.values[i];
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.classList.remove("hidden");
    if (v != null) { dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(v)); dot.classList.remove("hidden"); } else dot.classList.add("hidden");
    mcShowTip(e, `<div class="muted">${esc(mcPeriodLabel(periods[i], kind))}</div><div>${esc(s.name)} <b>${v == null ? "n/a" : esc(fmt(v))}</b></div>`);
  });
  el.querySelector(".hit").addEventListener("mouseleave", () => { mcHideTip(); cross.classList.add("hidden"); dot.classList.add("hidden"); });
}

function mcSpark(values) {
  const v = values.map((x, i) => [i, x]).filter(p => p[1] != null);
  if (v.length < 2) return "";
  const lo = Math.min(...v.map(p => p[1])), hi = Math.max(...v.map(p => p[1])), n = values.length;
  const d = v.map((p, k) => (k ? "L" : "M") + (p[0] / (n - 1) * 116 + 2).toFixed(1) + "," + (30 - (hi > lo ? (p[1] - lo) / (hi - lo) : 0.5) * 26).toFixed(1)).join("");
  return `<svg viewBox="0 0 120 34" class="spark"><path d="${d}" fill="none" stroke="var(--text-secondary)" stroke-width="1.5"/></svg>`;
}

function mcLegend(series) {
  if (series.length < 2) return "";
  return `<div class="legend">${series.map(s => `<span><span class="sw" style="background:${s.color}"></span>${esc(s.name)}</span>`).join("")}</div>`;
}

// ---- page ------------------------------------------------------------------------------------------
async function renderMarket() {
  $("#main").innerHTML = `
    <div class="card" id="mc-head"><p class="muted">Loading…</p></div>
    <div class="card"><div class="row"><h2 style="margin:0">Charts</h2><span class="spacer"></span>
      <div class="seg" id="mc-period">${["daily", "weekly", "monthly"].map(k => `<button data-k="${k}" class="${k === MC.period ? "on" : ""}">${k[0].toUpperCase() + k.slice(1)}</button>`).join("")}</div></div>
      <p class="note">Completed UTC periods only. Hover a bar or line for values. Daily: last 90 days · Weekly: 52 weeks · Monthly: 24 months.</p>
      <div class="grid2">
        <div><h3>Pump.fun bonding curve and PumpSwap volume</h3><div id="mc-c1"></div></div>
        <div><h3>Solana DEX volume</h3><div id="mc-c2"></div></div>
      </div>
      <h3 style="margin-top:14px">DEX volume share by chain</h3><div id="mc-c3"></div>
      <p class="note">Share of the tracked chains' total. Tron and Sui are grouped as Other (each about 1%).</p>
      <h3 style="margin-top:14px">Stablecoin supply per chain</h3><div class="mc-multi" id="mc-c4"></div>
      <p class="note">One chart per chain, each with its own scale (Ethereum's supply is about 10× Solana's).</p>
      <h3 style="margin-top:14px">SOL and BTC price (daily close, UTC)</h3><div class="mc-multi" id="mc-c5"></div>
    </div>
    <div class="grid2">
      <div class="card"><h2>Manual metrics</h2>
        <p class="note">Numbers with no free API (terminal volume, memecoin share of Solana volume, graduation rate, returning wallets…). They appear in the weekly and monthly reports that cover their date.</p>
        <form id="mc-form" class="mc-form">
          <input name="date_utc" type="date" required aria-label="Date (UTC)">
          <input name="metric" list="mc-metrics" placeholder="Metric" required maxlength="60" aria-label="Metric">
          <datalist id="mc-metrics"><option value="Terminal volume"><option value="Memecoin share of Solana volume %"><option value="Pump.fun graduation rate %"><option value="Returning wallets"></datalist>
          <input name="value" type="number" step="any" placeholder="Value" required aria-label="Value">
          <input name="source_note" placeholder="Source / note" maxlength="200" aria-label="Source note">
          <button type="submit">Add</button>
        </form><p id="mc-form-msg" class="note"></p>
        <div class="tablewrap" style="max-height:260px" id="mc-manual"></div>
      </div>
      <div class="card"><h2>Data health</h2><div id="mc-health"><p class="muted">Loading…</p></div>
        <h3 style="margin-top:12px">Download CSV (mc_daily_metrics)</h3>
        <form id="mc-csv" class="mc-form"><input name="from" type="date" required aria-label="From"><input name="to" type="date" required aria-label="To"><button type="submit">Download</button></form>
      </div>
    </div>
    <div class="card"><h2>Reports</h2><div id="mc-reports"><p class="muted">Loading…</p></div></div>`;
  $("#mc-period").querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    MC.period = b.dataset.k; $("#mc-period").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); mcCharts();
  }));
  const today = new Date(), iso = d => d.toISOString().slice(0, 10);
  const f = $("#mc-csv"); f.from.value = iso(new Date(today - 90 * 864e5)); f.to.value = iso(new Date(today - 864e5));
  f.addEventListener("submit", e => { e.preventDefault(); window.location.href = `api/market/csv?from=${encodeURIComponent(f.from.value)}&to=${encodeURIComponent(f.to.value)}`; });
  const m = $("#mc-form"); m.date_utc.value = iso(new Date(today - 864e5));
  m.addEventListener("submit", async e => {
    e.preventDefault();
    const body = { date_utc: m.date_utc.value, metric: m.metric.value, value: m.value.value, source_note: m.source_note.value };
    const r = await fetch("api/market/manual", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    $("#mc-form-msg").textContent = r.ok ? "Saved." : (j.error || "Could not save");
    if (r.ok) { m.metric.value = ""; m.value.value = ""; m.source_note.value = ""; mcManual(); }
  });
  mcHead(); mcCharts(); mcManual(); mcHealth(); mcReports();
}

async function mcHead() {
  let o; try { o = await api("api/market/overview"); } catch (e) { $("#mc-head").innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
  const [emoji, text] = o.headline;
  const d = new Date(o.date + "T00:00:00Z").toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  $("#mc-head").innerHTML = `<div class="row"><h2 style="margin:0">Market Conditions</h2><span class="spacer"></span><span class="muted">covers ${esc(d)} (UTC)</span></div>
    <div class="mc-headline">${esc(emoji)} ${esc(text)}</div>
    <p class="note">Labels: change vs the previous 7-day average · Rising above +${o.threshold_pct}% · Falling below −${o.threshold_pct}% · Flat in between. Information only: nothing here changes any strategy.</p>
    <div class="tiles">${o.cards.map(c => `<div class="tile"><div class="label">${esc(c.name)}</div><div class="value">${mcMoney(c.value)}</div>
      <div class="sub">${mcLabelChip(c.label)} ${esc(mcArrow(c.chg_avg))} vs 7-day avg</div>${mcSpark(c.spark)}</div>`).join("")}</div>
    ${o.missing.length ? `<p class="warn">⚠️ Missing data: ${esc(o.missing.join(", "))}</p>` : ""}`;
}

async function mcCharts() {
  let s; try { s = await api("api/market/series?period=" + MC.period); } catch (e) { return; }
  const k = s.kind, P = s.periods;
  mcBars($("#mc-c1"), P, k, Object.entries(s.launchpads).map(([n, v]) => ({ name: n === "pump.fun" ? "Pump.fun bonding curve" : "PumpSwap", values: v, color: mcColor(MC_LAUNCH[n]) })));
  mcBars($("#mc-c2"), P, k, [{ name: "Solana DEX", values: s.solana_dex, color: mcColor(1) }]);
  const named = Object.keys(s.shares).filter(c => MC_SLOT[c]);
  const other = Object.keys(s.shares).filter(c => !MC_SLOT[c]);
  const shareSeries = named.map(c => ({ name: c, values: s.shares[c], color: mcColor(MC_SLOT[c]) }));
  if (other.length) shareSeries.push({ name: "Other (" + other.join(", ") + ")", color: mcColor(0),
    values: P.map((_, i) => other.reduce((a, c) => a + (s.shares[c][i] || 0), 0)) });
  mcBars($("#mc-c3"), P, k, shareSeries, { percent: true, W: 1280, H: 300 });
  const c4 = $("#mc-c4"); c4.innerHTML = Object.keys(s.stable).map((_, i) => `<div id="mc-s${i}"></div>`).join("");
  Object.entries(s.stable).forEach(([c, v], i) => mcLine(document.getElementById("mc-s" + i), P, k, { name: c, values: v, color: mcColor(MC_SLOT[c]) }, usd));
  const c5 = $("#mc-c5"); c5.innerHTML = Object.keys(s.price).map((_, i) => `<div id="mc-p${i}"></div>`).join("");
  Object.entries(s.price).forEach(([p, v], i) => mcLine(document.getElementById("mc-p" + i), P, k, { name: p, values: v, color: "var(--series-1)" },
    x => x >= 1000 ? "$" + Math.round(x).toLocaleString() : "$" + x.toFixed(2)));
}

async function mcManual() {
  let rows; try { rows = await api("api/market/manual"); } catch (e) { return; }
  $("#mc-manual").innerHTML = `<table><tr><th>Date</th><th class="l">Metric</th><th>Value</th><th class="l">Source</th></tr>${rows.map(r =>
    `<tr><td>${esc(r.date_utc)}</td><td class="l">${esc(r.metric)}</td><td>${esc(r.value)}</td><td class="l">${esc(r.source_note)}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">None yet</td></tr>'}</table>`;
}

async function mcHealth() {
  let h; try { h = await api("api/market/health"); } catch (e) { return; }
  $("#mc-health").innerHTML = `<p class="note">${num(h.rows)} daily rows, ${esc(h.first_day || "–")} to ${esc(h.last_day || "–")}${h.fetch_running ? " · fetch running now" : ""}. Daily fetch at 01:30 UTC.</p>
    <div class="tablewrap"><table><tr><th>Source</th><th>Last success</th><th class="l">Latest errors</th></tr>${h.sources.map(s =>
      `<tr><td>${esc(s.code)} · ${esc(s.name)}</td><td>${s.enabled ? clock(s.last_ok) : "disabled"}</td><td class="l" style="white-space:normal">${!s.enabled ? esc(s.note) : s.errors.length ? s.errors.map(e => `<span class="bad">${esc(clock(e.at))} ${esc(e.key)}: ${esc(e.error)}</span>`).join("<br>") : '<span class="muted">none</span>'}</td></tr>`).join("")}</table></div>
    <h3 style="margin-top:10px">Recent fetch runs</h3><div class="tablewrap"><table><tr><th>Finished</th><th>Kind</th><th>Rows</th><th>OK</th><th class="l">Failed</th></tr>${h.runs.map(r =>
      `<tr><td>${clock(r.finished)}</td><td>${esc(r.kind)}</td><td>${num(r.rows)}</td><td>${num(r.ok)}</td><td class="l" style="white-space:normal">${r.failed.length ? `<span class="bad">${esc(r.failed.join("; "))}</span>` : '<span class="muted">none</span>'}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">No runs yet</td></tr>'}</table></div>`;
}

async function mcReports() {
  let rows; try { rows = await api("api/market/reports"); } catch (e) { return; }
  $("#mc-reports").innerHTML = rows.length ? rows.map(r => `<details class="mc-report"><summary><b>${esc(r.period_type)}</b> · ${esc(r.start)}${r.end !== r.start ? " – " + esc(r.end) : ""} · generated ${clock(r.generated)} · ${r.sent ? '<span class="good">sent</span>' : '<span class="muted">not sent</span>'}</summary>
      <pre>${esc(r.text)}</pre><button class="mc-send" data-id="${r.id}">Send to Telegram</button> <span class="note" id="mc-sent-${r.id}"></span></details>`).join("")
    : '<p class="muted">No reports yet. The first daily report is made at 08:00 London time.</p>';
  $("#mc-reports").querySelectorAll(".mc-send").forEach(b => b.addEventListener("click", async () => {
    b.disabled = true;
    const r = await fetch(`api/market/reports/${b.dataset.id}/send`, { method: "POST" });
    const j = await r.json().catch(() => ({}));
    document.getElementById("mc-sent-" + b.dataset.id).textContent = r.ok ? "Sent." : (j.error || "Send failed");
    b.disabled = false;
  }));
}
