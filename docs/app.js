/* Daily Market Analysis.
 * Reads data/series.json (aligned daily history) and data/status.json
 * (snapshot, written analysis and alert evaluation), both produced daily.
 */
(function () {
  "use strict";

  const PALETTE = [
    "#2563eb", "#dc2626", "#16a34a", "#f59e0b", "#9333ea", "#0891b2",
    "#db2777", "#65a30d", "#ea580c", "#4f46e5", "#0d9488", "#b45309",
    "#64748b", "#be123c", "#0284c7",
  ];
  const SHORT = {
    sp500: "S&P 500", dow: "Dow", nasdaq: "Nasdaq", btc: "BTC", eth: "ETH",
    copper: "Copper", gold: "Gold", silver: "Silver", eurusd: "EUR/USD",
    y3m: "3M", y2: "2Y", y5: "5Y", y10: "10Y", y30: "30Y", spread_10y_3m: "10Y-3M",
  };
  const RANGES = { "3M": 92, "1Y": 365, "5Y": 1825, Max: null };
  const GROUP_RANGES = ["3M", "1Y", "5Y", "Max"];
  const CORR_RANGES = ["3M", "1Y", "5Y"];
  const PRINT_WIDTH = 690;
  const PRINT_HEIGHT = 260;

  const state = {
    dates: [], meta: {}, keys: [], color: {}, snap: {}, rules: [], products: [],
    asOf: "", range: {}, mode: {}, corrRange: "1Y",
    pairA: "sp500", pairB: "btc", pairWin: 250, printing: false, title: document.title,
  };

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function val(key, i) {
    const v = state.meta[key].values[i];
    return v === null || v === undefined ? null : v;
  }

  /* ---------- formatting ---------- */

  const isNum = (v) => v !== null && v !== undefined && !Number.isNaN(v);
  function fmtPrice(v) {
    if (!isNum(v)) return "—";
    return v.toLocaleString("en-US", Math.abs(v) < 10
      ? { minimumFractionDigits: 4, maximumFractionDigits: 4 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  const signClass = (v) => (!isNum(v) || v === 0 ? "" : v > 0 ? "up" : "down");
  function pctCell(v) {
    return isNum(v) ? `<span class="${signClass(v)}">${v >= 0 ? "+" : ""}${v.toFixed(1)}%</span>` : "—";
  }
  function bpCell(v) {
    if (!isNum(v)) return "—";
    const bp = v * 100;
    return `<span class="${signClass(bp)}">${bp >= 0 ? "+" : ""}${bp.toFixed(0)}bp</span>`;
  }
  function trendTag(trend) {
    const cls = trend === "Uptrend" ? "t-up" : trend === "Downtrend" ? "t-down" : "";
    return `<span class="tag ${cls}">${esc(trend)}</span>`;
  }
  function statusChip(status, tone) {
    return `<span class="chip tone-${esc(tone)}"><span class="dot"></span>${esc(status)}</span>`;
  }

  /* ---------- dates and statistics ---------- */

  function windowIdx(rangeKey) {
    const all = state.dates.map((_, i) => i);
    const days = RANGES[rangeKey];
    if (days == null) return all;
    const last = new Date(state.dates[state.dates.length - 1] + "T00:00:00Z");
    last.setUTCDate(last.getUTCDate() - days);
    const cutoff = last.toISOString().slice(0, 10);
    return all.filter((i) => state.dates[i] >= cutoff);
  }

  function firstValid(k, idx) {
    for (const i of idx) { const v = val(k, i); if (v !== null) return v; }
    return null;
  }

  // Returns on dates where every key has a value (mirrors pipeline/common.py).
  function returnsFor(keys, idx) {
    const rows = idx.filter((i) => keys.every((k) => val(k, i) !== null));
    const out = {};
    keys.forEach((k) => (out[k] = []));
    for (let j = 1; j < rows.length; j++) {
      const a = rows[j - 1], b = rows[j];
      keys.forEach((k) => {
        const x = val(k, a), y = val(k, b);
        out[k].push(state.meta[k].transform === "log" ? Math.log(y / x) : y - x);
      });
    }
    return { rows, out };
  }

  function pearson(x, y) {
    const n = x.length;
    if (n < 3) return NaN;
    let mx = 0, my = 0;
    for (let i = 0; i < n; i++) { mx += x[i]; my += y[i]; }
    mx /= n; my /= n;
    let sxy = 0, sxx = 0, syy = 0;
    for (let i = 0; i < n; i++) {
      const dx = x[i] - mx, dy = y[i] - my;
      sxy += dx * dy; sxx += dx * dx; syy += dy * dy;
    }
    return sxy / Math.sqrt(sxx * syy);
  }

  function corrColor(r) {
    const t = Math.min(1, Math.abs(r));
    const base = r >= 0 ? [37, 99, 235] : [220, 38, 38];
    const mix = (c) => Math.round(255 + (c - 255) * t);
    return `rgb(${mix(base[0])}, ${mix(base[1])}, ${mix(base[2])})`;
  }

  /* ---------- plotting helpers ---------- */

  function baseLayout(extra) {
    const color = state.printing ? "#18181b" : getComputedStyle(document.body).color;
    const layout = {
      margin: { l: 56, r: 16, t: 30, b: 44 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color, size: 12 },
      hovermode: "x unified",
      legend: { orientation: "h", y: 1.16, x: 0 },
      xaxis: { gridcolor: "rgba(128,128,128,0.2)", zeroline: false, automargin: true },
    };
    if (state.printing) {
      layout.autosize = false;
      layout.width = PRINT_WIDTH;
      layout.height = PRINT_HEIGHT;
    }
    return Object.assign(layout, extra);
  }
  const plotConfig = () => ({ responsive: !state.printing, displaylogo: false });

  function makeChips(container, options, current, onPick) {
    container.innerHTML = "";
    options.forEach(([value, label]) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.setAttribute("aria-pressed", String(value === current));
      b.addEventListener("click", () => {
        container.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", "false"));
        b.setAttribute("aria-pressed", "true");
        onPick(value);
      });
      container.appendChild(b);
    });
  }

  /* ---------- introduction and today's read ---------- */

  function renderIntro(status) {
    $("cycle").innerHTML = state.products
      .map((g) => `<span class="chip tone-${esc(g.tone)}"><span class="dot"></span>${esc(g.title)}: ${esc(g.status)}</span>`)
      .join("");
    $("read").innerHTML = (status.observations || []).map((l) => `<li>${esc(l)}</li>`).join("");
  }

  /* ---------- product sections ---------- */

  function statsTable(g) {
    const yields = g.group === "Yields";
    const rows = g.items.map((it) => {
      const s = state.snap[it.key];
      if (!s) return "";
      const cells = yields
        ? [`${s.level.toFixed(2)}%`, bpCell(s.abs_1d), bpCell(s.abs_1m), bpCell(it.abs_3m), bpCell(s.abs_1y), "—"]
        : [fmtPrice(s.level), pctCell(s.pct_1d), pctCell(s.pct_1m), pctCell(it.pct_3m), pctCell(s.pct_1y), pctCell(s.drawdown_1y)];
      return `<tr><td>${esc(it.label)}</td>${cells.map((c) => `<td>${c}</td>`).join("")}
        <td class="trend">${trendTag(it.trend)}</td><td>${isNum(it.rsi) ? it.rsi.toFixed(0) : "—"}</td></tr>`;
    }).join("");
    return `<table class="stats"><thead><tr><th>Product</th><th>Last</th><th>1D</th><th>1M</th><th>3M</th><th>1Y</th>
      <th>From 1Y high</th><th>Trend</th><th>RSI</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function buildProducts() {
    const wrap = $("products");
    wrap.innerHTML = "";
    state.products.forEach((g) => {
      state.range[g.group] = "1Y";
      state.mode[g.group] = g.group === "Yields" ? "level" : "rebased";
      const sec = document.createElement("section");
      sec.className = "panel product";
      sec.id = `sec-${g.group}`;
      sec.innerHTML = `
        <div class="prod-head"><h2>${esc(g.title)}</h2>${statusChip(g.status, g.tone)}</div>
        <p>${esc(g.intro)}</p>
        <div class="controls no-print">
          <div class="chips" data-role="range" role="group" aria-label="Date range"></div>
          ${g.group === "Yields" ? "" : `<div class="chips" data-role="mode" role="group" aria-label="View"></div>`}
        </div>
        <div id="chart-${g.group}" class="chart"></div>
        <div class="scroll">${statsTable(g)}</div>
        <h3>Analysis</h3>
        <ul class="analysis">${g.paragraphs.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
        <div class="items">${g.items.map((it) =>
          `<div class="item" style="--c:${state.color[it.key]}"><h4>${esc(it.label)}</h4><p>${esc(it.summary)}</p></div>`).join("")}</div>`;
      wrap.appendChild(sec);

      makeChips(sec.querySelector('[data-role="range"]'),
        GROUP_RANGES.map((r) => [r, r]), state.range[g.group],
        (r) => { state.range[g.group] = r; renderGroupChart(g); });
      const modeBox = sec.querySelector('[data-role="mode"]');
      if (modeBox) {
        makeChips(modeBox, [["rebased", "Rebased to 100"], ["level", "Level"]], state.mode[g.group],
          (m) => { state.mode[g.group] = m; renderGroupChart(g); });
      }
    });
  }

  function renderGroupChart(g) {
    const idx = windowIdx(state.range[g.group]);
    const mode = state.mode[g.group];
    const traces = [];
    g.items.forEach((it) => {
      const k = it.key, m = state.meta[k];
      let base = null;
      if (mode === "rebased") {
        base = firstValid(k, idx);
        if (base === null) return;
      }
      const x = [], y = [];
      idx.forEach((i) => {
        const v = val(k, i);
        if (v === null) return;
        x.push(state.dates[i]);
        y.push(mode === "rebased" ? (v / base) * 100 : v);
      });
      traces.push({
        x, y, type: "scatter", mode: "lines", name: m.label, connectgaps: true,
        line: { width: 1.8, color: state.color[k] },
        hovertemplate: `%{y:,.2f}<extra>${esc(m.label)}</extra>`,
      });
    });
    const title = mode === "rebased" ? "Rebased to 100 at start of range" : g.group === "Yields" ? "Yield / spread (%)" : "Level";
    return Plotly.react(`chart-${g.group}`, traces, baseLayout({
      yaxis: { title, gridcolor: "rgba(128,128,128,0.2)", zeroline: g.group === "Yields" },
    }), plotConfig());
  }

  /* ---------- correlations ---------- */

  function renderCorrelation() {
    const keys = state.keys;
    const { rows, out } = returnsFor(keys, windowIdx(state.corrRange));
    const box = $("corr");
    if (rows.length < 10) {
      box.innerHTML = `<p class="hint">Not enough overlapping observations in this window.</p>`;
      return;
    }
    let html = `<table><thead><tr><th></th>${keys.map((k) => `<th>${esc(SHORT[k] || k)}</th>`).join("")}</tr></thead><tbody>`;
    keys.forEach((a) => {
      html += `<tr><th>${esc(SHORT[a] || a)}</th>`;
      keys.forEach((b) => {
        if (a === b) { html += `<td class="cell corr-diag">1.00</td>`; return; }
        const r = pearson(out[a], out[b]);
        const fg = Math.abs(r) > 0.6 ? "#fff" : "inherit";
        html += `<td class="cell" style="background:${corrColor(r)};color:${fg}">${r.toFixed(2)}</td>`;
      });
      html += `</tr>`;
    });
    html += `</tbody></table><p class="hint">${rows.length} common trading days · blue = move together, red = move in opposite directions.</p>`;
    box.innerHTML = html;
  }

  function renderRolling() {
    const a = state.pairA, b = state.pairB, W = state.pairWin;
    if (!a || !b || a === b) {
      return Plotly.react("rolling", [], baseLayout({
        annotations: [{ text: "Pick two different products", xref: "paper", yref: "paper", x: 0.5, y: 0.5, showarrow: false }],
      }), plotConfig());
    }
    const { rows, out } = returnsFor([a, b], state.dates.map((_, i) => i));
    const dates = rows.slice(1).map((i) => state.dates[i]);
    const x = [], y = [];
    const cutoff = state.dates[windowIdx("5Y")[0]];
    for (let t = W - 1; t < out[a].length; t++) {
      if (dates[t] < cutoff) continue;
      x.push(dates[t]);
      y.push(pearson(out[a].slice(t - W + 1, t + 1), out[b].slice(t - W + 1, t + 1)));
    }
    return Plotly.react("rolling", [{
      x, y, type: "scatter", mode: "lines",
      line: { width: 1.8, color: "#2563eb" }, hovertemplate: "%{y:.2f}<extra></extra>",
    }], baseLayout({
      title: { text: `${state.meta[a].label} vs ${state.meta[b].label}, ${W}-day correlation`, font: { size: 13 }, x: 0.02 },
      margin: { l: 56, r: 16, t: 40, b: 44 },
      showlegend: false,
      yaxis: {
        range: [-1, 1], tickvals: [-1, -0.5, 0, 0.5, 1], gridcolor: "rgba(128,128,128,0.2)",
        zeroline: true, zerolinecolor: "rgba(128,128,128,0.5)",
      },
    }), plotConfig());
  }

  /* ---------- alerts ---------- */

  function renderAlerts() {
    const rules = state.rules.slice().sort((x, y) =>
      Number(y.triggered) - Number(x.triggered) ||
      (x.severity === "warning" ? -1 : 1) - (y.severity === "warning" ? -1 : 1));
    const rows = rules.map((r) => `<tr>
      <td>${r.triggered ? `<span class="tag triggered">Triggered</span>` : `<span class="tag">OK</span>`}</td>
      <td><span class="tag ${esc(r.severity)}">${esc(r.severity)}</span></td>
      <td>${esc(r.series_label)}</td>
      <td class="msg">${esc(r.message)}</td>
      <td>${r.value == null ? "—" : Number(r.value).toFixed(2)}</td>
      <td>${esc(r.op)} ${esc(r.threshold)}</td></tr>`).join("");
    $("alerts").innerHTML = `<table class="alerts-table"><thead><tr>
      <th>Status</th><th>Severity</th><th>Product</th><th>Rule</th><th>Value</th><th>Threshold</th>
      </tr></thead><tbody>${rows}</tbody></table>`;
  }

  /* ---------- orchestration and export ---------- */

  function renderCharts() {
    return Promise.all([...state.products.map(renderGroupChart), renderRolling()]);
  }

  function beginPrint() {
    state.printing = true;
    document.title = `Market analysis ${state.asOf}`;
  }
  function endPrint() {
    state.printing = false;
    document.title = state.title;
    renderCharts();
  }

  async function exportPdf() {
    beginPrint();
    await renderCharts();
    window.print();
  }

  function setupControls() {
    makeChips($("corr-ranges"), CORR_RANGES.map((r) => [r, r]), state.corrRange,
      (r) => { state.corrRange = r; renderCorrelation(); });
    ["pair-a", "pair-b"].forEach((id) => {
      $(id).innerHTML = state.keys.map((k) => `<option value="${k}">${esc(state.meta[k].label)}</option>`).join("");
    });
    $("pair-a").value = state.pairA;
    $("pair-b").value = state.pairB;
    $("pair-a").addEventListener("change", (e) => { state.pairA = e.target.value; renderRolling(); });
    $("pair-b").addEventListener("change", (e) => { state.pairB = e.target.value; renderRolling(); });
    $("pair-win").addEventListener("change", (e) => { state.pairWin = Number(e.target.value); renderRolling(); });
    $("export").addEventListener("click", exportPdf);
    window.addEventListener("beforeprint", () => {
      if (!state.printing) { beginPrint(); renderCharts(); }
    });
    window.addEventListener("afterprint", endPrint);
  }

  async function init() {
    try {
      const get = (url) => fetch(url, { cache: "no-cache" }).then((r) => {
        if (!r.ok) throw new Error(`${url}: ${r.status}`);
        return r.json();
      });
      const [series, status] = await Promise.all([get("data/series.json"), get("data/status.json")]);
      state.dates = series.dates;
      state.meta = series.series;
      const order = (status.products || []).map((g) => g.group);
      state.keys = Object.keys(series.series).sort((a, b) =>
        order.indexOf(state.meta[a].group) - order.indexOf(state.meta[b].group));
      state.keys.forEach((k, i) => (state.color[k] = PALETTE[i % PALETTE.length]));
      state.snap = status.snapshot;
      state.rules = status.rules;
      state.products = status.products || [];
      state.asOf = status.as_of;
      if (!(state.pairA in state.meta)) state.pairA = state.keys[0];
      if (!(state.pairB in state.meta)) state.pairB = state.keys[1];

      $("asof").textContent = `Data as of ${status.as_of} · refreshed ${series.generated_utc.replace("T", " ").replace("+00:00", " UTC")}`;

      renderIntro(status);
      buildProducts();
      setupControls();
      renderCorrelation();
      renderAlerts();
      await renderCharts();
    } catch (err) {
      $("asof").textContent = "Could not load data. Has the daily update run yet?";
      console.error(err);
    }
  }

  init();
})();
