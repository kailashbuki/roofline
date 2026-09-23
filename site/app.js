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
// Only the top tier earns a marker. A number on every row is decoration: it
// cannot be acted on, and the ordering already encodes it.
const MUST_READ = 0.75;
const LEDE_COUNT = 5;
const PER_AREA = 6;

// Display order and labels. Mirrors classifier.AREAS.
const AREAS = [
  ["architecture", "Model architecture"],
  ["new-models", "New models"],
  ["inference-methods", "Inference optimization"],
  ["inference-engines", "Inference engines & serving"],
  ["silicon", "Silicon"],
  ["training", "Training & post-training"],
  ["other", "Everything else"],
];

const el = (id) => document.getElementById(id);

let articles = [];
let read = loadRead();
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

/** Rows passing the filter row, ordered most-important first. */
function inScope() {
  const days = Number(el("window").value);
  const cutoff = days ? Date.now() - days * 86400000 : null;
  const bar = Number(el("bar").value);
  const needle = el("search").value.trim().toLowerCase();

  return articles
    .filter((a) => {
      const when = a.published_date ? new Date(a.published_date + "Z").getTime() : null;
      if (cutoff && (!when || when < cutoff)) return false;
      if (el("unread").checked && read.has(a.url)) return false;
      if (needle && !(a.title || "").toLowerCase().includes(needle)) return false;
      // An unrated row has never been seen by the model. Don't hide it behind a
      // bar it never had the chance to clear — show it marked unrated instead.
      if (bar > 0 && typeof a.importance === "number" && a.importance < bar) return false;
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
  // Redundant in the lede, which is by definition the must-reads.
  if (!lede && typeof article.importance === "number" && article.importance >= MUST_READ) {
    const flag = span("must-read", "must read");
    flag.title = `importance ${article.importance.toFixed(2)}`;
    meta.append(flag);
  }
  meta.append(span("item-source", article.source));
  meta.append(span("", relativeDate(article.published_date)));
  if (!read.has(article.url)) meta.append(span("item-new", "new"));
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

function renderCounts() {
  const unread = articles.filter((a) => !read.has(a.url)).length;
  el("counts").textContent = `${articles.length} collected · ${unread} unread`;
}

function render() {
  const rows = inScope();
  // With few results the lede would swallow the whole page and the area grouping
  // would vanish, so it only earns its place when there is a tail to lead.
  const lede = rows.length > LEDE_COUNT * 2 ? rows.slice(0, LEDE_COUNT) : [];
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
    const visible = isOpen ? all : all.slice(0, PER_AREA);
    for (const article of visible) section.append(card(article));
    shown += visible.length;

    if (all.length > PER_AREA) {
      const more = document.createElement("button");
      more.className = "link more-in-area";
      more.textContent = isOpen
        ? "Show less"
        : `Show ${all.length - PER_AREA} more`;
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
  for (const id of ["window", "bar"]) {
    const value = params.get(id);
    if (value === null) continue;
    const control = el(id);
    if ([...control.options].some((o) => o.value === value)) control.value = value;
  }
  if (params.get("q")) el("search").value = params.get("q");
  if (params.get("unread") === "1") el("unread").checked = true;
}

function syncUrl() {
  const params = new URLSearchParams();
  params.set("window", el("window").value);
  params.set("bar", el("bar").value);
  if (el("search").value.trim()) params.set("q", el("search").value.trim());
  if (el("unread").checked) params.set("unread", "1");
  history.replaceState(null, "", `?${params}`);
}

initTheme();
applyUrlParams();

fetch("./data/articles.json")
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((data) => {
    articles = data.articles || [];
    if (data.generated_at) {
      const when = new Date(data.generated_at);
      el("updated").textContent = `updated ${when.toLocaleString(undefined, {
        year: "numeric", month: "short", day: "numeric",
        hour: "2-digit", minute: "2-digit",
      })}`;
      el("updated").title = data.generated_at;
      el("stamp").textContent =
        `showing the last ${data.hot_days ?? 120} days` +
        (data.total_collected ? ` of ${data.total_collected.toLocaleString()} collected` : "");
    }
    render();
  })
  .catch((error) => {
    el("empty").hidden = false;
    el("empty").textContent = `Could not load articles (${error.message}).`;
  });

for (const id of ["window", "bar", "unread"]) {
  el(id).addEventListener("change", () => { expanded.clear(); syncUrl(); render(); });
}
el("search").addEventListener("input", () => { expanded.clear(); syncUrl(); render(); });
el("mark-all").addEventListener("click", () => {
  for (const article of inScope()) read.add(article.url);
  saveRead();
  render();
});
