// roofline — a briefing, not a feed.
//
// The page answers one question: what must I read? Items are grouped by area of
// interest and ordered by the editorial importance score the classifier assigns,
// with its one-line justification shown inline so you can skip without opening.
//
// Read state lives in localStorage. The origin is shared with the personal
// homepage on github.io, hence the namespaced key.
const READ_KEY = "roofline:read";
const THEME_KEY = "roofline:theme";
// No per-row importance marker at all. Tried a printed score, then a "must read"
// badge at two thresholds: each marked most of what was on screen, because the
// sections SELECT for top rows, so any cut over the range fires on nearly every
// visible one. Rank is carried by the ordering, the cut by the band, and the worth
// by the why line.
const VISIT_KEY = "roofline:visit";
// A reload is not a new visit. Storing only "now" on every load meant refreshing
// five minutes later emptied the entire "new" set, which is the one view the page
// exists for. The mark therefore advances only when this load starts a new
// session — a gap of at least this long since the previous one.
const SESSION_GAP_MS = 30 * 60 * 1000;
// Only the first few per area. A briefing that needs scrolling is a list.
const PER_AREA = 3;
// The lede is one item per front, not the global top N. "Top 5 by importance"
// collapses to whichever source produces the most high scorers — measured, it was
// 5 of 5 arXiv covering 3 of 7 fronts, which is the opposite of cross-front
// triage. One per front guarantees breadth, which nothing else on the page gives.

// [key, section heading, tab label]. Mirrors classifier.AREAS. The tab label is
// short on purpose: the strip has to fit one line, or it costs more space than the
// content it filters.
const AREAS = [
  ["architecture", "Model architecture", "Arch"],
  ["new-models", "New models", "Models"],
  ["inference-methods", "Inference optimization", "Inference"],
  ["inference-engines", "Inference engines & serving", "Engines"],
  ["silicon", "Silicon", "Silicon"],
  ["training", "Training & post-training", "Training"],
  ["economics", "Cost & economics", "Cost"],
  ["other", "Everything else", "Other"],
];

// Short labels, because the count carries the meaning.
const BANDS = [
  { value: 0, label: "All", hint: "Everything in range" },
  { value: 0.35, label: "Notable", hint: "Skip the routine" },
  { value: 0.6, label: "Key", hint: "Only the consequential" },
];

const el = (id) => document.getElementById(id);

/** A missing node means the cached HTML predates this script. Say so. */
class StaleMarkupError extends Error {}

function need(id) {
  const node = el(id);
  if (!node) {
    throw new StaleMarkupError(
      `#${id} is missing: this page's HTML is older than its script.`
    );
  }
  return node;
}

function reportFailure(error) {
  const target = el("empty") || document.body;
  target.hidden = false;
  if (error instanceof StaleMarkupError) {
    target.textContent =
      "This page was loaded from a stale cache. Reload to get the current version " +
      "(hold Shift while reloading if it persists).";
  } else {
    target.textContent = `Could not load articles (${error.message}).`;
  }
}

let articles = [];
let digest = {};
let read = loadRead();
let visitMark = null;           // "new" means newer than this, not merely unread
let activeArea = "all";
let activeBand = 0.35;
const expanded = new Set();

function loadRead() {
  try {
    return new Set(JSON.parse(localStorage.getItem(READ_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

function saveRead() {
  try {
    localStorage.setItem(READ_KEY, JSON.stringify([...read]));
  } catch { /* private browsing — read state is best effort */ }
}

function relativeDate(iso) {
  if (!iso) return "";
  const then = new Date(iso + "Z");
  const days = Math.floor((Date.now() - then.getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function readVisit() {
  try {
    const raw = localStorage.getItem(VISIT_KEY);
    if (!raw) return { mark: null, seen: null };
    // A bare number is the old format: one timestamp, written on every load.
    const asNumber = Number(raw);
    if (Number.isFinite(asNumber) && asNumber > 0) return { mark: null, seen: asNumber };
    const parsed = JSON.parse(raw);
    return { mark: parsed.mark ?? null, seen: parsed.seen ?? null };
  } catch {
    return { mark: null, seen: null };
  }
}

/** Open a session: returns the timestamp "new" is measured against. */
function openSession() {
  const { mark, seen } = readVisit();
  const now = Date.now();

  let nextMark = mark;
  if (seen === null) {
    nextMark = null;                       // never been here; nothing to compare to
  } else if (now - seen > SESSION_GAP_MS) {
    nextMark = seen;                       // new session: last session's load time
  }

  try {
    localStorage.setItem(VISIT_KEY, JSON.stringify({ mark: nextMark, seen: now }));
  } catch { /* best effort */ }
  return nextMark;
}

/** Everything passing time/search/unread, ignoring the importance band. */
function inRange() {
  const saved = activeBand;
  activeBand = 0;
  try {
    return inScope();
  } finally {
    activeBand = saved;
  }
}

function renderBands(rangeRows) {
  const host = need("bar");
  host.textContent = "";
  for (const band of BANDS) {
    const n = rangeRows.filter(
      (a) => !(band.value > 0 && typeof a.importance === "number" && a.importance < band.value)
    ).length;

    const button = document.createElement("button");
    button.type = "button";
    button.className = `seg-btn${activeBand === band.value ? " on" : ""}`;
    button.append(span("", band.label));
    button.append(span("seg-n", n));
    button.title = `${band.hint} — ${n} items`;
    button.addEventListener("click", () => {
      activeBand = band.value;
      expanded.clear();
      syncUrl();
      render();
    });
    host.append(button);
  }
}

function inScope() {
  const range = el("window").value;
  let cutoff = null;
  if (range === "new") {
    // First visit has nothing to compare against, so fall back to a week.
    cutoff = visitMark ?? Date.now() - 7 * 86400000;
  } else if (Number(range)) {
    cutoff = Date.now() - Number(range) * 86400000;
  }
  const needle = el("search").value.trim().toLowerCase();

  return articles
    .filter((a) => {
      const when = a.published_date ? new Date(a.published_date + "Z").getTime() : null;
      if (cutoff && (!when || when < cutoff)) return false;
      if (el("unread").checked && read.has(a.url)) return false;
      if (needle && !(a.title || "").toLowerCase().includes(needle)) return false;
      // An unrated row has never been seen by the model. Don't hide it behind a
      // bar it never had the chance to clear — show it marked unrated instead.
      if (activeBand > 0 && typeof a.importance === "number" && a.importance < activeBand) {
        return false;
      }
      return true;
    })
    .sort((a, b) =>
      (b.importance ?? 0.5) - (a.importance ?? 0.5) ||
      (b.published_date || "").localeCompare(a.published_date || ""));
}

function toast(message) {
  const node = document.createElement("div");
  node.className = "toast";
  node.textContent = message;
  document.body.append(node);
  setTimeout(() => node.remove(), 2400);
}

function summarize(article) {
  const prompt = `Summarize this article: ${article.title} ${article.url}`;
  const open = () => window.open("https://gemini.google.com/app", "_blank", "noopener");
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(prompt).then(() => {
      toast("Prompt copied — paste into Gemini");
      open();
    }, open);
  } else {
    open();
  }
}

function markRead(article, node) {
  if (read.has(article.url)) return;
  read.add(article.url);
  saveRead();
  node.classList.add("read");
  renderCounts();
}

function span(className, text) {
  const node = document.createElement("span");
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

const AREA_LABEL = new Map(AREAS.map(([key, label]) => [key, label]));

function card(article, { lede = false } = {}) {
  const node = document.createElement("a");
  node.className = `item${read.has(article.url) ? " read" : ""}${lede ? " item-lede" : ""}`;
  node.href = article.url;
  node.target = "_blank";
  node.rel = "noopener";

  const body = document.createElement("span");
  body.className = "item-body";
  body.append(span("item-title", article.title));

  // The justification is the whole point: it lets you skip without opening.
  if (article.why) body.append(span("item-why", article.why));

  const meta = document.createElement("span");
  meta.className = "item-meta";
  // In the lede the rows are from different fronts, so each must say which.
  if (lede) {
    const badge = span("front", AREA_LABEL.get(article.area) || article.area || "other");
    meta.append(badge);
  }
  meta.append(span("item-source", article.source));
  meta.append(span("", relativeDate(article.published_date)));
  const when = article.published_date ? new Date(article.published_date + "Z").getTime() : 0;
  if (visitMark && when > visitMark) meta.append(span("item-new", "new"));
  // Sub-topic chips. The section header already carries the area, so these are
  // the finer grain that helps scanning within a section.
  for (const tag of (article.tags || "").split(",").filter(Boolean).slice(0, 4)) {
    meta.append(span("chip", tag));
  }
  body.append(meta);

  const spark = document.createElement("button");
  spark.className = "summarize";
  spark.type = "button";
  spark.title = "Summarize with Gemini";
  spark.textContent = "✨";
  spark.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    summarize(article);
  });

  node.addEventListener("click", () => markRead(article, node));
  node.append(body, spark);
  return node;
}

function renderNotice() {
  const rated = articles.filter((a) => typeof a.importance === "number").length;
  const unrated = articles.length - rated;
  const notice = el("notice");

  // Never let the page look broken without saying why.
  if (unrated > articles.length * 0.05) {
    notice.hidden = false;
    notice.textContent =
      `${unrated.toLocaleString()} of ${articles.length.toLocaleString()} items ` +
      `have not been classified yet, so they have no area or importance and ` +
      `collect under "Everything else". Run ./sync.sh to fill them in.`;
  } else {
    notice.hidden = true;
  }
}

/** Fronts as tabs: label over count, plus how many are new since the last visit. */
function renderTabs(rows) {
  const counts = new Map();
  const fresh = new Map();
  for (const a of rows) {
    const area = a.area || "other";
    counts.set(area, (counts.get(area) || 0) + 1);
    const when = a.published_date ? new Date(a.published_date + "Z").getTime() : 0;
    if (visitMark && when > visitMark) fresh.set(area, (fresh.get(area) || 0) + 1);
  }

  const host = need("tabs");
  host.textContent = "";
  const entries = [["all", "All fronts", "All"], ...AREAS];

  entries.forEach(([area, label, short]) => {
    const n = area === "all" ? rows.length : counts.get(area) || 0;
    if (area !== "all" && !n) return;

    const newCount = area === "all"
      ? [...fresh.values()].reduce((total, v) => total + v, 0)
      : fresh.get(area) || 0;

    const tab = document.createElement("button");
    tab.type = "button";
    tab.role = "tab";
    tab.ariaSelected = String(activeArea === area);
    tab.className = `tab${activeArea === area ? " on" : ""}`;
    tab.append(span("tab-label", short || label));

    const figure = span("tab-n", String(n));
    if (newCount) figure.append(span("tab-new", `+${newCount}`));
    tab.append(figure);

    // The area's digest as the tooltip: survey every front without clicking one.
    const brief = digest[area]?.text;
    tab.title = `${label}: ${n} items` +
      (newCount ? `, ${newCount} new since your last visit` : "") +
      (brief ? `\n\n${brief}` : "");

    tab.addEventListener("click", () => {
      activeArea = area;
      expanded.clear();
      syncUrl();
      render();
    });
    host.append(tab);
  });
}

function renderDigest() {
  const node = el("digest");
  const entry = activeArea !== "all" ? digest[activeArea] : null;
  node.hidden = !entry;
  node.classList.remove("open");
  node.textContent = entry ? entry.text : "";
}

function renderCounts() {
  const unread = articles.filter((a) => !read.has(a.url)).length;
  el("counts").textContent = `${articles.length} collected · ${unread} unread`;
}

function render() {
  const rangeRows = inRange();
  renderBands(rangeRows);

  let rows = inScope();
  renderTabs(rows);
  renderDigest();

  if (activeArea !== "all") rows = rows.filter((a) => (a.area || "other") === activeArea);

  // One item per front, best first — not the global top N. Measured, "top 5 by
  // importance" was 5 of 5 arXiv covering 3 of 7 fronts, which is the opposite of
  // cross-front triage. One per front guarantees the breadth nothing else on the
  // page provides. "other" never supplies a row: it is the unclassified bucket.
  // Suppressed entirely for a single front, where it would just repeat row one.
  const lede = [];
  if (activeArea === "all") {
    const taken = new Set();
    for (const article of rows) {
      const area = article.area || "other";
      if (area === "other" || taken.has(area)) continue;
      taken.add(area);
      lede.push(article);
    }
  }
  const ledeUrls = new Set(lede.map((a) => a.url));

  el("lede-section").hidden = lede.length === 0;
  const ledeHost = el("lede");
  ledeHost.textContent = "";
  for (const article of lede) ledeHost.append(card(article, { lede: true }));

  const host = el("areas");
  host.textContent = "";
  let shown = lede.length;

  for (const [area, label] of AREAS) {
    const all = rows.filter((a) => (a.area || "other") === area && !ledeUrls.has(a.url));
    if (!all.length) continue;

    const section = document.createElement("section");
    section.className = "area";

    const head = document.createElement("div");
    head.className = "area-head";
    head.append(Object.assign(document.createElement("h2"), { textContent: label }));
    head.append(span("area-count", all.length));
    section.append(head);

    const isOpen = expanded.has(area);
    // "Everything else" starts collapsed: it is a holding pen, not a section.
    const cap = area === "other" && activeArea !== "other" ? 0
      : activeArea !== "all" ? Infinity
      : PER_AREA;
    const visible = isOpen ? all : all.slice(0, cap);
    for (const article of visible) section.append(card(article));
    shown += visible.length;

    if (all.length > cap) {
      const more = document.createElement("button");
      more.className = "link more-in-area";
      more.textContent = isOpen ? "Show less" : `${all.length - cap} more`;
      more.addEventListener("click", () => {
        if (isOpen) expanded.delete(area); else expanded.add(area);
        render();
      });
      section.append(more);
    }

    host.append(section);
  }

  const empty = el("empty");
  empty.hidden = shown > 0;
  empty.textContent = shown > 0 ? "" : "Nothing clears that bar in this range.";

  renderCounts();
  renderNotice();
}

const THEMES = ["auto", "light", "dark"];
const THEME_ICON = { auto: "◐", light: "☀", dark: "☾" };

function applyTheme(theme) {
  if (theme === "auto") {
    delete document.documentElement.dataset.theme;
  } else {
    document.documentElement.dataset.theme = theme;
  }
  const button = el("theme");
  if (button) {
    button.textContent = THEME_ICON[theme];
    button.title = `Theme: ${theme} (click to change)`;
    button.setAttribute("aria-label", `Theme: ${theme}`);
  }
}

function initTheme() {
  let theme = "auto";
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (THEMES.includes(stored)) theme = stored;
  } catch { /* ignore */ }
  applyTheme(theme);

  el("theme").addEventListener("click", () => {
    const next = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
    try { localStorage.setItem(THEME_KEY, next); } catch { /* ignore */ }
    applyTheme(next);
  });
}

function currentTheme() {
  return document.documentElement.dataset.theme || "auto";
}

/** Filters live in the URL: shareable, bookmarkable, and testable. */
function applyUrlParams() {
  const params = new URLSearchParams(location.search);
  const windowValue = params.get("window");
  if (windowValue !== null && [...el("window").options].some((o) => o.value === windowValue)) {
    el("window").value = windowValue;
  }
  const band = Number(params.get("bar"));
  if (BANDS.some((b) => b.value === band)) activeBand = band;
  if (params.get("q")) el("search").value = params.get("q");
  const area = params.get("area");
  if (area && (area === "all" || AREAS.some(([key]) => key === area))) activeArea = area;
  if (params.get("unread") === "1") el("unread").checked = true;
}

function syncUrl() {
  const params = new URLSearchParams();
  params.set("window", el("window").value);
  params.set("bar", String(activeBand));
  if (el("search").value.trim()) params.set("q", el("search").value.trim());
  if (el("unread").checked) params.set("unread", "1");
  if (activeArea !== "all") params.set("area", activeArea);
  history.replaceState(null, "", `?${params}`);
}

initTheme();
applyUrlParams();

visitMark = openSession();

Promise.all([
  // no-cache forces revalidation. Without it the browser happily serves an
  // hours-old articles.json and the page silently shows stale state — which
  // looked exactly like the backfill having been lost.
  fetch("./data/articles.json", { cache: "no-cache" }).then((r) => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }),
  // Optional: absent until build_digest.py has run with a key.
  fetch("./data/digest.json", { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null),
])
  .then(([data, digestData]) => {
    // Any DOM mismatch surfaces here rather than as a misleading data error.
    digest = digestData?.areas || {};
    articles = data.articles || [];
    if (data.generated_at) {
      const when = new Date(data.generated_at);
      el("updated").textContent = `updated ${when.toLocaleString(undefined, {
        year: "numeric", month: "short", day: "numeric",
        hour: "2-digit", minute: "2-digit",
      })}`;
      el("updated").title = data.generated_at;
      const since = visitMark
        ? `new = published since your last visit, ${new Date(visitMark).toLocaleString(undefined, {
            month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}`
        : "new = everything, since this is your first visit here";
      el("stamp").textContent =
        `${data.hot_days ?? 120}-day window` +
        (data.total_collected ? ` of ${data.total_collected.toLocaleString()} collected` : "") +
        ` · ${since}`;
    }
    render();
  })
  .catch(reportFailure);

for (const id of ["window", "unread"]) {
  el(id).addEventListener("change", () => { expanded.clear(); syncUrl(); render(); });
}
el("search").addEventListener("input", () => { expanded.clear(); syncUrl(); render(); });
// 0 = all fronts, 1-7 = each area. Faster than reaching for the pills.
addEventListener("keydown", (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return;
  const index = "01234567".indexOf(event.key);
  if (index < 0) return;
  const target = index === 0 ? "all" : (AREAS[index - 1] || [])[0];
  if (!target) return;
  activeArea = target;
  expanded.clear();
  syncUrl();
  render();
});

el("digest").addEventListener("click", () => el("digest").classList.toggle("open"));

el("mark-all").addEventListener("click", () => {
  for (const article of inScope()) read.add(article.url);
  saveRead();
  render();
});
