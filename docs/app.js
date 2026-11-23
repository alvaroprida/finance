/* Market Analysis dashboard.
 * Reads data/series.json (aligned daily history) and data/status.json
 * (snapshot + alert evaluation), both written by the pipeline.
 */
(function () {
  "use strict";

  const PALETTE = [
    "#2563eb", "#dc2626", "#16a34a", "#f59e0b", "#9333ea", "#0891b2",
    "#db2777", "#65a30d", "#ea580c", "#4f46e5", "#0d9488", "#b45309",
    "#64748b", "#be123c", "#0284c7",
  ];
  const RANGES = { "1Y": 365, "3Y": 365 * 3, "5Y": 365 * 5, "10Y": 365 * 10, Max: null };
  const GROUP_ORDER = ["Equities", "Crypto", "Metals", "FX", "Yields"];
  const DEFAULT_OFF = new Set(["Yields"]);

  const state = {
    dates: [],
    meta: {},          // key -> {label, group, unit, transform, values}
    keys: [],
    color: {},
    snap: {},
    rules: [],
    selected: new Set(),
    range: "5Y",
    mode: "rebased",
    logY: false,
    pairA: null,
    pairB: null,
    pairWin: 250,
  };

  const $ = (id) => document.getElementById(id);

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function val(key, i) {
    const v = state.meta[key].values[i];
    return v === null || v === undefined ? null : v;
  }

  function fmtLevel(v, unit) {
    if (v == null) return "—";
    if (unit === "%") return v.toFixed(2) + "%";
    return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  function fmtPct(v) {
    if (v == null || Number.isNaN(v)) return "—";
    return (v >= 0 ? "+" : "") + v.toFixed(1) + "%";
  }
  function fmtBp(v) {
    if (v == null || Number.isNaN(v)) return "—";
    const bp = v * 100;
    return (bp >= 0 ? "+" : "") + bp.toFixed(0) + "bp";
  }
  function signClass(v) {
    if (v == null || Number.isNaN(v) || v === 0) return "";
    return v > 0 ? "up" : "down";
  }

  /* ---------- date windows ---------- */

  function windowIdx(rangeKey) {
    const all = state.dates.map((_, i) => i);
    const days = RANGES[rangeKey];
    if (days == null) return all;
    const last = new Date(state.dates[state.dates.length - 1] + "T00:00:00Z");
    last.setUTCDate(last.getUTCDate() - days);
    const cutoff = last.toISOString().slice(0, 10);
    return all.filter((i) => state.dates[i] >= cutoff);
  }

  /* ---------- statistics (mirrors pipeline/common.py) ---------- */

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

  /* ---------- controls ---------- */

  function buildControls() {
    const list = $("series-list");
    list.innerHTML = "";
    GROUP_ORDER.forEach((group) => {
      const keys = state.keys.filter((k) => state.meta[k].group === group);
      if (!keys.length) return;
      const title = document.createElement("div");
      title.className = "group-title";
      title.textContent = group;
      list.appendChild(title);
      keys.forEach((k) => {
        const label = document.createElement("label");
        label.className = "series-item";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = state.selected.has(k);
        cb.dataset.key = k;
        cb.addEventListener("change", () => {
          cb.checked ? state.selected.add(k) : state.selected.delete(k);
          refresh();
        });
        const sw = document.createElement("span");
        sw.className = "swatch";
        sw.style.background = state.color[k];
        const name = document.createElement("span");
        name.textContent = state.meta[k].label;
        label.append(cb, sw, name);
        list.appendChild(label);
      });
    });

    const ranges = $("ranges");
    ranges.innerHTML = "";
    Object.keys(RANGES).forEach((r) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = r;
      b.setAttribute("aria-pressed", String(r === state.range));
      b.addEventListener("click", () => {
        state.range = r;
        ranges.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x.textContent === r)));
        refresh();
      });
      ranges.appendChild(b);
    });

    $("mode").value = state.mode;
    $("mode").addEventListener("change", (e) => { state.mode = e.target.value; refresh(); });
    $("logy").addEventListener("change", (e) => { state.logY = e.target.checked; refresh(); });

    $("select-all").addEventListener("click", () => {
      state.keys.forEach((k) => state.selected.add(k));
      syncCheckboxes(); refresh();
    });
    $("select-none").addEventListener("click", () => {
      state.selected.clear();
      syncCheckboxes(); refresh();
    });

    const a = $("pair-a"), b = $("pair-b");
    [a, b].forEach((sel) => {
      sel.innerHTML = state.keys.map((k) => `<option value="${k}">${esc(state.meta[k].label)}</option>`).join("");
    });
    a.value = state.pairA; b.value = state.pairB;
    a.addEventListener("change", (e) => { state.pairA = e.target.value; renderRolling(); });
    b.addEventListener("change", (e) => { state.pairB = e.target.value; renderRolling(); });
    $("pair-win").addEventListener("change", (e) => { state.pairWin = Number(e.target.value); renderRolling(); });
  }

  function syncCheckboxes() {
    document.querySelectorAll("#series-list input[type=checkbox]").forEach((cb) => {
      cb.checked = state.selected.has(cb.dataset.key);
    });
    document.querySelectorAll(".card").forEach((c) => {
      c.classList.toggle("off", !state.selected.has(c.dataset.key));
    });
  }

  /* ---------- cards ---------- */

  function renderCards() {
    const wrap = $("cards");
    wrap.innerHTML = "";
    state.keys.forEach((k) => {
      const m = state.meta[k];
      const s = state.snap[k];
      if (!s) return;
      const isYield = m.transform === "diff";
      const moves = isYield
        ? [["1D", fmtBp(s.abs_1d), s.abs_1d], ["1M", fmtBp(s.abs_1m), s.abs_1m], ["1Y", fmtBp(s.abs_1y), s.abs_1y]]
        : [["1D", fmtPct(s.pct_1d), s.pct_1d], ["1M", fmtPct(s.pct_1m), s.pct_1m], ["1Y", fmtPct(s.pct_1y), s.pct_1y]];
      const card = document.createElement("button");
      card.type = "button";
      card.className = "card" + (state.selected.has(k) ? "" : " off");
      card.dataset.key = k;
      card.style.setProperty("--c", state.color[k]);
      card.innerHTML = `
        <div class="name">${esc(m.label)} · ${esc(m.unit)}</div>
        <div class="last">${fmtLevel(s.level, m.unit)}</div>
        <div class="moves">${moves.map(([l, t, v]) =>
          `<span><b>${l}</b> <span class="${signClass(v)}">${t}</span></span>`).join("")}</div>
        <div class="moves" style="margin-top:4px"><span><b>${isYield ? "" : "from 1Y high"}</b> <span class="${signClass(s.drawdown_1y)}">${isYield ? "" : fmtPct(s.drawdown_1y)}</span></span></div>`;
      card.title = "Click to show or hide on the chart";
      card.addEventListener("click", () => {
        state.selected.has(k) ? state.selected.delete(k) : state.selected.add(k);
        syncCheckboxes(); refresh();
      });
      wrap.appendChild(card);
    });
  }

  /* ---------- main chart ---------- */

  function firstValid(k, idx) {
    for (const i of idx) { const v = val(k, i); if (v !== null) return v; }
    return null;
  }

  function renderChart() {
    const idx = windowIdx(state.range);
    const traces = [];
    const levelMix = new Set();
    state.keys.forEach((k) => {
      if (!state.selected.has(k)) return;
      const m = state.meta[k];
      levelMix.add(m.unit);
      let base = null;
      if (state.mode === "rebased") {
        base = firstValid(k, idx);
        if (base === null) return;
      }
      const x = [], y = [];
      idx.forEach((i) => {
        const v = val(k, i);
        if (v === null) return;
        x.push(state.dates[i]);
        y.push(state.mode === "rebased" ? (v / base) * 100 : v);
      });
      traces.push({
        x, y, type: "scatter", mode: "lines", name: m.label, connectgaps: true,
        line: { width: 1.8, color: state.color[k] },
        hovertemplate: `%{y:,.2f}<extra>${esc(m.label)} (${esc(m.unit)})</extra>`,
      });
    });

    const text = getComputedStyle(document.body).color;
    const layout = {
      margin: { l: 56, r: 16, t: 40, b: 44 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: text, size: 12 },
      hovermode: "x unified",
      legend: { orientation: "h", y: 1.12, x: 0 },
      xaxis: { gridcolor: "rgba(128,128,128,0.2)", zeroline: false },
      yaxis: {
        type: state.logY ? "log" : "linear",
        gridcolor: "rgba(128,128,128,0.2)",
        zeroline: false,
        title: state.mode === "rebased" ? "Rebased (first date in range = 100)" : "Level",
      },
    };
    if (state.mode === "level" && levelMix.size > 1) {
      layout.annotations = [{
        text: "Level mode mixes units. Use rebased for a fair comparison.",
        xref: "paper", yref: "paper", x: 0, y: 1.2, showarrow: false, font: { size: 11, color: "#a1a1aa" },
      }];
    }
    if (!traces.length) {
      layout.annotations = [{ text: "Select at least one series", xref: "paper", yref: "paper", x: 0.5, y: 0.5, showarrow: false }];
    }
    Plotly.react("chart", traces, layout, { responsive: true, displaylogo: false });
  }

  /* ---------- correlation matrix ---------- */

  function renderCorrelation() {
    const keys = state.keys.filter((k) => state.selected.has(k));
    const box = $("corr");
    if (keys.length < 2) {
      box.innerHTML = `<p class="hint">Select at least two series.</p>`;
      return;
    }
    const idx = windowIdx(state.range);
    const { rows, out } = returnsFor(keys, idx);
    if (rows.length < 10) {
      box.innerHTML = `<p class="hint">Not enough overlapping observations in this range.</p>`;
      return;
    }
    let html = `<table><thead><tr><th></th>${keys.map((k) => `<th>${esc(state.meta[k].label)}</th>`).join("")}</tr></thead><tbody>`;
    keys.forEach((a) => {
      html += `<tr><th>${esc(state.meta[a].label)}</th>`;
      keys.forEach((b) => {
        if (a === b) { html += `<td class="cell corr-diag">1.00</td>`; return; }
        const r = pearson(out[a], out[b]);
        const txt = Math.abs(r) > 0.6 ? "#fff" : "inherit";
        html += `<td class="cell" style="background:${corrColor(r)};color:${txt}">${r.toFixed(2)}</td>`;
      });
      html += `</tr>`;
    });
    html += `</tbody></table>`;
    html += `<p class="hint">${rows.length} common trading days in range · blue = positive, red = negative.</p>`;
    box.innerHTML = html;
  }

  /* ---------- rolling correlation ---------- */

  function renderRolling() {
    const a = state.pairA, b = state.pairB, W = state.pairWin;
    if (!a || !b || a === b) {
      Plotly.react("rolling", [], { annotations: [{ text: "Pick two different series", xref: "paper", yref: "paper", x: 0.5, y: 0.5, showarrow: false }] }, { responsive: true });
      return;
    }
    const all = state.dates.map((_, i) => i);
    const { rows, out } = returnsFor([a, b], all);
    const dates = rows.slice(1).map((i) => state.dates[i]);
    const roll = [], rollDates = [];
    for (let t = W - 1; t < out[a].length; t++) {
      const xs = out[a].slice(t - W + 1, t + 1);
      const ys = out[b].slice(t - W + 1, t + 1);
      roll.push(pearson(xs, ys));
      rollDates.push(dates[t]);
    }
    const start = windowIdx(state.range)[0];
    const cutoff = state.dates[start];
    const keep = rollDates.map((d, i) => d >= cutoff);
    const x = rollDates.filter((_, i) => keep[i]);
    const y = roll.filter((_, i) => keep[i]);

    const text = getComputedStyle(document.body).color;
    Plotly.react("rolling", [{
      x, y, type: "scatter", mode: "lines", name: `${state.meta[a].label} vs ${state.meta[b].label}`,
      line: { width: 1.8, color: "#2563eb" },
      hovertemplate: "%{y:.2f}<extra></extra>",
    }], {
      margin: { l: 56, r: 16, t: 20, b: 52 },
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: text, size: 12 },
      yaxis: { range: [-1, 1], tickvals: [-1, -0.5, 0, 0.5, 1], title: `${W}-day correlation`, gridcolor: "rgba(128,128,128,0.2)", zeroline: true, zerolinecolor: "rgba(128,128,128,0.5)" },
      xaxis: { gridcolor: "rgba(128,128,128,0.2)", automargin: true },
      showlegend: false,
    }, { responsive: true, displaylogo: false });
  }

  /* ---------- alerts ---------- */

  function renderAlerts() {
    const rules = state.rules.slice().sort((x, y) =>
      Number(y.triggered) - Number(x.triggered) || (x.severity === "warning" ? -1 : 1) - (y.severity === "warning" ? -1 : 1));
    const rows = rules.map((r) => {
      const status = r.triggered
        ? `<span class="tag triggered">Triggered</span>`
        : `<span class="tag">OK</span>`;
      const value = r.value == null ? "—" : Number(r.value).toFixed(2);
      return `<tr>
        <td>${status}</td>
        <td><span class="tag ${esc(r.severity)}">${esc(r.severity)}</span></td>
        <td>${esc(r.series_label)}</td>
        <td class="msg">${esc(r.message)}</td>
        <td>${esc(r.metric)}</td>
        <td>${value}</td>
        <td>${esc(r.op)} ${esc(r.threshold)}</td>
      </tr>`;
    }).join("");
    $("alerts").innerHTML = `
      <table class="alerts-table">
        <thead><tr><th>Status</th><th>Severity</th><th>Series</th><th>Rule</th><th>Metric</th><th>Value</th><th>Threshold</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  /* ---------- orchestration ---------- */

  function refresh() {
    renderChart();
    renderCorrelation();
    syncCheckboxes();
  }

  async function init() {
    try {
      const [series, status] = await Promise.all([
        fetch("data/series.json", { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }),
        fetch("data/status.json", { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }),
      ]);
      state.dates = series.dates;
      state.meta = series.series;
      state.keys = Object.keys(series.series).sort((a, b) =>
        GROUP_ORDER.indexOf(state.meta[a].group) - GROUP_ORDER.indexOf(state.meta[b].group));
      state.keys.forEach((k, i) => (state.color[k] = PALETTE[i % PALETTE.length]));
      state.snap = status.snapshot;
      state.rules = status.rules;
      state.selected = new Set(state.keys.filter((k) => !DEFAULT_OFF.has(state.meta[k].group)));
      state.pairA = "sp500" in state.meta ? "sp500" : state.keys[0];
      state.pairB = "btc" in state.meta ? "btc" : state.keys[1];

      $("asof").textContent = `Data as of ${status.as_of} · refreshed ${series.generated_utc.replace("T", " ").replace("+00:00", " UTC")}`;

      buildControls();
      renderCards();
      renderAlerts();
      refresh();
      renderRolling();
    } catch (err) {
      $("asof").textContent = "Could not load data. Has the daily pipeline run yet?";
      console.error(err);
    }
  }

  init();
})();
