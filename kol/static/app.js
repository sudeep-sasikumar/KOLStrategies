"use strict";
// KOL Strategies dashboard. All links are relative: the page is served under /kol/ on the VPS.

const state = { strategies: [], tab: localGet("tab") || "overview", days: Number(localGet("days")) || 7,
                col: {}, timers: [] };

function localGet(k) { try { return localStorage.getItem("kol." + k); } catch (e) { return null; } }
function localSet(k, v) { try { localStorage.setItem("kol." + k, v); } catch (e) { /* private mode */ } }

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const $ = sel => document.querySelector(sel);

async function api(path) {
  const r = await fetch(path, { credentials: "same-origin" });
  if (r.status === 401) { showLogin(); throw new Error("login required"); }
  if (!r.ok) throw new Error(path + ": HTTP " + r.status);
  return r.json();
}

// ---- formatting ---------------------------------------------------------------------------------
function usd(v) {
  if (v == null) return "–";
  const a = Math.abs(v);
  if (a >= 1e9) return "$" + (v / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return "$" + (v / 1e6).toFixed(2) + "M";
  if (a >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
  return "$" + v.toFixed(0);
}
function num(v, d = 0) { return v == null ? "–" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }); }
function pct(v, d = 1) { return v == null ? "–" : Number(v).toFixed(d) + "%"; }
function mult(v) {
  if (v == null) return "–";
  const cls = v >= 2 ? "good" : v < 1 ? "bad" : "";
  return `<span class="${cls}">${v.toFixed(v >= 10 ? 0 : 2)}x</span>`;
}
function ago(ts) {
  if (!ts) return "–";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return Math.floor(s) + "s";
  if (s < 3600) return Math.floor(s / 60) + "m";
  if (s < 86400) return (s / 3600).toFixed(1) + "h";
  return (s / 86400).toFixed(1) + "d";
}
function ageMin(m) { return m == null ? "–" : m < 1 ? Math.round(m * 60) + "s" : m < 60 ? m.toFixed(1) + "m" : (m / 60).toFixed(1) + "h"; }
function clock(ts) { return ts ? new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "–"; }
function tokenCell(r) {
  const label = (r.symbol ? "$" + r.symbol : r.mint.slice(0, 6)) + (r.name ? " · " + r.name : "");
  return `<span class="name" title="${esc(r.name)} ${esc(r.mint)}">${esc(label)}</span>`;
}
function links(mint) {
  const m = encodeURIComponent(mint);
  return `<span class="links"><a href="https://dexscreener.com/solana/${m}" target="_blank" rel="noopener noreferrer">dex</a>` +
         `<a href="https://pump.fun/coin/${m}" target="_blank" rel="noopener noreferrer">pump</a>` +
         `<a href="https://solscan.io/token/${m}" target="_blank" rel="noopener noreferrer">scan</a></span>`;
}
function tile(label, value, sub) {
  return `<div class="tile"><div class="label">${esc(label)}</div><div class="value">${value}</div>` +
         (sub ? `<div class="sub">${sub}</div>` : "") + `</div>`;
}
function chip(q) { return `<span class="chip ${esc(q)}">${esc(q)}</span>`; }

// ---- login --------------------------------------------------------------------------------------
function showLogin() { $("#login").classList.remove("hidden"); $("#pw").focus(); }
$("#login-form").addEventListener("submit", async e => {
  e.preventDefault();
  $("#login-err").textContent = "";
  const r = await fetch("login", { method: "POST", headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ password: $("#pw").value }) });
  if (r.ok) { $("#login").classList.add("hidden"); $("#pw").value = ""; boot(); }
  else { const j = await r.json().catch(() => ({})); $("#login-err").textContent = j.error || "Sign-in failed"; }
});

// ---- header -------------------------------------------------------------------------------------
async function refreshStatus() {
  try {
    const s = await api("api/status");
    state.status = s;
    const ws = s.ws_connected ? `<span class="dot ok"></span>stream live` : `<span class="dot bad"></span>stream down`;
    $("#pills").innerHTML = [
      `<span class="pill">${ws}</span>`,
      `<span class="pill">last token ${ago(s.last_create_at)} ago</span>`,
      `<span class="pill">SOL ${s.sol_usd ? "$" + s.sol_usd.toFixed(2) : "–"}</span>`,
      `<span class="pill">${num(s.followed)} tokens followed</span>`,
      `<span class="pill">v ${esc(s.version)}</span>`,
    ].join("");
    if (state.tab === "overview") renderOverview();
  } catch (e) { /* shown on next success */ }
}

// ---- tabs ---------------------------------------------------------------------------------------
function renderTabs() {
  const tabs = [{ key: "overview", name: "Overview" }, { key: "market", name: "Market Conditions" },
                ...state.strategies.map(s => ({ key: s.key, name: s.name }))];
  if (!tabs.some(t => t.key === state.tab)) state.tab = "overview";
  $("#tabs").innerHTML = tabs.map(t =>
    `<button class="tab ${t.key === state.tab ? "active" : ""}" role="tab" data-tab="${esc(t.key)}">${esc(t.name)}</button>`).join("");
  $("#tabs").querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    state.tab = b.dataset.tab; localSet("tab", state.tab); renderTabs(); openTab();
  }));
}

function clearTimers() { state.timers.forEach(clearInterval); state.timers = []; }

function openTab() {
  clearTimers();
  if (state.tab === "overview") { renderOverview(); return; }
  if (state.tab === "market") { renderMarket(); return; }
  const s = state.strategies.find(x => x.key === state.tab);
  renderStrategy(s);
}

// ---- overview -----------------------------------------------------------------------------------
function renderOverview() {
  const s = state.status;
  if (!s) return;
  const up = (Date.now() / 1000 - s.started);
  $("#main").innerHTML = `
    <div class="card"><h2>Collector</h2><div class="tiles">
      ${tile("Uptime", ago(s.started))}
      ${tile("New tokens seen", num(s.creates), "since this start, " + num(s.creates / Math.max(up / 3600, 1 / 60), 0) + " per hour")}
      ${tile("Migrations seen", num(s.migrations))}
      ${tile("Tokens followed", num(s.followed), num(s.live) + " in their first 20 min")}
      ${tile("DexScreener calls", num(s.dex.requests), s.dex.errors ? esc(s.dex.errors + " errors · " + s.dex.last_error) : "no errors")}
      ${tile("Solana RPC calls", num(s.rpc.calls), (s.rpc.public ? "public RPC" : "private RPC") + (s.rpc.errors ? " · " + esc(s.rpc.errors + " retries · " + s.rpc.last_error) : ""))}
      ${tile("On-chain audits", num(s.rpc.audits), num(s.rpc.queue) + " queued" + (s.rpc.audit_errors ? " · " + num(s.rpc.audit_errors) + " failed" : ""))}
      ${tile("Token metadata", num(s.meta.ok), (s.meta.failed ? num(s.meta.failed) + " failed · " : "") + num(s.meta.queue) + " queued")}
      ${tile("Database", num(s.db_mb, 1) + " MB")}
    </div></div>
    <div class="grid2">
      <div class="card"><h2>Strategies</h2>
        ${state.strategies.map(x => `<p><a href="#" data-go="${esc(x.key)}">${esc(x.name)}</a><br><span class="note">${esc(x.summary)}</span></p>`).join("")}
        <h3>How far to trust a filter</h3>
        <p class="note">${chip("exact")} read directly (pump.fun event, DexScreener, on-chain balances)<br>
        ${chip("approx")} our reading of the trader's definition (e.g. snipers = buyers in the first 3 slots)<br>
        ${chip("estimate")} computed from samples (total fees). Compare a few tokens with Terminal and we can calibrate.</p>
        <h3>Data sources</h3>
        <p class="note">PumpPortal (every pump.fun creation and migration) · DexScreener (market cap, volume, buys/sells)
        · Solana RPC (holders, dev %, snipers, fees). Every token is followed for 24 hours, so each column's hits and
        misses can be measured. Telegram signals are off.</p>
      </div>
      <div class="card"><h2>System log</h2><div class="log">
        ${(s.events || []).map(e => `<div><span class="muted">${clock(e.ts)}</span> <span class="${e.level === "info" ? "" : "warn"}">${esc(e.msg)}</span></div>`).join("") || '<span class="muted">No events yet</span>'}
      </div></div>
    </div>`;
  $("#main").querySelectorAll("[data-go]").forEach(a => a.addEventListener("click", e => {
    e.preventDefault(); state.tab = a.dataset.go; localSet("tab", state.tab); renderTabs(); openTab();
  }));
}

// ---- strategy tab -------------------------------------------------------------------------------
function renderStrategy(s) {
  state.col[s.key] = state.col[s.key] || s.columns[1]?.key || s.columns[0].key;
  $("#main").innerHTML = `
    <div class="card">
      <div class="row"><h2 style="margin:0">${esc(s.name)}</h2><span class="spacer"></span>
        <a href="${esc(s.source_url)}" target="_blank" rel="noopener noreferrer">Source video</a></div>
      <p class="note">${esc(s.summary)}<br>Platform: ${esc(s.platform)}</p>
      <details><summary>Trader's notes</summary><ul>${s.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul></details>
    </div>
    <div class="card"><h2>Filters</h2><div class="grid3">
      ${s.columns.map(c => `<div><h3>${esc(c.title)}</h3><table class="filters">
        ${c.filters.map(f => `<tr><td class="l" title="${esc(f.note)}">${esc(f.label)}</td><td class="l">${esc(f.rule)}</td><td>${chip(f.quality)}</td></tr>`).join("")}
        </table><details><summary>His reasons</summary><ul>${c.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul></details></div>`).join("")}
    </div></div>
    <div class="card"><div class="row"><h2 style="margin:0">Live board</h2><span class="muted" id="board-at"></span></div>
      <p class="note">Tokens passing each column now. New also lists its hits from the last 10 minutes, since tokens pass through it fast.</p>
      <div class="grid3" id="board">${s.columns.map(c => `<div><h3>${esc(c.title)}</h3><div class="board-col" id="board-${esc(c.key)}"><span class="muted">…</span></div></div>`).join("")}</div>
    </div>
    <div class="card"><div class="row"><h2 style="margin:0">Results</h2><span class="spacer"></span>
      <div class="seg" id="days">${[1, 3, 7, 30].map(d => `<button data-d="${d}" class="${d === state.days ? "on" : ""}">${d}d</button>`).join("")}</div></div>
      <div id="report"><p class="muted">Loading…</p></div></div>`;
  $("#days").querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    state.days = Number(b.dataset.d); localSet("days", state.days);
    $("#days").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    loadReport(s);
  }));
  loadBoard(s); loadReport(s);
  state.timers.push(setInterval(() => loadBoard(s), 10000));
  state.timers.push(setInterval(() => loadReport(s), 60000));
}

async function loadBoard(s) {
  let b;
  try { b = await api("api/board/" + encodeURIComponent(s.key)); } catch (e) { return; }
  $("#board-at") && ($("#board-at").textContent = "updated " + new Date().toLocaleTimeString());
  for (const c of s.columns) {
    const rows = b.columns[c.key] || [];
    const box = document.getElementById("board-" + c.key);
    if (!box) continue;
    box.innerHTML = rows.length ? `<table><tr><th>Token</th><th>Age</th><th>MC</th><th>Since hit</th>${c.key === "new" ? "" : "<th>Hold.</th><th>Dev</th><th>Snip.</th><th>Fees</th>"}</tr>
      ${rows.map(r => `<tr><td>${tokenCell(r)}${links(r.mint)}</td><td>${ageMin(r.age_min)}</td><td>${usd(r.mc_usd)}</td>
        <td>${r.mc_at_hit && r.mc_usd ? mult(r.mc_usd / r.mc_at_hit) : "–"}</td>
        ${c.key === "new" ? "" : `<td>${num(r.holders)}</td><td>${pct(r.dev_pct, 0)}</td><td>${pct(r.snipers_pct, 0)}</td><td>${num(r.fees_sol, 2)}</td>`}</tr>`).join("")}
      </table>` : '<span class="muted">Nothing passing right now</span>';
  }
}

async function loadReport(s) {
  let r;
  try { r = await api(`api/report/${encodeURIComponent(s.key)}?days=${state.days}`); } catch (e) {
    $("#report") && ($("#report").innerHTML = `<p class="bad">${esc(e.message)}</p>`); return;
  }
  if (!$("#report")) return;
  const u = r.universe;
  const cols = s.columns.map(c => ({ ...c, rep: r.columns[c.key] }));
  const sel = state.col[s.key];
  const c = cols.find(x => x.key === sel) || cols[0];
  $("#report").innerHTML = `
    <div class="tiles" style="margin:12px 0">
      ${tile("pump.fun tokens created", num(u.created), r.coverage.uptime_pct != null ? "stream up " + pct(r.coverage.uptime_pct, 0) + " of the time" : "")}
      ${tile("Runners", num(u.runners), esc(r.runner_rule))}
      ${tile("Runner rate", pct(u.runner_rate, 2), "of all new tokens")}
      ${tile("Migrations", num(u.migrated))}
      ${tile("Other launchpads", num(u.other_launchpads), "e.g. Bonk: recorded, not evaluated")}
    </div>
    <div class="tablewrap"><table>
      <tr><th>Column</th><th title="tokens that passed every filter">Hits</th><th>Per hour</th><th title="hits at least 1 hour old">Settled (1h+)</th>
        <th title="peak after the hit ≥ 2x the market cap at the hit">2x</th><th>5x</th><th>10x</th><th title="${esc(r.runner_rule)}">Runner</th>
        <th>Migrated</th><th title="median peak / market cap at hit">Median peak</th><th title="market cap 1 h after the hit / at the hit">Median 1h</th>
        <th title="runners this column showed / runners it could have shown">Runners caught</th><th title="hits shown per runner caught: the noise">Hits per runner</th></tr>
      ${cols.map(x => { const q = x.rep; return `<tr><td>${esc(x.title)}</td><td>${num(q.hits)}</td><td>${num(q.hits_per_hour, 1)}</td><td>${num(q.matured_1h)}</td>
        <td>${pct(q.rate_2x)}</td><td>${pct(q.rate_5x)}</td><td>${pct(q.rate_10x)}</td><td>${pct(q.rate_runner)}</td><td>${pct(q.rate_migrated)}</td>
        <td>${mult(q.median_mult)}</td><td>${mult(q.median_1h)}</td>
        <td>${num(q.runners_caught)} / ${num(q.runners_in_pool)} ${q.recall != null ? `<span class="muted">(${pct(q.recall, 0)})</span>` : ""}</td>
        <td>${num(q.hits_per_runner, 1)}</td></tr>`; }).join("")}
    </table></div>
    <p class="note">Rates use hits at least 1 hour old; peaks keep updating for 24 hours. Early numbers move a lot: wait for a few hundred settled hits before reading patterns.</p>
    <div class="row" style="margin:14px 0 6px"><div class="seg" id="colsel">${cols.map(x => `<button data-c="${esc(x.key)}" class="${x.key === c.key ? "on" : ""}">${esc(x.title)}</button>`).join("")}</div></div>
    ${columnDetail(c)}
    <h3 style="margin-top:16px">By day (UTC)</h3>
    <div class="tablewrap"><table><tr><th>Day</th><th>Created</th><th>Runners</th><th>Migrated</th>${cols.map(x => `<th>${esc(x.title)} hits</th>`).join("")}</tr>
      ${r.daily.map(d => `<tr><td>${esc(d.day)}</td><td>${num(d.created)}</td><td>${num(d.runners)}</td><td>${num(d.migrated)}</td>${cols.map(x => `<td>${num(d["hits_" + x.key] || 0)}</td>`).join("")}</tr>`).join("")}
    </table></div>`;
  $("#colsel").querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    state.col[s.key] = b.dataset.c; loadReport(s);
  }));
}

function columnDetail(c) {
  const q = c.rep;
  const maxReason = Math.max(1, ...q.missed_reasons.map(x => x.n));
  const feat = q.features.filter(f => f.n_win || f.n_lose);
  return `<div class="grid2">
    <div><h3>Which filter costs runners? (${esc(c.title)})</h3>
      <p class="note">Tokens that failed only this one filter: what it removed, and how many of those became runners or migrated.</p>
      <div class="tablewrap"><table><tr><th>Filter</th><th>Removed</th><th>Runners removed</th><th>Migrated removed</th></tr>
        ${q.filter_impact.map(f => `<tr><td>${esc(f.label)}</td><td>${num(f.removed)}</td><td class="${f.runners_removed ? "warn" : ""}">${num(f.runners_removed)}</td><td>${num(f.migrated_removed)}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">No data yet</td></tr>'}
      </table></div>
    </div>
    <div><h3>Runners missed: why</h3>
      <p class="note">${num(q.runners_in_pool - q.runners_caught)} runners not shown. Closest each came: the filters it failed.</p>
      <div class="bars">${q.missed_reasons.slice(0, 10).map(m => `<span>${esc(m.label)}</span><div class="bar" style="width:${(m.n / maxReason * 100).toFixed(1)}%"></div><span class="n">${num(m.n)}</span>`).join("") || '<span class="muted">None yet</span>'}</div>
    </div>
  </div>
  <div class="grid2" style="margin-top:14px">
    <div><h3>Winners vs the rest at the moment of the hit</h3>
      <p class="note">Median values. Winner = peak ≥ 2x the market cap at the hit (settled hits only).</p>
      <div class="tablewrap"><table><tr><th>Feature</th><th>Winners</th><th>Others</th><th>n</th></tr>
        ${feat.map(f => `<tr><td>${esc(f.label)}</td><td>${fmtFeat(f, f.win)}</td><td>${fmtFeat(f, f.lose)}</td><td class="muted">${num(f.n_win)} / ${num(f.n_lose)}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">No settled hits yet</td></tr>'}
      </table></div>
    </div>
    <div><h3>By session (hit time, UTC)</h3>
      <div class="tablewrap"><table><tr><th>Session</th><th>Hits</th><th>2x rate</th></tr>
        ${q.sessions.map(x => `<tr><td>${esc(x.session)}</td><td>${num(x.hits)}</td><td>${pct(x.rate_2x)}</td></tr>`).join("")}
      </table></div>
      <p class="note">Asia 22–07 · Europe 07–13 · EU+US overlap 13–16 · US 16–22 (UTC). He reports New is cleanest in the European session.</p>
      <h3 style="margin-top:12px">Missed runners</h3>
      <div class="tablewrap" style="max-height:260px"><table><tr><th>Token</th><th>Peak</th><th class="l">Failed</th></tr>
        ${q.missed.map(m => `<tr><td>${tokenCell(m)}${links(m.mint)}</td><td>${usd(m.peak_mc)}</td><td class="l">${esc(m.failed.join(", "))}</td></tr>`).join("") || '<tr><td colspan="3" class="muted">None</td></tr>'}
      </table></div>
    </div>
  </div>
  <h3 style="margin-top:16px">Recent hits (${esc(c.title)})</h3>
  <div class="tablewrap" style="max-height:480px"><table><tr><th>Token</th><th>Hit</th><th>Age</th><th>MC at hit</th><th>Peak</th><th>Peak x</th>
    <th>5m</th><th>1h</th><th>24h</th><th>Vol</th><th>Holders</th><th>Dev</th><th>Snipers</th><th>Fees</th><th>Migr.</th></tr>
    ${q.recent.map(h => `<tr><td>${tokenCell(h)}${links(h.mint)}</td><td>${clock(h.hit_at)}</td><td>${ageMin(h.age_min)}</td><td>${usd(h.mc_at_hit)}</td>
      <td>${usd(h.peak_mc)}</td><td>${mult(h.mult)}</td><td>${usd(h.mc_5m)}</td><td>${usd(h.mc_1h)}</td><td>${usd(h.mc_24h)}</td><td>${usd(h.vol_usd)}</td>
      <td>${num(h.holders)}</td><td>${pct(h.dev_pct, 0)}</td><td>${pct(h.snipers_pct, 0)}</td><td>${num(h.fees_sol, 2)}</td><td>${h.migrated ? "yes" : ""}</td></tr>`).join("") || '<tr><td colspan="15" class="muted">No hits yet</td></tr>'}
  </table></div>`;
}

function fmtFeat(f, v) {
  if (v == null) return "–";
  if (f.pct || f.key.endsWith("_pct")) return pct(v, 1);
  if (f.key === "mc_usd" || f.key === "vol_usd") return usd(v);
  if (f.key === "buy_ratio") return (v * 100).toFixed(0) + "%";
  if (f.key === "age_min") return ageMin(v);
  return num(v, v < 10 ? 2 : 0);
}

// ---- boot ---------------------------------------------------------------------------------------
async function boot() {
  try { state.strategies = await api("api/strategies"); } catch (e) { return; }
  renderTabs();
  await refreshStatus();
  openTab();
  if (!state.statusTimer) state.statusTimer = setInterval(refreshStatus, 10000);
}
boot();
