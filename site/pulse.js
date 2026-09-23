// roofline · pulse — trend dashboard over data/articles.json.
//
// Charts are hand-rolled inline SVG: no build step, no chart library. Colors come
// from CSS custom properties (see style.css .viz-root) so light and dark are two
// selected palettes rather than an automatic flip.
const READ_KEY = "roofline:read";
const WEEK_MS = 7 * 86400000;

const el = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";

let articles = [];
let read = new Set();

try {
  read = new Set(JSON.parse(localStorage.getItem(READ_KEY) || "[]"));
} catch { /* best effort */ }

const css = (name) =>
  getComputedStyle(document.body).getPropertyValue(name).trim();

// ---------------------------------------------------------------- data helpers

const parseDate = (iso) => (iso ? new Date(iso + "Z") : null);

function inScope() {
  const days = Number(el("window").value);
  const cutoff = days ? Date.now() - days * 86400000 : null;
  const source = el("source").value;

  return articles.filter((a) => {
    if (source !== "all" && a.source !== source) return false;
    const when = parseDate(a.published_date);
    if (cutoff && (!when || when.getTime() < cutoff)) return false;
    return true;
  });
}

/** Monday 00:00 UTC of the week containing `date`, as a ms timestamp. */
function weekStart(date) {
  const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.getTime();
}

/** Weekly counts for the last `weeks` weeks, zero-filled so gaps are visible. */
function weekly(rows, weeks) {
  const thisWeek = weekStart(new Date());
  const buckets = new Map();
  for (let i = weeks - 1; i >= 0; i--) buckets.set(thisWeek - i * WEEK_MS, 0);

  for (const a of rows) {
    const when = parseDate(a.published_date);
    if (!when) continue;
    const key = weekStart(when);
    if (buckets.has(key)) buckets.set(key, buckets.get(key) + 1);
  }
  return [...buckets].map(([t, count]) => ({ t, count }));
}

function tagsOf(article) {
  return (article.tags || "").split(",").filter(Boolean);
}

function countSince(rows, days) {
  const cutoff = Date.now() - days * 86400000;
  return rows.filter((a) => {
    const when = parseDate(a.published_date);
    return when && when.getTime() >= cutoff;
  }).length;
}

/** Share of attention this week minus share over the prior three weeks.
 *
 * Measured in percentage points, deliberately NOT as percent change: a ratio
 * divides by a baseline that is frequently zero, which collapses "appeared from
 * nothing" and "doubled" into the same +100%. Share shift is bounded, defined
 * when the baseline is zero, and answers the question the reader actually has —
 * what is taking up more of the field this week.
 */
function momentum(rows) {
  const now = Date.now();
  const recent = new Map();
  const prior = new Map();
  let recentTotal = 0;
  let priorTotal = 0;

  for (const a of rows) {
    const when = parseDate(a.published_date);
    if (!when) continue;
    const age = now - when.getTime();
    const fresh = age <= WEEK_MS;
    if (!fresh && age > 4 * WEEK_MS) continue;

    for (const tag of tagsOf(a)) {
      if (fresh) {
        recent.set(tag, (recent.get(tag) || 0) + 1);
        recentTotal++;
      } else {
        prior.set(tag, (prior.get(tag) || 0) + 1);
        priorTotal++;
      }
    }
  }

  const out = [];
  for (const tag of new Set([...recent.keys(), ...prior.keys()])) {
    const now7 = recent.get(tag) || 0;
    const before = prior.get(tag) || 0;
    if (!now7 && !before) continue;

    const recentShare = recentTotal ? now7 / recentTotal : 0;
    const priorShare = priorTotal ? before / priorTotal : 0;
    out.push({
      tag,
      now7,
      before,
      priorPerWeek: before / 3,
      shift: (recentShare - priorShare) * 100,
      isNew: before === 0 && now7 > 0,
    });
  }
  return out.sort((a, b) => b.shift - a.shift);
}

// ------------------------------------------------------------------- svg utils

function svg(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function tip(html, x, y) {
  const node = el("tip");
  node.innerHTML = html;
  node.hidden = false;
  const box = node.getBoundingClientRect();
  const left = Math.min(Math.max(8, x - box.width / 2), innerWidth - box.width - 8);
  node.style.left = `${left}px`;
  node.style.top = `${y - box.height - 12 + scrollY}px`;
}

const hideTip = () => { el("tip").hidden = true; };

function tableFor(target, columns, rows) {
  const host = el(`${target}-table`);
  const table = document.createElement("table");
  const head = table.insertRow();
  for (const c of columns) {
    const th = document.createElement("th");
    th.textContent = c;
    head.append(th);
  }
  for (const r of rows) {
    const tr = table.insertRow();
    for (const cell of r) tr.insertCell().textContent = cell;
  }
  host.textContent = "";
  host.append(table);
}

const fmtWeek = (t) =>
  new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric" });

// --------------------------------------------------------------- the KPI tiles

function renderKpis(rows) {
  const tiles = [
    ["New today", countSince(rows, 1)],
    ["Last 7 days", countSince(rows, 7)],
    ["Last 30 days", countSince(rows, 30)],
    ["Unread", rows.filter((a) => !read.has(a.url)).length],
    ["Sources", new Set(rows.map((a) => a.source)).size],
  ];

  const host = el("kpis");
  host.textContent = "";
  for (const [label, value] of tiles) {
    const tile = document.createElement("div");
    tile.className = "kpi";
    const v = document.createElement("div");
    v.className = "kpi-value";
    v.textContent = value.toLocaleString();
    const l = document.createElement("div");
    l.className = "kpi-label";
    l.textContent = label;
    tile.append(v, l);
    host.append(tile);
  }
}

// ------------------------------------------------- volume per week (area+line)

function renderVolume(rows) {
  const data = weekly(rows, 26);
  const host = el("volume");
  host.textContent = "";

  const W = host.clientWidth || 760;
  const H = 190;
  const pad = { t: 14, r: 16, b: 26, l: 34 };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;
  const max = Math.max(4, ...data.map((d) => d.count));

  const x = (i) => pad.l + (plotW * i) / Math.max(1, data.length - 1);
  const y = (v) => pad.t + plotH - (plotH * v) / max;

  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img" });
  const caption = svg("title");
  caption.textContent = "Articles collected per week";
  chart.append(caption);

  // Recessive solid hairline grid — never dashed.
  for (let i = 0; i <= 3; i++) {
    const value = Math.round((max / 3) * i);
    chart.append(svg("line", {
      x1: pad.l, x2: W - pad.r, y1: y(value), y2: y(value),
      stroke: css("--viz-grid"), "stroke-width": 1,
    }));
    const label = svg("text", {
      x: pad.l - 7, y: y(value) + 3.5, "text-anchor": "end", class: "tick",
    });
    label.textContent = value;
    chart.append(label);
  }

  const line = data.map((d, i) => `${x(i)},${y(d.count)}`).join(" ");
  chart.append(svg("polygon", {
    points: `${pad.l},${y(0)} ${line} ${W - pad.r},${y(0)}`,
    fill: css("--viz-series-1"), opacity: 0.16,
  }));
  chart.append(svg("polyline", {
    points: line, fill: "none", stroke: css("--viz-series-1"),
    "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round",
  }));

  // Selective direct label: the endpoint only.
  const last = data[data.length - 1];
  chart.append(svg("circle", {
    cx: x(data.length - 1), cy: y(last.count), r: 4,
    fill: css("--viz-series-1"), stroke: css("--surface-1"), "stroke-width": 2,
  }));
  const endLabel = svg("text", {
    x: x(data.length - 1) - 6, y: y(last.count) - 9, "text-anchor": "end", class: "point-label",
  });
  endLabel.textContent = `${last.count} this week`;
  chart.append(endLabel);

  for (const i of [0, Math.floor(data.length / 2), data.length - 1]) {
    const t = svg("text", {
      x: x(i), y: H - 8,
      "text-anchor": i === 0 ? "start" : i === data.length - 1 ? "end" : "middle",
      class: "tick",
    });
    t.textContent = fmtWeek(data[i].t);
    chart.append(t);
  }

  // Crosshair + tooltip across the whole plot, not per-point hit targets.
  const crosshair = svg("line", {
    y1: pad.t, y2: pad.t + plotH, stroke: css("--viz-axis"), "stroke-width": 1, opacity: 0,
  });
  chart.append(crosshair);
  const surface = svg("rect", {
    x: pad.l, y: pad.t, width: plotW, height: plotH, fill: "transparent",
  });
  surface.addEventListener("mousemove", (event) => {
    const box = chart.getBoundingClientRect();
    const rel = ((event.clientX - box.left) / box.width) * W;
    const i = Math.max(0, Math.min(data.length - 1,
      Math.round(((rel - pad.l) / plotW) * (data.length - 1))));
    crosshair.setAttribute("x1", x(i));
    crosshair.setAttribute("x2", x(i));
    crosshair.setAttribute("opacity", 1);
    tip(`<strong>${data[i].count}</strong> articles<br>week of ${fmtWeek(data[i].t)}`,
        event.clientX, event.clientY);
  });
  surface.addEventListener("mouseleave", () => {
    crosshair.setAttribute("opacity", 0);
    hideTip();
  });
  chart.append(surface);
  host.append(chart);

  tableFor("volume", ["Week of", "Articles"], data.map((d) => [fmtWeek(d.t), d.count]));
}

// ----------------------------------------------- topic momentum (diverging)

function renderMomentum(rows) {
  const data = momentum(rows);
  const host = el("momentum");
  host.textContent = "";

  const legend = el("momentum-legend");
  legend.innerHTML =
    `<span class="key"><i style="background:${css("--viz-hot")}"></i>heating up</span>` +
    `<span class="key"><i style="background:${css("--viz-cool")}"></i>cooling off</span>`;

  if (!data.length) {
    host.innerHTML = '<p class="empty">Not enough recent data for momentum.</p>';
    return;
  }

  const rowH = 26;
  const W = host.clientWidth || 760;
  const H = data.length * rowH + 22;
  const labelW = 104;
  // Reserve room for the direct label on both arms so a bar can never run off
  // the edge and clip its own value.
  const valueW = 62;
  const arm = (W - labelW - valueW * 2) / 2;
  const mid = labelW + valueW + arm;
  // Scale to the data, not to a fixed cap.
  const maxAbs = Math.max(0.5, ...data.map((d) => Math.abs(d.shift)));

  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img" });

  // Neutral gray zero line: the diverging midpoint must read as "nothing".
  chart.append(svg("line", {
    x1: mid, x2: mid, y1: 4, y2: H - 18,
    stroke: css("--viz-zero"), "stroke-width": 1,
  }));

  data.forEach((d, i) => {
    const y = 4 + i * rowH;
    const width = Math.max(2, (Math.abs(d.shift) / maxAbs) * arm);
    const rising = d.shift >= 0;
    const fill = rising ? css("--viz-hot") : css("--viz-cool");

    const label = svg("text", { x: labelW - 10, y: y + 15, "text-anchor": "end", class: "row-label" });
    label.textContent = d.tag;
    chart.append(label);

    // 4px rounded data-end, anchored at the zero baseline.
    const bar = svg("rect", {
      x: rising ? mid + 1 : mid - 1 - width,
      y: y + 4, width, height: rowH - 12, rx: 4,
      fill,
    });
    chart.append(bar);

    // Direct label on every bar: this is the relief for the light-mode
    // contrast WARN, so values never depend on the fill being legible.
    const pct = `${d.shift > 0 ? "+" : ""}${d.shift.toFixed(1)}pp${d.isNew ? " new" : ""}`;
    const value = svg("text", {
      x: rising ? mid + width + 7 : mid - width - 7,
      y: y + 15, "text-anchor": rising ? "start" : "end", class: "row-value",
    });
    value.textContent = pct;
    chart.append(value);

    const hit = svg("rect", {
      x: 0, y, width: W, height: rowH, fill: "transparent",
    });
    hit.addEventListener("mousemove", (event) => tip(
      `<strong>${d.tag}</strong><br>${d.now7} in last 7d<br>` +
      `${d.priorPerWeek.toFixed(1)}/wk over prior 3w<br>` +
      `share shift ${pct}`,
      event.clientX, event.clientY));
    hit.addEventListener("mouseleave", hideTip);
    chart.append(hit);
  });

  host.append(chart);
  tableFor("momentum", ["Topic", "Last 7d", "Prior weekly avg", "Share shift"],
    data.map((d) => [d.tag, d.now7, d.priorPerWeek.toFixed(1),
      `${d.shift > 0 ? "+" : ""}${d.shift.toFixed(1)}pp${d.isNew ? " (new)" : ""}`]));
}

// -------------------------------------------- topics over time (small multiples)

function renderTopics(rows) {
  const counts = new Map();
  for (const a of rows) for (const t of tagsOf(a)) counts.set(t, (counts.get(t) || 0) + 1);
  const tags = [...counts].sort((a, b) => b[1] - a[1]).slice(0, 12).map(([t]) => t);

  const host = el("topics");
  host.textContent = "";
  const tableRows = [];

  for (const tag of tags) {
    const series = weekly(rows.filter((a) => tagsOf(a).includes(tag)), 12);
    const max = Math.max(1, ...series.map((d) => d.count));

    const panel = document.createElement("div");
    panel.className = "spark";

    const head = document.createElement("div");
    head.className = "spark-head";
    // Identity comes from the panel label, so every sparkline can share one hue.
    head.innerHTML = `<span class="spark-name">${tag}</span>` +
      `<span class="spark-total">${counts.get(tag)}</span>`;
    panel.append(head);

    const W = 190, H = 34;
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart" });
    const x = (i) => (W * i) / Math.max(1, series.length - 1);
    const y = (v) => H - 3 - ((H - 8) * v) / max;
    const points = series.map((d, i) => `${x(i)},${y(d.count)}`).join(" ");

    chart.append(svg("polyline", {
      points, fill: "none", stroke: css("--viz-series-1"),
      "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round",
    }));
    chart.append(svg("circle", {
      cx: x(series.length - 1), cy: y(series[series.length - 1].count), r: 2.5,
      fill: css("--viz-series-1"),
    }));
    panel.append(chart);

    panel.addEventListener("mousemove", (event) => tip(
      `<strong>${tag}</strong><br>${counts.get(tag)} in range<br>` +
      `peak ${max}/wk`, event.clientX, event.clientY));
    panel.addEventListener("mouseleave", hideTip);

    host.append(panel);
    tableRows.push([tag, counts.get(tag), max, series.map((d) => d.count).join(" ")]);
  }

  tableFor("topics", ["Topic", "Total in range", "Peak per week", "Weekly counts (12w)"], tableRows);
}

// ----------------------------------------------------------------- source mix

function renderSources(rows) {
  const counts = new Map();
  for (const a of rows) counts.set(a.source, (counts.get(a.source) || 0) + 1);
  const data = [...counts].sort((a, b) => b[1] - a[1]).slice(0, 12);

  const host = el("sources");
  host.textContent = "";
  if (!data.length) return;

  const rowH = 24;
  const W = host.clientWidth || 760;
  const H = data.length * rowH + 6;
  const labelW = 168;
  const max = data[0][1];
  const plotW = W - labelW - 54;

  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img" });

  // One series, one hue — never a value-ramp across nominal categories.
  data.forEach(([source, count], i) => {
    const y = i * rowH;
    const width = Math.max(2, (count / max) * plotW);

    const label = svg("text", { x: labelW - 10, y: y + 15, "text-anchor": "end", class: "row-label" });
    label.textContent = source;
    chart.append(label);

    chart.append(svg("rect", {
      x: labelW, y: y + 4, width, height: rowH - 11, rx: 4,
      fill: css("--viz-series-1"),
    }));

    const value = svg("text", { x: labelW + width + 7, y: y + 15, class: "row-value" });
    value.textContent = count;
    chart.append(value);

    const hit = svg("rect", { x: 0, y, width: W, height: rowH, fill: "transparent" });
    hit.addEventListener("mousemove", (event) =>
      tip(`<strong>${source}</strong><br>${count} articles`, event.clientX, event.clientY));
    hit.addEventListener("mouseleave", hideTip);
    chart.append(hit);
  });

  host.append(chart);
  tableFor("sources", ["Source", "Articles"], data);
}

// ------------------------------------------------------------- highest signal

function renderTop(rows) {
  const cutoff = Date.now() - 7 * 86400000;
  const picks = rows
    .filter((a) => {
      const when = parseDate(a.published_date);
      return when && when.getTime() >= cutoff && !read.has(a.url);
    })
    .sort((a, b) => (b.relevance_score || 0) - (a.relevance_score || 0))
    .slice(0, 10);

  const host = el("top");
  host.textContent = "";
  if (!picks.length) {
    host.innerHTML = '<p class="empty">Nothing unread from the last 7 days.</p>';
    return;
  }

  for (const a of picks) {
    const row = document.createElement("a");
    row.className = "top-row";
    row.href = a.url;
    row.target = "_blank";
    row.rel = "noopener";
    row.innerHTML =
      `<span class="top-score">${(a.relevance_score || 0).toFixed(2)}</span>` +
      `<span class="top-title"></span>` +
      `<span class="top-source"></span>`;
    row.querySelector(".top-title").textContent = a.title;
    row.querySelector(".top-source").textContent = a.source;
    host.append(row);
  }
}

// ------------------------------------------------------------------- lifecycle

function renderAll() {
  const rows = inScope();
  el("scope").textContent = `${rows.length.toLocaleString()} articles in range`;
  renderKpis(rows);
  renderVolume(rows);
  renderMomentum(rows);
  renderTopics(rows);
  renderSources(rows);
  renderTop(rows);
}

for (const button of document.querySelectorAll(".table-toggle")) {
  button.addEventListener("click", () => {
    const view = el(`${button.dataset.for}-table`);
    view.hidden = !view.hidden;
    button.textContent = view.hidden ? "Table" : "Chart";
    el(button.dataset.for).hidden = !view.hidden;
  });
}

fetch("./data/articles.json")
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((data) => {
    articles = data.articles || [];
    el("updated").textContent = data.generated_at
      ? `updated ${new Date(data.generated_at).toLocaleString()}`
      : "";
    el("source").append(new Option("All sources", "all"));
    for (const source of data.sources || []) el("source").append(new Option(source, source));
    renderAll();
  })
  .catch((error) => {
    document.querySelector("main").innerHTML =
      `<p class="empty">Could not load data (${error.message}).</p>`;
  });

for (const control of ["window", "source"]) {
  el(control).addEventListener("change", renderAll);
}
let resizeTimer;
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(renderAll, 180);
});
