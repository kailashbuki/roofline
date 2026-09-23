// Inference News — static reader over data/articles.json.
// Read state lives in localStorage. Note the origin is shared with the personal
// homepage on github.io, hence the namespaced keys.
const READ_KEY = "inference-news:read";
const PAGE_SIZE = 60;

const el = {
  list: document.getElementById("list"),
  source: document.getElementById("source"),
  window: document.getElementById("window"),
  sort: document.getElementById("sort"),
  search: document.getElementById("search"),
  unread: document.getElementById("unread"),
  stats: document.getElementById("stats"),
  updated: document.getElementById("updated"),
  more: document.getElementById("more"),
  markAll: document.getElementById("mark-all"),
};

let articles = [];
let shown = PAGE_SIZE;
let read = loadRead();

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
  } catch {
    /* private browsing or quota exceeded — read state is best-effort */
  }
}

function relativeDate(iso) {
  if (!iso) return "unknown date";
  const then = new Date(iso + "Z");
  const days = Math.floor((Date.now() - then.getTime()) / 86400000);
  if (days < 0) return then.toLocaleDateString();
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  return then.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function visible() {
  const days = Number(el.window.value);
  const cutoff = days ? Date.now() - days * 86400000 : null;
  const source = el.source.value;
  const needle = el.search.value.trim().toLowerCase();

  const rows = articles.filter((a) => {
    if (source !== "all" && a.source !== source) return false;
    if (cutoff && a.published_date && new Date(a.published_date + "Z").getTime() < cutoff) return false;
    if (el.unread.checked && read.has(a.url)) return false;
    if (needle && !a.title.toLowerCase().includes(needle)) return false;
    return true;
  });

  if (el.sort.value === "relevance") {
    rows.sort((a, b) =>
      (b.relevance_score || 0) - (a.relevance_score || 0) ||
      (b.published_date || "").localeCompare(a.published_date || "")
    );
  }
  return rows;
}

function toast(message) {
  const node = document.createElement("div");
  node.className = "toast";
  node.textContent = message;
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 2600);
}

function summarize(article) {
  const prompt = `Summarize this article: ${article.title} ${article.url}`;
  const open = () => window.open("https://gemini.google.com/app", "_blank", "noopener");
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(prompt).then(
      () => { toast("Prompt copied — paste into Gemini"); open(); },
      open
    );
  } else {
    open();
  }
}

function card(article) {
  const isRead = read.has(article.url);
  const node = document.createElement("a");
  node.className = "card" + (isRead ? " read" : "");
  node.href = article.url;
  node.target = "_blank";
  node.rel = "noopener";

  const title = document.createElement("h2");
  title.textContent = (isRead ? "" : "🔥 ") + article.title;

  const meta = document.createElement("div");
  meta.className = "meta";
  const source = document.createElement("span");
  source.className = "source";
  source.textContent = article.source;
  const date = document.createElement("span");
  date.textContent = relativeDate(article.published_date);
  meta.append(source, date);

  for (const tag of (article.tags || "").split(",").filter(Boolean).slice(0, 4)) {
    const chip = document.createElement("span");
    chip.className = "tag";
    chip.textContent = tag;
    meta.append(chip);
  }

  const button = document.createElement("button");
  button.className = "summarize";
  button.type = "button";
  button.title = "Summarize with Gemini";
  button.textContent = "✨";
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    summarize(article);
  });

  node.addEventListener("click", () => {
    if (!read.has(article.url)) {
      read.add(article.url);
      saveRead();
      node.classList.add("read");
      title.textContent = article.title;
      renderStats();
    }
  });

  node.append(title, meta, button);
  return node;
}

function renderStats() {
  const unread = articles.filter((a) => !read.has(a.url)).length;
  el.stats.textContent = `${articles.length} articles · ${unread} unread`;
}

function render() {
  const rows = visible();
  el.list.textContent = "";

  if (!rows.length) {
    el.list.innerHTML = '<p class="empty">Nothing matches those filters.</p>';
    el.more.hidden = true;
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const article of rows.slice(0, shown)) fragment.append(card(article));
  el.list.append(fragment);

  el.more.hidden = rows.length <= shown;
  el.more.textContent = `Show more (${rows.length - shown} left)`;
  renderStats();
}

function reset() {
  shown = PAGE_SIZE;
  render();
}

fetch("./data/articles.json")
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((data) => {
    articles = data.articles || [];
    el.updated.textContent = data.generated_at
      ? `updated ${relativeDate(data.generated_at.replace("Z", ""))}`
      : "";

    el.source.append(new Option("All sources", "all"));
    for (const source of data.sources || []) el.source.append(new Option(source, source));

    render();
  })
  .catch((error) => {
    el.list.innerHTML = `<p class="empty">Could not load articles (${error.message}).</p>`;
  });

for (const control of [el.source, el.window, el.sort, el.unread]) {
  control.addEventListener("change", reset);
}
el.search.addEventListener("input", reset);
el.more.addEventListener("click", () => {
  shown += PAGE_SIZE;
  render();
});
el.markAll.addEventListener("click", () => {
  for (const article of visible()) read.add(article.url);
  saveRead();
  render();
});
